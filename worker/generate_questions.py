import os
import re
import json
import time
import hashlib
from typing import Any, Dict, List

import requests
from supabase import create_client

BOOK_ID = os.environ["BOOK_ID"].strip()
CHAPTER = os.environ["CHAPTER"].strip()
EXAM_MODE = os.getenv("EXAM_MODE", "mixed").strip().lower()
REQUESTED_COUNT = int(os.getenv("QUESTION_COUNT", "20"))
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


def clean(value: Any, limit: int = 10000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def signature(stem: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", stem.lower()).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def existing_signatures() -> set:
    response = (
        supabase.table("questions")
        .select("stem")
        .eq("book_id", BOOK_ID)
        .execute()
    )
    return {signature(row.get("stem", "")) for row in (response.data or []) if row.get("stem")}


def load_book() -> Dict[str, Any]:
    response = (
        supabase.table("books")
        .select("id,title,subject")
        .eq("id", BOOK_ID)
        .limit(1)
        .execute()
    )
    if not response.data:
        raise RuntimeError("Book not found")
    return response.data[0]


def load_chunks() -> List[Dict[str, Any]]:
    response = (
        supabase.table("book_chunks")
        .select("id,chunk_index,chapter,page_start,page_end,content")
        .eq("book_id", BOOK_ID)
        .eq("chapter", CHAPTER)
        .order("chunk_index")
        .execute()
    )
    chunks = [row for row in (response.data or []) if len(clean(row.get("content"))) >= 300]
    if not chunks:
        raise RuntimeError("No usable processed chunks found for this chapter")
    return chunks


def parse_json_array(content: str) -> List[Dict[str, Any]]:
    content = (content or "").strip()
    content = re.sub(r"^```(?:json)?", "", content, flags=re.I).strip()
    content = re.sub(r"```$", "", content).strip()
    start, end = content.find("["), content.rfind("]")
    if start < 0 or end <= start:
        raise RuntimeError("AI response did not contain a JSON array")
    value = json.loads(content[start:end + 1])
    if not isinstance(value, list):
        raise RuntimeError("AI response was not a list")
    return value


def prompt_for(chunk: Dict[str, Any], amount: int, subject: str) -> str:
    if EXAM_MODE == "amc":
        exam_instruction = (
            "Write AMC CAT-style single-best-answer questions. Prefer realistic clinical "
            "vignettes, safe next-best-step decisions, diagnosis, investigation and management."
        )
    elif EXAM_MODE == "fmge":
        exam_instruction = (
            "Write FMGE-style single-best-answer questions. Emphasize high-yield MBBS facts "
            "with clinically relevant diagnosis, pathology, pharmacology, investigations and treatment."
        )
    else:
        exam_instruction = (
            "Create a balanced mix of AMC clinical reasoning and FMGE high-yield application questions. "
            "Set exam_type to amc or fmge for each question."
        )

    return f"""
You are a senior medical examination question writer for MedQ.

AUTHORITATIVE BOOK CHAPTER: {CHAPTER}
SUBJECT: {subject}
TARGET: {EXAM_MODE.upper()}

{exam_instruction}

Use ONLY facts supported by SOURCE TEXT. Never ask about prefaces, publishing details, authors,
page numbers, tables of contents, or non-clinical book metadata. Do not invent guidelines or facts.
The authoritative chapter is {CHAPTER}; do not rename it.

Create exactly {amount} high-quality, non-duplicate single-best-answer MCQs.
Each question must have exactly five distinct options A-E, one best answer, a useful explanation,
a concise specific clinical topic, and difficulty easy/medium/hard. Avoid trivial wording and
avoid questions answerable from grammar alone. Explanations should teach why the answer is best.

Return ONLY a JSON array. Each object must contain:
stem, option_a, option_b, option_c, option_d, option_e, correct_option,
explanation, topic, difficulty, exam_type, question_type.

SOURCE TEXT:
{clean(chunk.get('content'), 18000)}
""".strip()


def call_ai(chunk: Dict[str, Any], amount: int, subject: str) -> List[Dict[str, Any]]:
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
                "content": (
                    "Generate rigorous textbook-grounded medical exam questions. "
                    "Output valid JSON only."
                ),
            },
            {"role": "user", "content": prompt_for(chunk, amount, subject)},
        ],
        "temperature": 0.25,
        "max_tokens": 5000,
    }

    last_error = None
    for attempt in range(3):
        response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=180)
        if response.ok:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return parse_json_array(content)
        last_error = f"OpenRouter {response.status_code}: {response.text[:300]}"
        if response.status_code == 429:
            time.sleep(20 * (attempt + 1))
        else:
            time.sleep(5)
    raise RuntimeError(last_error or "AI request failed")


