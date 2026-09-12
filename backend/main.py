import os
import re
import uuid
import json
import time
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional, List, Dict, Any

import boto3
from botocore.config import Config
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from supabase import create_client


load_dotenv()

app = FastAPI(
    title="MedQ API",
    version="0.9.0"
)


# ---------------------------------------------------------
# Environment
# ---------------------------------------------------------

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv(
    "R2_BUCKET_NAME",
    "medq-books"
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv(
    "SUPABASE_SECRET_KEY"
)

FRONTEND_ORIGINS = os.getenv(
    "FRONTEND_ORIGINS",
    "http://localhost:5173,https://medq-practice.netlify.app"
)

# GitHub Actions
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

GITHUB_REPO_OWNER = os.getenv(
    "GITHUB_REPO_OWNER",
    "saieal10"
)

GITHUB_REPO_NAME = os.getenv(
    "GITHUB_REPO_NAME",
    "medq"
)

GITHUB_WORKFLOW_FILE = os.getenv(
    "GITHUB_WORKFLOW_FILE",
    "process-book.yml"
)

GITHUB_BRANCH = os.getenv(
    "GITHUB_BRANCH",
    "main"
)


# Gemini / MedBot
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"

# MedBot performance controls. These defaults keep the free-tier request
# small and responsive while preserving textbook grounding.
MEDBOT_MAX_CHUNKS = int(os.getenv("MEDBOT_MAX_CHUNKS", "1200"))
MEDBOT_TOP_CHUNKS = int(os.getenv("MEDBOT_TOP_CHUNKS", "4"))
MEDBOT_CONTEXT_CHARS = int(os.getenv("MEDBOT_CONTEXT_CHARS", "10000"))
MEDBOT_AI_TIMEOUT = int(os.getenv("MEDBOT_AI_TIMEOUT", "45"))
MEDBOT_MAX_TOKENS = int(os.getenv("MEDBOT_MAX_TOKENS", "750"))


origins = [
    origin.strip()
    for origin in FRONTEND_ORIGINS.split(",")
    if origin.strip()
]


# ---------------------------------------------------------
# CORS
# ---------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Clients
# ---------------------------------------------------------

def get_r2_client():

    required = [
        R2_ACCOUNT_ID,
        R2_ACCESS_KEY_ID,
        R2_SECRET_ACCESS_KEY,
        R2_BUCKET_NAME,
    ]

    if not all(required):
        raise HTTPException(
            status_code=500,
            detail="R2 configuration is incomplete."
        )

    return boto3.client(
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


def get_supabase():

    if (
        not SUPABASE_URL
        or not SUPABASE_SECRET_KEY
    ):
        raise HTTPException(
            status_code=500,
            detail=(
                "Supabase backend configuration "
                "is incomplete."
            )
        )

    return create_client(
        SUPABASE_URL,
        SUPABASE_SECRET_KEY
    )


# ---------------------------------------------------------
# Models
# ---------------------------------------------------------

class UploadRequest(BaseModel):
    filename: str
    content_type: str = "application/pdf"


class RegisterBookRequest(BaseModel):
    title: str
    subject: Optional[str] = None
    file_key: str
    file_size_bytes: Optional[int] = None
    uploaded_by: str



class MedBotMessage(BaseModel):
    role: str
    content: str


class MedBotRequest(BaseModel):
    message: str
    book_id: Optional[str] = None
    question_id: Optional[str] = None
    conversation: Optional[List[MedBotMessage]] = None


class GenerateQuestionsRequest(BaseModel):
    book_id: Optional[str] = None
    chapter: str = "__AUTO__"
    subject: str = "__ALL__"
    topic: str = "__ALL__"
    subtopic: str = "__ALL__"
    difficulty: str = "all"
    exam_mode: str = "mixed"
    count: int = 20


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def safe_filename(filename: str):

    filename = filename.strip()

    filename = re.sub(
        r"[^A-Za-z0-9._-]+",
        "-",
        filename
    )

    return filename[:180]




# ---------------------------------------------------------
# MedBot helpers
# ---------------------------------------------------------

MEDBOT_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by",
    "for", "from", "how", "i", "in", "is", "it", "me",
    "of", "on", "or", "that", "the", "this", "to", "what",
    "when", "where", "which", "why", "with", "you", "your",
    "explain", "tell", "about", "please", "can", "could",
    "would", "should", "do", "does", "did"
}


def require_authenticated_user(
    authorization: Optional[str]
):

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Authentication required."
        )

    parts = authorization.split(
        " ",
        1
    )

    if (
        len(parts) != 2
        or parts[0].lower() != "bearer"
        or not parts[1].strip()
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header."
        )

    token = parts[1].strip()
    supabase = get_supabase()

    try:
        response = supabase.auth.get_user(
            token
        )
        user = getattr(
            response,
            "user",
            None
        )
    except Exception:
        user = None

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Session is invalid or expired."
        )

    return user


