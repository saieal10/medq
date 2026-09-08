import os
import io
import re
import json
import time
import tempfile
import statistics
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

import boto3
import fitz
import pytesseract
import requests

from PIL import Image
from botocore.config import Config
from supabase import create_client


# =========================================================
# ENVIRONMENT
# =========================================================

BOOK_ID = os.getenv("BOOK_ID")
FILE_KEY = os.getenv("FILE_KEY")
BOOK_SUBJECT = os.getenv("BOOK_SUBJECT", "General")

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "medq-books")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


# =========================================================
# PROCESSING SETTINGS
# =========================================================

# Entire textbook is extracted. No page cap.
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "18000"))
OCR_DPI = int(os.getenv("OCR_DPI", "150"))
NATIVE_TEXT_MIN_CHARS = int(os.getenv("NATIVE_TEXT_MIN_CHARS", "140"))
MIN_USABLE_PAGE_CHARS = int(os.getenv("MIN_USABLE_PAGE_CHARS", "80"))

# IMPORTANT:
# Uploading a textbook should first build a clean knowledge base.
# It should NOT try to manufacture thousands of MCQs in one GitHub run.
#
# Seed generation is deliberately modest. More MCQs should later be
# generated on demand by chapter/topic.
GENERATE_SEED_QUESTIONS = (
    os.getenv("GENERATE_SEED_QUESTIONS", "true").lower() == "true"
)
SEED_CHUNK_LIMIT = int(os.getenv("SEED_CHUNK_LIMIT", "24"))
QUESTIONS_PER_CHUNK = int(os.getenv("QUESTIONS_PER_CHUNK", "5"))

AI_DELAY_SECONDS = float(os.getenv("AI_DELAY_SECONDS", "3"))
AI_RETRIES = int(os.getenv("AI_RETRIES", "2"))


# =========================================================
# VALIDATION
# =========================================================

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
    raise RuntimeError(
        "Missing required environment variables: " + ", ".join(missing)
    )


# =========================================================
# CLIENTS
# =========================================================

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
# GENERAL HELPERS
# =========================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_book(fields: Dict[str, Any]):
    (
        supabase
        .table("books")
        .update(fields)
        .eq("id", BOOK_ID)
        .execute()
    )


def set_stage(stage: str, status: str = "processing", **extra):
    payload = {
        "status": status,
        "processing_stage": stage,
    }
    payload.update(extra)
    update_book(payload)
    print(f"[BOOK] {stage} | {status}")


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+\n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Common extraction garbage.
    text = re.sub(r"(?m)^\s*\d+\s*$", "", text)

    return text.strip()


def normalize_label(value: str, max_len: int = 160) -> str:
    value = clean_text(str(value or ""))
    value = re.sub(r"\s+", " ", value).strip(" -–—:;,.")
    return value[:max_len]


def looks_like_junk_label(value: str) -> bool:
    label = normalize_label(value).lower()

    if not label:
        return True

    if re.fullmatch(r"e\d+", label):
        return True

    if re.fullmatch(r"(part|section|chapter)\s+\d+", label):
        return True

    if re.fullmatch(r"\d+", label):
        return True

    if len(label) < 4:
        return True

    junk_terms = [
        "preface",
        "foreword",
        "acknowledg",
        "contributors",
        "editorial board",
        "copyright",
        "contents",
        "table of contents",
        "video library",
        "atlas of",
        "index",
        "references",
        "bibliography",
        "appendix",
        "abbreviations",
        "illustration credits",
        "about the author",
        "dedication",
    ]

    return any(term in label for term in junk_terms)


def is_frontmatter_text(text: str) -> bool:
    sample = clean_text(text).lower()[:5000]

    if not sample:
        return True

    strong_markers = [
        "table of contents",
        "copyright ©",
        "all rights reserved",
        "isbn",
        "library of congress",
        "preface",
        "foreword",
        "contributors",
        "editorial board",
        "acknowledgments",
    ]

    if any(marker in sample for marker in strong_markers):
        return True

    # TOC-like pages: many short title + page-number lines.
    lines = [line.strip() for line in sample.splitlines() if line.strip()]
    toc_like = 0

    for line in lines[:80]:
        if re.search(r"\.{2,}\s*\d+\s*$", line):
            toc_like += 1
        elif re.search(r"\s\d{1,4}\s*$", line) and len(line) < 100:
            toc_like += 1

    if toc_like >= 8:
        return True

    return False