def prepare(q: Dict[str, Any], chunk: Dict[str, Any], subject: str, sigs: set) -> Dict[str, Any] | None:
    required = ["stem","option_a","option_b","option_c","option_d","option_e","correct_option","explanation"]
    if any(not clean(q.get(key)) for key in required):
        return None

    stem = clean(q["stem"], 2500)
    explanation = clean(q["explanation"], 5000)
    if len(stem) < 35 or len(explanation) < 45:
        return None

    sig = signature(stem)
    if sig in sigs:
        return None

    options = [clean(q[f"option_{letter}"], 1000) for letter in "abcde"]
    if len({x.lower() for x in options}) != 5:
        return None

    correct = clean(q["correct_option"], 10).upper()[:1]
    if correct not in "ABCDE":
        return None

    difficulty = clean(q.get("difficulty", "medium"), 20).lower()
    if difficulty not in {"easy","medium","hard"}:
        difficulty = "medium"

    exam_type = clean(q.get("exam_type", EXAM_MODE), 20).lower()
    if EXAM_MODE in {"amc","fmge"}:
        exam_type = EXAM_MODE
    elif exam_type not in {"amc","fmge"}:
        exam_type = "both"

    topic = clean(q.get("topic"), 250)
    if not topic or len(topic.split()) > 12:
        topic = CHAPTER

    sigs.add(sig)
    return {
        "book_id": BOOK_ID,
        "source_chunk_id": chunk["id"],
        "subject": subject,
        "chapter": CHAPTER,
        "topic": topic,
        "exam_type": exam_type,
        "question_type": clean(q.get("question_type", "clinical"), 100) or "clinical",
        "difficulty": difficulty,
        "stem": stem,
        "option_a": options[0],
        "option_b": options[1],
        "option_c": options[2],
        "option_d": options[3],
        "option_e": options[4],
        "correct_option": correct,
        "explanation": explanation,
        "source_page": chunk.get("page_start"),
        "source_page_end": chunk.get("page_end"),
        "review_status": "generated",
        "quality_score": None,
        "reviewer_notes": None,
    }


def main():
    if EXAM_MODE not in {"amc","fmge","mixed"}:
        raise RuntimeError("Invalid exam mode")
    if REQUESTED_COUNT not in {10,20,50}:
        raise RuntimeError("Question count must be 10, 20, or 50")

    book = load_book()
    subject = clean(book.get("subject") or "General", 120)
    chunks = load_chunks()
    sigs = existing_signatures()

    print("========================================")
    print("MEDQ ON-DEMAND QUESTION GENERATOR")
    print(f"Book: {book.get('title')}")
    print(f"Chapter: {CHAPTER}")
    print(f"Exam: {EXAM_MODE}")
    print(f"Requested: {REQUESTED_COUNT}")
    print(f"Usable chunks: {len(chunks)}")
    print("========================================")

    created = 0
    cursor = 0
    failures = 0

    while created < REQUESTED_COUNT and cursor < max(len(chunks) * 2, 1):
        chunk = chunks[cursor % len(chunks)]
        remaining = REQUESTED_COUNT - created
        ask = min(5, remaining)
        print(f"[AI] chunk {chunk.get('chunk_index')} | need {remaining}")

        try:
            generated = call_ai(chunk, ask, subject)
            rows = []
            for q in generated:
                prepared = prepare(q, chunk, subject, sigs)
                if prepared:
                    rows.append(prepared)
                if created + len(rows) >= REQUESTED_COUNT:
                    break

            if rows:
                result = supabase.table("questions").insert(rows).execute()
                saved = len(result.data or rows)
                created += saved
                print(f"[DB] saved {saved}; total {created}/{REQUESTED_COUNT}")
            else:
                print("[QUALITY] no valid new questions from this chunk")
        except Exception as exc:
            failures += 1
            print(f"[AI] failed: {exc}")
            if failures >= 4 and created == 0:
                raise

        cursor += 1
        time.sleep(4)

    print("========================================")
    print(f"DONE: {created} new questions created")
    print("========================================")

    if created == 0:
        raise RuntimeError("No questions were generated. Check AI quota/provider logs.")


if __name__ == "__main__":
    main()
