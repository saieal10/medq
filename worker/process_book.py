import os
import re
import tempfile
from typing import Dict, List, Tuple

import boto3
import pymupdf
from botocore.config import Config
from supabase import create_client

BOOK_ID = os.getenv("BOOK_ID")
FILE_KEY = os.getenv("FILE_KEY")
BOOK_SUBJECT = os.getenv("BOOK_SUBJECT", "General")
BOOK_EXAM_TRACK = os.getenv("BOOK_EXAM_TRACK", "FMGE_NEET_PG")
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "medq-books")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

MAX_MCQS_PER_RUN = int(os.getenv("MAX_MCQS_PER_RUN", "5000"))
SAVE_BATCH = int(os.getenv("SAVE_BATCH", "250"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "0"))

if not all([
    BOOK_ID, FILE_KEY, R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY, SUPABASE_URL, SUPABASE_SECRET_KEY
]):
    raise RuntimeError("Missing required worker environment variables.")

sb = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
r2 = boto3.client(
    "s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(signature_version="s3v4"),
)

LETTERS = "ABCDE"
PAGE_MAP: List[Tuple[int, int]] = []


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def stem_key(s: str) -> str:
    s = norm(s).lower()
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def exam_type() -> str:
    t = (BOOK_EXAM_TRACK or "").upper()
    if "AMC" in t and ("FMGE" in t or "NEET" in t):
        return "BOTH"
    if "AMC" in t:
        return "AMC"
    return "FMGE"


def existing_stems() -> set:
    found = set()
    offset = 0
    while True:
        res = (
            sb.table("questions")
            .select("stem")
            .eq("book_id", BOOK_ID)
            .range(offset, offset + 999)
            .execute()
        )
        rows = res.data or []
        for row in rows:
            k = stem_key(row.get("stem", ""))
            if k:
                found.add(k)
        if len(rows) < 1000:
            break
        offset += 1000
    return found


def download_pdf() -> str:
    path = os.path.join(tempfile.gettempdir(), f"medq_{BOOK_ID}.pdf")
    print(f"[PDF] downloading {FILE_KEY}")
    r2.download_file(R2_BUCKET_NAME, FILE_KEY, path)
    return path


def build_pages(path: str) -> List[str]:
    global PAGE_MAP
    doc = pymupdf.open(path)
    limit = len(doc) if not MAX_PAGES else min(MAX_PAGES, len(doc))
    pages = []
    PAGE_MAP = []
    for pno in range(limit):
        txt = doc[pno].get_text("text") or ""
        pages.append(txt)
        PAGE_MAP.append((pno, pno + 1))
    doc.close()
    return pages


def clean_page_headers(s: str) -> str:
    s = re.sub(r"\[\[MEDQ_PAGE_\d+\]\]", " ", s, flags=re.I)
    s = re.sub(r"Prepladder\s+X\s+Qbank\s*\n?Page\s*\d+\s*of\s*\d+", " ", s, flags=re.I)
    s = re.sub(r"Prepladder\s+X\s+Qbank", " ", s, flags=re.I)
    return norm(s)


def contents_sections(pages: List[str]) -> List[Tuple[str, int]]:
    """Read a numbered Lesson/Page contents table when present."""
    lines: List[str] = []
    for p in pages[:8]:
        lines.extend(x.strip() for x in p.splitlines() if x.strip())
    out: List[Tuple[str, int]] = []
    for i, line in enumerate(lines[:-1]):
        m = re.match(r"^(\d+)\.\s*(.+)$", line)
        if not m:
            continue
        if re.fullmatch(r"\d{1,4}", lines[i + 1]):
            page = int(lines[i + 1])
            if 1 <= page <= len(pages):
                out.append((norm(m.group(2)), page))
    # Keep first occurrence of a contents entry/page pair.
    seen = set()
    clean = []
    for title, page in out:
        key = (title.lower(), page)
        if key not in seen:
            seen.add(key)
            clean.append((title, page))
    return clean


