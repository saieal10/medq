import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="MedQ API", version="0.1.0")

frontend_origins = os.getenv(
    "FRONTEND_ORIGINS",
    "http://localhost:5173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in frontend_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "name": "MedQ API",
        "status": "online",
        "phase": "landing-dashboard-database"
    }

@app.get("/api/health")
def health():
    return {"ok": True}

# Next phase:
# POST /api/books/upload-url   -> create direct Cloudflare R2 upload
# POST /api/books/register     -> store book metadata
# POST /api/books/process      -> local OCR worker registration
