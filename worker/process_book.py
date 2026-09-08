import os
import io
import re
import json
import time
import tempfile
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

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

OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "openrouter/free"
)

OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)


# =========================================================
# PROCESSING SETTINGS
# =========================================================

# Whole textbook is processed.
# There is intentionally NO MAX_PAGES.

CHUNK_SIZE = int(
    os.getenv("CHUNK_SIZE", "22000")
)

QUESTIONS_PER_CHUNK = int(
    os.getenv("QUESTIONS_PER_CHUNK", "6")
)

OCR_DPI = int(
    os.getenv("OCR_DPI", "150")
)

NATIVE_TEXT_MIN_CHARS = int(
    os.getenv("NATIVE_TEXT_MIN_CHARS", "140")
)

MIN_USABLE_PAGE_CHARS = int(
    os.getenv("MIN_USABLE_PAGE_CHARS", "60")
)

AI_DELAY_SECONDS = float(
    os.getenv("AI_DELAY_SECONDS", "2")
)

AI_RETRIES = int(
    os.getenv("AI_RETRIES", "3")
)


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
    "OPENROUTER_API_KEY": OPENROUTER_API_KEY,
}

missing = [
    key
    for key, value in required.items()
    if not value
]

if missing:
    raise RuntimeError(
        "Missing required environment variables: "
        + ", ".join(missing)
    )


# =========================================================
# CLIENTS
# =========================================================

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

r2 = boto3.client(
    "s3",
    endpoint_url=(
        f"https://{R2_ACCOUNT_ID}"
        ".r2.cloudflarestorage.com"
    ),
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(
        signature_version="s3v4"
    ),
)


# =========================================================
# GENERAL HELPERS
# =========================================================

def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def update_book(
    fields: Dict[str, Any]
):
    (
        supabase
        .table("books")
        .update(fields)
        .eq("id", BOOK_ID)
        .execute()
    )


def set_stage(
    stage: str,
    status: str = "processing",
    **extra
):
    data = {
        "status": status,
        "processing_stage": stage,
    }

    data.update(extra)

    update_book(data)

    print(
        f"[BOOK] {stage} | {status}"
    )


# =========================================================
# R2 DOWNLOAD
# =========================================================

def download_pdf(
    destination: str
):
    print(
        "[R2] Downloading textbook..."
    )

    r2.download_file(
        R2_BUCKET_NAME,
        FILE_KEY,
        destination
    )

    size = os.path.getsize(
        destination
    )

    print(
        "[R2] Downloaded "
        f"{size / 1024 / 1024:.2f} MB"
    )


# =========================================================
# TEXT CLEANING
# =========================================================

