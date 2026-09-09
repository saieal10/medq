
import os
import io
import re
import json
import time
import tempfile
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
import fitz
import pytesseract
import requests
from PIL import Image
from botocore.config import Config
from supabase import create_client


# =========================================================
# MEDQ FULL-BOOK QUESTION ENGINE
# =========================================================
# One worker handles both:
#   A) MCQ books -> direct question extraction first
#      (fast; avoids wasting Gemini calls recreating MCQs)
#   B) Theory textbooks -> clinical filtering + parallel Gemini
#      generation across the complete book
#
# It deliberately ignores front matter, author/publisher material,
# contents, indexes, references and other non-question material.
# =========================================================


BOOK_ID = os.getenv("BOOK_ID")
FILE_KEY = os.getenv("FILE_KEY")
BOOK_SUBJECT = os.getenv("BOOK_SUBJECT", "General")
BOOK_EXAM_TRACK = os.getenv("BOOK_EXAM_TRACK", "FMGE_NEET_PG").upper()

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "medq-books")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "18000"))
OCR_DPI = int(os.getenv("OCR_DPI", "150"))
NATIVE_TEXT_MIN_CHARS = int(os.getenv("NATIVE_TEXT_MIN_CHARS", "140"))
MIN_USABLE_PAGE_CHARS = int(os.getenv("MIN_USABLE_PAGE_CHARS", "80"))

# Theory generation:
QUESTIONS_PER_CHUNK = int(os.getenv("QUESTIONS_PER_CHUNK", "8"))
MAX_PARALLEL_AI = int(os.getenv("MAX_PARALLEL_AI", "3"))
AI_RETRIES = int(os.getenv("AI_RETRIES", "4"))
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "150"))

# MCQ extraction:
MCQ_MIN_DETECTED = int(os.getenv("MCQ_MIN_DETECTED", "8"))
MCQ_AI_BATCH = int(os.getenv("MCQ_AI_BATCH", "20"))

# Do not use the old seed limitation.
FULL_BOOK = True


required = {
    "BOOK_ID": BOOK_ID,
    "FILE_KEY": FILE_KEY,
    "R2_ACCOUNT_ID": R2_ACCOUNT_ID,
    "R2_ACCESS_KEY_ID": R2_ACCESS_KEY_ID,
    "R2_SECRET_ACCESS_KEY": R2_SECRET_ACCESS_KEY,
    "R2_BUCKET_NAME": R2_BUCKET_NAME,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_SECRET_KEY": SUPABASE_SECRET_KEY,
}
missing = [k for k, v in required.items() if not v]
if missing:
    raise RuntimeError("Missing required environment variables: " + ", ".join(missing))


supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

r2 = boto3.client(
    "s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(signature_version="s3v4"),
)


# =========================================================
# STATUS
# =========================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat()


def update_book(fields: Dict[str, Any]):
    try:
        supabase.table("books").update(fields).eq("id", BOOK_ID).execute()
    except Exception as exc:
        print("[DB] book update failed:", exc)


def set_stage(stage: str, **extra):
    payload = {"processing_stage": stage}
    payload.update(extra)
    update_book(payload)


# =========================================================
# TEXT CLEANING / FILTERING
# =========================================================

def clean_text(text: str) -> str:
    text = (text or "").replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_label(value: str, max_len: int = 250) -> str:
    value = clean_text(value)
    value = re.sub(r"\s+", " ", value)
    return value[:max_len].strip(" -:;,")


NONCLINICAL_TERMS = [
    "preface", "foreword", "about the author", "about the authors",
    "author biography", "author bio", "contributors", "editorial board",
    "acknowledg", "dedication", "copyright", "all rights reserved",
    "isbn", "library of congress", "publisher", "publication history",
    "table of contents", "contents", "index", "bibliography",
    "references", "appendix", "answer key", "answers at the end",
    "video library", "disclaimer", "legal notice", "permissions",
]