def section_ranges(pages: List[str]) -> List[Tuple[str, int, int]]:
    sections = contents_sections(pages)
    if not sections:
        return [(BOOK_SUBJECT, 1, len(pages))]
    out = []
    for i, (title, start) in enumerate(sections):
        end = sections[i + 1][1] - 1 if i + 1 < len(sections) else len(pages)
        if end >= start:
            out.append((title, start, end))
    return out


def answer_map_for_section(section_text: str) -> Dict[int, str]:
    """Supports numeric answer tables, letter answer tables, and inline solution answers."""
    mapping: Dict[int, str] = {}
    key = re.search(r"(?im)^\s*(?:Correct\s+Answers?|Answer\s+Key|Answers)\s*$", section_text)
    if key:
        tail = section_text[key.start():]
        sol = re.search(r"(?im)^\s*Solution\s+for\s+Question\s+1\s*:", tail)
        if sol:
            tail = tail[:sol.start()]
        # Prepladder format: Question 1 1 / Question 2 3 ...
        for q, a in re.findall(r"Question\s+(\d{1,5})\s+([1-5])\b", tail, flags=re.I):
            mapping[int(q)] = LETTERS[int(a) - 1]
        # Generic numeric/letter pairs: 1-A, 2 B, Q3: C, etc.
        for q, a in re.findall(r"(?:Q(?:uestion)?\s*)?(\d{1,5})\s*[\.\)\-:\s]+\(?([A-E])\)?(?=\s|$)", tail, flags=re.I):
            mapping[int(q)] = a.upper()

    # If no table (or only a partial table), harvest explicit solution answers.
    for m in re.finditer(
        r"(?is)Solution\s+for\s+Question\s+(\d{1,5})\s*:.*?"
        r"Correct\s+(?:answer|option)\s*[:\-]?\s*\(?([A-E])\)?",
        section_text,
    ):
        mapping.setdefault(int(m.group(1)), m.group(2).upper())
    return mapping


def question_starts(text: str) -> List[re.Match]:
    # Actual Qbank question numbering in the supplied PDF uses "1.".
    # Internal match-list items commonly use "1)" and are therefore ignored.
    return list(re.finditer(r"(?im)^\s*(\d{1,5})\.\s+", text))


def extract_section_questions(section_text: str, chapter: str) -> List[Dict]:
    key_heading = re.search(
        r"(?im)^\s*(?:Correct\s+Answers?|Answer\s+Key|Answers)\s*$",
        section_text,
    )
    qtext = section_text[:key_heading.start()] if key_heading else section_text
    starts = question_starts(qtext)
    if not starts:
        return []

    # Start at the first real Q1 and follow 2,3,4... while ignoring internal numbered lists.
    first = next((i for i, m in enumerate(starts) if int(m.group(1)) == 1), None)
    if first is None:
        return []
    accepted: List[re.Match] = [starts[first]]
    expected = 2
    for m in starts[first + 1:]:
        n = int(m.group(1))
        if n == expected:
            accepted.append(m)
            expected += 1

    answers = answer_map_for_section(section_text)
    questions: List[Dict] = []
    for i, m in enumerate(accepted):
        end = accepted[i + 1].start() if i + 1 < len(accepted) else len(qtext)
        block = qtext[m.start():end]
        opts = list(re.finditer(r"(?im)^\s*\(?([A-E])\)?\s*[\.\)\-:]\s+", block))
        if len(opts) < 4:
            continue
        # Only the first 5 option markers belong to the question.
        opts = opts[:5]
        values = []
        for j, opt in enumerate(opts):
            e = opts[j + 1].start() if j + 1 < len(opts) else len(block)
            value = block[opt.end():e]
            value = clean_page_headers(value)
            # Remove accidental trailing answer/solution material.
            value = re.split(r"\b(?:Correct\s+(?:Answer|Option)|Solution\s+for\s+Question)\b", value, maxsplit=1, flags=re.I)[0]
            values.append(norm(value))
        while len(values) < 5:
            values.append("")

        stem = clean_page_headers(block[:opts[0].start()])
        stem = re.sub(r"^\s*\d{1,5}\.\s*", "", stem)
        if len(stem) < 15:
            continue
        if any(not values[j] for j in range(4)):
            continue

        qnum = int(m.group(1))
        answer = answers.get(qnum, "")
        if answer not in LETTERS:
            continue

        # Page from the nearest embedded page marker, otherwise section start page is assigned later.
        page = 1
        markers = list(re.finditer(r"(?im)\[\[MEDQ_PAGE_(\d+)\]\]", block[: max(0, opts[0].start())]))
        if markers:
            page = int(markers[-1].group(1))
        questions.append({
            "number": qnum,
            "stem": stem,
            "option_a": values[0],
            "option_b": values[1],
            "option_c": values[2],
            "option_d": values[3],
            "option_e": values[4],
            "correct_option": answer,
            "chapter": chapter,
            "source_page": page,
        })
    return questions