def clean_text(
    text: str
) -> str:

    if not text:
        return ""

    text = text.replace(
        "\x00",
        " "
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text
    )

    text = re.sub(
        r"\n[ \t]+\n",
        "\n\n",
        text
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


# =========================================================
# OCR
# =========================================================

def ocr_page(
    page
) -> str:

    zoom = OCR_DPI / 72

    matrix = fitz.Matrix(
        zoom,
        zoom
    )

    pix = page.get_pixmap(
        matrix=matrix,
        alpha=False
    )

    image = Image.open(
        io.BytesIO(
            pix.tobytes("png")
        )
    )

    text = pytesseract.image_to_string(
        image,
        lang="eng",
        config="--psm 6"
    )

    return clean_text(
        text
    )


# =========================================================
# PDF EXTRACTION
# =========================================================

def extract_pages(
    pdf_path: str
) -> List[Dict[str, Any]]:

    document = fitz.open(
        pdf_path
    )

    total_pages = len(
        document
    )

    print(
        f"[PDF] Total pages: {total_pages}"
    )

    update_book({
        "page_count": total_pages,
        "total_pages": total_pages,
        "processed_pages": 0,
        "extraction_progress": 0
    })

    extracted = []

    last_saved_progress = -1

    for index in range(
        total_pages
    ):

        page = document[
            index
        ]

        page_number = (
            index + 1
        )

        native_text = clean_text(
            page.get_text(
                "text"
            )
        )

        text = native_text

        extraction_method = "text"

        # OCR ONLY when the PDF page does not already
        # contain enough usable digital text.
        if (
            len(native_text)
            < NATIVE_TEXT_MIN_CHARS
        ):

            try:

                ocr_text = ocr_page(
                    page
                )

                if len(ocr_text) > len(
                    native_text
                ):

                    text = ocr_text
                    extraction_method = "ocr"

                else:

                    extraction_method = (
                        "text"
                    )

            except Exception as exc:

                print(
                    "[OCR] Failed page "
                    f"{page_number}: {exc}"
                )

                text = native_text

                extraction_method = (
                    "text-fallback"
                )

        if (
            len(text)
            >= MIN_USABLE_PAGE_CHARS
        ):

            extracted.append({
                "page": page_number,
                "text": text,
                "method":
                    extraction_method
            })

        progress = int(
            (
                page_number
                / total_pages
            )
            * 100
        )

        if (
            progress
            >= last_saved_progress + 2
            or page_number
            == total_pages
        ):

            update_book({
                "processed_pages":
                    page_number,

                "extraction_progress":
                    progress
            })

            last_saved_progress = (
                progress
            )

            print(
                "[PDF] Extraction "
                f"{progress}% "
                f"({page_number}/"
                f"{total_pages})"
            )

    document.close()

    print(
        "[PDF] Usable pages: "
        f"{len(extracted)}/"
        f"{total_pages}"
    )

    return extracted


# =========================================================
# SIMPLE CHAPTER / HEADING DETECTION
# =========================================================

def detect_heading(
    text: str
) -> Optional[str]:

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for line in lines[
        :15
    ]:

        candidate = re.sub(
            r"\s+",
            " ",
            line
        ).strip()

        if len(candidate) < 4:
            continue

        if len(candidate) > 120:
            continue

        words = candidate.split()

        if len(words) > 14:
            continue

        alpha_chars = [
            char
            for char in candidate
            if char.isalpha()
        ]

        if not alpha_chars:
            continue

        uppercase_chars = sum(
            1
            for char in alpha_chars
            if char.isupper()
        )

        upper_ratio = (
            uppercase_chars
            / len(alpha_chars)
        )

        numbered_heading = bool(
            re.match(
                (
                    r"^(chapter\s+)?"
                    r"\d+[\s:.\-]"
                ),
                candidate,
                flags=re.IGNORECASE
            )
        )

        if (
            upper_ratio > 0.65
            or numbered_heading
        ):

            return candidate[
                :120
            ]

    return None


# =========================================================
# CHUNKING
# =========================================================

def make_chunks(
    pages: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:

    chunks = []

    current_text = ""

    current_pages = []

    current_methods = []

    active_heading = None

    for page in pages:

        detected = detect_heading(
            page["text"]
        )

        if detected:
            active_heading = detected

        addition = (
            f"\n\n--- PAGE "
            f"{page['page']} ---\n"
            f"{page['text']}"
        )

        if (
            current_text
            and
            len(current_text)
            + len(addition)
            > CHUNK_SIZE
        ):

            chunks.append({
                "text":
                    current_text.strip(),

                "pages":
                    current_pages.copy(),

                "methods":
                    current_methods.copy(),

                "chapter":
                    active_heading
            })

            current_text = ""

            current_pages = []

            current_methods = []

        current_text += addition

        current_pages.append(
            page["page"]
        )

        current_methods.append(
            page["method"]
        )

    if current_text:

        chunks.append({
            "text":
                current_text.strip(),

            "pages":
                current_pages.copy(),

            "methods":
                current_methods.copy(),

            "chapter":
                active_heading
        })

    print(
        "[CHUNK] Created "
        f"{len(chunks)} chunks"
    )

    return chunks


# =========================================================
# CHUNK DATABASE STORAGE
# =========================================================

def get_extraction_method(
    methods: List[str]
) -> str:

    unique_methods = set(
        methods
    )

    if unique_methods == {
        "text"
    }:
        return "text"

    if unique_methods == {
        "ocr"
    }:
        return "ocr"

    return "mixed"


def save_book_chunks(
    chunks: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:

    print(
        "[DB] Saving book chunks..."
    )

    rows = []

    for index, chunk in enumerate(
        chunks
    ):

        pages = chunk[
            "pages"
        ]

        chapter = (
            chunk.get(
                "chapter"
            )
            or
            (
                f"Pages "
                f"{min(pages)}-"
                f"{max(pages)}"
            )
        )

        rows.append({
            "book_id":
                BOOK_ID,

            "chunk_index":
                index,

            "chapter":
                chapter[:250],

            "section":
                None,

            "topic":
                None,

            "page_start":
                min(pages),

            "page_end":
                max(pages),

            "content":
                chunk["text"],

            "word_count":
                len(
                    chunk["text"]
                    .split()
                ),

            "extraction_method":
                get_extraction_method(
                    chunk[
                        "methods"
                    ]
                ),

            "processing_status":
                "ready"
        })

    batch_size = 25

    for start in range(
        0,
        len(rows),
        batch_size
    ):

        batch = rows[
            start:
            start + batch_size
        ]

        (
            supabase
            .table("book_chunks")
            .upsert(
                batch,
                on_conflict=(
                    "book_id,"
                    "chunk_index"
                )
            )
            .execute()
        )

        print(
            "[DB] Stored chunks "
            f"{start + 1}-"
            f"{min(start + batch_size, len(rows))}"
        )

    response = (
        supabase
        .table("book_chunks")
        .select(
            (
                "id,"
                "chunk_index,"
                "chapter,"
                "page_start,"
                "page_end,"
                "content"
            )
        )
        .eq(
            "book_id",
            BOOK_ID
        )
        .order(
            "chunk_index"
        )
        .execute()
    )

    saved_chunks = (
        response.data
        or []
    )

    print(
        "[DB] Knowledge chunks ready: "
        f"{len(saved_chunks)}"
    )

    return saved_chunks


# =========================================================
# AI JSON PARSER
# =========================================================

def parse_ai_json(
    content: str
) -> List[Dict[str, Any]]:

    if not content:

        raise RuntimeError(
            "AI returned empty response."
        )

    content = content.strip()

    content = re.sub(
        r"^```(?:json)?",
        "",
        content,
        flags=re.IGNORECASE
    )

    content = re.sub(
        r"```$",
        "",
        content
    )

    content = content.strip()

    start = content.find(
        "["
    )

    end = content.rfind(
        "]"
    )

    if (
        start == -1
        or end == -1
    ):

        raise RuntimeError(
            (
                "AI response did not "
                "contain a JSON array."
            )
        )

    json_text = content[
        start:
        end + 1
    ]

    try:

        parsed = json.loads(
            json_text
        )

    except Exception as exc:

        print(
            "[AI] Invalid JSON:"
        )

        print(
            json_text[:3000]
        )

        raise RuntimeError(
            (
                "Unable to parse AI JSON: "
                f"{exc}"
            )
        )

    if not isinstance(
        parsed,
        list
    ):

        raise RuntimeError(
            (
                "AI response JSON "
                "was not a list."
            )
        )

    return parsed


# =========================================================
# OPENROUTER
# =========================================================

def call_openrouter(
    chunk: Dict[str, Any]
) -> List[Dict[str, Any]]:

    page_start = chunk[
        "page_start"
    ]

    page_end = chunk[
        "page_end"
    ]

    chapter = (
        chunk.get(
            "chapter"
        )
        or "Unknown"
    )

    system_prompt = """
You are MedQ's senior medical examination question writer.

MedQ prepares medical students specifically for:

1. Australian Medical Council (AMC) CAT MCQ style
2. Foreign Medical Graduate Examination (FMGE) style

Your task is to transform medical textbook content into
original high-quality single-best-answer medical questions.

SOURCE RULES

Use the supplied textbook passage as the primary medical source.

Do not invent unsupported facts.

Do not simply copy textbook sentences into questions.

Every question must be answerable from the supplied source.

AMC STYLE

AMC questions should strongly emphasise:

- realistic clinical vignettes
- clinical reasoning
- diagnosis
- differential diagnosis
- next best investigation
- interpretation
- immediate management
- definitive management
- complications
- pharmacological decisions
- patient safety
- prioritisation
- next-best-step reasoning

When the textbook passage supports a clinical question,
prefer clinical reasoning over simple recall for AMC.

FMGE STYLE

FMGE questions should include an appropriate mixture of:

- high-yield facts
- clinical application
- diagnosis
- pathology
- microbiology
- pharmacology
- investigations
- treatment
- complications
- mechanisms
- characteristic findings
- important associations

QUALITY RULES

Every question must:

- have exactly five options A-E
- have exactly one best answer
- contain plausible distractors
- avoid ambiguous wording
- avoid clues that reveal the answer
- test an important medical concept
- contain a useful explanation
- explain why the correct option is correct
- specify the most appropriate source page
- specify a topic
- specify difficulty as easy, medium or hard

Generate approximately half AMC and half FMGE questions.

Do not create multiple questions testing the exact same fact.

Return ONLY valid JSON.

No Markdown.

Required JSON format:

[
  {
    "exam_type": "AMC",
    "question_type": "clinical_reasoning",
    "stem": "Question...",
    "option_a": "...",
    "option_b": "...",
    "option_c": "...",
    "option_d": "...",
    "option_e": "...",
    "correct_option": "A",
    "explanation": "...",
    "chapter": "...",
    "topic": "...",
    "difficulty": "medium",
    "source_page": 123,
    "source_page_end": 123
  }
]
""".strip()

    user_prompt = f"""
SUBJECT:
{BOOK_SUBJECT}

CHAPTER OR SECTION:
{chapter}

SOURCE PAGES:
{page_start}-{page_end}

Create exactly {QUESTIONS_PER_CHUNK} useful questions
from this textbook material.

Use both AMC and FMGE patterns.

Prioritise clinically and educationally important concepts.

TEXTBOOK CONTENT:

{chunk["content"]}
""".strip()

    headers = {
        "Authorization":
            f"Bearer "
            f"{OPENROUTER_API_KEY}",

        "Content-Type":
            "application/json",

        "HTTP-Referer":
            (
                "https://"
                "medq-practice."
                "netlify.app"
            ),

        "X-Title":
            "MedQ"
    }

    payload = {
        "model":
            OPENROUTER_MODEL,

        "messages": [
            {
                "role":
                    "system",

                "content":
                    system_prompt
            },
            {
                "role":
                    "user",

                "content":
                    user_prompt
            }
        ],

        "temperature":
            0.2,

        "max_tokens":
            7000
    }

    last_error = None

    for attempt in range(
        1,
        AI_RETRIES + 1
    ):

        try:

            print(
                "[AI] Request attempt "
                f"{attempt}/"
                f"{AI_RETRIES}"
            )

            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=payload,
                timeout=240
            )

            if not response.ok:

                raise RuntimeError(
                    (
                        "OpenRouter "
                        f"{response.status_code}: "
                        f"{response.text[:1000]}"
                    )
                )

            data = response.json()

            content = (
                data
                .get(
                    "choices",
                    [{}]
                )[0]
                .get(
                    "message",
                    {}
                )
                .get(
                    "content",
                    ""
                )
            )

            return parse_ai_json(
                content
            )

        except Exception as exc:

            last_error = exc

            print(
                "[AI] Attempt failed: "
                f"{exc}"
            )

            if attempt < AI_RETRIES:

                time.sleep(
                    5 * attempt
                )

    raise RuntimeError(
        (
            "OpenRouter failed after "
            f"{AI_RETRIES} attempts: "
            f"{last_error}"
        )
    )


# =========================================================
# QUESTION VALIDATION
# =========================================================

def prepare_question(
    question: Dict[str, Any],
    chunk: Dict[str, Any]
) -> Optional[Dict[str, Any]]:

    required_fields = [
        "stem",
        "option_a",
        "option_b",
        "option_c",
        "option_d",
        "option_e",
        "correct_option",
        "explanation"
    ]

    for field in required_fields:

        if not question.get(
            field
        ):

            print(
                "[VALIDATION] Missing "
                f"{field}"
            )

            return None

    correct_option = str(
        question.get(
            "correct_option",
            ""
        )
    ).strip().upper()

    if correct_option not in [
        "A",
        "B",
        "C",
        "D",
        "E"
    ]:

        return None

    exam_type = str(
        question.get(
            "exam_type",
            "FMGE"
        )
    ).strip().upper()

    if exam_type not in [
        "AMC",
        "FMGE"
    ]:

        exam_type = "FMGE"

    difficulty = str(
        question.get(
            "difficulty",
            "medium"
        )
    ).strip().lower()

    if difficulty not in [
        "easy",
        "medium",
        "hard"
    ]:

        difficulty = "medium"

    source_page = question.get(
        "source_page"
    )

    source_page_end = question.get(
        "source_page_end"
    )

    try:

        source_page = int(
            source_page
        )

    except Exception:

        source_page = chunk[
            "page_start"
        ]

    try:

        source_page_end = int(
            source_page_end
        )

    except Exception:

        source_page_end = (
            source_page
        )

    if (
        source_page
        < chunk["page_start"]
        or source_page
        > chunk["page_end"]
    ):

        source_page = chunk[
            "page_start"
        ]

    if (
        source_page_end
        < source_page
        or source_page_end
        > chunk["page_end"]
    ):

        source_page_end = (
            source_page
        )

    stem = str(
        question["stem"]
    ).strip()

    options = [
        str(
            question[
                "option_a"
            ]
        ).strip(),

        str(
            question[
                "option_b"
            ]
        ).strip(),

        str(
            question[
                "option_c"
            ]
        ).strip(),

        str(
            question[
                "option_d"
            ]
        ).strip(),

        str(
            question[
                "option_e"
            ]
        ).strip(),
    ]

    # Reject duplicate options.
    if len(
        set(
            option.lower()
            for option
            in options
        )
    ) != 5:

        return None

    if len(stem) < 25:

        return None

    explanation = str(
        question[
            "explanation"
        ]
    ).strip()

    if len(explanation) < 30:

        return None

    return {
        "book_id":
            BOOK_ID,

        "source_chunk_id":
            chunk["id"],

        "subject":
            BOOK_SUBJECT,

        "chapter":
            str(
                question.get(
                    "chapter",
                    chunk.get(
                        "chapter",
                        ""
                    )
                )
            )[:250],

        "topic":
            str(
                question.get(
                    "topic",
                    ""
                )
            )[:250],

        "exam_type":
            exam_type,

        "question_type":
            str(
                question.get(
                    "question_type",
                    "concept"
                )
            )[:100],

        "difficulty":
            difficulty,

        "stem":
            stem,

        "option_a":
            options[0],

        "option_b":
            options[1],

        "option_c":
            options[2],

        "option_d":
            options[3],

        "option_e":
            options[4],

        "correct_option":
            correct_option,

        "explanation":
            explanation,

        "source_page":
            source_page,

        "source_page_end":
            source_page_end,

        "review_status":
            "generated",

        "quality_score":
            None,

        "reviewer_notes":
            None
    }


# =========================================================
# RESUME CHECK
# =========================================================

def questions_exist_for_chunk(
    chunk_id: str
) -> bool:

    response = (
        supabase
        .table("questions")
        .select("id")
        .eq(
            "book_id",
            BOOK_ID
        )
        .eq(
            "source_chunk_id",
            chunk_id
        )
        .limit(1)
        .execute()
    )

    return bool(
        response.data
    )


# =========================================================
# SAVE QUESTIONS
# =========================================================

def save_questions(
    generated: List[Dict[str, Any]],
    chunk: Dict[str, Any]
) -> int:

    valid_questions = []

    local_stems = set()

    for question in generated:

        cleaned = prepare_question(
            question,
            chunk
        )

        if not cleaned:

            continue

        normalized = re.sub(
            r"\W+",
            "",
            cleaned[
                "stem"
            ].lower()
        )

        if normalized in local_stems:

            continue

        local_stems.add(
            normalized
        )

        valid_questions.append(
            cleaned
        )

    if not valid_questions:

        return 0

    response = (
        supabase
        .table("questions")
        .insert(
            valid_questions
        )
        .execute()
    )

    count = len(
        response.data
        or []
    )

    print(
        "[DB] Saved "
        f"{count} questions"
    )

    return count


# =========================================================
# EXISTING QUESTION COUNT
# =========================================================

def count_new_questions() -> int:

    response = (
        supabase
        .table("questions")
        .select(
            "id,source_chunk_id"
        )
        .eq(
            "book_id",
            BOOK_ID
        )
        .execute()
    )

    rows = (
        response.data
        or []
    )

    return sum(
        1
        for row in rows
        if row.get(
            "source_chunk_id"
        )
    )


# =========================================================
# GENERATE QUESTIONS
# =========================================================

def generate_questions(
    chunks: List[Dict[str, Any]]
) -> int:

    total_chunks = len(
        chunks
    )

    total_created = (
        count_new_questions()
    )

    for index, chunk in enumerate(
        chunks,
        start=1
    ):

        if questions_exist_for_chunk(
            chunk["id"]
        ):

            print(
                "[AI] Chunk "
                f"{index}/"
                f"{total_chunks} "
                "already processed — "
                "skipping"
            )

        else:

            print(
                "--------------------------------"
            )

            print(
                "[AI] Chunk "
                f"{index}/"
                f"{total_chunks}"
            )

            print(
                "[AI] Pages "
                f"{chunk['page_start']}-"
                f"{chunk['page_end']}"
            )

            try:

                generated = (
                    call_openrouter(
                        chunk
                    )
                )

                saved = save_questions(
                    generated,
                    chunk
                )

                total_created += (
                    saved
                )

            except Exception as exc:

                print(
                    "[AI] Chunk failed: "
                    f"{exc}"
                )

        progress = int(
            (
                index
                / total_chunks
            )
            * 100
        )

        update_book({
            "question_progress":
                progress,

            "questions_generated":
                total_created
        })

        time.sleep(
            AI_DELAY_SECONDS
        )

    return total_created


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "========================================"
    )

    print(
        "MEDQ FULL TEXTBOOK PROCESSOR"
    )

    print(
        f"Book ID: {BOOK_ID}"
    )

    print(
        f"Subject: {BOOK_SUBJECT}"
    )

    print(
        "========================================"
    )

    set_stage(
        "downloading",
        processing_started_at=
            utc_now(),
        error_message=None
    )

    try:

        with tempfile.TemporaryDirectory() as temp_dir:

            pdf_path = os.path.join(
                temp_dir,
                "book.pdf"
            )

            download_pdf(
                pdf_path
            )

            # -----------------------------------------
            # EXTRACT WHOLE TEXTBOOK
            # -----------------------------------------

            set_stage(
                "extracting"
            )

            pages = extract_pages(
                pdf_path
            )

            if not pages:

                raise RuntimeError(
                    (
                        "No usable textbook "
                        "text could be extracted."
                    )
                )

            # -----------------------------------------
            # CREATE KNOWLEDGE CHUNKS
            # -----------------------------------------

            set_stage(
                "chunking",
                extraction_progress=100
            )

            chunks = make_chunks(
                pages
            )

            if not chunks:

                raise RuntimeError(
                    (
                        "No textbook chunks "
                        "were created."
                    )
                )

            saved_chunks = (
                save_book_chunks(
                    chunks
                )
            )

            if not saved_chunks:

                raise RuntimeError(
                    (
                        "Textbook chunks "
                        "could not be stored."
                    )
                )

            # At this point the book has already
            # become a reusable MedBot knowledge base.

            # -----------------------------------------
            # GENERATE AMC + FMGE QUESTIONS
            # -----------------------------------------

            set_stage(
                "generating_questions",
                extraction_progress=100
            )

            total_questions = (
                generate_questions(
                    saved_chunks
                )
            )

            if total_questions == 0:

                raise RuntimeError(
                    (
                        "Textbook extraction "
                        "worked, but no new "
                        "questions were generated."
                    )
                )

            # -----------------------------------------
            # FINISH
            # -----------------------------------------

            update_book({
                "status":
                    "ready",

                "processing_stage":
                    "ready",

                "extraction_progress":
                    100,

                "question_progress":
                    100,

                "questions_generated":
                    total_questions,

                "processed_pages":
                    len(pages),

                "processing_completed_at":
                    utc_now(),

                "error_message":
                    None
            })

            print(
                "========================================"
            )

            print(
                "MEDQ BOOK PROCESSING COMPLETE"
            )

            print(
                "New-format questions: "
                f"{total_questions}"
            )

            print(
                "========================================"
            )

    except Exception as exc:

        print(
            "========================================"
        )

        print(
            "PROCESSING FAILED"
        )

        print(
            str(exc)
        )

        print(
            "========================================"
        )

        try:

            update_book({
                "status":
                    "failed",

                "processing_stage":
                    "failed",

                "error_message":
                    str(exc)[:1000]
            })

        except Exception as status_exc:

            print(
                (
                    "Could not update "
                    "failure status:"
                )
            )

            print(
                status_exc
            )

        raise


if __name__ == "__main__":
    main()
