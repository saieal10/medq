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
AUTO_MODE = CHAPTER == "__AUTO__"
EXAM_MODE = os.getenv("EXAM_MODE", "mixed").strip().lower()
REQUESTED_COUNT = int(os.getenv("QUESTION_COUNT", "20"))
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"

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
    query = (
        supabase.table("book_chunks")
        .select("id,chunk_index,chapter,page_start,page_end,content")
        .eq("book_id", BOOK_ID)
        .order("chunk_index")
    )
    if not AUTO_MODE:
        query = query.eq("chapter", CHAPTER)
    response = query.execute()
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
    source_chapter = clean(chunk.get("chapter") or "Clinical medicine", 250)
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

AUTHORITATIVE BOOK CHAPTER: {source_chapter}
SUBJECT: {subject}
TARGET: {EXAM_MODE.upper()}

{exam_instruction}

Use ONLY facts supported by SOURCE TEXT. Never ask about prefaces, publishing details, authors,
page numbers, tables of contents, or non-clinical book metadata. Do not invent guidelines or facts.
The authoritative chapter is {source_chapter}; do not rename it.

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
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    payload = {
        "systemInstruction": {"parts": [{"text": (
            "You are MedQ's rigorous medical examination question writer. "
            "AMC and FMGE are different exam styles. Use the supplied textbook source as the factual basis. "
            "Return valid JSON only."
        )}]},
        "contents": [{"role": "user", "parts": [{"text": prompt_for(chunk, amount, subject)}]}],
        "generationConfig": {"temperature": 0.25, "maxOutputTokens": 7000, "responseMimeType": "application/json"},
    }

    models = []
    for model in [GEMINI_MODEL, "gemini-3.5-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite"]:
        if model and model not in models:
            models.append(model)

    last_error = None
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            response = requests.post(url, headers=headers, json=payload, timeout=180)
            if response.ok:
                data = response.json()
                parts = data["candidates"][0]["content"]["parts"]
                content = "\n".join(part.get("text", "") for part in parts if part.get("text"))
                print(f"[AI] Gemini model used: {model}")
                return parse_json_array(content)
            last_error = f"Gemini {model} {response.status_code}: {response.text[:500]}"
            print("[AI]", last_error)
            if response.status_code in (400, 403, 404):
                break
            if response.status_code == 429:
                time.sleep(20 * (attempt + 1))
            else:
                time.sleep(5)
    raise RuntimeError(last_error or "Gemini request failed")


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
        topic = clean(chunk.get("chapter") or "Clinical medicine", 250)

    sigs.add(sig)
    return {
        "book_id": BOOK_ID,
        "source_chunk_id": chunk["id"],
        "subject": subject,
        "chapter": clean(chunk.get("chapter") or "Clinical medicine", 250),
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
    print(f"Mode: {'AUTOPILOT / whole book' if AUTO_MODE else CHAPTER}")
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
