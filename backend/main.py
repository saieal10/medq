import os
import re
import uuid
import json
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional, List, Dict, Any

import boto3
from botocore.config import Config
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client


load_dotenv()

app = FastAPI(
    title="MedQ API",
    version="0.6.0"
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
    book_id: str
    chapter: str
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
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY is not configured on the backend."
        )

    # Gemini generateContent accepts the full conversation. System messages
    # are supplied through systemInstruction; assistant becomes model.
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
        contents.append({
            "role": "model" if role == "assistant" else "user",
            "parts": [{"text": text}]
        })

    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": MEDBOT_MAX_TOKENS,
        },
    }

    if system_text:
        payload["systemInstruction"] = {
            "parts": [{"text": system_text}]
        }

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "x-goog-api-key": GEMINI_API_KEY,
            "Content-Type": "application/json",
            "User-Agent": "MedQ-Backend",
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=MEDBOT_AI_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        print("Gemini MedBot error:", detail)
        if exc.code == 429:
            raise HTTPException(
                status_code=429,
                detail="MedBot's Gemini allowance is temporarily rate-limited. Please try again shortly."
            )
        raise HTTPException(
            status_code=502,
            detail=f"Gemini returned an error ({exc.code})."
        )
    except Exception as exc:
        print("Gemini connection error:", str(exc))
        raise HTTPException(
            status_code=502,
            detail="MedBot could not contact Gemini."
        )

    try:
        data = json.loads(raw)
        parts = data["candidates"][0]["content"]["parts"]
        answer = "\n".join(
            part.get("text", "") for part in parts if part.get("text")
        ).strip()
        if not answer:
            raise ValueError("empty Gemini response")
    except Exception as exc:
        print("Gemini response parse error:", str(exc), raw[:1000])
        raise HTTPException(
            status_code=502,
            detail="MedBot received an invalid Gemini response."
        )

    return answer, GEMINI_MODEL

def trigger_github_workflow(
    book_id: str,
    file_key: str,
    subject: str
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
        "version": "0.7.0",
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
        "version": "0.7.0"
    }




# ---------------------------------------------------------
# MedBot textbook-grounded chat
# ---------------------------------------------------------

@app.post("/api/questions/generate")
def generate_questions_on_demand(
    request: GenerateQuestionsRequest,
    authorization: Optional[str] = Header(default=None),
):
    require_authenticated_user(authorization)

    if request.exam_mode not in {"amc", "fmge", "mixed"}:
        raise HTTPException(
            status_code=400,
            detail="exam_mode must be amc, fmge, or mixed."
        )

    if request.count not in {10, 20, 50}:
        raise HTTPException(
            status_code=400,
            detail="count must be 10, 20, or 50."
        )

    chapter = (request.chapter or "").strip()
    if not chapter or len(chapter) > 250:
        raise HTTPException(
            status_code=400,
            detail="Choose a valid chapter."
        )

    supabase = get_supabase()

    try:
        book_result = (
            supabase
            .table("books")
            .select("id,title,subject,status")
            .eq("id", request.book_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to load book: {str(exc)}"
        )

    if not book_result.data:
        raise HTTPException(status_code=404, detail="Book not found.")

    try:
        chunk_result = (
            supabase
            .table("book_chunks")
            .select("id")
            .eq("book_id", request.book_id)
            .eq("chapter", chapter)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to validate chapter: {str(exc)}"
        )

    if not chunk_result.data:
        raise HTTPException(
            status_code=404,
            detail="No processed textbook chunks were found for this chapter."
        )

    if not GITHUB_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="GitHub Actions token is not configured."
        )

    workflow_url = (
        f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/"
        f"{GITHUB_REPO_NAME}/actions/workflows/"
        f"generate-questions.yml/dispatches"
    )

    payload = {
        "ref": GITHUB_BRANCH,
        "inputs": {
            "book_id": request.book_id,
            "chapter": chapter,
            "exam_mode": request.exam_mode,
            "count": str(request.count),
        },
    }

    github_request = urllib.request.Request(
        workflow_url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "MedQ-API",
        },
    )

    try:
        with urllib.request.urlopen(github_request, timeout=20) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HTTPException(
            status_code=502,
            detail=f"GitHub generation dispatch failed ({exc.code}): {body[:300]}"
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Unable to start question worker: {str(exc)}"
        )

    if status not in {200, 201, 202, 204}:
        raise HTTPException(
            status_code=502,
            detail="GitHub did not accept the generation job."
        )

    return {
        "ok": True,
        "status": "queued",
        "book_id": request.book_id,
        "chapter": chapter,
        "exam_mode": request.exam_mode,
        "count": request.count,
    }