def medbot_tokens(text: str):

    words = re.findall(
        r"[A-Za-z0-9]+",
        (text or "").lower()
    )

    return [
        word
        for word in words
        if (
            len(word) >= 3
            and word not in MEDBOT_STOP_WORDS
        )
    ]


def get_chunk_text(chunk: Dict[str, Any]):

    for key in [
        "content",
        "text",
        "chunk_text",
        "text_content",
        "body",
        "source_text"
    ]:
        value = chunk.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def get_chunk_chapter(chunk: Dict[str, Any]):

    for key in [
        "chapter",
        "chapter_title",
        "section",
        "section_title",
        "topic"
    ]:
        value = chunk.get(key)

        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def load_medbot_chunks(
    supabase,
    book_id: Optional[str] = None,
    max_rows: int = 5000
):

    rows = []
    batch_size = 1000
    start = 0

    while start < max_rows:

        query = (
            supabase
            .table("book_chunks")
            .select("*")
        )

        if book_id:
            query = query.eq(
                "book_id",
                book_id
            )

        result = (
            query
            .range(
                start,
                min(
                    start + batch_size - 1,
                    max_rows - 1
                )
            )
            .execute()
        )

        batch = result.data or []
        rows.extend(batch)

        if len(batch) < batch_size:
            break

        start += batch_size

    return rows


def rank_medbot_chunks(
    chunks: List[Dict[str, Any]],
    search_text: str,
    limit: int = 6
):

    tokens = medbot_tokens(
        search_text
    )

    if not tokens:
        return []

    unique_tokens = list(
        dict.fromkeys(tokens)
    )

    phrase = " ".join(
        unique_tokens[:8]
    )

    ranked = []

    for chunk in chunks:

        body = get_chunk_text(
            chunk
        )

        if not body:
            continue

        chapter = get_chunk_chapter(
            chunk
        )

        body_lower = body.lower()
        chapter_lower = chapter.lower()

        score = 0.0
        matched = 0

        for token in unique_tokens:

            body_count = body_lower.count(
                token
            )

            if body_count:
                matched += 1
                score += min(
                    body_count,
                    5
                )

            if token in chapter_lower:
                score += 4.0

        if phrase and phrase in body_lower:
            score += 8.0

        if matched >= 2:
            score += matched * 1.5

        if score > 0:
            ranked.append(
                (score, chunk)
            )

    ranked.sort(
        key=lambda item: item[0],
        reverse=True
    )

    return [
        chunk
        for _, chunk in ranked[:limit]
    ]


def load_book_titles(
    supabase,
    book_ids: List[str]
):

    titles = {}

    for book_id in list(
        dict.fromkeys(
            book_ids
        )
    ):

        if not book_id:
            continue

        try:
            result = (
                supabase
                .table("books")
                .select("id,title,subject")
                .eq(
                    "id",
                    book_id
                )
                .limit(1)
                .execute()
            )

            if result.data:
                titles[book_id] = (
                    result.data[0]
                    .get("title")
                    or "Uploaded textbook"
                )

        except Exception:
            pass

    return titles


def call_gemini_medbot(messages: List[Dict[str, str]]):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured on the backend.")

    system_text = ""
    contents = []
    for item in messages:
        role = (item.get("role") or "").lower()
        text = (item.get("content") or "").strip()
        if not text:
            continue
        if role == "system":
            system_text += ("\n" if system_text else "") + text
            continue
        contents.append({"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]})

    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": MEDBOT_MAX_TOKENS},
    }
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}

    # Account/project access can differ by Gemini model. Try the configured
    # model first, then stable fallbacks instead of exposing a useless 404.
    models = []
    for model in [GEMINI_MODEL, "gemini-3.5-flash", "gemini-2.5-flash", "gemini-3.5-flash-lite"]:
        if model and model not in models:
            models.append(model)

    last_detail = ""
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json", "User-Agent": "MedQ-Backend"},
        )
        try:
            with urllib.request.urlopen(request, timeout=MEDBOT_AI_TIMEOUT) as response:
                raw = response.read().decode("utf-8")
            data = json.loads(raw)
            parts = data["candidates"][0]["content"]["parts"]
            answer = "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()
            if answer:
                return answer, model
        except urllib.error.HTTPError as exc:
            try:
                last_detail = exc.read().decode("utf-8")
            except Exception:
                last_detail = str(exc)
            print(f"Gemini MedBot {model} error:", last_detail)
            if exc.code == 429:
                raise HTTPException(status_code=429, detail="MedBot's Gemini free allowance is temporarily rate-limited. Please try again shortly.")
            if exc.code in (400, 403, 404):
                continue
            raise HTTPException(status_code=502, detail=f"Gemini returned an error ({exc.code}).")
        except Exception as exc:
            last_detail = str(exc)
            print(f"Gemini MedBot {model} connection error:", last_detail)
            continue

    raise HTTPException(
        status_code=502,
        detail="MedBot could not use any available Gemini model. Check the Gemini API key/project access in Google AI Studio."
    )




