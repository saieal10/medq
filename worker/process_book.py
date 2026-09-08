import os
import io
import re
import json
import time
import tempfile
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
# LIMITS FOR FIRST VERSION
# =========================================================

# Keeps GitHub Actions and free AI usage under control.
# We can increase these later.
MAX_PAGES = int(
    os.getenv("MAX_PAGES", "40")
)

CHUNK_SIZE = int(
    os.getenv("CHUNK_SIZE", "9000")
)

QUESTIONS_PER_CHUNK = int(
    os.getenv("QUESTIONS_PER_CHUNK", "5")
)

MAX_CHUNKS = int(
    os.getenv("MAX_CHUNKS", "8")
)

OCR_DPI = int(
    os.getenv("OCR_DPI", "160")
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
# BOOK STATUS
# =========================================================

def update_book_status(
    status: str
):
    print(
        f"Updating book status → {status}"
    )

    (
        supabase
        .table("books")
        .update({
            "status": status
        })
        .eq(
            "id",
            BOOK_ID
        )
        .execute()
    )


# =========================================================
# DOWNLOAD PDF FROM R2
# =========================================================

def download_pdf(
    destination: str
):
    print(
        "Downloading PDF from R2..."
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
        f"Downloaded {size / 1024 / 1024:.2f} MB"
    )


# =========================================================
# TEXT CLEANING
# =========================================================

def clean_text(
    text: str
) -> str:

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

    print(
        "Running OCR on scanned page..."
    )

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
        lang="eng"
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

    print(
        "Opening PDF..."
    )

    document = fitz.open(
        pdf_path
    )

    total_pages = len(
        document
    )

    pages_to_process = min(
        total_pages,
        MAX_PAGES
    )

    print(
        f"PDF pages: {total_pages}"
    )

    print(
        f"Processing first {pages_to_process} pages"
    )

    extracted = []

    for index in range(
        pages_to_process
    ):
        page = document[
            index
        ]

        page_number = (
            index + 1
        )

        print(
            f"Page {page_number}/{pages_to_process}"
        )

        text = clean_text(
            page.get_text(
                "text"
            )
        )

        # If very little embedded text is present,
        # treat page as scanned and OCR it.
        if len(text) < 120:
            try:
                text = ocr_page(
                    page
                )
            except Exception as exc:
                print(
                    f"OCR failed on page "
                    f"{page_number}: {exc}"
                )

        if len(text) >= 80:
            extracted.append({
                "page": page_number,
                "text": text
            })

    document.close()

    print(
        f"Extracted usable text from "
        f"{len(extracted)} pages"
    )

    return extracted


# =========================================================
# CHUNKING
# =========================================================

def make_chunks(
    pages: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:

    chunks = []

    current_text = ""
    current_pages = []

    for page in pages:

        page_marker = (
            f"\n\n"
            f"--- PAGE {page['page']} ---\n"
        )

        addition = (
            page_marker
            + page["text"]
        )

        if (
            len(current_text)
            + len(addition)
            > CHUNK_SIZE
            and current_text
        ):
            chunks.append({
                "text": current_text,
                "pages": current_pages
            })

            current_text = ""
            current_pages = []

        current_text += addition

        current_pages.append(
            page["page"]
        )

    if current_text:
        chunks.append({
            "text": current_text,
            "pages": current_pages
        })

    chunks = chunks[
        :MAX_CHUNKS
    ]

    print(
        f"Created {len(chunks)} AI chunks"
    )

    return chunks


# =========================================================
# OPENROUTER
# =========================================================

def call_openrouter(
    text: str,
    pages: List[int]
) -> List[Dict[str, Any]]:

    page_range = (
        f"{min(pages)}-{max(pages)}"
        if pages
        else "unknown"
    )

    system_prompt = """
You are an expert medical examination question writer.

Create high-quality single-best-answer medical MCQs suitable for:
1. AMC CAT MCQ examination preparation
2. FMGE examination preparation

Only use facts contained in the provided source text.

Do not invent facts that are not present in the source.

Questions should test clinical reasoning, diagnosis, investigation,
management, pharmacology, pathology, complications, or core concepts
when those topics are supported by the source.

Avoid trivial questions.

Every question must have:
- exactly one best answer
- five options A-E
- plausible distractors
- clear explanation
- difficulty: easy, medium, or hard
- chapter
- topic
- source_page

Return ONLY a valid JSON array.

Do not use Markdown.
Do not wrap JSON in ```.

Required JSON structure:

[
  {
    "stem": "question text",
    "option_a": "answer A",
    "option_b": "answer B",
    "option_c": "answer C",
    "option_d": "answer D",
    "option_e": "answer E",
    "correct_option": "A",
    "explanation": "clear medical explanation",
    "chapter": "chapter or section name",
    "topic": "specific medical topic",
    "difficulty": "medium",
    "source_page": 12
  }
]
""".strip()

    user_prompt = f"""
Subject: {BOOK_SUBJECT}

Source pages:
{page_range}

Create exactly {QUESTIONS_PER_CHUNK} good MCQs from this source.

SOURCE TEXT:

{text}
""".strip()

    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type":
            "application/json",
        "HTTP-Referer":
            "https://medq-practice.netlify.app",
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
            0.25,

        "max_tokens":
            4500
    }

    print(
        "Calling OpenRouter..."
    )

    response = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=180
    )

    if not response.ok:
        print(
            response.text
        )

        raise RuntimeError(
            "OpenRouter request failed: "
            f"{response.status_code}"
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


# =========================================================
# AI JSON CLEANUP
# =========================================================

def parse_ai_json(
    content: str
) -> List[Dict[str, Any]]:

    if not content:
        raise RuntimeError(
            "AI returned an empty response."
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
            "AI response did not contain a JSON array."
        )

    content = content[
        start:end + 1
    ]

    try:
        parsed = json.loads(
            content
        )
    except Exception as exc:
        print(
            "AI OUTPUT:"
        )

        print(
            content[:5000]
        )

        raise RuntimeError(
            f"Unable to parse AI JSON: {exc}"
        )

    if not isinstance(
        parsed,
        list
    ):
        raise RuntimeError(
            "AI response JSON was not a list."
        )

    return parsed


# =========================================================
# QUESTION VALIDATION
# =========================================================

def prepare_question(
    question: Dict[str, Any]
) -> Dict[str, Any] | None:

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
                f"Skipping question: missing {field}"
            )

            return None

    correct_option = (
        str(
            question.get(
                "correct_option",
                ""
            )
        )
        .strip()
        .upper()
    )

    if correct_option not in [
        "A",
        "B",
        "C",
        "D",
        "E"
    ]:
        print(
            "Skipping question: "
            "invalid correct option"
        )

        return None

    difficulty = (
        str(
            question.get(
                "difficulty",
                "medium"
            )
        )
        .strip()
        .lower()
    )

    if difficulty not in [
        "easy",
        "medium",
        "hard"
    ]:
        difficulty = "medium"

    source_page = question.get(
        "source_page"
    )

    try:
        if source_page is not None:
            source_page = int(
                source_page
            )
    except Exception:
        source_page = None

    return {
        "book_id":
            BOOK_ID,

        "subject":
            BOOK_SUBJECT,

        "chapter":
            str(
                question.get(
                    "chapter",
                    ""
                )
            )[:250],

        "topic":
            str(
                question.get(
                    "topic",
                    ""
                )
            )[:250],

        "difficulty":
            difficulty,

        "stem":
            str(
                question["stem"]
            ).strip(),

        "option_a":
            str(
                question["option_a"]
            ).strip(),

        "option_b":
            str(
                question["option_b"]
            ).strip(),

        "option_c":
            str(
                question["option_c"]
            ).strip(),

        "option_d":
            str(
                question["option_d"]
            ).strip(),

        "option_e":
            str(
                question["option_e"]
            ).strip(),

        "correct_option":
            correct_option,

        "explanation":
            str(
                question["explanation"]
            ).strip(),

        "source_page":
            source_page
    }