def looks_nonclinical_text(text: str) -> bool:
    t = clean_text(text).lower()
    if not t:
        return True

    # Strong metadata pages.
    hits = sum(1 for term in NONCLINICAL_TERMS if term in t)
    if hits >= 2:
        return True

    # A single very strong front-matter marker near the start.
    first = t[:1800]
    if any(x in first for x in [
        "preface", "foreword", "about the author", "copyright",
        "table of contents", "acknowledgments", "dedication"
    ]):
        return True

    # Typical contents page.
    lines = [x.strip() for x in t.splitlines() if x.strip()]
    toc_like = 0
    for line in lines[:100]:
        if re.search(r"\.{2,}\s*\d{1,4}\s*$", line):
            toc_like += 1
        elif re.search(r"\s\d{1,4}\s*$", line) and len(line) < 100:
            toc_like += 1
    if toc_like >= 10:
        return True

    return False


def is_nonclinical_chapter(title: str) -> bool:
    t = normalize_label(title).lower()
    if not t:
        return False
    return any(term in t for term in NONCLINICAL_TERMS)


# =========================================================
# PDF / OCR
# =========================================================

def download_pdf(destination: str):
    print("[R2] Downloading:", FILE_KEY)
    r2.download_file(R2_BUCKET_NAME, FILE_KEY, destination)
    size = os.path.getsize(destination)
    print(f"[R2] Downloaded {size / 1024 / 1024:.1f} MB")


def ocr_page(page) -> str:
    zoom = OCR_DPI / 72
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    image = Image.open(io.BytesIO(pix.tobytes("png")))
    return clean_text(pytesseract.image_to_string(image, lang="eng"))


def build_toc_ranges(document) -> List[Dict[str, Any]]:
    toc = document.get_toc(simple=True) or []
    cleaned = []

    for row in toc:
        if len(row) < 3:
            continue
        try:
            level, title, page = int(row[0]), normalize_label(row[1]), int(row[2])
        except Exception:
            continue
        if page < 1 or not title:
            continue
        cleaned.append((level, title, page))

    if not cleaned:
        return []

    counts = {}
    for level, title, page in cleaned:
        if not is_nonclinical_chapter(title):
            counts[level] = counts.get(level, 0) + 1

    levels = [level for level, count in sorted(counts.items()) if count >= 5]
    preferred = levels[0] if levels else None
    if preferred is None:
        return []

    entries = [(l, t, p) for l, t, p in cleaned if l == preferred]
    ranges = []

    for i, (_, title, start) in enumerate(entries):
        if is_nonclinical_chapter(title):
            continue
        end = entries[i + 1][2] - 1 if i + 1 < len(entries) else len(document)
        ranges.append({
            "title": title,
            "page_start": max(1, start),
            "page_end": max(start, end),
        })

    print(f"[TOC] Clinical chapter ranges: {len(ranges)}")
    return ranges


def chapter_for_page(page_number: int, ranges):
    for item in ranges:
        if item["page_start"] <= page_number <= item["page_end"]:
            return item["title"]
    return None


def fallback_heading(text: str) -> Optional[str]:
    lines = [normalize_label(x) for x in text.splitlines() if normalize_label(x)]
    for candidate in lines[:30]:
        if len(candidate) > 100 or is_nonclinical_chapter(candidate):
            continue
        words = candidate.split()
        if not (2 <= len(words) <= 12):
            continue

        if re.match(r"^(chapter\s+)?\d+\s*[:.\-–—]?\s+\S+", candidate, re.I):
            return candidate

        letters = [c for c in candidate if c.isalpha()]
        if len(letters) >= 10:
            ratio = sum(c.isupper() for c in letters) / len(letters)
            if ratio >= 0.88:
                return candidate.title()

    return None