def medbot_should_use_library(message: str) -> bool:
    """Only search the large textbook library when the student asks for it.

    Normal medical questions take the fast AI-only path, like ChatGPT/Gemini.
    This avoids scanning up to thousands of Supabase chunks before every reply.
    """
    text = (message or "").lower()
    library_phrases = [
        "my library", "medq library", "uploaded book", "uploaded textbook",
        "from the book", "from my book", "from textbook", "from the textbook",
        "according to harrison", "harrison", "prepladder", "my notes",
        "according to the book", "source from", "book source", "textbook source",
    ]
    return any(phrase in text for phrase in library_phrases)


def _sse_event(payload: Dict[str, Any]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def stream_gemini_medbot(messages: List[Dict[str, str]]):
    """Stream Gemini with automatic retry + model fallback.

    Transient 429/500/502/503/504 responses are retried automatically.
    The browser receives status events while MedBot retries, so it does not
    look frozen. A user-visible error is emitted only after every configured
    model/retry path has been exhausted.
    """
    if not GEMINI_API_KEY:
        yield _sse_event({"type": "error", "message": "GEMINI_API_KEY is not configured on the backend."})
        return

    system_text = ""
    contents = []
    for item in messages:
        role = (item.get("role") or "").lower()
        msg_text = (item.get("content") or "").strip()
        if not msg_text:
            continue
        if role == "system":
            system_text += ("\n" if system_text else "") + msg_text
            continue
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": msg_text}],
        })

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": MEDBOT_MAX_TOKENS,
        },
    }
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}

    # Configured model first, then lightweight fallbacks already used by MedQ.
    models = []
    for model in [
        GEMINI_MODEL,
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash",
    ]:
        if model and model not in models:
            models.append(model)

    retryable_codes = {429, 500, 502, 503, 504}
    max_attempts_per_model = 3
    last_error = ""

    for model_index, model in enumerate(models):
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:streamGenerateContent?alt=sse"
        )

        for attempt in range(1, max_attempts_per_model + 1):
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={
                    "x-goog-api-key": GEMINI_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "User-Agent": "MedQ-Backend",
                },
            )

            try:
                with urllib.request.urlopen(req, timeout=MEDBOT_AI_TIMEOUT) as response:
                    yield _sse_event({"type": "meta", "model": model})
                    accumulated = ""
                    received_text = False

                    for raw_line in response:
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line.startswith("data:"):
                            continue

                        raw_json = line[5:].strip()
                        if not raw_json:
                            continue

                        try:
                            data = json.loads(raw_json)
                        except Exception:
                            continue

                        try:
                            parts = data.get("candidates", [])[0].get("content", {}).get("parts", [])
                        except Exception:
                            parts = []

                        chunk_text = "".join(
                            part.get("text", "")
                            for part in parts
                            if isinstance(part, dict) and part.get("text")
                        )
                        if not chunk_text:
                            continue

                        received_text = True

                        # Handles both delta-style and cumulative chunks.
                        if accumulated and chunk_text.startswith(accumulated):
                            delta = chunk_text[len(accumulated):]
                            accumulated = chunk_text
                        else:
                            delta = chunk_text
                            accumulated += chunk_text

                        if delta:
                            yield _sse_event({"type": "delta", "text": delta})

                    if received_text:
                        yield _sse_event({"type": "done", "model": model})
                        return

                    # Empty successful response: retry/fallback instead of hanging.
                    last_error = f"{model} returned an empty response."
                    print("Gemini streaming MedBot:", last_error)

            except urllib.error.HTTPError as exc:
                try:
                    last_error = exc.read().decode("utf-8", errors="ignore")
                except Exception:
                    last_error = str(exc)

                print(f"Gemini streaming MedBot {model} attempt {attempt} error:", last_error)

                if exc.code in (400, 403, 404):
                    # Model/project incompatibility: immediately try next model.
                    break

                if exc.code in retryable_codes:
                    if attempt < max_attempts_per_model:
                        # Respect Retry-After when present, otherwise exponential backoff.
                        try:
                            retry_after = float(exc.headers.get("Retry-After", "0") or "0")
                        except Exception:
                            retry_after = 0.0
                        delay = retry_after if retry_after > 0 else min(1.5 * (2 ** (attempt - 1)), 6.0)

                        yield _sse_event({
                            "type": "status",
                            "message": "MedBot is reconnecting to the AI…",
                        })
                        time.sleep(delay)
                        continue

                    # Same model exhausted: transparently fall through to next model.
                    yield _sse_event({
                        "type": "status",
                        "message": "Trying another AI model…",
                    })
                    break

                # Non-transient provider error: try next model rather than immediately failing.
                break

            except Exception as exc:
                last_error = str(exc)
                print(f"Gemini streaming MedBot {model} attempt {attempt} connection error:", last_error)

                if attempt < max_attempts_per_model:
                    yield _sse_event({
                        "type": "status",
                        "message": "MedBot is reconnecting to the AI…",
                    })
                    time.sleep(min(1.5 * (2 ** (attempt - 1)), 6.0))
                    continue
                break

        # Small pause before switching models; avoids hammering the provider.
        if model_index < len(models) - 1:
            time.sleep(0.4)

    yield _sse_event({
        "type": "error",
        "message": (
            "The AI service is temporarily busy. MedBot retried automatically, "
            "but no Gemini model responded. Please try again in a minute."
        ),
    })

