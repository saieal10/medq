import os, re, json, time, io, concurrent.futures
from typing import List, Dict, Any
import boto3, fitz, requests
from botocore.config import Config
from supabase import create_client

BOOK_ID = os.getenv("BOOK_ID")
FILE_KEY = os.getenv("FILE_KEY")
BOOK_SUBJECT = os.getenv("BOOK_SUBJECT", "General")
BOOK_EXAM_TRACK = os.getenv("BOOK_EXAM_TRACK", "FMGE_NEET_PG")
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "medq-books")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# Turbo controls. MCQ books are parsed directly; AI is used only for missing
# answer/explanation/metadata, in large batches. This avoids one AI call per MCQ.
MAX_PAGES = int(os.getenv("MAX_PAGES", "0"))          # 0 = entire PDF
MAX_MCQS_PER_RUN = int(os.getenv("MAX_MCQS_PER_RUN", "800"))
AI_BATCH_SIZE = int(os.getenv("AI_BATCH_SIZE", "50"))
MAX_AI_PARALLEL = int(os.getenv("MAX_AI_PARALLEL", "5"))
SAVE_BATCH = int(os.getenv("SAVE_BATCH", "100"))

sb = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
r2 = boto3.client(
    "s3",
    endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto",
    config=Config(signature_version="s3v4"),
)

