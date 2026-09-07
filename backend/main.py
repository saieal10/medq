import os
import re
import uuid
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
    version="0.2.0"
)


# ---------------------------------------------------------
# Environment
# ---------------------------------------------------------

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "medq-books")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

FRONTEND_ORIGINS = os.getenv(
    "FRONTEND_ORIGINS",
    "http://localhost:5173,https://medq-practice.netlify.app"
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
            f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        ),
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(
            signature_version="s3v4"
        ),
    )


def get_supabase():
    if not SUPABASE_URL or not SUPABASE_SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="Supabase backend configuration is incomplete."
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


# ---------------------------------------------------------
# Health
# ---------------------------------------------------------

@app.get("/")
def root():
    return {
        "name": "MedQ API",
        "status": "online",
        "version": "0.2.0",
        "features": [
            "r2-storage",
            "supabase-books",
            "direct-pdf-upload"
        ]
    }


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "service": "medq-api"
    }


# ---------------------------------------------------------
# Generate secure R2 upload URL
# ---------------------------------------------------------

@app.post("/api/books/upload-url")
def create_upload_url(request: UploadRequest):

    if request.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed."
        )

    filename = safe_filename(request.filename)

    if not filename.lower().endswith(".pdf"):
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
        upload_url = r2.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": R2_BUCKET_NAME,
                "Key": file_key,
                "ContentType": "application/pdf",
            },
            ExpiresIn=3600,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to create upload URL: {str(exc)}"
        )

    return {
        "upload_url": upload_url,
        "file_key": file_key,
        "expires_in": 3600,
    }


# ---------------------------------------------------------
# Register uploaded book in Supabase
# ---------------------------------------------------------

@app.post("/api/books/register")
def register_book(request: RegisterBookRequest):

    supabase = get_supabase()

    record = {
        "title": request.title,
        "subject": request.subject,
        "file_key": request.file_key,
        "file_size_bytes": request.file_size_bytes,
        "uploaded_by": request.uploaded_by,
        "status": "uploaded",
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
            detail=f"Unable to register book: {str(exc)}"
        )

    if not result.data:
        raise HTTPException(
            status_code=500,
            detail="Book registration returned no data."
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
            detail=f"Unable to load books: {str(exc)}"
        )

    return {
        "books": result.data or []
    }


# ---------------------------------------------------------
# Processing placeholder
# ---------------------------------------------------------

@app.post("/api/books/{book_id}/process")
def process_book(book_id: str):

    supabase = get_supabase()

    try:
        result = (
            supabase
            .table("books")
            .update({
                "status": "processing"
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
            detail=f"Unable to start processing: {str(exc)}"
        )

    if not result.data:
        raise HTTPException(
            status_code=404,
            detail="Book not found."
        )

    return {
        "ok": True,
        "book_id": book_id,
        "status": "processing",
        "message": (
            "Book registered for OCR processing. "
            "The OCR worker will be connected next."
        ),
    }
