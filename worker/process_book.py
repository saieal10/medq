import os, re, json, time, tempfile
from typing import List, Dict, Tuple
import boto3
import fitz
import requests
from botocore.config import Config
from supabase import create_client

BOOK_ID = os.getenv('BOOK_ID')
FILE_KEY = os.getenv('FILE_KEY')
BOOK_SUBJECT = os.getenv('BOOK_SUBJECT', 'General')
BOOK_EXAM_TRACK = os.getenv('BOOK_EXAM_TRACK', 'FMGE_NEET_PG')
R2_ACCOUNT_ID = os.getenv('R2_ACCOUNT_ID')
R2_ACCESS_KEY_ID = os.getenv('R2_ACCESS_KEY_ID')
R2_SECRET_ACCESS_KEY = os.getenv('R2_SECRET_ACCESS_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME', 'medq-books')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_SECRET_KEY = os.getenv('SUPABASE_SECRET_KEY')

MAX_MCQS_PER_RUN = int(os.getenv('MAX_MCQS_PER_RUN', '2000'))
SAVE_BATCH = int(os.getenv('SAVE_BATCH', '250'))
MAX_PAGES = int(os.getenv('MAX_PAGES', '0'))

if not all([BOOK_ID, FILE_KEY, R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, SUPABASE_URL, SUPABASE_SECRET_KEY]):
    raise RuntimeError('Missing required worker environment variables.')

sb = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
r2 = boto3.client(
    's3',
    endpoint_url=f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name='auto',
    config=Config(signature_version='s3v4')
)

LETTERS = 'ABCDE'


def norm(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '')).strip()


def stem_key(s: str) -> str:
    s = norm(s).lower()
    s = re.sub(r'[^a-z0-9 ]+', '', s)
    return re.sub(r'\s+', ' ', s)


def exam_type() -> str:
    t = (BOOK_EXAM_TRACK or '').upper()
    if 'AMC' in t and 'FMGE' in t:
        return 'BOTH'
    if 'AMC' in t:
        return 'AMC'
    return 'FMGE'


def existing_stems() -> set:
    found = set()
    offset = 0
    while True:
        res = sb.table('questions').select('stem').eq('book_id', BOOK_ID).range(offset, offset + 999).execute()
        rows = res.data or []
        for row in rows:
            k = stem_key(row.get('stem', ''))
            if k:
                found.add(k)
        if len(rows) < 1000:
            break
        offset += 1000
    return found


def download_pdf() -> str:
    path = os.path.join(tempfile.gettempdir(), f'medq_{BOOK_ID}.pdf')
    print(f'[PDF] downloading {FILE_KEY}')
    r2.download_file(R2_BUCKET_NAME, FILE_KEY, path)
    return path


def build_full_text(path: str) -> Tuple[str, List[int]]:
    doc = fitz.open(path)
    limit = len(doc) if not MAX_PAGES else min(MAX_PAGES, len(doc))
    parts = []
    page_for_char = []
    for pno in range(limit):
        txt = doc[pno].get_text('text') or ''
        # Preserve page boundary and make the page discoverable for each question.
        marker = f'\n\n[[MEDQ_PAGE_{pno + 1}]]\n'
        start = sum(len(x) for x in parts)
        parts.append(marker + txt)
        page_for_char.append((start + len(marker), pno + 1))
    return ''.join(parts), page_for_char


def page_at(pos: int, page_map: List[Tuple[int, int]]) -> int:
    current = 1
    for start, page in page_map:
        if start > pos:
            break
        current = page
    return current


def answer_key_map(text: str) -> Dict[int, str]:
    """Extract common answer-key formats without touching question option lines."""
    mapping: Dict[int, str] = {}
    lines = text.splitlines()
    key_mode = False
    key_hits = 0

    heading_re = re.compile(r'\b(answer\s*key|answers?|correct\s+answers?|solutions?)\b', re.I)
    stop_re = re.compile(r'^\s*(?:explanation|rationale|references|chapter|questions?)\b', re.I)
    single_re = re.compile(r'^\s*(?:q(?:uestion)?\s*)?(\d{1,5})\s*[\.\)\-:\s]+\(?([A-E])\)?\s*$', re.I)
    pair_re = re.compile(r'(?:^|\s)(\d{1,5})\s*[\.\)\-:\s]\s*\(?([A-E])\)?(?=\s|$)', re.I)

    for line in lines:
        if heading_re.search(line):
            key_mode = True
            key_hits = 0
            # Parse mappings that occur on the same heading line after the heading.
            tail = heading_re.sub(' ', line)
            for m in pair_re.finditer(tail):
                mapping[int(m.group(1))] = m.group(2).upper()
            continue
        if key_mode and stop_re.search(line) and not re.search(r'\d', line):
            key_mode = False
        if not key_mode:
            continue
        m = single_re.match(line)
        if m:
            mapping[int(m.group(1))] = m.group(2).upper()
            key_hits += 1
            continue
        for m in pair_re.finditer(line):
            mapping[int(m.group(1))] = m.group(2).upper()
            key_hits += 1
        # A large run of non-key material usually means the key section ended.
        if key_hits and key_hits > 5 and len(line.strip()) > 140:
            key_mode = False
    print(f'[KEY] extracted {len(mapping)} answer-key mappings')
    return mapping