# =========================================================
# SAVE QUESTIONS
# =========================================================

def save_questions(
    questions: List[Dict[str, Any]]
) -> int:

    valid_questions = []

    for question in questions:
        cleaned = prepare_question(
            question
        )

        if cleaned:
            valid_questions.append(
                cleaned
            )

    if not valid_questions:
        return 0

    result = (
        supabase
        .table("questions")
        .insert(
            valid_questions
        )
        .execute()
    )

    count = len(
        result.data or []
    )

    print(
        f"Saved {count} questions"
    )

    return count


# =========================================================
# REMOVE OLD QUESTIONS
# =========================================================

def clear_existing_questions():

    print(
        "Removing existing generated questions "
        "for this book..."
    )

    (
        supabase
        .table("questions")
        .delete()
        .eq(
            "book_id",
            BOOK_ID
        )
        .execute()
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print(
        "====================================="
    )

    print(
        "MEDQ BOOK PROCESSOR"
    )

    print(
        f"Book ID: {BOOK_ID}"
    )

    print(
        f"Subject: {BOOK_SUBJECT}"
    )

    print(
        "====================================="
    )

    update_book_status(
        "processing"
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

            pages = extract_pages(
                pdf_path
            )

            if not pages:
                raise RuntimeError(
                    "No usable text could be extracted "
                    "from this PDF."
                )

            chunks = make_chunks(
                pages
            )

            if not chunks:
                raise RuntimeError(
                    "No usable text chunks were created."
                )

            clear_existing_questions()

            total_saved = 0

            for index, chunk in enumerate(
                chunks,
                start=1
            ):

                print(
                    "-------------------------------------"
                )

                print(
                    f"AI chunk {index}/{len(chunks)}"
                )

                try:

                    generated = call_openrouter(
                        chunk["text"],
                        chunk["pages"]
                    )

                    saved = save_questions(
                        generated
                    )

                    total_saved += saved

                except Exception as exc:

                    print(
                        f"Chunk {index} failed: {exc}"
                    )

                # Be gentle with free API limits.
                time.sleep(
                    4
                )

            if total_saved == 0:
                raise RuntimeError(
                    "Processing finished but no valid "
                    "MCQs were generated."
                )

            update_book_status(
                "ready"
            )

            print(
                "====================================="
            )

            print(
                f"SUCCESS: {total_saved} questions created"
            )

            print(
                "====================================="
            )

    except Exception as exc:

        print(
            "====================================="
        )

        print(
            "PROCESSING FAILED"
        )

        print(
            str(exc)
        )

        print(
            "====================================="
        )

        try:
            update_book_status(
                "failed"
            )
        except Exception as status_exc:
            print(
                "Could not update failure status:"
            )

            print(
                status_exc
            )

        raise


if __name__ == "__main__":
    main()