def trigger_github_workflow(
    book_id: str,
    file_key: str,
    subject: str,
    exam_track: str = "fmge_neetpg"
):

    if not GITHUB_TOKEN:
        raise HTTPException(
            status_code=500,
            detail=(
                "GitHub workflow configuration "
                "is incomplete."
            )
        )

    url = (
        f"https://api.github.com/repos/"
        f"{GITHUB_REPO_OWNER}/"
        f"{GITHUB_REPO_NAME}/"
        f"actions/workflows/"
        f"{GITHUB_WORKFLOW_FILE}/dispatches"
    )

    payload = {
        "ref": GITHUB_BRANCH,
        "inputs": {
            "book_id": str(book_id),
            "file_key": str(file_key),
            "subject": subject or "General",
            "exam_track": exam_track or "fmge_neetpg",
        }
    }

    encoded_payload = json.dumps(
        payload
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=encoded_payload,
        method="POST",
        headers={
            "Authorization": (
                f"Bearer {GITHUB_TOKEN}"
            ),
            "Accept": (
                "application/vnd.github+json"
            ),
            "X-GitHub-Api-Version": (
                "2022-11-28"
            ),
            "Content-Type": (
                "application/json"
            ),
            "User-Agent": "MedQ-Backend",
        }
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:

            status_code = (
                response.status
            )

    except urllib.error.HTTPError as exc:

        try:
            error_body = (
                exc.read()
                .decode("utf-8")
            )
        except Exception:
            error_body = str(exc)

        print(
            "GitHub workflow error:",
            error_body
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "GitHub workflow could not start. "
                f"GitHub returned {exc.code}."
            )
        )

    except Exception as exc:

        print(
            "Unable to contact GitHub:",
            str(exc)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to contact GitHub "
                "Actions."
            )
        )

    # GitHub workflow_dispatch normally
    # returns HTTP 204 when accepted.
    if status_code not in [
        200,
        201,
        204
    ]:

        raise HTTPException(
            status_code=500,
            detail=(
                "GitHub workflow returned "
                f"unexpected status "
                f"{status_code}."
            )
        )

    return True


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

@app.get("/")
def root():

    return {
        "name": "MedQ API",
        "status": "online",
        "version": "0.9.0",
        "features": [
            "r2-storage",
            "supabase-books",
            "direct-pdf-upload",
            "github-processing-worker",
            "medbot-gemini-textbook-retrieval"
        ]
    }


@app.get("/api/health")
def health():

    return {
        "ok": True,
        "service": "medq-api",
        "version": "0.9.0"
    }




# ---------------------------------------------------------
# MedBot textbook-grounded chat
# ---------------------------------------------------------

