import os
import re
import json
import time
import math
import hashlib
from collections import Counter
from typing import Any, Dict, List, Optional

import requests
from supabase import create_client

BOOK_ID = os.environ["BOOK_ID"].strip()
CHAPTER = os.getenv("CHAPTER", "__AUTO__").strip()
AUTO_MODE = CHAPTER == "__AUTO__"
TARGET_SUBJECT = os.getenv("TARGET_SUBJECT", "__ALL__").strip()
TARGET_TOPIC = os.getenv("TARGET_TOPIC", "__ALL__").strip()
TARGET_SUBTOPIC = os.getenv("TARGET_SUBTOPIC", "__ALL__").strip()
TARGET_DIFFICULTY = os.getenv("TARGET_DIFFICULTY", "all").strip().lower()
EXAM_MODE = os.getenv("EXAM_MODE", "mixed").strip().lower()
REQUESTED_COUNT = int(os.getenv("QUESTION_COUNT", "20"))
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-3.5-flash"

supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

AMC_DOMAINS = [
    ("Adult Health — Medicine", 30.0),
    ("Adult Health — Surgery", 20.0),
    ("Women's Health / Obstetrics & Gynaecology", 12.5),
    ("Child Health / Paediatrics", 12.5),
    ("Mental Health / Psychiatry", 12.5),
    ("Population Health & Ethics", 12.5),
]

FMGE_SUBJECTS = [
    "Anatomy", "Physiology", "Biochemistry", "Pathology", "Pharmacology",
    "Microbiology", "Forensic Medicine", "Community Medicine (PSM)",
    "Medicine", "Surgery", "Obstetrics & Gynaecology", "Pediatrics",
    "Orthopedics", "ENT", "Ophthalmology", "Dermatology", "Psychiatry",
    "Radiology", "Anaesthesiology",
]

SUBJECT_KEYWORDS = {
    "Adult Health — Medicine": ["medicine", "cardio", "respir", "gastro", "endocr", "neph", "renal", "neuro", "haemat", "hemat", "infect", "rheumat", "dermat"],
    "Adult Health — Surgery": ["surgery", "surgical", "trauma", "fracture", "perioperative", "vascular", "urology", "abdomen"],
    "Women's Health / Obstetrics & Gynaecology": ["obstetric", "gynaec", "gynec", "pregnan", "labour", "labor", "antenatal", "menstrual"],
    "Child Health / Paediatrics": ["paedi", "pedi", "child", "neonat", "infant", "vaccin", "development"],
    "Mental Health / Psychiatry": ["psychi", "depress", "anxiety", "psychosis", "bipolar", "suicide", "mental"],
    "Population Health & Ethics": ["ethic", "consent", "population", "epidemi", "public health", "medicare", "pbs", "reporting"],
    "Community Medicine (PSM)": ["community", "psm", "epidemi", "public health", "screening", "biostat"],
    "Obstetrics & Gynaecology": ["obstetric", "gynaec", "gynec", "pregnan", "labour", "labor"],
    "Pediatrics": ["pedi", "paedi", "child", "neonat", "infant"],
    "Orthopedics": ["orthop", "fracture", "bone", "joint"],
    "ENT": ["ear", "nose", "throat", "laryn", "otitis", "sinus"],
    "Ophthalmology": ["ophthal", "eye", "retina", "cornea", "glaucoma"],
    "Anaesthesiology": ["anaesth", "anesth", "airway", "perioperative"],
    "Radiology": ["radiolog", "imaging", "x-ray", "ct ", "mri", "ultrasound"],
}