def is_nonclinical_chapter(title: str) -> bool:
    t = normalize_label(title).lower()

    if looks_like_junk_label(t):
        return True

    nonclinical_terms = [
        "preface",
        "foreword",
        "contributors",
        "contents",
        "index",
        "references",
        "bibliography",
        "appendix",
        "video library",
        "atlas of",
        "copyright",
    ]

    return any(term in t for term in nonclinical_terms)


# =========================================================
# R2 DOWNLOAD
# =========================================================

def download_pdf(destination: str):
    print("[R2] Downloading textbook...")
    r2.download_file(R2_BUCKET_NAME, FILE_KEY, destination)
    size = os.path.getsize(destination)
    print(f"[R2] Downloaded {size / 1024 / 1024:.2f} MB")


# =========================================================
# PDF TOC / CHAPTER MAP
# =========================================================

def professional_chapter_title(value: str) -> str:
    """Turn bookmark labels into clean student-facing chapter names."""
    title = normalize_label(value, 250)

    # Remove broad hierarchy prefixes if they leak through.
    title = re.sub(
        r"^(?:chapter)\s+\d+[A-Za-z]?\s*[:.\-–—]?\s*",
        "",
        title,
        flags=re.IGNORECASE,
    ).strip()

    # Remove a standalone leading chapter number such as "123 Heart Failure".
    # Keep disease numbers that are part of names by requiring a following word.
    title = re.sub(
        r"^\d{1,4}[A-Za-z]?\s*[:.\-–—]?\s+(?=[A-Za-z])",
        "",
        title,
    ).strip()

    return normalize_label(title, 250)


def build_toc_ranges(document) -> List[Dict[str, Any]]:
    """
    Build a professional chapter map from embedded PDF bookmarks.

    The old worker chose the shallowest useful TOC level, which produced
    broad labels such as "Part 10: Disorders of the Cardiovascular System".
    This version scores TOC levels and prefers the chapter-like level:
    many entries, sensible page spans, and few broad Part/Section labels.
    """
    toc = document.get_toc(simple=True) or []

    cleaned: List[Tuple[int, str, int]] = []

    for row in toc:
        if len(row) < 3:
            continue

        level, title, page = row[:3]

        try:
            level = int(level)
            page = int(page)
        except Exception:
            continue

        title = normalize_label(title, 250)

        if page < 1 or not title:
            continue

        cleaned.append((level, title, page))

    if not cleaned:
        print("[TOC] No usable embedded TOC found.")
        return []

    levels = sorted({level for level, _, _ in cleaned})
    scored = []

    for level in levels:
        entries = [
            (title, page)
            for row_level, title, page in cleaned
            if row_level == level
            and not is_nonclinical_chapter(title)
        ]

        if len(entries) < 8:
            continue

        pages = sorted(page for _, page in entries)
        gaps = [
            max(1, pages[i + 1] - pages[i])
            for i in range(len(pages) - 1)
        ]

        median_gap = (
            statistics.median(gaps)
            if gaps
            else 999
        )

        broad_count = sum(
            1
            for title, _ in entries
            if re.match(
                r"^(part|section)\s+[ivxlcdm\d]+\b",
                title,
                flags=re.IGNORECASE,
            )
        )

        broad_ratio = broad_count / max(len(entries), 1)

        # Chapter-level bookmarks usually number in the tens/hundreds and
        # span a few pages each. Extremely deep heading levels often have
        # hundreds/thousands of tiny 1-page entries.
        count = len(entries)
        sensible_count = 10 <= count <= 700
        sensible_span = 2 <= median_gap <= 40

        score = 0.0
        if sensible_count:
            score += 40
        if sensible_span:
            score += 35
        score += min(count, 400) / 10
        score -= broad_ratio * 80

        # Prefer deeper chapter level over broad Part level when scores tie.
        score += level * 2

        scored.append((score, level, count, median_gap, broad_ratio))

    if not scored:
        print("[TOC] No reliable chapter-like bookmark level found.")
        return []

    scored.sort(reverse=True)
    _, preferred_level, count, median_gap, broad_ratio = scored[0]

    print(
        f"[TOC] Selected level {preferred_level}; "
        f"entries={count}; median span≈{median_gap:.1f} pages; "
        f"broad ratio={broad_ratio:.2f}."
    )

    raw_entries = [
        (title, page)
        for level, title, page in cleaned
        if level == preferred_level
    ]

    ranges = []

    for i, (raw_title, start_page) in enumerate(raw_entries):
        if is_nonclinical_chapter(raw_title):
            continue

        title = professional_chapter_title(raw_title)

        if (
            not title
            or looks_like_junk_label(title)
            or re.match(
                r"^(part|section)\s+[ivxlcdm\d]+\b",
                title,
                flags=re.IGNORECASE,
            )
        ):
            continue

        end_page = (
            raw_entries[i + 1][1] - 1
            if i + 1 < len(raw_entries)
            else len(document)
        )

        if end_page < start_page:
            end_page = start_page

        ranges.append({
            "title": title,
            "page_start": start_page,
            "page_end": end_page,
        })

    # De-duplicate adjacent duplicate bookmark titles while preserving order.
    deduped = []
    seen = set()

    for item in ranges:
        key = item["title"].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    print(
        f"[TOC] Professional chapter catalogue: "
        f"{len(deduped)} chapters."
    )

    return deduped