@app.post("/api/questions/generate")
def generate_questions_on_demand(
    request: GenerateQuestionsRequest,
    authorization: Optional[str] = Header(default=None),
):
    """
    Bank-only practice endpoint.

    Practice NEVER asks Gemini to create questions. It only reports how many
    already-built questions are available in the permanent MedQ question bank.
    Background GitHub workers build the bank from uploaded books.
    """
    require_authenticated_user(authorization)

    if request.exam_mode not in {"amc", "fmge", "mixed"}:
        raise HTTPException(status_code=400, detail="exam_mode must be amc, fmge, or mixed.")

    if request.count not in {10, 20, 50, 100}:
        raise HTTPException(status_code=400, detail="count must be 10, 20, 50, or 100.")

    supabase = get_supabase()
    query = supabase.table("questions").select("id", count="exact")

    if request.subject and request.subject != "all":
        query = query.eq("subject", request.subject)
    if request.book_id and request.book_id != "all":
        query = query.eq("book_id", request.book_id)
    if request.chapter and request.chapter != "all":
        query = query.eq("chapter", request.chapter)
    if request.topic and request.topic != "all":
        query = query.eq("topic", request.topic)
    if request.difficulty and request.difficulty != "all":
        query = query.eq("difficulty", request.difficulty)

    result = query.limit(1).execute()
    available = getattr(result, "count", None)
    if available is None:
        available = len(result.data or [])

    return {
        "ok": True,
        "status": "bank_only",
        "available": int(available or 0),
        "requested": request.count,
        "exam_mode": request.exam_mode,
        "message": (
            "Questions are served from the permanent MedQ question bank. "
            "Background book processing continues separately."
        ),
    }


@app.post("/api/medbot/stream")
def medbot_stream(
    request: MedBotRequest,
    authorization: Optional[str] = Header(default=None)
):
    """Fast ChatGPT/Gemini-style MedBot with streamed output.

    General medical questions go straight to Gemini. The large MedQ textbook
    library is searched only when the student explicitly asks for book/library
    grounding, which removes the main source of delay.
    """
    require_authenticated_user(authorization)

    message = (request.message or "").strip()
    if len(message) < 2:
        raise HTTPException(status_code=400, detail="Please enter a question.")
    if len(message) > 5000:
        raise HTTPException(status_code=400, detail="Question is too long.")

    supabase = get_supabase()
    question_context = ""
    preferred_book_id = request.book_id
    search_text = message

    # Practice question context is a small single-row lookup and stays fast.
    if request.question_id:
        try:
            result = (
                supabase.table("questions")
                .select("stem,topic,chapter,explanation,book_id")
                .eq("id", request.question_id)
                .limit(1)
                .execute()
            )
            if result.data:
                q = result.data[0]
                if not preferred_book_id:
                    preferred_book_id = q.get("book_id")
                stem = q.get("stem") or ""
                topic = q.get("topic") or ""
                search_text = " ".join([message, stem, topic])
                question_context = f"Practice question:\n{stem}\n"
                if q.get("explanation"):
                    question_context += f"Existing explanation:\n{q.get('explanation')}\n"
        except Exception as exc:
            print("Unable to load practice question context:", str(exc))

    source_items = []
    context_sections = []

    # Critical performance change: do NOT scan book_chunks for ordinary chat.
    # Only do it when the user explicitly requests textbook/library grounding.
    if medbot_should_use_library(message):
        try:
            chunks = load_medbot_chunks(
                supabase,
                book_id=preferred_book_id,
                max_rows=min(MEDBOT_MAX_CHUNKS, 600),
            )
            relevant = rank_medbot_chunks(chunks, search_text, limit=min(MEDBOT_TOP_CHUNKS, 3))
            if relevant:
                book_ids = [str(c.get("book_id")) for c in relevant if c.get("book_id")]
                titles = load_book_titles(supabase, book_ids)
                total_chars = 0
                seen = set()
                for i, chunk in enumerate(relevant, start=1):
                    body = get_chunk_text(chunk)
                    if not body:
                        continue
                    remaining = min(MEDBOT_CONTEXT_CHARS, 6500) - total_chars
                    if remaining <= 0:
                        break
                    body = body[:remaining]
                    total_chars += len(body)
                    bid = str(chunk.get("book_id") or "")
                    title = titles.get(bid) or "MedQ textbook"
                    chapter = get_chunk_chapter(chunk)
                    context_sections.append(
                        f"REFERENCE {i}: {title}" + (f" | {chapter}" if chapter else "") + f"\n{body}"
                    )
                    key = (title, chapter)
                    if key not in seen:
                        seen.add(key)
                        item = {"book_title": title}
                        if chapter:
                            item["chapter"] = chapter
                        source_items.append(item)
        except Exception as exc:
            print("Optional fast library retrieval skipped:", str(exc))

    system_prompt = (
        "You are MedBot, a fast conversational AI medical tutor for an MBBS student preparing "
        "for AMC CAT MCQ, FMGE and NEET-PG. Behave like a high-quality integrated Gemini/ChatGPT "
        "medical assistant: answer the question directly, keep context across turns, and adapt depth "
        "to the student's wording. Start concise, then add detail when useful. For AMC emphasize "
        "clinical reasoning, safety, next-best-step, investigations and management. For FMGE/NEET-PG "
        "include high-yield facts and clinical application. Explain simply first, then precise medical "
        "terms. For MCQs explain why the best answer wins and important distractors lose. You can make "
        "mnemonics, tables, differentials and mini-quizzes when asked. Do not mention page numbers. "
        "Uploaded textbook excerpts, when supplied, are optional reference context rather than a limit. "
        "Do not say you are searching the library unless library excerpts were actually supplied. "
        "This is educational information, not personal medical care."
    )

    messages = [{"role": "system", "content": system_prompt}]
    if request.conversation:
        for item in request.conversation[-6:]:
            role = (item.role or "").lower()
            content = (item.content or "").strip()
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content[:2200]})

    user_prompt = message
    if question_context:
        user_prompt += "\n\n" + question_context
    if context_sections:
        user_prompt += (
            "\n\nUse these MedQ textbook excerpts when helpful:\n\n"
            + "\n\n---\n\n".join(context_sections)
        )
    messages.append({"role": "user", "content": user_prompt})

    def event_stream():
        # Send metadata immediately so the browser knows the request is alive.
        yield _sse_event({
            "type": "ready",
            "sources": source_items,
            "knowledge_mode": "ai_plus_library" if source_items else "ai",
        })
        yield from stream_gemini_medbot(messages)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