def clean(value: Any, limit: int = 10000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def signature(stem: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", stem.lower()).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def existing_signatures() -> set:
    response = supabase.table("questions").select("stem").execute()
    return {
        signature(row.get("stem", ""))
        for row in (response.data or [])
        if row.get("stem")
    }


def load_book() -> Dict[str, Any]:
    response = (
        supabase.table("books")
        .select("id,title,subject")
        .eq("id", BOOK_ID)
        .limit(1)
        .execute()
    )
    if not response.data:
        raise RuntimeError("Generation anchor book not found")
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
    chunks = [
        row for row in (response.data or [])
        if len(clean(row.get("content"))) >= 300
    ]
    if not chunks:
        raise RuntimeError("No usable processed library chunks found")
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


def weighted_counts(total: int) -> List[str]:
    raw = [(name, total * pct / 100.0) for name, pct in AMC_DOMAINS]
    floors = {name: int(math.floor(value)) for name, value in raw}
    remaining = total - sum(floors.values())
    fractions = sorted(raw, key=lambda item: item[1] - math.floor(item[1]), reverse=True)
    for index in range(remaining):
        floors[fractions[index % len(fractions)][0]] += 1

    plan = []
    for name, _ in AMC_DOMAINS:
        plan.extend([name] * floors[name])
    return plan


def build_subject_plan(total: int) -> List[str]:
    if TARGET_SUBJECT != "__ALL__":
        return [TARGET_SUBJECT] * total

    if EXAM_MODE == "amc":
        return weighted_counts(total)

    # FMGE/NEET-PG and Mixed: guarantee all 19 subjects across larger banks.
    plan = []
    while len(plan) < total:
        plan.extend(FMGE_SUBJECTS)
    return plan[:total]


def source_score(target_subject: str, chunk: Dict[str, Any], book_subject: str) -> int:
    haystack = (
        f"{book_subject} {chunk.get('chapter') or ''} "
        f"{clean(chunk.get('content'), 2500)}"
    ).lower()
    keywords = list(SUBJECT_KEYWORDS.get(target_subject) or [])
    if not keywords:
        keywords = [part.lower() for part in re.findall(r"[A-Za-z]{4,}", target_subject)[:8]]
    curriculum_text = " ".join(v for v in [TARGET_TOPIC, TARGET_SUBTOPIC] if v and v != "__ALL__")
    keywords.extend(part.lower() for part in re.findall(r"[A-Za-z]{4,}", curriculum_text)[:12])
    return sum(haystack.count(keyword.lower()) for keyword in keywords if keyword)


def best_source_chunk(target_subject: str, chunks: List[Dict[str, Any]], book_subject: str, cursor: int) -> Optional[Dict[str, Any]]:
    if not chunks:
        return None
    scored = [(source_score(target_subject, chunk, book_subject), chunk) for chunk in chunks]
    scored.sort(key=lambda item: item[0], reverse=True)
    useful = [chunk for score, chunk in scored if score > 0]
    if useful:
        return useful[cursor % min(len(useful), 12)]
    return None


def exam_instruction(exam_mode: str, target_subject: str) -> str:
    if exam_mode == "amc":
        return f"""
Write Australian Medical Council CAT MCQ-style single-best-answer questions for {target_subject}.
The AMC style must prioritize realistic clinical vignettes, clinical reasoning, diagnosis,
next best investigation, interpretation, immediate management, definitive management,
patient safety, prioritisation, preventive care, communication and ethics where relevant.
Do NOT turn this into recall-only FMGE questions.
""".strip()
    if exam_mode == "fmge":
        return f"""
Write FMGE / NEET-PG-style single-best-answer questions for {target_subject}.
Use a high-yield MBBS mixture of recall plus clinical application, pathology, pharmacology,
microbiology, anatomy, investigations, treatment, complications, mechanisms and associations
as appropriate for the subject. Keep the level suitable for Indian postgraduate entrance preparation.
""".strip()
    return f"""
Create a balanced mix of AMC clinical-reasoning and FMGE/NEET-PG high-yield questions for {target_subject}.
Set exam_type to amc or fmge for every question.
""".strip()


def prompt_for(target_subject: str, amount: int, chunk: Optional[Dict[str, Any]], book: Dict[str, Any]) -> str:
    source_text = ""
    source_note = (
        "No directly relevant library passage was found for this batch. Use reliable general medical knowledge."
    )
    if chunk:
        source_text = clean(chunk.get("content"), 14000)
        source_note = (
            f"Relevant MedQ library reference is available from {book.get('title')} / "
            f"{clean(chunk.get('chapter') or 'clinical section', 180)}. Use it as grounding where relevant, "
            "but you may supplement missing coverage with reliable general medical knowledge."
        )

    difficulty_rule = (
        f"All questions in this batch must be {TARGET_DIFFICULTY} difficulty."
        if TARGET_DIFFICULTY in {"easy", "medium", "hard"}
        else "Use a sensible mix of easy, medium and hard questions."
    )

    return f"""
You are MedQ's senior medical examination question writer.

TARGET EXAM: {EXAM_MODE.upper()}
TARGET SUBJECT / DOMAIN: {target_subject}
TARGET TOPIC: {TARGET_TOPIC if TARGET_TOPIC != "__ALL__" else "Any appropriate topic within this subject"}
TARGET SUBTOPIC: {TARGET_SUBTOPIC if TARGET_SUBTOPIC != "__ALL__" else "Any appropriate subtopic within the selected topic/subject"}

{exam_instruction(EXAM_MODE, target_subject)}

HYBRID KNOWLEDGE RULE:
{source_note}
MedQ is deliberately AI + library hybrid. The library is a preferred reference, NOT a limitation.
Do not fabricate obscure facts. Use mainstream, clinically accepted medical knowledge when the library
is incomplete. Never ask about authors, publication details, timestamps, page numbers, video headings,
or table-of-contents artefacts.

{difficulty_rule}

If a TARGET TOPIC or TARGET SUBTOPIC is specified, every question must stay within that curriculum area.
The library is grounding, not the syllabus; do not drift merely because a retrieved passage is broader.

Create exactly {amount} original, non-duplicate single-best-answer MCQs.
Every question must:
- test the requested subject/domain
- have exactly five distinct options A-E
- have exactly one best answer
- use plausible distractors
- have a clear teaching explanation
- have a concise clinical topic
- avoid ambiguity and trick wording
- avoid copying source sentences verbatim

Return ONLY a JSON array. Each object must contain:
stem, option_a, option_b, option_c, option_d, option_e, correct_option,
explanation, topic, difficulty, exam_type, question_type.

OPTIONAL LIBRARY REFERENCE:
{source_text or '[No directly relevant library excerpt for this batch]'}
""".strip()


def call_ai(target_subject: str, amount: int, chunk: Optional[Dict[str, Any]], book: Dict[str, Any]) -> List[Dict[str, Any]]:
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    payload = {
        "systemInstruction": {"parts": [{"text": (
            "You are MedQ's rigorous medical examination question writer. "
            "AMC CAT and FMGE/NEET-PG require different question styles. "
            "Use MedQ library excerpts when relevant and supplement with reliable general medical knowledge when needed. "
            "Return valid JSON only."
        )}]},
        "contents": [{"role": "user", "parts": [{"text": prompt_for(target_subject, amount, chunk, book)}]}],
        "generationConfig": {
            "temperature": 0.28,
            "maxOutputTokens": 7000,
            "responseMimeType": "application/json"
        },
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


def prepare(
    q: Dict[str, Any],
    target_subject: str,
    chunk: Optional[Dict[str, Any]],
    book: Dict[str, Any],
    sigs: set,
) -> Optional[Dict[str, Any]]:
    required = ["stem", "option_a", "option_b", "option_c", "option_d", "option_e", "correct_option", "explanation"]
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
    if len({item.lower() for item in options}) != 5:
        return None

    correct = clean(q["correct_option"], 10).upper()[:1]
    if correct not in "ABCDE":
        return None

    difficulty = clean(q.get("difficulty", TARGET_DIFFICULTY if TARGET_DIFFICULTY != "all" else "medium"), 20).lower()
    if TARGET_DIFFICULTY in {"easy", "medium", "hard"}:
        difficulty = TARGET_DIFFICULTY
    elif difficulty not in {"easy", "medium", "hard"}:
        difficulty = "medium"

    exam_type = clean(q.get("exam_type", EXAM_MODE), 20).lower()
    if EXAM_MODE in {"amc", "fmge"}:
        exam_type = EXAM_MODE
    elif exam_type not in {"amc", "fmge"}:
        exam_type = "fmge"

    generated_topic = clean(q.get("topic"), 250)
    if not generated_topic or len(generated_topic.split()) > 14:
        generated_topic = target_subject

    source_used = chunk is not None
    # Student-facing hierarchy is curriculum-based; raw PDF/video headings remain internal only.
    chapter = TARGET_TOPIC if TARGET_TOPIC != "__ALL__" else target_subject
    topic = TARGET_SUBTOPIC if TARGET_SUBTOPIC != "__ALL__" else generated_topic

    sigs.add(sig)
    return {
        "book_id": BOOK_ID,
        "source_chunk_id": chunk.get("id") if source_used else None,
        "subject": target_subject,
        "chapter": chapter or target_subject,
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
        "source_page": chunk.get("page_start") if source_used else None,
        "source_page_end": chunk.get("page_end") if source_used else None,
        "review_status": "generated",
        "quality_score": None,
        "reviewer_notes": "hybrid-library-ai" if source_used else "ai-supplemented",
    }


def main():
    if EXAM_MODE not in {"amc", "fmge", "mixed"}:
        raise RuntimeError("Invalid exam mode")
    if REQUESTED_COUNT not in {10, 20, 50, 100}:
        raise RuntimeError("Question count must be 10, 20, 50, or 100")
    if TARGET_DIFFICULTY not in {"all", "easy", "medium", "hard"}:
        raise RuntimeError("Invalid difficulty")

    book = load_book()
    chunks = load_chunks()
    sigs = existing_signatures()
    plan = build_subject_plan(REQUESTED_COUNT)
    remaining = Counter(plan)

    print("========================================")
    print("MEDQ FINAL HYBRID EXAM ENGINE")
    print(f"Anchor library book: {book.get('title')}")
    print(f"Exam: {EXAM_MODE}")
    print(f"Target subject: {TARGET_SUBJECT}")
    print(f"Target topic: {TARGET_TOPIC}")
    print(f"Target subtopic: {TARGET_SUBTOPIC}")
    print(f"Difficulty: {TARGET_DIFFICULTY}")
    print(f"Requested: {REQUESTED_COUNT}")
    print(f"Plan: {dict(remaining)}")
    print("========================================")

    created = 0
    failures = 0
    subject_cursor = Counter()

    # Work subject-by-subject in small batches so AMC weighting and the 19-subject bank are explicit.
    ordered_subjects = []
    for item in plan:
        if item not in ordered_subjects:
            ordered_subjects.append(item)

    for target_subject in ordered_subjects:
        need = remaining[target_subject]
        while need > 0:
            amount = min(5, need)
            chunk = best_source_chunk(
                target_subject,
                chunks,
                clean(book.get("subject") or "", 120),
                subject_cursor[target_subject],
            )
            subject_cursor[target_subject] += 1

            print(f"[AI] {target_subject} | need {need} | library={'yes' if chunk else 'supplement'}")

            try:
                generated = call_ai(target_subject, amount, chunk, book)
                rows = []
                for q in generated:
                    prepared = prepare(q, target_subject, chunk, book, sigs)
                    if prepared:
                        rows.append(prepared)
                    if len(rows) >= amount:
                        break

                if rows:
                    result = supabase.table("questions").insert(rows).execute()
                    saved = len(result.data or rows)
                    created += saved
                    need -= saved
                    print(f"[DB] saved {saved}; total {created}/{REQUESTED_COUNT}")
                else:
                    failures += 1
                    print("[QUALITY] no valid new questions from batch")
            except Exception as exc:
                failures += 1
                print(f"[AI] failed: {exc}")

            if failures >= 8 and created == 0:
                raise RuntimeError("AI generation repeatedly failed before saving any questions")
            if failures >= 15:
                print("[WARN] stopping after repeated provider/quality failures")
                break

            time.sleep(3)

        if failures >= 15:
            break

    print("========================================")
    print(f"DONE: {created} new questions created")
    print("========================================")

    if created == 0:
        raise RuntimeError("No questions were generated. Check Gemini quota/provider logs.")


if __name__ == "__main__":
    main()