def extract_pages(pdf_path: str):
    document = fitz.open(pdf_path)
    total = len(document)
    ranges = build_toc_ranges(document)

    update_book({
        "page_count": total,
        "total_pages": total,
        "processed_pages": 0,
        "extraction_progress": 0,
    })

    extracted = []
    active_heading = None

    for i in range(total):
        page = document[i]
        page_no = i + 1

        native = clean_text(page.get_text("text"))
        text = native
        method = "text"

        if len(native) < NATIVE_TEXT_MIN_CHARS:
            try:
                ocr = ocr_page(page)
                if len(ocr) > len(native):
                    text = ocr
                    method = "ocr"
            except Exception as exc:
                print(f"[OCR] page {page_no} failed:", exc)

        chapter = chapter_for_page(page_no, ranges)
        if not ranges:
            detected = fallback_heading(text)
            if detected:
                active_heading = detected
            chapter = active_heading

        frontmatter = looks_nonclinical_text(text)
        if chapter and is_nonclinical_chapter(chapter):
            frontmatter = True

        if len(text) >= MIN_USABLE_PAGE_CHARS:
            extracted.append({
                "page": page_no,
                "text": text,
                "method": method,
                "chapter": chapter,
                "question_eligible": not frontmatter,
            })

        progress = int(page_no / max(total, 1) * 100)
        if page_no == total or progress % 2 == 0:
            update_book({
                "processed_pages": page_no,
                "extraction_progress": progress,
            })

        if page_no % 100 == 0:
            print(f"[PDF] {page_no}/{total}")

    document.close()
    print(f"[PDF] usable pages: {len(extracted)}/{total}")
    return extracted, ranges


# =========================================================
# CHUNKS
# =========================================================

def make_chunks(pages):
    chunks = []
    current = ""
    page_numbers = []
    methods = []
    chapter = None
    eligible = False

    def flush():
        nonlocal current, page_numbers, methods, chapter, eligible
        if not current or not page_numbers:
            return
        chunks.append({
            "text": current.strip(),
            "pages": page_numbers.copy(),
            "methods": methods.copy(),
            "chapter": normalize_label(chapter or "Unclassified clinical medicine"),
            "question_eligible": bool(eligible),
        })
        current = ""
        page_numbers = []
        methods = []
        chapter = None
        eligible = False

    for page in pages:
        page_chapter = page.get("chapter")
        addition = f"\n\n--- PAGE {page['page']} ---\n{page['text']}"

        chapter_changed = (
            current and page_chapter and chapter and page_chapter != chapter
        )
        size_exceeded = current and len(current) + len(addition) > CHUNK_SIZE

        if chapter_changed or size_exceeded:
            flush()

        if chapter is None:
            chapter = page_chapter

        current += addition
        page_numbers.append(page["page"])
        methods.append(page["method"])
        eligible = eligible or bool(page.get("question_eligible"))

    flush()

    # Final safety pass.
    cleaned = []
    for chunk in chunks:
        ch = normalize_label(chunk["chapter"])
        if is_nonclinical_chapter(ch):
            chunk["question_eligible"] = False
        chunk["chapter"] = ch
        cleaned.append(chunk)

    eligible_count = sum(1 for c in cleaned if c["question_eligible"])
    print(f"[CHUNK] {len(cleaned)} total; {eligible_count} eligible")
    return cleaned


def extraction_method(methods):
    unique = set(methods)
    if unique == {"text"}:
        return "text"
    if unique == {"ocr"}:
        return "ocr"
    return "mixed"


def save_book_chunks(chunks):
    # Remove only this book's old chunks/questions so reprocessing is clean.
    try:
        supabase.table("questions").delete().eq("book_id", BOOK_ID).execute()
    except Exception as exc:
        print("[DB] old questions cleanup failed:", exc)

    try:
        supabase.table("book_chunks").delete().eq("book_id", BOOK_ID).execute()
    except Exception as exc:
        print("[DB] old chunks cleanup failed:", exc)

    rows = []
    for idx, chunk in enumerate(chunks):
        pages = chunk["pages"]
        rows.append({
            "book_id": BOOK_ID,
            "chunk_index": idx,
            "chapter": normalize_label(chunk["chapter"], 250),
            "section": None,
            "topic": None,
            "page_start": min(pages),
            "page_end": max(pages),
            "content": chunk["text"],
            "word_count": len(chunk["text"].split()),
            "extraction_method": extraction_method(chunk["methods"]),
            "processing_status": "ready",
        })

    saved = []
    for start in range(0, len(rows), 25):
        result = supabase.table("book_chunks").insert(rows[start:start + 25]).execute()
        saved.extend(result.data or [])

    print(f"[DB] saved {len(saved)} chunks")
    return saved


