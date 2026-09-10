import os
import io
import re
import json
import time
import tempfile
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import boto3
import pymupdf
import pytesseract
import requests
from PIL import Image
from botocore.config import Config
from supabase import create_client

BOOK_ID = os.getenv("BOOK_ID")
FILE_KEY = os.getenv("FILE_KEY")
BOOK_SUBJECT = os.getenv("BOOK_SUBJECT", "General")
BOOK_EXAM_TRACK = os.getenv("BOOK_EXAM_TRACK", "fmge_neetpg")

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "medq-books")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "18000"))
QUESTIONS_PER_CHUNK = int(os.getenv("QUESTIONS_PER_CHUNK", "8"))
AI_PASSES_PER_CHUNK = int(os.getenv("AI_PASSES_PER_CHUNK", "2"))
CHUNKS_PER_RUN = int(os.getenv("CHUNKS_PER_RUN", "20"))
AI_RETRIES = int(os.getenv("AI_RETRIES", "4"))
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "150"))
OCR_DPI = int(os.getenv("OCR_DPI", "150"))
MIN_USABLE_PAGE_CHARS = int(os.getenv("MIN_USABLE_PAGE_CHARS", "80"))
NATIVE_TEXT_MIN_CHARS = int(os.getenv("NATIVE_TEXT_MIN_CHARS", "140"))

required = {
    "BOOK_ID": BOOK_ID,
    "FILE_KEY": FILE_KEY,
    "R2_ACCOUNT_ID": R2_ACCOUNT_ID,
    "R2_ACCESS_KEY_ID": R2_ACCESS_KEY_ID,
    "R2_SECRET_ACCESS_KEY": R2_SECRET_ACCESS_KEY,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_SECRET_KEY": SUPABASE_SECRET_KEY,
    "GEMINI_API_KEY": GEMINI_API_KEY,
}
missing = [k for k, v in required.items() if not v]
if missing:
    raise RuntimeError("Missing required environment variables: " + ", ".join(missing))

supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
r2 = boto3.client(
    "s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(signature_version="s3v4"),
)

def now():
    return datetime.now(timezone.utc).isoformat()

def clean_text(text):
    text = (text or "").replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def nonclinical(text):
    s = (text or "").lower()
    bad = [
        "preface", "foreword", "about the author", "about the editor",
        "contributors", "publisher", "copyright", "isbn", "acknowledg",
        "table of contents", "contents", "bibliography", "references",
        "index", "advertisement", "dedication", "permissions",
        "disclaimer", "video library", "editorial board"
    ]
    return any(x in s for x in bad)

def chapter_label(text):
    lines = [re.sub(r"\s+", " ", x).strip(" -:") for x in (text or "").splitlines()]
    for line in lines[:40]:
        low=line.lower()
        if not line or len(line)>120: continue
        if nonclinical(line): continue
        if re.match(r"^(chapter|part|section)\s+[ivxlcdm\d]+", low):
            return line
    return None

def extract_pages(pdf_path):
    doc = pymupdf.open(pdf_path)
    pages=[]
    for i,page in enumerate(doc):
        raw=clean_text(page.get_text("text"))
        method="text"
        if len(raw) < NATIVE_TEXT_MIN_CHARS:
            pix=page.get_pixmap(matrix=pymupdf.Matrix(OCR_DPI/72, OCR_DPI/72), alpha=False)
            image=Image.open(io.BytesIO(pix.tobytes("png")))
            raw=clean_text(pytesseract.image_to_string(image, lang="eng"))
            method="ocr"
        if len(raw) < MIN_USABLE_PAGE_CHARS or nonclinical(raw[:1200]):
            continue
        pages.append({"page": i+1, "text": raw, "method": method})
        if (i+1) % 50 == 0:
            print(f"[EXTRACT] page {i+1}/{len(doc)}")
    return pages

def make_chunks(pages):
    chunks=[]
    current=""
    page_nums=[]
    chapter=None
    for p in pages:
        possible=chapter_label(p["text"])
        if possible:
            chapter=possible
        addition=f"\n[PAGE {p['page']}]\n{p['text']}"
        if len(current)+len(addition)>CHUNK_SIZE and current:
            chunks.append({"content":current.strip(),"pages":page_nums,"chapter":chapter})
            current=""
            page_nums=[]
        current += addition
        page_nums.append(p["page"])
    if current:
        chunks.append({"content":current.strip(),"pages":page_nums,"chapter":chapter})
    return chunks