def clean_stem(raw: str) -> str:
    s = re.sub(r'\[\[MEDQ_PAGE_\d+\]\]', ' ', raw, flags=re.I)
    s = re.sub(r'^\s*(?:Q(?:uestion)?\s*)?\d{1,5}\s*[\.\)\-:]\s*', '', s, flags=re.I)
    # Remove an inline answer annotation from the stem when captured.
    s = re.split(r'\b(?:correct\s+answer|answer|ans(?:wer)?)\s*[:\-]\s*[A-E]\b', s, maxsplit=1, flags=re.I)[0]
    return norm(s)


def parse_mcqs(text: str, key: Dict[int, str]) -> List[Dict]:
    # Question starts must be line-based. This prevents chapter headings and answer-key
    # entries from being mistaken for questions unless they also contain 4+ options.
    starts = list(re.finditer(
        r'(?im)^\s*(?:Q(?:uestion)?\s*)?(\d{1,5})\s*[\.\)\-:]\s+', text)
    )
    option_re = re.compile(r'(?im)^\s*\(?([A-E])\)?\s*[\.\)\-:]\s+', re.I)
    blocks: List[Dict] = []

    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        block = text[m.start():end]
        options = list(option_re.finditer(block))
        if len(options) < 4:
            continue
        # Use the first five option markers only; ignore later A-E markers in explanations.
        options = options[:5]
        vals = []
        for j, opt in enumerate(options):
            opt_end = options[j + 1].start() if j + 1 < len(options) else len(block)
            vals.append(norm(re.sub(r'\[\[MEDQ_PAGE_\d+\]\]', ' ', block[opt.end():opt_end])))
        stem = clean_stem(block[:options[0].start()])
        if len(stem) < 15:
            continue
        if any(len(v) < 1 for v in vals[:4]):
            continue
        qnum = int(m.group(1))
        inline = re.search(r'\b(?:correct\s+answer|answer|ans(?:wer)?)\s*[:\-]\s*\(?([A-E])\)?', block, re.I)
        answer = inline.group(1).upper() if inline else key.get(qnum)
        # Strip answer labels that were swallowed into the final option.
        vals = [re.split(r'\b(?:correct\s+answer|answer|ans(?:wer)?)\s*[:\-]\s*\(?[A-E]\)?', v, maxsplit=1, flags=re.I)[0].strip() for v in vals]
        if len(vals) == 4:
            vals.append('')
        # Don't accept obvious answer-key-only blocks.
        if re.fullmatch(r'(?:answer|ans|key)\s*[:\-]?\s*[A-E]', stem, re.I):
            continue
        blocks.append({
            'number': qnum,
            'stem': stem,
            'option_a': vals[0], 'option_b': vals[1], 'option_c': vals[2],
            'option_d': vals[3], 'option_e': vals[4],
            'correct_option': answer,
            'source_page': page_at(m.start(), PAGE_MAP),
        })
    return blocks


def save_rows(rows: List[Dict]) -> int:
    saved = 0
    for i in range(0, len(rows), SAVE_BATCH):
        part = rows[i:i + SAVE_BATCH]
        try:
            res = sb.table('questions').insert(part).execute()
            saved += len(res.data or [])
        except Exception as exc:
            print(f'[DB] batch failed ({len(part)}): {exc}')
            # Retry individually so one malformed row does not discard a whole batch.
            for row in part:
                try:
                    res = sb.table('questions').insert(row).execute()
                    if res.data:
                        saved += 1
                except Exception as one_exc:
                    print(f'[DB] skipped one question: {one_exc}')
    return saved


def main():
    global PAGE_MAP
    print(f'MEDQ MCQ DIRECT EXTRACTOR | book={BOOK_ID} | subject={BOOK_SUBJECT} | track={BOOK_EXAM_TRACK}')
    path = download_pdf()
    text, PAGE_MAP = build_full_text(path)
    print(f'[PDF] extracted {len(text):,} characters')

    existing = existing_stems()
    print(f'[BANK] existing stems for this book: {len(existing)}')
    keys = answer_key_map(text)
    candidates = parse_mcqs(text, keys)
    print(f'[PARSE] detected {len(candidates)} MCQ blocks before dedupe')

    seen = set(existing)
    rows = []
    for q in candidates:
        k = stem_key(q['stem'])
        if not k or k in seen:
            continue
        answer = (q.get('correct_option') or '').upper().strip()
        if answer not in LETTERS:
            # We intentionally do not invent answers. A later enrichment workflow can handle these.
            continue
        if not all(q.get(x) for x in ['stem', 'option_a', 'option_b', 'option_c', 'option_d']):
            continue
        seen.add(k)
        rows.append({
            'book_id': BOOK_ID,
            'exam_type': exam_type(),
            'question_type': 'recall',
            'stem': q['stem'],
            'option_a': q['option_a'],
            'option_b': q['option_b'],
            'option_c': q['option_c'],
            'option_d': q['option_d'],
            'option_e': q['option_e'],
            'correct_option': answer,
            'explanation': 'Answer key/source answer detected during direct extraction.',
            'subject': BOOK_SUBJECT,
            'chapter': BOOK_SUBJECT,
            'topic': BOOK_SUBJECT,
            'difficulty': 'medium',
            'source_page': q['source_page'],
        })
        if len(rows) >= MAX_MCQS_PER_RUN:
            break

    print(f'[PARSE] {len(rows)} new answer-verified MCQs ready to save')
    saved = save_rows(rows)
    print(f'MEDQ DIRECT EXTRACTOR COMPLETE: saved {saved} new questions.')
    if len(rows) >= MAX_MCQS_PER_RUN:
        print('[CONTINUE] Run again to continue from the remaining unseen MCQs.')


if __name__ == '__main__':
    main()