# =========================================================
# MCQ BOOK DETECTION
# =========================================================

QUESTION_START_RE = re.compile(
    r"^\s*(?:Q(?:uestion)?\s*)?(\d{1,5})\s*[\.\):\-]\s*(.+)$",
    re.I
)

OPTION_RE = re.compile(
    r"^\s*[\(\[]?([A-E])[\)\].:\-]\s+(.+)$",
    re.I
)

ANSWER_RE = re.compile(
    r"\b(?:answer|ans|correct\s+answer|correct\s+option|key)\s*[:\-]?\s*[\(\[]?([A-E])[\)\].]?\b",
    re.I
)


def clean_mcq_line(line):
    line = clean_text(line)
    # Remove common OCR bullets.
    line = re.sub(r"^[•▪◦]\s*", "", line)
    return line.strip()


def parse_mcq_blocks(pages):
    """
    Extract actual MCQ-shaped blocks from clinically eligible pages.
    It does not send the page to AI just to rediscover existing MCQs.
    """
    blocks = []
    current = None

    for page in pages:
        if not page.get("question_eligible"):
            continue

        lines = [clean_mcq_line(x) for x in page["text"].splitlines()]
        lines = [x for x in lines if x]

        for line in lines:
            m = QUESTION_START_RE.match(line)

            # Strong question start: numbered item followed by real prose.
            if m and len(m.group(2).strip()) >= 12:
                if current:
                    blocks.append(current)
                current = {
                    "number": m.group(1),
                    "stem_lines": [m.group(2).strip()],
                    "options": {},
                    "answer": None,
                    "page": page["page"],
                    "chapter": page.get("chapter"),
                    "raw_lines": [line],
                }
                continue

            if current is None:
                continue

            om = OPTION_RE.match(line)
            if om:
                letter = om.group(1).upper()
                current["options"][letter] = om.group(2).strip()
                current["raw_lines"].append(line)
                continue

            am = ANSWER_RE.search(line)
            if am:
                current["answer"] = am.group(1).upper()
                current["raw_lines"].append(line)
                continue

            # Answer may be written as "Ans. C"
            am2 = re.search(r"^\s*(?:Ans|Answer)\.?\s*([A-E])\s*$", line, re.I)
            if am2:
                current["answer"] = am2.group(1).upper()
                current["raw_lines"].append(line)
                continue

            # Continue stem before options; after options, keep explanation
            # text but don't merge it into the stem.
            if not current["options"]:
                current["stem_lines"].append(line)
            else:
                current["raw_lines"].append(line)

    if current:
        blocks.append(current)

    # Keep only genuine 5-option MCQs.
    valid = []
    for b in blocks:
        if len(b["options"]) == 5 and all(x in b["options"] for x in "ABCDE"):
            stem = clean_text(" ".join(b["stem_lines"]))
            if len(stem) >= 25:
                b["stem"] = stem
                valid.append(b)

    print(f"[MCQ] detected {len(valid)} five-option question blocks")
    return valid


def mcq_book_likelihood(pages, detected_count):
    eligible_pages = [p for p in pages if p.get("question_eligible")]
    if not eligible_pages:
        return False

    sample = eligible_pages[: min(120, len(eligible_pages))]
    option_lines = 0
    numbered_lines = 0

    for p in sample:
        for line in p["text"].splitlines():
            if OPTION_RE.match(clean_mcq_line(line)):
                option_lines += 1
            if QUESTION_START_RE.match(clean_mcq_line(line)):
                numbered_lines += 1

    # Existing MCQ books normally show repeated question + A-E structure.
    return (
        detected_count >= MCQ_MIN_DETECTED
        and option_lines >= detected_count * 2
        and numbered_lines >= detected_count
    )


# =========================================================
# GEMINI
# =========================================================