def chapter_for_page(
    page_number: int,
    toc_ranges: List[Dict[str, Any]],
) -> Optional[str]:
    for item in toc_ranges:
        if item["page_start"] <= page_number <= item["page_end"]:
            return item["title"]

    return None


# =========================================================
# OCR / EXTRACTION
# =========================================================

def ocr_page(page) -> str:
    zoom = OCR_DPI / 72
    matrix = fitz.Matrix(zoom, zoom)

    pix = page.get_pixmap(
        matrix=matrix,
        alpha=False,
    )

    image = Image.open(
        io.BytesIO(pix.tobytes("png"))
    )

    text = pytesseract.image_to_string(
        image,
        lang="eng",
        config="--psm 6",
    )

    return clean_text(text)


def fallback_heading(text: str) -> Optional[str]:
    """
    Only used when the PDF has no useful embedded TOC.
    Much stricter than the old heading detector.
    """
    lines = [
        normalize_label(line)
        for line in text.splitlines()
        if normalize_label(line)
    ][:20]

    for candidate in lines:
        if looks_like_junk_label(candidate):
            continue

        if len(candidate) > 100:
            continue

        words = candidate.split()

        if not (2 <= len(words) <= 12):
            continue

        # Strong chapter pattern.
        if re.match(
            r"^(chapter\s+)?\d+\s*[:.\-–—]?\s+\S+",
            candidate,
            flags=re.IGNORECASE,
        ):
            return candidate

        # All-caps disease/section titles, but reject tiny/generic labels.
        letters = [c for c in candidate if c.isalpha()]

        if len(letters) >= 8:
            upper_ratio = sum(c.isupper() for c in letters) / len(letters)

            if upper_ratio >= 0.88:
                return candidate.title()

    return None