@app.post("/api/medbot/chat")
def medbot_chat(
    request: MedBotRequest,
    authorization: Optional[str] = Header(default=None)
):
    """AI-first MedBot.

    Gemini is the main medical tutor. Processed MedQ books are optional
    retrieval context when they are relevant, never a requirement for an
    answer. Practice-question context is also supplied when MedBot is opened
    from Practice.
    """

    require_authenticated_user(authorization)

    message = (request.message or "").strip()
    if len(message) < 2:
        raise HTTPException(status_code=400, detail="Please enter a question.")
    if len(message) > 5000:
        raise HTTPException(status_code=400, detail="Question is too long.")

    supabase = get_supabase()
    search_text = message
    question_context = ""
    preferred_book_id = request.book_id

    # Optional practice-question context.
    if request.question_id:
        try:
            result = (
                supabase.table("questions")
                .select("*")
                .eq("id", request.question_id)
                .limit(1)
                .execute()
            )
            if result.data:
                question = result.data[0]
                stem = question.get("stem") or ""
                topic = question.get("topic") or ""
                subtopic = question.get("subtopic") or ""
                chapter = question.get("chapter") or ""
                explanation = question.get("explanation") or ""

                if not preferred_book_id:
                    preferred_book_id = question.get("book_id")

                search_text = " ".join(
                    [message, stem, topic, subtopic, chapter]
                )
                question_context = f"Practice question:\n{stem}\n"
                if explanation:
                    question_context += (
                        "Existing explanation for reference:\n"
                        f"{explanation}\n"
                    )
        except Exception as exc:
            print("Unable to load question context:", str(exc))

    # Library retrieval is optional. A library error must not prevent the AI
    # tutor from answering from its medical knowledge.
    relevant_chunks = []
    try:
        chunks = load_medbot_chunks(
            supabase,
            book_id=preferred_book_id,
            max_rows=MEDBOT_MAX_CHUNKS,
        )
        if chunks:
            relevant_chunks = rank_medbot_chunks(
                chunks,
                search_text,
                limit=MEDBOT_TOP_CHUNKS,
            )
    except Exception as exc:
        print("Optional MedBot library retrieval skipped:", str(exc))
        relevant_chunks = []

    source_items = []
    context_sections = []

    if relevant_chunks:
        book_ids = [
            str(chunk.get("book_id"))
            for chunk in relevant_chunks
            if chunk.get("book_id")
        ]
        try:
            book_titles = load_book_titles(supabase, book_ids)
        except Exception:
            book_titles = {}

        seen_sources = set()
        total_chars = 0

        for index, chunk in enumerate(relevant_chunks, start=1):
            body = get_chunk_text(chunk)
            if not body:
                continue

            remaining = MEDBOT_CONTEXT_CHARS - total_chars
            if remaining <= 0:
                break

            body = body[:remaining]
            total_chars += len(body)

            book_id = str(chunk.get("book_id") or "")
            title = book_titles.get(book_id) or "MedQ textbook"
            chapter = get_chunk_chapter(chunk)

            header = f"REFERENCE {index}: {title}"
            if chapter:
                header += f" | {chapter}"
            context_sections.append(f"{header}\n{body}")

            # Keep source labels compact. Raw headings remain optional metadata
            # and are not required in the answer itself.
            key = (title, chapter)
            if key not in seen_sources:
                seen_sources.add(key)
                item = {"book_title": title}
                if chapter:
                    item["chapter"] = chapter
                source_items.append(item)

    system_prompt = (
        "You are MedBot, MedQ's full AI medical tutor for an MBBS student "
        "preparing for AMC CAT MCQ, FMGE and NEET-PG. You are NOT limited to "
        "the uploaded textbook library. Answer using strong general medical "
        "knowledge and clinical reasoning. When MedQ textbook excerpts are "
        "provided, use them as useful supporting context and reconcile them "
        "with current standard medical knowledge; never invent a quotation or "
        "claim a book says something it does not say. For AMC, emphasize "
        "clinical vignettes, safety, next-best-step, investigation and "
        "management reasoning. For FMGE/NEET-PG, include high-yield facts, "
        "clinical application, pathology, pharmacology, investigations and "
        "treatment when relevant. Explain difficult concepts in simple language "
        "first, then precise medical terminology. For MCQs, explain why the "
        "best answer wins and why important distractors lose. You may create "
        "mnemonics, tables, mini-quizzes, differential diagnoses, revision "
        "plans and exam-style questions when asked. Do not mention page numbers. "
        "Do not force a textbook citation into every answer. Keep answers concise "
        "unless the student asks for depth. This is educational information, not "
        "personal medical care."
    )

    messages = [{"role": "system", "content": system_prompt}]

    if request.conversation:
        for item in request.conversation[-8:]:
            role = (item.role or "").lower()
            content = (item.content or "").strip()
            if role in ["user", "assistant"] and content:
                messages.append({
                    "role": role,
                    "content": content[:3000],
                })

    user_prompt = f"Student question:\n{message}\n"
    if question_context:
        user_prompt += f"\n{question_context}\n"

    if context_sections:
        user_prompt += (
            "\nOptional MedQ library references. Use them when helpful, but do "
            "not restrict the answer to them:\n\n"
            + "\n\n---\n\n".join(context_sections)
        )
    else:
        user_prompt += (
            "\nNo relevant MedQ textbook excerpt was retrieved. Answer normally "
            "from your medical knowledge."
        )

    messages.append({"role": "user", "content": user_prompt})
    answer, used_model = call_gemini_medbot(messages)

    return {
        "ok": True,
        "answer": answer,
        "sources": source_items,
        "grounded": bool(source_items),
        "knowledge_mode": "ai_plus_library" if source_items else "ai",
        "model": used_model,
    }