def gemini_request(system_prompt, user_prompt):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured in GitHub Actions secrets.")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.15,
            "maxOutputTokens": 12000,
            "responseMimeType": "application/json",
        },
    }

    last = None

    for attempt in range(1, AI_RETRIES + 1):
        try:
            response = requests.post(
                url,
                headers={
                    "x-goog-api-key": GEMINI_API_KEY,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=AI_TIMEOUT,
            )

            if response.status_code in (429, 500, 502, 503, 504):
                last = f"Gemini {response.status_code}: {response.text[:500]}"
                wait = min(30, 2 ** attempt)
                print(f"[AI] transient error; retrying in {wait}s")
                time.sleep(wait)
                continue

            response.raise_for_status()
            data = response.json()

            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            content = "\n".join(
                p.get("text", "") for p in parts if p.get("text")
            ).strip()

            if not content:
                raise RuntimeError("Gemini returned empty content.")

            # Be tolerant if the model wraps JSON despite responseMimeType.
            content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.I)
            content = re.sub(r"\s*```$", "", content)
            return json.loads(content)

        except requests.HTTPError as exc:
            last = str(exc)
            print("[AI] HTTP error:", last)
            if attempt < AI_RETRIES:
                time.sleep(min(30, 2 ** attempt))
        except Exception as exc:
            last = str(exc)
            print("[AI] error:", last)
            if attempt < AI_RETRIES:
                time.sleep(min(30, 2 ** attempt))

    raise RuntimeError(f"Gemini failed after retries: {last}")


# =========================================================
# MCQ BOOK -> ANSWER/EXPLANATION ENRICHMENT
# =========================================================

MCQ_SYSTEM = """
You are MedQ's medical question verifier.

The input contains MCQs extracted from a medical MCQ book. The text itself
may contain OCR noise.

Your job is NOT to rewrite the question unless necessary to repair obvious
OCR damage. Preserve the source question's meaning and options.

For every item:
- determine the single best answer
- give a concise medically accurate explanation
- assign a clinically useful topic
- assign easy/medium/hard
- assign question_type: clinical_reasoning, diagnosis, investigation,
  management, pharmacology, pathology, anatomy, physiology, microbiology,
  or concept
- reject an item only if it is clearly not a medical MCQ

Ignore:
- author biographies
- prefaces
- publisher information
- contents
- advertisements
- acknowledgements
- abstract/introductory publishing material
- non-medical trivia

Return ONLY JSON:
{
  "items": [
    {
      "id": 1,
      "keep": true,
      "correct_option": "A",
      "explanation": "...",
      "topic": "...",
      "difficulty": "medium",
      "question_type": "clinical_reasoning"
    }
  ]
}
"""


def enrich_mcq_batch(batch):
    payload = []
    for idx, q in enumerate(batch, start=1):
        payload.append({
            "id": idx,
            "question": q["stem"],
            "A": q["options"]["A"],
            "B": q["options"]["B"],
            "C": q["options"]["C"],
            "D": q["options"]["D"],
            "E": q["options"]["E"],
            "source_answer": q.get("answer"),
            "page": q["page"],
        })

    result = gemini_request(
        MCQ_SYSTEM,
        "Verify these extracted MCQs. Do not invent a different question.\n\n"
        + json.dumps(payload, ensure_ascii=False),
    )
    return result.get("items", [])


def prepare_mcq_question(q, meta):
    if not meta.get("keep", True):
        return None

    correct = str(meta.get("correct_option") or q.get("answer") or "").upper().strip()
    if correct not in "ABCDE":
        return None

    options = [q["options"].get(x, "").strip() for x in "ABCDE"]
    if any(not x for x in options) or len(set(x.lower() for x in options)) != 5:
        return None

    stem = clean_text(q["stem"])
    explanation = clean_text(str(meta.get("explanation") or ""))

    if len(stem) < 25 or len(explanation) < 20:
        return None

    return {
        "book_id": BOOK_ID,
        "source_chunk_id": None,
        "subject": BOOK_SUBJECT,
        "chapter": normalize_label(q.get("chapter") or BOOK_SUBJECT, 250),
        "topic": normalize_label(meta.get("topic") or "", 250),
        "subtopic": None,
        "exam_type": "AMC" if BOOK_EXAM_TRACK == "AMC" else "FMGE",
        "question_type": normalize_label(meta.get("question_type") or "concept", 100),
        "difficulty": str(meta.get("difficulty") or "medium").lower(),
        "stem": stem,
        "option_a": options[0],
        "option_b": options[1],
        "option_c": options[2],
        "option_d": options[3],
        "option_e": options[4],
        "correct_option": correct,
        "explanation": explanation,
        "source_page": int(q["page"]),
        "source_page_end": int(q["page"]),
        "review_status": "generated",
        "quality_score": None,
        "reviewer_notes": None,
    }