def save_chunks(chunks):
    rows=[]
    for idx,c in enumerate(chunks):
        pages=c["pages"]
        rows.append({
            "book_id":BOOK_ID,
            "chunk_index":idx,
            "chapter":(c.get("chapter") or "Clinical medicine")[:250],
            "section":None,
            "topic":None,
            "page_start":min(pages),
            "page_end":max(pages),
            "content":c["content"],
            "word_count":len(c["content"].split()),
            "extraction_method":"ocr" if "[PAGE" in c["content"] and False else "mixed",
            "processing_status":"ready"
        })
    for i in range(0,len(rows),25):
        supabase.table("book_chunks").upsert(
            rows[i:i+25], on_conflict="book_id,chunk_index"
        ).execute()
    return supabase.table("book_chunks").select(
        "id,chunk_index,chapter,page_start,page_end,content"
    ).eq("book_id",BOOK_ID).order("chunk_index").execute().data or []

def parse_json(text):
    text=(text or "").strip()
    if "```" in text:
        text=re.sub(r"^```(?:json)?\s*|\s*```$","",text,flags=re.I|re.S).strip()
    a=text.find("["); b=text.rfind("]")
    if a<0 or b<0: raise RuntimeError("Gemini response did not contain a JSON array.")
    data=json.loads(text[a:b+1])
    if not isinstance(data,list): raise RuntimeError("Gemini response was not a list.")
    return data

def gemini(chunk, pass_no):
    page_start, page_end=min(chunk["pages"]),max(chunk["pages"])
    style = "AMC CAT clinical reasoning" if BOOK_EXAM_TRACK=="amc" else "FMGE/NEET-PG high-yield clinical and factual"
    system=f"""
You are the background question-bank engine for MedQ.
Create original single-best-answer medical MCQs from the supplied textbook material.
Exam target: {style}.
This is a permanent question bank, not an on-demand chat.

Generate {QUESTIONS_PER_CHUNK} questions for this pass.
Use different concepts, clinical presentations, investigations, management decisions,
mechanisms, complications, pharmacology, pathology, or important associations when
supported by the source. Do not make all questions test the same fact.
If this chunk already has questions, deliberately choose different concepts from
those likely to have been tested before; vary diagnosis, next-best step, investigation,
management, complications, mechanisms, drugs, pathology, and clinical associations.
For AMC: favour realistic clinical vignettes, prioritisation, next-best-step,
diagnosis, investigation and management.
For FMGE/NEET-PG: mix high-yield facts with clinical application, pathology,
pharmacology, microbiology, investigations and treatment.
Use only information supported by the source passage.
Exactly five options A-E, one best answer, plausible distractors, clear explanation.
Do not copy sentences from the textbook.
Return ONLY a JSON array.

Fields:
exam_type, question_type, stem, option_a, option_b, option_c, option_d, option_e,
correct_option, explanation, topic, difficulty, source_page, source_page_end
"""
    prompt=f"""
SUBJECT: {BOOK_SUBJECT}
CHAPTER: {chunk.get("chapter") or "Clinical medicine"}
SOURCE PAGES: {page_start}-{page_end}
PASS: {pass_no}
EXISTING QUESTIONS FROM THIS CHUNK: {chunk.get("existing_question_count", 0)}

TEXTBOOK:
{chunk["content"]}
"""
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload={
        "contents":[{"role":"user","parts":[{"text":system+"\n\n"+prompt}]}],
        "generationConfig":{"temperature":0.45,"responseMimeType":"application/json"}
    }
    last=None
    for attempt in range(1,AI_RETRIES+1):
        try:
            r=requests.post(url,headers={"x-goog-api-key":GEMINI_API_KEY,"Content-Type":"application/json"},
                            json=payload,timeout=AI_TIMEOUT)
            if r.status_code in (429,500,502,503,504):
                raise RuntimeError(f"Gemini temporary error {r.status_code}: {r.text[:500]}")
            r.raise_for_status()
            data=r.json()
            text="\n".join(p.get("text","") for p in data["candidates"][0]["content"]["parts"])
            return parse_json(text)
        except Exception as e:
            last=e
            print(f"[AI] attempt {attempt}/{AI_RETRIES} failed: {e}")
            if attempt<AI_RETRIES:
                time.sleep(min(2**attempt,12))
    raise RuntimeError(f"Gemini failed after retries: {last}")