# ---------------------------------------------------------
# Generate secure R2 upload URL
# ---------------------------------------------------------

@app.post("/api/books/upload-url")
def create_upload_url(
    request: UploadRequest
):

    if (
        request.content_type
        != "application/pdf"
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Only PDF files are allowed."
            )
        )

    filename = safe_filename(
        request.filename
    )

    if not filename.lower().endswith(
        ".pdf"
    ):
        raise HTTPException(
            status_code=400,
            detail="File must be a PDF."
        )

    file_key = (
        f"books/"
        f"{datetime.utcnow().strftime('%Y/%m')}/"
        f"{uuid.uuid4()}-{filename}"
    )

    r2 = get_r2_client()

    try:

        upload_url = (
            r2.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket":
                        R2_BUCKET_NAME,

                    "Key":
                        file_key,

                    "ContentType":
                        "application/pdf",
                },
                ExpiresIn=3600,
            )
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to create upload URL: "
                f"{str(exc)}"
            )
        )

    return {
        "upload_url": upload_url,
        "file_key": file_key,
        "expires_in": 3600,
    }


# ---------------------------------------------------------
# Register uploaded book
# ---------------------------------------------------------

@app.post("/api/books/register")
def register_book(
    request: RegisterBookRequest
):

    supabase = get_supabase()

    record = {
        "title":
            request.title,

        "subject":
            request.subject,

        "file_key":
            request.file_key,

        "file_size_bytes":
            request.file_size_bytes,

        "uploaded_by":
            request.uploaded_by,

        "status":
            "uploaded",
    }

    try:

        result = (
            supabase
            .table("books")
            .insert(record)
            .execute()
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to register book: "
                f"{str(exc)}"
            )
        )

    if not result.data:

        raise HTTPException(
            status_code=500,
            detail=(
                "Book registration "
                "returned no data."
            )
        )

    return {
        "ok": True,
        "book": result.data[0],
    }


# ---------------------------------------------------------
# List books
# ---------------------------------------------------------

@app.get("/api/books")
def list_books():

    supabase = get_supabase()

    try:

        result = (
            supabase
            .table("books")
            .select("*")
            .order(
                "created_at",
                desc=True
            )
            .execute()
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to load books: "
                f"{str(exc)}"
            )
        )

    return {
        "books": result.data or []
    }