def save_mcq_questions(questions):
    if not questions:
        return 0

    # Avoid duplicates within this book.
    seen = set()
    unique = []
    for q in questions:
        key = re.sub(r"\W+", "", q["stem"].lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(q)

    # Insert in manageable batches.
    saved = 0
    for start in range(0, len(unique), 50):
        result = supabase.table("questions").insert(unique[start:start + 50]).execute()
        saved += len(result.data or [])

    print(f"[MCQ] saved {saved} questions")
    return saved


def process_mcq_book(pages, detected):
    set_stage("extracting_mcqs", extraction_progress=100, question_progress=0)

    total = 0
    batches = [detected[i:i + MCQ_AI_BATCH] for i in range(0, len(detected), MCQ_AI_BATCH)]

    for i, batch in enumerate(batches, start=1):
        print(f"[MCQ] verifying batch {i}/{len(batches)}")
        try:
            metas = enrich_mcq_batch(batch)
            by_id = {
                int(x.get("id")): x
                for x in metas
                if str(x.get("id", "")).isdigit()
            }
            prepared = []
            for idx, q in enumerate(batch, start=1):
                item = by_id.get(idx, {})
                clean = prepare_mcq_question(q, item)
                if clean:
                    prepared.append(clean)

            total += save_mcq_questions(prepared)
        except Exception as exc:
            print("[MCQ] batch failed:", exc)

        progress = int(i / max(len(batches), 1) * 100)
        update_book({
            "question_progress": progress,
            "questions_generated": total,
        })

    return total


# =========================================================
# THEORY TEXTBOOK -> FULL-BOOK PARALLEL GENERATION
# =========================================================

THEORY_SYSTEM = """
You are MedQ's medical examination question writer.

Create NEW, high-quality single-best-answer medical MCQs from the supplied
clinical textbook content.

The source may be a textbook chapter, not an MCQ book.

Hard rules:
1. Use ONLY medically relevant clinical/scientific content from the source.
2. NEVER create questions from:
   - preface
   - foreword
   - about-the-author
   - contributor biographies
   - publisher/copyright information
   - acknowledgements
   - contents
   - index
   - references/bibliography
   - advertisements
   - dedication
   - abstract/metadata that is not medical teaching content
   - page headers/footers
3. Ignore generic author/publishing information even if it appears inside a
   chunk.
4. Do not make trivial questions from isolated definitions unless clinically
   useful.
5. Do not copy a textbook sentence as the stem.
6. Questions must be useful for AMC or FMGE/NEET-PG preparation.
7. AMC track: emphasize clinical reasoning, next best step, interpretation,
   diagnosis, management and safety.
8. FMGE track: emphasize high-yield diagnosis, pathology, pharmacology,
   investigations, treatment, complications and core concepts.
9. Exactly five options A-E.
10. Exactly one best answer.
11. Give a clear explanation.
12. Give topic and subtopic when possible.
13. Include source page start/end.

Return ONLY JSON:
{
  "items": [
    {
      "exam_type": "AMC",
      "question_type": "clinical_reasoning",
      "stem": "...",
      "option_a": "...",
      "option_b": "...",
      "option_c": "...",
      "option_d": "...",
      "option_e": "...",
      "correct_option": "A",
      "explanation": "...",
      "topic": "...",
      "subtopic": "...",
      "difficulty": "medium",
      "source_page": 10,
      "source_page_end": 12
    }
  ]
}
"""


def generate_theory_chunk(chunk):
    pages = chunk["pages"]
    page_start = min(pages)
    page_end = max(pages)

    track_instruction = (
        "AMC"
        if BOOK_EXAM_TRACK == "AMC"
        else "FMGE/NEET-PG"
    )

    prompt = f"""
Exam track: {track_instruction}
Book subject: {BOOK_SUBJECT}
Chapter: {chunk.get("chapter")}
Source pages: {page_start}-{page_end}

Generate exactly {QUESTIONS_PER_CHUNK} NEW useful MCQs if the source supports
that many. If the chunk is mostly non-teaching material, return fewer or an
empty items array rather than inventing questions.

SOURCE:
{chunk["content"]}
"""

    return gemini_request(THEORY_SYSTEM, prompt).get("items", [])


def prepare_generated_question(q, chunk):
    required_fields = [
        "stem", "option_a", "option_b", "option_c", "option_d",
        "option_e", "correct_option", "explanation"
    ]
    if any(not q.get(k) for k in required_fields):
        return None

    correct = str(q.get("correct_option")).upper().strip()
    if correct not in "ABCDE":
        return None

    options = [clean_text(str(q[k])) for k in [
        "option_a", "option_b", "option_c", "option_d", "option_e"
    ]]
    if len(set(x.lower() for x in options)) != 5:
        return None

    stem = clean_text(str(q["stem"]))
    explanation = clean_text(str(q["explanation"]))
    if len(stem) < 25 or len(explanation) < 30:
        return None

    source_start = min(chunk["pages"])
    source_end = max(chunk["pages"])

    try:
        p1 = int(q.get("source_page", source_start))
    except Exception:
        p1 = source_start
    try:
        p2 = int(q.get("source_page_end", p1))
    except Exception:
        p2 = p1

    p1 = max(source_start, min(source_end, p1))
    p2 = max(p1, min(source_end, p2))

    return {
        "book_id": BOOK_ID,
        "source_chunk_id": chunk.get("id"),
        "subject": BOOK_SUBJECT,
        "chapter": normalize_label(q.get("chapter") or chunk.get("chapter") or BOOK_SUBJECT, 250),
        "topic": normalize_label(q.get("topic") or "", 250),
        "subtopic": normalize_label(q.get("subtopic") or "", 250) or None,
        "exam_type": (
            "AMC" if BOOK_EXAM_TRACK == "AMC" else "FMGE"
        ),
        "question_type": normalize_label(q.get("question_type") or "concept", 100),
        "difficulty": str(q.get("difficulty") or "medium").lower(),
        "stem": stem,
        "option_a": options[0],
        "option_b": options[1],
        "option_c": options[2],
        "option_d": options[3],
        "option_e": options[4],
        "correct_option": correct,
        "explanation": explanation,
        "source_page": p1,
        "source_page_end": p2,
        "review_status": "generated",
        "quality_score": None,
        "reviewer_notes": None,
    }


def chunk_has_clinical_content(chunk):
    text = chunk["text"].lower()
    chapter = (chunk.get("chapter") or "").lower()

    if is_nonclinical_chapter(chapter):
        return False

    # Explicitly reject publishing-only chunks.
    if looks_nonclinical_text(text) and len(text) < 5000:
        return False

    clinical_terms = [
        "patient", "diagnosis", "symptom", "sign", "disease", "syndrome",
        "treatment", "therapy", "drug", "dose", "investigation", "laboratory",
        "imaging", "pathology", "clinical", "management", "prognosis",
        "complication", "physiology", "anatomy", "infection", "cancer",
        "hypertension", "diabetes", "heart", "lung", "kidney", "liver",
        "neurolog", "pregnan", "child", "antibiotic", "surgery"
    ]
    hits = sum(1 for term in clinical_terms if term in text)
    return hits >= 2


def save_generated_questions(questions):
    if not questions:
        return 0

    seen = set()
    unique = []

    for q in questions:
        key = re.sub(r"\W+", "", q["stem"].lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(q)

    saved = 0
    for start in range(0, len(unique), 50):
        result = supabase.table("questions").insert(unique[start:start + 50]).execute()
        saved += len(result.data or [])

    return saved


def process_theory_book(chunks):
    eligible = [c for c in chunks if c.get("question_eligible") and chunk_has_clinical_content(c)]

    total = len(eligible)
    print(f"[AI] FULL BOOK mode: {total} clinical chunks")
    set_stage("generating_questions", extraction_progress=100, question_progress=0)

    total_saved = 0
    completed = 0

    # Parallel calls are deliberately capped. This is much faster than the
    # old one-by-one + sleep design, while retries protect against 429/503.
    with ThreadPoolExecutor(max_workers=max(1, MAX_PARALLEL_AI)) as pool:
        future_map = {
            pool.submit(generate_theory_chunk, chunk): chunk
            for chunk in eligible
        }

        for future in as_completed(future_map):
            chunk = future_map[future]
            completed += 1

            try:
                generated = future.result()
                prepared = []
                for q in generated:
                    clean = prepare_generated_question(q, chunk)
                    if clean:
                        prepared.append(clean)

                saved = save_generated_questions(prepared)
                total_saved += saved

                print(
                    f"[AI] {completed}/{total} | "
                    f"{chunk.get('chapter')} | "
                    f"pages {min(chunk['pages'])}-{max(chunk['pages'])} | "
                    f"saved {saved}"
                )
            except Exception as exc:
                print(
                    f"[AI] chunk failed {chunk.get('chapter')} "
                    f"{min(chunk['pages'])}-{max(chunk['pages'])}: {exc}"
                )

            progress = int(completed / max(total, 1) * 100)
            update_book({
                "question_progress": progress,
                "questions_generated": total_saved,
            })

    return total_saved


# =========================================================
# MAIN
# =========================================================

def main():
    print("==============================================")
    print("MEDQ FULL-BOOK QUESTION ENGINE")
    print(f"Book: {BOOK_ID}")
    print(f"Subject: {BOOK_SUBJECT}")
    print(f"Exam track: {BOOK_EXAM_TRACK}")
    print("Mode: FULL BOOK / NO 24-CHUNK SEED LIMIT")
    print("==============================================")

    set_stage(
        "downloading",
        processing_started_at=utc_now(),
        error_message=None,
    )

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = os.path.join(temp_dir, "book.pdf")
            download_pdf(pdf_path)

            set_stage("extracting", extraction_progress=0)
            pages, toc_ranges = extract_pages(pdf_path)

            if not pages:
                raise RuntimeError("No usable text could be extracted from this PDF.")

            set_stage("building_knowledge_base", extraction_progress=100)
            chunks = make_chunks(pages)

            if not chunks:
                raise RuntimeError("No usable chunks were created.")

            saved_chunks = save_book_chunks(chunks)

            update_book({
                "status": "ready",
                "processing_stage": "knowledge_ready",
                "extraction_progress": 100,
                "processed_pages": len(pages),
                "processing_completed_at": utc_now(),
                "error_message": None,
            })

            # Detect an MCQ book from the structure, not its filename.
            detected_mcqs = parse_mcq_blocks(pages)
            is_mcq = mcq_book_likelihood(pages, detected_mcqs)

            print(
                f"[CLASSIFY] detected_mcqs={len(detected_mcqs)} "
                f"-> {'MCQ_BOOK' if is_mcq else 'THEORY_BOOK'}"
            )

            if is_mcq:
                total_questions = process_mcq_book(pages, detected_mcqs)
            else:
                total_questions = process_theory_book(saved_chunks)

            update_book({
                "status": "ready",
                "processing_stage": "ready",
                "extraction_progress": 100,
                "question_progress": 100,
                "questions_generated": total_questions,
                "processed_pages": len(pages),
                "processing_completed_at": utc_now(),
                "error_message": None,
            })

            print("==============================================")
            print("MEDQ PROCESSING COMPLETE")
            print(f"Chunks: {len(saved_chunks)}")
            print(f"Questions: {total_questions}")
            print("==============================================")

    except Exception as exc:
        print("==============================================")
        print("MEDQ PROCESSING FAILED")
        print(str(exc))
        print("==============================================")
        try:
            update_book({
                "status": "failed",
                "processing_stage": "failed",
                "error_message": str(exc)[:1000],
            })
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