@app.post("/api/medbot/chat")
def medbot_chat(
    request: MedBotRequest,
    authorization: Optional[str] = Header(
        default=None
    )
):

    require_authenticated_user(
        authorization
    )

    message = (
        request.message
        or ""
    ).strip()

    if len(message) < 2:
        raise HTTPException(
            status_code=400,
            detail="Please enter a question."
        )

    if len(message) > 5000:
        raise HTTPException(
            status_code=400,
            detail="Question is too long."
        )

    supabase = get_supabase()

    search_text = message
    question_context = ""
    preferred_book_id = request.book_id

    # If MedBot was opened from a practice question,
    # use that question as extra retrieval context.
    if request.question_id:
        try:
            result = (
                supabase
                .table("questions")
                .select("*")
                .eq(
                    "id",
                    request.question_id
                )
                .limit(1)
                .execute()
            )

            if result.data:
                question = result.data[0]

                stem = (
                    question.get("stem")
                    or ""
                )

                topic = (
                    question.get("topic")
                    or ""
                )

                chapter = (
                    question.get("chapter")
                    or ""
                )

                explanation = (
                    question.get("explanation")
                    or ""
                )

                if not preferred_book_id:
                    preferred_book_id = (
                        question.get("book_id")
                    )

                search_text = " ".join([
                    message,
                    stem,
                    topic,
                    chapter
                ])

                question_context = (
                    "Practice question context:\n"
                    f"{stem}\n"
                )

                if explanation:
                    question_context += (
                        "Existing generated explanation: "
                        f"{explanation}\n"
                    )

        except Exception as exc:
            print(
                "Unable to load question context:",
                str(exc)
            )

    try:
        chunks = load_medbot_chunks(
            supabase,
            book_id=preferred_book_id,
            max_rows=MEDBOT_MAX_CHUNKS
        )
    except Exception as exc:
        print(
            "Unable to load book chunks:",
            str(exc)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "MedBot could not search the "
                "processed textbook library."
            )
        )

    if not chunks:
        raise HTTPException(
            status_code=404,
            detail=(
                "No processed textbook content is "
                "available yet. Wait for a book to "
                "finish processing."
            )
        )

    relevant_chunks = rank_medbot_chunks(
        chunks,
        search_text,
        limit=MEDBOT_TOP_CHUNKS
    )

    if not relevant_chunks:
        fallback_messages = [
            {
                "role": "system",
                "content": (
                    "You are MedBot, a concise medical study assistant for AMC and FMGE preparation. "
                    "No relevant uploaded textbook excerpt was found for this question, so answer from reliable general medical knowledge. "
                    "State briefly that this answer is from general medical knowledge, not the uploaded textbook library. "
                    "Explain clinical reasoning, key clues, diagnosis/concept, investigation or next step, management, and exam traps when relevant. "
                    "Do not give personal medical advice and do not mention page numbers."
                )
            }
        ]
        if request.conversation:
            for item in request.conversation[-6:]:
                role = (item.role or "").lower()
                content = (item.content or "").strip()
                if role in ["user", "assistant"] and content:
                    fallback_messages.append({"role": role, "content": content[:2500]})
        fallback_messages.append({"role": "user", "content": message})
        answer, used_model = call_gemini_medbot(fallback_messages)
        return {
            "ok": True,
            "answer": answer,
            "sources": [],
            "grounded": False,
            "model": used_model,
        }

    book_ids = [
        str(chunk.get("book_id"))
        for chunk in relevant_chunks
        if chunk.get("book_id")
    ]

    book_titles = load_book_titles(
        supabase,
        book_ids
    )

    context_sections = []
    source_items = []
    seen_sources = set()

    total_chars = 0
    max_context_chars = MEDBOT_CONTEXT_CHARS

    for index, chunk in enumerate(
        relevant_chunks,
        start=1
    ):

        body = get_chunk_text(
            chunk
        )

        if not body:
            continue

        book_id = str(
            chunk.get("book_id")
            or ""
        )

        title = (
            book_titles.get(book_id)
            or "Uploaded textbook"
        )

        chapter = get_chunk_chapter(
            chunk
        )

        remaining = (
            max_context_chars - total_chars
        )

        if remaining <= 0:
            break

        body = body[:remaining]
        total_chars += len(body)

        header = f"SOURCE {index}: {title}"

        if chapter:
            header += f" | {chapter}"

        context_sections.append(
            f"{header}\n{body}"
        )

        source_key = (
            title,
            chapter
        )

        if source_key not in seen_sources:
            seen_sources.add(
                source_key
            )

            item = {
                "book_title": title
            }

            if chapter:
                item["chapter"] = chapter

            source_items.append(
                item
            )

    context_text = "\n\n---\n\n".join(
        context_sections
    )

    system_prompt = (
        "You are MedBot, MedQ's medical reasoning assistant for an MBBS student preparing for AMC and FMGE. "
        "Treat the supplied MedQ textbook excerpts as the PRIMARY source whenever they are relevant. "
        "Do not misquote or invent textbook content. If the excerpts are incomplete, you MAY supplement with reliable general medical knowledge, "
        "but explicitly label the supplemental part as 'General medical knowledge'. For clinical questions, reason in this order when useful: "
        "key clues -> likely diagnosis/concept -> why -> investigation/next best step -> management -> exam trap. For MCQs, explain why the best "
        "answer wins and why important distractors lose. Distinguish AMC-style clinical/next-best-step reasoning from FMGE high-yield recall when useful. "
        "Use clear MBBS language followed by precise terminology. Never show page numbers. Keep answers concise unless depth is requested. "
        "This is educational content, not personal medical advice."
    )

    user_prompt = (
        f"Student question:\n{message}\n\n"
    )

    if question_context:
        user_prompt += (
            f"{question_context}\n"
        )

    user_prompt += (
        "Relevant MedQ textbook excerpts:\n\n"
        f"{context_text}"
    )

    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    # Keep only a small amount of recent chat history.
    if request.conversation:
        for item in request.conversation[-4:]:
            role = (
                item.role
                or ""
            ).lower()

            content = (
                item.content
                or ""
            ).strip()

            if (
                role in ["user", "assistant"]
                and content
            ):
                messages.append({
                    "role": role,
                    "content": content[:2000]
                })

    messages.append({
        "role": "user",
        "content": user_prompt
    })

    answer, used_model = call_gemini_medbot(
        messages
    )

    return {
        "ok": True,
        "answer": answer,
        "sources": source_items,
        "grounded": True,
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
            subject=subject
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