# ---------------------------------------------------------
# Delete book (admin only)
# ---------------------------------------------------------

ADMIN_EMAILS = {
    item.strip().lower()
    for item in os.getenv(
        "ADMIN_EMAILS",
        "saiealnaik17@gmail.com"
    ).split(",")
    if item.strip()
}

def require_admin_user(authorization: Optional[str]):
    user = require_authenticated_user(authorization)
    email = (getattr(user, "email", None) or "").strip().lower()
    if not email or email not in ADMIN_EMAILS:
        raise HTTPException(
            status_code=403,
            detail="Only the MedQ administrator can delete books."
        )
    return user


@app.delete("/api/books/{book_id}")
def delete_book(
    book_id: str,
    authorization: Optional[str] = Header(default=None),
):
    """Permanently remove one shared book and its generated data."""
    require_admin_user(authorization)
    supabase = get_supabase()

    try:
        result = (
            supabase.table("books")
            .select("id,title,file_key")
            .eq("id", book_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unable to load book: {exc}")

    if not result.data:
        raise HTTPException(status_code=404, detail="Book not found.")

    book = result.data[0]
    file_key = book.get("file_key")

    # Remove dependent records first so foreign-key relationships do not block
    # deletion. Missing optional tables/columns are safely ignored.
    question_ids = []
    try:
        qres = (
            supabase.table("questions")
            .select("id")
            .eq("book_id", book_id)
            .execute()
        )
        question_ids = [str(row.get("id")) for row in (qres.data or []) if row.get("id")]
    except Exception:
        question_ids = []

    if question_ids:
        for table in ("attempts", "bookmarks"):
            for start in range(0, len(question_ids), 100):
                batch = question_ids[start:start + 100]
                try:
                    supabase.table(table).delete().in_("question_id", batch).execute()
                except Exception:
                    pass

    for table in ("questions", "book_chunks", "book_chapters", "book_processing_jobs"):
        try:
            supabase.table(table).delete().eq("book_id", book_id).execute()
        except Exception:
            pass

    try:
        supabase.table("books").delete().eq("id", book_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Book data could not be deleted: {exc}")

    # R2 deletion is attempted last. If the object was already deleted manually,
    # that is harmless and the database record is still cleaned up.
    r2_deleted = False
    if file_key and all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        try:
            get_r2_client().delete_object(Bucket=R2_BUCKET_NAME, Key=file_key)
            r2_deleted = True
        except Exception:
            r2_deleted = False

    return {
        "ok": True,
        "book_id": book_id,
        "title": book.get("title"),
        "r2_deleted": r2_deleted,
        "message": "Book and its generated data were deleted from MedQ."
    }

# ---------------------------------------------------------
# Start automatic processing
# ---------------------------------------------------------

@app.post(
    "/api/books/{book_id}/process"
)
def process_book(
    book_id: str
):

    supabase = get_supabase()

    # ---------------------------------------------
    # Find the book
    # ---------------------------------------------

    try:

        result = (
            supabase
            .table("books")
            .select("*")
            .eq(
                "id",
                book_id
            )
            .execute()
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to load book: "
                f"{str(exc)}"
            )
        )

    if not result.data:

        raise HTTPException(
            status_code=404,
            detail="Book not found."
        )

    book = result.data[0]

    file_key = book.get(
        "file_key"
    )

    subject = (
        book.get("subject")
        or "General"
    )

    if not file_key:

        raise HTTPException(
            status_code=400,
            detail=(
                "Book has no R2 file key."
            )
        )

    # ---------------------------------------------
    # Mark processing
    # ---------------------------------------------

    try:

        (
            supabase
            .table("books")
            .update({
                "status":
                    "processing"
            })
            .eq(
                "id",
                book_id
            )
            .execute()
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to update book "
                f"status: {str(exc)}"
            )
        )

    # ---------------------------------------------
    # Trigger GitHub Actions
    # ---------------------------------------------

    try:

        trigger_github_workflow(
            book_id=book_id,
            file_key=file_key,
            subject=subject,
            exam_track=book.get("exam_track") or "fmge_neetpg"
        )

    except HTTPException as exc:

        # Change status to failed
        # if GitHub cannot start.
        try:

            (
                supabase
                .table("books")
                .update({
                    "status":
                        "failed"
                })
                .eq(
                    "id",
                    book_id
                )
                .execute()
            )

        except Exception:
            pass

        raise exc

    return {
        "ok": True,
        "book_id": book_id,
        "status": "processing",
        "message": (
            "MedQ automatic processing "
            "has started."
        )
    }