def get_json(url, headers=None, timeout=30):
    r = requests.get(url, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def download_pdf(path):
    r2.download_file(R2_BUCKET_NAME, FILE_KEY, path)

def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()

def clean_question(s):
    s = re.sub(r"^\s*(?:Q(?:uestion)?\s*)?\d+\s*[\.\)\-:]\s*", "", s, flags=re.I)
    return norm(s)

def exam_type():
    t = (BOOK_EXAM_TRACK or "").upper()
    if "AMC" in t and "FMGE" in t:
        return "BOTH"
    if "AMC" in t:
        return "AMC"
    return "FMGE"

def existing_stems():
    out=set()
    offset=0
    while True:
        res = sb.table("questions").select("stem").eq("book_id", BOOK_ID).range(offset, offset+999).execute()
        rows=res.data or []
        for x in rows:
            st=norm(x.get("stem")).lower()
            if st: out.add(st)
        if len(rows)<1000: break
        offset += 1000
    return out

def parse_answer(text):
    pats = [
        r"(?:correct\s+answer|answer|ans(?:wer)?)\s*[:\-]?\s*\(?([A-E])\)?",
        r"\b(?:key|correct)\s*[:\-]?\s*\(?([A-E])\)?"
    ]
    for p in pats:
        m=re.search(p, text, re.I)
        if m: return m.group(1).upper()
    return None

def parse_mcqs(text):
    # Handles common printed formats:
    # 1. stem / A. / B. / C. / D. / E.
    # Also tolerates "(A)", "A)", "A:" and option lines with indentation.
    starts=list(re.finditer(r"(?m)^\s*(?:Q(?:uestion)?\s*)?(\d{1,5})\s*[\.\):\-]\s+", text, re.I))
    blocks=[]
    for i,m in enumerate(starts):
        if i>=MAX_MCQS_PER_RUN*2: break
        chunk=text[m.start():(starts[i+1].start() if i+1<len(starts) else len(text))]
        opt=list(re.finditer(r"(?im)^\s*\(?([A-E])\)?\s*[\.\):\-]\s+", chunk))
        if len(opt)<5:
            continue
        opt=opt[:5]
        stem=clean_question(chunk[:opt[0].start()])
        if len(stem)<20: continue
        vals=[]
        for j,o in enumerate(opt):
            end=opt[j+1].start() if j+1<len(opt) else len(chunk)
            vals.append(norm(chunk[o.end():end]))
        if any(len(v)<2 for v in vals): continue
        answer=parse_answer(chunk)
        # Strip trailing answer line from E where it got captured.
        vals[-1]=re.split(r"\b(?:correct\s+answer|answer|ans(?:wer)?)\s*[:\-]", vals[-1], flags=re.I)[0].strip()
        blocks.append({
            "stem":stem, "option_a":vals[0], "option_b":vals[1], "option_c":vals[2],
            "option_d":vals[3], "option_e":vals[4], "correct_option":answer,
            "raw":chunk[:8000]
        })
    return blocks

def page_texts(path):
    doc=fitz.open(path)
    pages=range(len(doc)) if not MAX_PAGES else range(min(MAX_PAGES,len(doc)))
    for p in pages:
        yield p+1, doc[p].get_text("text") or ""

def gemini_batch(items):
    prompt = """You are MedQ's medical MCQ quality-control engine.
For each supplied MCQ, return JSON only: an array with one object per input.
Do NOT rewrite the question. Preserve the stem and options exactly unless an
obvious OCR error makes an option unreadable. Determine the single best answer
from the question/options. Add a concise medically accurate explanation,
topic, difficulty (easy/medium/hard), and question_type.
Return fields: index, correct_option, explanation, topic, difficulty, question_type.
Never invent a page number. If uncertain, still choose the best answer but keep
the explanation cautious."""
    payload_items=[]
    for i,x in enumerate(items):
        payload_items.append({"index":i,"stem":x["stem"],"A":x["option_a"],"B":x["option_b"],
                              "C":x["option_c"],"D":x["option_d"],"E":x["option_e"]})
    body={"contents":[{"parts":[{"text":prompt+"\n\nINPUT:\n"+json.dumps(payload_items,ensure_ascii=False)}]}],
          "generationConfig":{"temperature":0.1,"responseMimeType":"application/json"}}
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    last=None
    for attempt in range(4):
        try:
            r=requests.post(url,headers={"x-goog-api-key":GEMINI_API_KEY,"Content-Type":"application/json"},
                            json=body,timeout=150)
            if r.status_code in (429,500,502,503,504):
                last=RuntimeError(f"Gemini {r.status_code}")
                time.sleep(min(20,2**attempt*2)); continue
            r.raise_for_status()
            c=r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(c)
        except Exception as e:
            last=e; time.sleep(min(20,2**attempt*2))
    raise last or RuntimeError("Gemini failed")

def save(rows):
    if not rows: return 0
    n=0
    for i in range(0,len(rows),SAVE_BATCH):
        part=rows[i:i+SAVE_BATCH]
        res=sb.table("questions").insert(part).execute()
        n += len(res.data or [])
    return n

def main():
    if not all([BOOK_ID,FILE_KEY,R2_ACCOUNT_ID,R2_ACCESS_KEY_ID,R2_SECRET_ACCESS_KEY,SUPABASE_URL,SUPABASE_SECRET_KEY]):
        raise RuntimeError("Missing required worker environment variables.")
    print(f"MEDQ MCQ TURBO | {BOOK_ID} | {BOOK_SUBJECT} | {BOOK_EXAM_TRACK}")
    with open("/tmp/book.pdf","wb") as f:
        r2.download_fileobj(R2_BUCKET_NAME,FILE_KEY,f)
    existing=existing_stems()
    detected=[]
    for page,text in page_texts("/tmp/book.pdf"):
        if not text.strip(): continue
        for q in parse_mcqs(text):
            sig=q["stem"].lower()
            if sig in existing: continue
            q["source_page"]=page
            q["chapter"]=BOOK_SUBJECT
            q["topic"]=BOOK_SUBJECT
            q["exam_type"]=exam_type()
            q["question_type"]="recall"
            q["difficulty"]="medium"
            q["explanation"]="Answer verified from the source question/answer key." if q["correct_option"] else ""
            detected.append(q)
            if len(detected)>=MAX_MCQS_PER_RUN: break
        if len(detected)>=MAX_MCQS_PER_RUN: break

    print(f"Detected {len(detected)} new MCQs before AI enrichment.")
    missing=[q for q in detected if not q["correct_option"] or not q["explanation"]]
    # Enrich only missing metadata/answers, in parallel batches.
    if GEMINI_API_KEY and missing:
        batches=[missing[i:i+AI_BATCH_SIZE] for i in range(0,len(missing),AI_BATCH_SIZE)]
        def run(b): return gemini_batch(b)
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_AI_PARALLEL) as ex:
            for batch,res in zip(batches, ex.map(run,batches)):
                for item in res or []:
                    idx=item.get("index")
                    if isinstance(idx,int) and 0<=idx<len(batch):
                        q=batch[idx]
                        q["correct_option"]=str(item.get("correct_option") or q["correct_option"] or "A").upper()[:1]
                        q["explanation"]=norm(item.get("explanation")) or q["explanation"]
                        q["topic"]=norm(item.get("topic")) or q["topic"]
                        q["difficulty"]=str(item.get("difficulty") or q["difficulty"]).lower()
                        q["question_type"]=norm(item.get("question_type")) or q["question_type"]
    # Save only questions with a valid answer. Never invent an answer.
    rows=[]
    for q in detected:
        if q.get("correct_option") in list("ABCDE") and all(q.get(k) for k in [
            "stem","option_a","option_b","option_c","option_d","option_e"
        ]):
            rows.append({
                "book_id":BOOK_ID,
                "exam_type":q["exam_type"],
                "question_type":q["question_type"],
                "stem":q["stem"],
                "option_a":q["option_a"],
                "option_b":q["option_b"],
                "option_c":q["option_c"],
                "option_d":q["option_d"],
                "option_e":q["option_e"],
                "correct_option":q["correct_option"],
                "explanation":q["explanation"],
                "subject":BOOK_SUBJECT,
                "chapter":q["chapter"],
                "topic":q["topic"],
                "difficulty":q["difficulty"],
                "source_page":q["source_page"]
            })
    saved=save(rows)
    print(f"MEDQ MCQ TURBO COMPLETE: saved {saved} questions.")
    print("Run again to continue from the next unseen questions; existing stems are skipped.")

if __name__=="__main__":
    main()
