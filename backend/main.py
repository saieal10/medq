import os
import re
import uuid
import json
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional

import boto3
from botocore.config import Config
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client


load_dotenv()

app = FastAPI(
    title="MedQ API",
    version="0.3.0"
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
        "version": "0.3.0",
        "features": [
            "r2-storage",
            "supabase-books",
            "direct-pdf-upload",
            "github-processing-worker"
        ]
    }


@app.get("/api/health")
def health():

    return {
        "ok": True,
        "service": "medq-api",
        "version": "0.3.0"
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