def extract_pages(
    pdf_path: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    document = fitz.open(pdf_path)
    total_pages = len(document)

    print(f"[PDF] Total pages: {total_pages}")

    toc_ranges = build_toc_ranges(document)

    update_book({
        "page_count": total_pages,
        "total_pages": total_pages,
        "processed_pages": 0,
        "extraction_progress": 0,
    })

    extracted = []
    active_fallback_heading = None
    last_saved_progress = -1

    for index in range(total_pages):
        page = document[index]
        page_number = index + 1

        native_text = clean_text(page.get_text("text"))
        text = native_text
        extraction_method = "text"

        if len(native_text) < NATIVE_TEXT_MIN_CHARS:
            try:
                ocr_text = ocr_page(page)

                if len(ocr_text) > len(native_text):
                    text = ocr_text
                    extraction_method = "ocr"

            except Exception as exc:
                print(f"[OCR] Failed page {page_number}: {exc}")
                extraction_method = "text-fallback"

        chapter = chapter_for_page(
            page_number,
            toc_ranges,
        )

        if not toc_ranges:
            detected = fallback_heading(text)

            if detected:
                active_fallback_heading = detected

            chapter = active_fallback_heading

        # Do not let preface/contents/index become MCQ source.
        frontmatter = is_frontmatter_text(text)

        if chapter and is_nonclinical_chapter(chapter):
            frontmatter = True

        if len(text) >= MIN_USABLE_PAGE_CHARS:
            extracted.append({
                "page": page_number,
                "text": text,
                "method": extraction_method,
                "chapter": chapter,
                "question_eligible": not frontmatter,
            })

        progress = int((page_number / total_pages) * 100)

        if (
            progress >= last_saved_progress + 2
            or page_number == total_pages
        ):
            update_book({
                "processed_pages": page_number,
                "extraction_progress": progress,
            })

            last_saved_progress = progress

            print(
                f"[PDF] Extraction {progress}% "
                f"({page_number}/{total_pages})"
            )

    document.close()

    eligible = sum(
        1
        for row in extracted
        if row["question_eligible"]
    )

    print(
        f"[PDF] Usable pages: {len(extracted)}/{total_pages}; "
        f"question-eligible pages: {eligible}"
    )

    return extracted, toc_ranges


# =========================================================
# CHUNKING
# =========================================================

def make_chunks(
    pages: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Chunks never intentionally cross chapter boundaries.
    This fixes the old problem where one chunk inherited a random
    heading from a neighbouring page.
    """
    chunks = []

    current_text = ""
    current_pages = []
    current_methods = []
    current_chapter = None
    current_eligible = False

    def flush():
        nonlocal current_text
        nonlocal current_pages
        nonlocal current_methods
        nonlocal current_chapter
        nonlocal current_eligible

        if not current_text or not current_pages:
            return

        chunks.append({
            "text": current_text.strip(),
            "pages": current_pages.copy(),
            "methods": current_methods.copy(),
            "chapter": current_chapter,
            "question_eligible": bool(current_eligible),
        })

        current_text = ""
        current_pages = []
        current_methods = []
        current_eligible = False

    for page in pages:
        page_chapter = page.get("chapter")
        addition = (
            f"\n\n--- PAGE {page['page']} ---\n"
            f"{page['text']}"
        )

        chapter_changed = (
            current_pages
            and page_chapter
            and current_chapter
            and page_chapter != current_chapter
        )

        size_exceeded = (
            current_text
            and len(current_text) + len(addition) > CHUNK_SIZE
        )

        if chapter_changed or size_exceeded:
            flush()

        if not current_chapter or chapter_changed:
            current_chapter = page_chapter

        current_text += addition
        current_pages.append(page["page"])
        current_methods.append(page["method"])
        current_eligible = (
            current_eligible
            or bool(page.get("question_eligible"))
        )

    flush()

    # Remove chunks that are obvious front matter/junk.
    cleaned = []

    for chunk in chunks:
        chapter = normalize_label(chunk.get("chapter") or "")

        if chapter and is_nonclinical_chapter(chapter):
            chunk["question_eligible"] = False

        # If chapter is missing, don't invent garbage names.
        if not chapter:
            chapter = "Unclassified textbook section"

        chunk["chapter"] = chapter
        cleaned.append(chunk)

    print(
        f"[CHUNK] Created {len(cleaned)} chunks; "
        f"{sum(1 for c in cleaned if c['question_eligible'])} "
        f"eligible for MCQ generation."
    )

    return cleaned


# =========================================================
# CHUNK DATABASE STORAGE
# =========================================================

def get_extraction_method(methods: List[str]) -> str:
    unique = set(methods)

    if unique == {"text"}:
        return "text"

    if unique == {"ocr"}:
        return "ocr"

    return "mixed"


def save_book_chunks(
    chunks: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    print("[DB] Saving clean book chunks...")

    rows = []

    for index, chunk in enumerate(chunks):
        pages = chunk["pages"]

        rows.append({
            "book_id": BOOK_ID,
            "chunk_index": index,
            "chapter": normalize_label(
                chunk.get("chapter") or "Unclassified textbook section",
                250,
            ),
            "section": None,
            "topic": None,
            "page_start": min(pages),
            "page_end": max(pages),
            "content": chunk["text"],
            "word_count": len(chunk["text"].split()),
            "extraction_method": get_extraction_method(
                chunk["methods"]
            ),
            "processing_status": "ready",
        })

    batch_size = 25

    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]

        (
            supabase
            .table("book_chunks")
            .upsert(
                batch,
                on_conflict="book_id,chunk_index",
            )
            .execute()
        )

        print(
            f"[DB] Stored chunks "
            f"{start + 1}-{min(start + batch_size, len(rows))}"
        )

    response = (
        supabase
        .table("book_chunks")
        .select(
            "id,chunk_index,chapter,page_start,page_end,content"
        )
        .eq("book_id", BOOK_ID)
        .order("chunk_index")
        .execute()
    )

    saved = response.data or []

    # Reattach local eligibility flag by chunk_index.
    local_by_index = {
        i: chunk
        for i, chunk in enumerate(chunks)
    }

    for row in saved:
        local = local_by_index.get(
            row.get("chunk_index"),
            {},
        )

        row["question_eligible"] = bool(
            local.get("question_eligible")
        )

    print(f"[DB] Knowledge chunks ready: {len(saved)}")

    return saved


# =========================================================
# AI HELPERS
# =========================================================

def parse_ai_json(content: str) -> List[Dict[str, Any]]:
    if not content:
        raise RuntimeError("AI returned empty response.")

    content = content.strip()

    content = re.sub(
        r"^```(?:json)?",
        "",
        content,
        flags=re.IGNORECASE,
    )

    content = re.sub(r"```$", "", content).strip()

    start = content.find("[")
    end = content.rfind("]")

    if start == -1 or end == -1:
        raise RuntimeError(
            "AI response did not contain a JSON array."
        )

    parsed = json.loads(content[start:end + 1])

    if not isinstance(parsed, list):
        raise RuntimeError("AI response JSON was not a list.")

    return parsed


def call_openrouter(
    chunk: Dict[str, Any]
) -> List[Dict[str, Any]]:
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not configured."
        )

    chapter = normalize_label(
        chunk.get("chapter") or "Clinical medicine"
    )

    system_prompt = """
You are MedQ's senior medical examination editor.

Write ORIGINAL, HIGH-QUALITY single-best-answer questions
for AMC CAT MCQ and FMGE preparation from the supplied
clinical textbook passage.

NON-NEGOTIABLE RULES

1. NEVER write questions from:
- preface
- foreword
- copyright
- acknowledgments
- contributors
- table of contents
- index
- references
- bibliography
- video-library lists
- atlas lists
- chapter-number lists
- publishing information
- author/editor information

If the source passage is mostly any of the above,
return an empty JSON array [].

2. The CHAPTER supplied by MedQ is authoritative.
Do not rename the chapter.

3. TOPIC must be a real medical concept, disease,
syndrome, investigation, treatment, complication,
drug class, pathology, or physiology concept.
Never output labels such as:
"Part 1", "Section 2", "e42", "e46", "Chapter 3",
"General", "Introduction", "Overview", "Miscellaneous".

4. AMC questions:
- realistic clinical vignette where supported
- next-best-step / diagnosis / investigation / management
- patient safety and prioritisation
- plausible distractors
- no trivia

5. FMGE questions:
- high-yield clinically relevant knowledge
- diagnosis / pathology / pharmacology / investigation /
  treatment / complication / mechanism
- avoid obscure publishing or historical trivia

6. Every question must:
- have exactly five options A-E
- have one best answer
- be medically important
- have a clear explanation
- explain why the correct answer is correct
- avoid copying a source sentence as the stem
- use only facts supported by the source

7. Return ONLY valid JSON array. No Markdown.

JSON:
[
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
    "topic": "Heart failure",
    "difficulty": "medium",
    "source_page": 100,
    "source_page_end": 100
  }
]
""".strip()

    user_prompt = f"""
SUBJECT:
{BOOK_SUBJECT}

AUTHORITATIVE CHAPTER:
{chapter}

SOURCE PAGES:
{chunk["page_start"]}-{chunk["page_end"]}

Create exactly {QUESTIONS_PER_CHUNK} useful questions.
Use approximately half AMC and half FMGE where appropriate.

TEXTBOOK CONTENT:

{chunk["content"]}
""".strip()

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://medq-practice.netlify.app",
        "X-Title": "MedQ",
    }

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": 0.15,
        "max_tokens": 6500,
    }

    last_error = None

    for attempt in range(1, AI_RETRIES + 1):
        try:
            print(
                f"[AI] Request attempt "
                f"{attempt}/{AI_RETRIES}"
            )

            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=240,
            )

            if not response.ok:
                raise RuntimeError(
                    f"OpenRouter {response.status_code}: "
                    f"{response.text[:1000]}"
                )

            data = response.json()

            content = (
                data
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

            return parse_ai_json(content)

        except Exception as exc:
            last_error = exc
            print(f"[AI] Attempt failed: {exc}")

            if attempt < AI_RETRIES:
                time.sleep(5 * attempt)

    raise RuntimeError(
        f"OpenRouter failed after {AI_RETRIES} attempts: "
        f"{last_error}"
    )


# =========================================================
# QUESTION QUALITY / VALIDATION
# =========================================================

def clean_topic(value: str) -> Optional[str]:
    topic = normalize_label(value, 120)

    if not topic:
        return None

    if looks_like_junk_label(topic):
        return None

    lower = topic.lower()

    banned = [
        "general",
        "miscellaneous",
        "overview",
        "introduction",
        "background",
        "part ",
        "section ",
        "chapter ",
        "video library",
        "atlas of",
    ]

    if any(lower == item.strip() or lower.startswith(item) for item in banned):
        return None

    if re.fullmatch(r"e\d+", lower):
        return None

    return topic


def stem_is_nonclinical(stem: str) -> bool:
    s = normalize_label(stem, 500).lower()

    bad = [
        "preface",
        "foreword",
        "editor",
        "publisher",
        "copyright",
        "isbn",
        "table of contents",
        "which chapter",
        "which section",
        "video library",
    ]

    return any(term in s for term in bad)


def prepare_question(
    question: Dict[str, Any],
    chunk: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    required_fields = [
        "stem",
        "option_a",
        "option_b",
        "option_c",
        "option_d",
        "option_e",
        "correct_option",
        "explanation",
        "topic",
    ]

    for field in required_fields:
        if not question.get(field):
            return None

    stem = normalize_label(
        question["stem"],
        2000,
    )

    if len(stem) < 35:
        return None

    if stem_is_nonclinical(stem):
        return None

    topic = clean_topic(
        question.get("topic")
    )

    if not topic:
        return None

    correct_option = str(
        question.get("correct_option", "")
    ).strip().upper()

    if correct_option not in ["A", "B", "C", "D", "E"]:
        return None

    options = [
        normalize_label(question["option_a"], 500),
        normalize_label(question["option_b"], 500),
        normalize_label(question["option_c"], 500),
        normalize_label(question["option_d"], 500),
        normalize_label(question["option_e"], 500),
    ]

    if any(not option for option in options):
        return None

    if len(set(option.lower() for option in options)) != 5:
        return None

    explanation = clean_text(
        str(question["explanation"])
    )

    if len(explanation) < 60:
        return None

    exam_type = str(
        question.get("exam_type", "FMGE")
    ).strip().upper()

    if exam_type not in ["AMC", "FMGE"]:
        exam_type = "FMGE"

    difficulty = str(
        question.get("difficulty", "medium")
    ).strip().lower()

    if difficulty not in ["easy", "medium", "hard"]:
        difficulty = "medium"

    source_page = question.get("source_page")
    source_page_end = question.get("source_page_end")

    try:
        source_page = int(source_page)
    except Exception:
        source_page = chunk["page_start"]

    try:
        source_page_end = int(source_page_end)
    except Exception:
        source_page_end = source_page

    if not (
        chunk["page_start"]
        <= source_page
        <= chunk["page_end"]
    ):
        source_page = chunk["page_start"]

    if not (
        source_page
        <= source_page_end
        <= chunk["page_end"]
    ):
        source_page_end = source_page

    # IMPORTANT:
    # Chapter comes from MedQ's cleaned PDF structure,
    # never from the AI.
    chapter = normalize_label(
        chunk.get("chapter") or "Clinical medicine",
        250,
    )

    return {
        "book_id": BOOK_ID,
        "source_chunk_id": chunk["id"],
        "subject": BOOK_SUBJECT,
        "chapter": chapter,
        "topic": topic,
        "exam_type": exam_type,
        "question_type": normalize_label(
            question.get(
                "question_type",
                "clinical_application",
            ),
            100,
        ),
        "difficulty": difficulty,
        "stem": stem,
        "option_a": options[0],
        "option_b": options[1],
        "option_c": options[2],
        "option_d": options[3],
        "option_e": options[4],
        "correct_option": correct_option,
        "explanation": explanation,
        "source_page": source_page,
        "source_page_end": source_page_end,
        "review_status": "generated",
        "quality_score": None,
        "reviewer_notes": None,
    }


def existing_stem_signatures() -> set:
    response = (
        supabase
        .table("questions")
        .select("stem")
        .eq("book_id", BOOK_ID)
        .execute()
    )

    signatures = set()

    for row in response.data or []:
        stem = row.get("stem") or ""
        signatures.add(
            re.sub(r"\W+", "", stem.lower())[:500]
        )

    return signatures


def save_questions(
    generated: List[Dict[str, Any]],
    chunk: Dict[str, Any],
    global_signatures: set,
) -> int:
    valid = []

    for question in generated:
        cleaned = prepare_question(
            question,
            chunk,
        )

        if not cleaned:
            continue

        signature = re.sub(
            r"\W+",
            "",
            cleaned["stem"].lower(),
        )[:500]

        if signature in global_signatures:
            continue

        global_signatures.add(signature)
        valid.append(cleaned)

    if not valid:
        return 0

    response = (
        supabase
        .table("questions")
        .insert(valid)
        .execute()
    )

    count = len(response.data or [])
    print(f"[DB] Saved {count} quality-filtered questions")

    return count


# =========================================================
# SEED QUESTION GENERATION
# =========================================================

def choose_seed_chunks(
    chunks: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Spread seed questions across different chapters instead of
    burning the quota on the first pages of the book.
    """
    eligible = [
        chunk
        for chunk in chunks
        if chunk.get("question_eligible")
        and not is_nonclinical_chapter(
            chunk.get("chapter") or ""
        )
    ]

    if len(eligible) <= SEED_CHUNK_LIMIT:
        return eligible

    # Round-robin across chapters.
    by_chapter: Dict[str, List[Dict[str, Any]]] = {}

    for chunk in eligible:
        chapter = chunk.get("chapter") or "Clinical medicine"
        by_chapter.setdefault(chapter, []).append(chunk)

    chosen = []
    round_index = 0

    while len(chosen) < SEED_CHUNK_LIMIT:
        added = False

        for chapter in list(by_chapter.keys()):
            chapter_chunks = by_chapter[chapter]

            if round_index < len(chapter_chunks):
                chosen.append(chapter_chunks[round_index])
                added = True

                if len(chosen) >= SEED_CHUNK_LIMIT:
                    break

        if not added:
            break

        round_index += 1

    return chosen


def generate_seed_questions(
    chunks: List[Dict[str, Any]]
) -> int:
    if not GENERATE_SEED_QUESTIONS:
        print("[AI] Seed generation disabled.")
        return 0

    if not OPENROUTER_API_KEY:
        print(
            "[AI] No OpenRouter key; "
            "knowledge base will still be ready."
        )
        return 0

    selected = choose_seed_chunks(chunks)

    print(
        f"[AI] Seed generation from "
        f"{len(selected)} clinically useful chunks."
    )

    total_created = 0
    signatures = existing_stem_signatures()

    for index, chunk in enumerate(selected, start=1):
        print(
            f"[AI] Seed chunk {index}/{len(selected)} | "
            f"{chunk.get('chapter')} | "
            f"pages {chunk['page_start']}-{chunk['page_end']}"
        )

        try:
            generated = call_openrouter(chunk)

            total_created += save_questions(
                generated,
                chunk,
                signatures,
            )

        except Exception as exc:
            # AI failure must NEVER make the entire textbook unusable.
            print(f"[AI] Seed chunk failed: {exc}")

        progress = int(
            (index / max(len(selected), 1)) * 100
        )

        update_book({
            "question_progress": progress,
            "questions_generated": total_created,
        })

        time.sleep(AI_DELAY_SECONDS)

    return total_created


# =========================================================
# MAIN
# =========================================================

def main():
    print("========================================")
    print("MEDQ TEXTBOOK INGESTION WORKER v3")
    print(f"Book ID: {BOOK_ID}")
    print(f"Subject: {BOOK_SUBJECT}")
    print("========================================")

    set_stage(
        "downloading",
        processing_started_at=utc_now(),
        error_message=None,
    )

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = os.path.join(
                temp_dir,
                "book.pdf",
            )

            download_pdf(pdf_path)

            # ---------------------------------------------
            # 1. EXTRACT THE ENTIRE BOOK
            # ---------------------------------------------
            set_stage("extracting")

            pages, toc_ranges = extract_pages(
                pdf_path
            )

            if not pages:
                raise RuntimeError(
                    "No usable textbook text could be extracted."
                )

            # ---------------------------------------------
            # 2. BUILD CLEAN KNOWLEDGE BASE
            # ---------------------------------------------
            set_stage(
                "building_knowledge_base",
                extraction_progress=100,
            )

            # Reprocessing must not leave stale broad Part-level chunks or
            # old seed questions behind. This only affects the selected book.
            print("[DB] Clearing previous generated questions and chunks for this book...")
            (
                supabase
                .table("questions")
                .delete()
                .eq("book_id", BOOK_ID)
                .execute()
            )
            (
                supabase
                .table("book_chunks")
                .delete()
                .eq("book_id", BOOK_ID)
                .execute()
            )

            chunks = make_chunks(pages)

            if not chunks:
                raise RuntimeError(
                    "No textbook chunks were created."
                )

            saved_chunks = save_book_chunks(
                chunks
            )

            if not saved_chunks:
                raise RuntimeError(
                    "Textbook chunks could not be stored."
                )

            # At this exact point the full book is already usable
            # as a clean MedBot knowledge source.
            update_book({
                "status": "ready",
                "processing_stage": "knowledge_ready",
                "extraction_progress": 100,
                "processed_pages": len(pages),
                "processing_completed_at": utc_now(),
                "error_message": None,
            })

            print(
                "[BOOK] Full textbook knowledge base is ready."
            )

            # ---------------------------------------------
            # 3. CREATE ONLY A DISTRIBUTED SEED QUESTION SET
            # ---------------------------------------------
            # Full question-bank expansion should later happen
            # on demand by chapter/topic. This avoids hours of
            # upload-time waiting and free-API rate-limit failures.
            set_stage(
                "generating_seed_questions",
                status="ready",
                extraction_progress=100,
            )

            total_questions = generate_seed_questions(
                saved_chunks
            )

            update_book({
                "status": "ready",
                "processing_stage": "ready",
                "extraction_progress": 100,
                "question_progress": (
                    100
                    if GENERATE_SEED_QUESTIONS
                    else 0
                ),
                "questions_generated": total_questions,
                "processed_pages": len(pages),
                "processing_completed_at": utc_now(),
                "error_message": None,
            })

            print("========================================")
            print("MEDQ TEXTBOOK INGESTION COMPLETE")
            print(
                f"Stored knowledge chunks: {len(saved_chunks)}"
            )
            print(
                f"Seed questions created this run: "
                f"{total_questions}"
            )
            print(
                "Next architecture step: on-demand "
                "chapter/topic question expansion."
            )
            print("========================================")

    except Exception as exc:
        print("========================================")
        print("PROCESSING FAILED")
        print(str(exc))
        print("========================================")

        try:
            update_book({
                "status": "failed",
                "processing_stage": "failed",
                "error_message": str(exc)[:1000],
            })
        except Exception as status_exc:
            print(
                "Could not update failure status:",
                status_exc,
            )

        raise


if __name__ == "__main__":
    main()