def process_book(path: str) -> List[Dict]:
    pages = build_pages(path)
    print(f"[PDF] pages read: {len(pages)}")
    # Embed page markers so source_page can be recovered even when a question crosses a page.
    marked = [f"[[MEDQ_PAGE_{i + 1}]]\n{p}" for i, p in enumerate(pages)]
    ranges = section_ranges(marked)
    print(f"[PDF] detected {len(ranges)} lesson/section ranges")
    all_questions: List[Dict] = []
    for title, start, end in ranges:
        sec = "\n".join(marked[start - 1:end])
        qs = extract_section_questions(sec, title)
        # Fallback source page to the section start where marker recovery is unavailable.
        for q in qs:
            if not q.get("source_page") or q["source_page"] == 1:
                q["source_page"] = start
        all_questions.extend(qs)
    return all_questions


def save_rows(rows: List[Dict]) -> int:
    saved = 0
    for i in range(0, len(rows), SAVE_BATCH):
        part = rows[i:i + SAVE_BATCH]
        try:
            res = sb.table("questions").insert(part).execute()
            saved += len(res.data or [])
            print(f"[DB] inserted batch {i + 1}-{i + len(part)} ({len(res.data or [])})")
        except Exception as exc:
            print(f"[DB] batch failed ({len(part)}): {exc}")
            for row in part:
                try:
                    res = sb.table("questions").insert(row).execute()
                    if res.data:
                        saved += 1
                except Exception as one_exc:
                    print(f"[DB] skipped one question: {one_exc}")
    return saved


def main():
    print(
        f"MEDQ MCQ DIRECT EXTRACTOR v3 | book={BOOK_ID} | "
        f"subject={BOOK_SUBJECT} | track={BOOK_EXAM_TRACK}"
    )
    path = download_pdf()
    existing = existing_stems()
    print(f"[BANK] existing stems for this book: {len(existing)}")

    candidates = process_book(path)
    print(f"[PARSE] detected {len(candidates)} answer-verified MCQs before dedupe")

    seen = set(existing)
    rows = []
    for q in candidates:
        k = stem_key(q["stem"])
        if not k or k in seen:
            continue
        seen.add(k)
        rows.append({
            "book_id": BOOK_ID,
            "exam_type": exam_type(),
            "question_type": "recall",
            "stem": q["stem"],
            "option_a": q["option_a"],
            "option_b": q["option_b"],
            "option_c": q["option_c"],
            "option_d": q["option_d"],
            "option_e": q["option_e"],
            "correct_option": q["correct_option"],
            "explanation": "Answer and question extracted directly from the source Qbank.",
            "subject": BOOK_SUBJECT,
            "chapter": q["chapter"],
            "topic": q["chapter"],
            "difficulty": "medium",
            "source_page": q["source_page"],
        })
        if len(rows) >= MAX_MCQS_PER_RUN:
            break

    print(f"[PARSE] {len(rows)} NEW MCQs ready to save")
    saved = save_rows(rows)
    print(f"MEDQ DIRECT EXTRACTOR COMPLETE: saved {saved} new questions.")
    if len(rows) >= MAX_MCQS_PER_RUN:
        print("[CONTINUE] Per-run cap reached; the next run will dedupe and continue with remaining unseen MCQs.")


if __name__ == "__main__":
    main()