def prepare(q, chunk):
    try:
        stem=str(q.get("stem","")).strip()
        opts=[str(q.get(f"option_{x}","")).strip() for x in "abcde"]
        correct=str(q.get("correct_option","")).strip().upper()
        explanation=str(q.get("explanation","")).strip()
        topic=str(q.get("topic","")).strip()[:250]
        difficulty=str(q.get("difficulty","medium")).strip().lower()
        exam=str(q.get("exam_type","FMGE")).strip().upper()
        if exam not in ("AMC","FMGE","BOTH"): exam="FMGE" if BOOK_EXAM_TRACK!="amc" else "AMC"
        if difficulty not in ("easy","medium","hard"): difficulty="medium"
        if len(stem)<30 or not topic or len(explanation)<30 or correct not in "ABCDE" or any(not x for x in opts):
            return None
        if len(set(x.lower() for x in opts)) != 5: return None
        pages=chunk["pages"]
        sp=q.get("source_page",min(pages)); ep=q.get("source_page_end",sp)
        try: sp=int(sp)
        except: sp=min(pages)
        try: ep=int(ep)
        except: ep=sp
        if not min(pages)<=sp<=max(pages): sp=min(pages)
        if not sp<=ep<=max(pages): ep=sp
        return {
            "book_id":BOOK_ID,
            "source_chunk_id":chunk["id"],
            "subject":BOOK_SUBJECT,
            "chapter":str(chunk.get("chapter") or "Clinical medicine")[:250],
            "topic":topic,
            "exam_type":exam,
            "question_type":str(q.get("question_type","clinical_application"))[:100],
            "difficulty":difficulty,
            "stem":stem,
            "option_a":opts[0],"option_b":opts[1],"option_c":opts[2],"option_d":opts[3],"option_e":opts[4],
            "correct_option":correct,
            "explanation":explanation,
            "source_page":sp,
            "source_page_end":ep,
            "review_status":"generated",
            "quality_score":None,
            "reviewer_notes":None
        }
    except Exception:
        return None

def question_counts_by_chunk():
    counts = {}
    start = 0
    while True:
        res = supabase.table("questions").select("source_chunk_id").eq("book_id", BOOK_ID).range(start, start + 999).execute().data or []
        for r in res:
            cid = r.get("source_chunk_id")
            if cid:
                counts[cid] = counts.get(cid, 0) + 1
        if len(res) < 1000:
            break
        start += 1000
    return counts

def save_questions(items):
    valid=[x for x in items if x]
    if not valid:return 0
    for i in range(0,len(valid),25):
        supabase.table("questions").insert(valid[i:i+25]).execute()
    return len(valid)

def main():
    print("========================================")
    print("MEDQ BACKGROUND QUESTION BANK WORKER")
    print("========================================")
    print("Book:",BOOK_ID)
    print("Subject:",BOOK_SUBJECT)
    print("Exam track:",BOOK_EXAM_TRACK)
    try:
        with tempfile.TemporaryDirectory() as td:
            pdf=os.path.join(td,"book.pdf")
            print("[R2] Downloading book...")
            r2.download_file(R2_BUCKET_NAME,FILE_KEY,pdf)
            print(f"[R2] {os.path.getsize(pdf)/1024/1024:.1f} MB")
            pages=extract_pages(pdf)
            chunks=make_chunks(pages)
            saved=save_chunks(chunks)
            print(f"[BANK] {len(saved)} knowledge chunks available")
            counts=question_counts_by_chunk()
            # Continuous background growth: do NOT skip a chunk merely because it
            # already has questions. Pick the least-covered chunks so every book
            # keeps producing more questions on future scheduled runs.
            ranked=sorted(saved, key=lambda c: (counts.get(str(c["id"]), 0), c["chunk_index"]))
            selected=ranked[:max(1, min(CHUNKS_PER_RUN, len(ranked)))]
            print(f"[BANK] Existing question coverage: {sum(counts.values())} questions across {len(counts)} chunks.")
            print(f"[BANK] This run will expand {len(selected)} chunks (lowest coverage first).")
            total=0
            for pos,chunk in enumerate(selected,1):
                cid=str(chunk["id"])
                existing_count=counts.get(cid,0)
                print(f"[BANK] expansion {pos}/{len(selected)} | chunk {chunk['chunk_index']+1}/{len(saved)} | existing {existing_count} questions | pages {chunk['page_start']}-{chunk['page_end']}")
                batch=[]
                for p in range(1,AI_PASSES_PER_CHUNK+1):
                    try:
                        generated=gemini({"content":chunk["content"],"pages":list(range(chunk["page_start"],chunk["page_end"]+1)),"chapter":chunk.get("chapter"),"id":chunk["id"],"existing_question_count":existing_count,"run_pass":p},p)
                        batch.extend([prepare(q,{"id":chunk["id"],"chapter":chunk.get("chapter"),"pages":list(range(chunk["page_start"],chunk["page_end"]+1))}) for q in generated])
                    except Exception as e:
                        print("[BANK] pass failed:",e)
                saved_count=save_questions(batch)
                total+=saved_count
                print(f"[BANK] +{saved_count} questions (total this run {total})")
            print(f"SUCCESS: background bank processing complete. Added {total} questions.")
    except Exception as e:
        print("PROCESSING FAILED:",e)
        raise

if __name__=="__main__":
    main()
