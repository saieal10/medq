
import os,re,json,asyncio,httpx,hashlib
from datetime import datetime,timezone
from difflib import SequenceMatcher
from supabase import create_client

SUPABASE_URL=os.environ["SUPABASE_URL"]
SUPABASE_KEY=os.environ["SUPABASE_SECRET_KEY"]
GEMINI_KEY=os.environ["GEMINI_API_KEY"]
MODEL=os.getenv("GEMINI_MODEL","gemini-3.5-flash")
TARGET=int(os.getenv("AMC_DAILY_TARGET","1000"))
REQUESTS=int(os.getenv("AMC_REQUESTS_PER_RUN","20"))
PER_REQUEST=int(os.getenv("AMC_QUESTIONS_PER_REQUEST","50"))
CONCURRENCY=int(os.getenv("AMC_CONCURRENCY","2"))

DOMAINS=[
"Adult Health — Medicine","Adult Health — Surgery",
"Women's Health — Obstetrics & Gynaecology","Child Health — Paediatrics",
"Mental Health — Psychiatry","Population Health & Ethics"]

BAD=re.compile(r"(preface|foreword|acknowledg|copyright|isbn|contents|index|bibliograph|references|advertis|about the author|dedication)",re.I)

def norm(s):
    s=re.sub(r"[^a-z0-9 ]+"," ",(s or "").lower())
    return re.sub(r"\s+"," ",s).strip()

def similar(a,b):
    return SequenceMatcher(None,norm(a),norm(b)).ratio()

def start_today():
    return datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).isoformat()

def sb():
    return create_client(SUPABASE_URL,SUPABASE_KEY)

def daily_count(db):
    r=db.table("questions").select("id",count="exact").eq("exam_type","AMC").gte("created_at",start_today()).execute()
    return int(r.count or 0)

def existing_stems(db):
    out=[]; off=0
    while True:
        r=db.table("questions").select("stem").eq("exam_type","AMC").range(off,off+999).execute()
        rows=r.data or []
        out += [x.get("stem","") for x in rows if x.get("stem")]
        if len(rows)<1000: break
        off+=1000
        if off>=100000: break
    return out

def books(db):
    return db.table("books").select("id,title,subject,exam_track").execute().data or []

def chunks(db,bid,limit=120):
    r=db.table("book_chunks").select("id,book_id,chapter,content").eq("book_id",bid).range(0,limit-1).execute()
    return [x for x in (r.data or []) if len(x.get("content",""))>=600 and not BAD.search(x.get("chapter") or "")]

def prompt(domain,source_chunks,avoid):
    source="\n\n".join(f"[SOURCE {i+1} | {c.get('chapter') or 'Clinical section'}]\n{c.get('content','')[:6500]}" for i,c in enumerate(source_chunks))
    exclusions="\n".join("- "+x[:220] for x in avoid[-250:])
    return f"""You are a senior medical examiner and quality reviewer writing AMC CAT-style MCQs.

Create {PER_REQUEST} ORIGINAL questions for the AMC domain: {domain}.

STRICT INTEGRITY:
1. Do not copy, paraphrase, or transform any existing question in the exclusion list.
2. Do not invent facts unsupported by standard medical knowledge or the supplied sources.
3. Each item must be a genuine single-best-answer clinical MCQ.
4. EXACTLY five plausible options A-E.
5. Exactly one best answer.
6. No all/none of the above.
7. Avoid trivial wording-only questions and duplicate clinical scenarios.
8. Use realistic clinical vignettes and test diagnosis, investigation, management, emergency decisions, therapeutics, adverse effects, prevention or ethics.
9. Prefer Australian spelling where appropriate.
10. Return only JSON.

Schema:
{{"questions":[{{"question":"clinical vignette + question","option_a":"...","option_b":"...","option_c":"...","option_d":"...","option_e":"...","correct_option":"A","explanation":"...","topic":"...","difficulty":"easy|medium|hard"}}]}}

Existing AMC stems to avoid:
{exclusions}

Medical source material:
{source}
"""

async def call(client,p):
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload={"contents":[{"parts":[{"text":p}]}],
             "generationConfig":{"temperature":0.35,"responseMimeType":"application/json","maxOutputTokens":30000}}
    last=""
    for attempt in range(1,6):
        try:
            r=await client.post(url,headers={"x-goog-api-key":GEMINI_KEY},json=payload,timeout=300)
            if r.status_code in (429,403): raise RuntimeError("QUOTA")
            if r.status_code in (500,502,503,504):
                last=f"HTTP {r.status_code}"
                if attempt<5:
                    await asyncio.sleep(min(30,2**attempt))
                    continue
                raise RuntimeError(f"GEMINI_TRANSIENT: {last}")
            r.raise_for_status()
            return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
        except httpx.HTTPError as exc:
            last=str(exc)
            if attempt<5:
                await asyncio.sleep(min(30,2**attempt))
                continue
            raise RuntimeError(f"GEMINI_NETWORK: {last}")
    raise RuntimeError(f"GEMINI_TRANSIENT: {last}")

def valid(q):
    stem=(q.get("question") or "").strip()
    opts=[(q.get(k) or "").strip() for k in ["option_a","option_b","option_c","option_d","option_e"]]
    ans=(q.get("correct_option") or "").strip().upper()
    exp=(q.get("explanation") or "").strip()
    if len(stem)<80 or any(len(x)<2 for x in opts) or ans not in "ABCDE" or len(exp)<50:return False
    if len(set(norm(x) for x in opts))<5:return False
    bad=norm(stem+" "+" ".join(opts))
    if "all of the above" in bad or "none of the above" in bad:return False
    return True

async def main():
    db=sb(); today=daily_count(db)
    print(f"AMC created today: {today} target: {TARGET}")
    if today>=TARGET:return
    old=existing_stems(db); allbooks=books(db)
    if not allbooks:
        print("No books available."); return

    # Build one source pool per AMC domain, retaining real book_id for each request.
    tasks=[]
    for domain in DOMAINS:
        hints=[x for x in norm(domain).split() if len(x)>3]
        scored=[]
        for b in allbooks:
            txt=norm(f"{b.get('title','')} {b.get('subject','')}")
            score=sum(h in txt for h in hints)
            scored.append((score,b))
        scored.sort(key=lambda x:x[0],reverse=True)
        candidates=[b for _,b in scored[:8]]
        for b in candidates:
            try:
                cs=chunks(db,b["id"])
            except Exception as e:
                print("chunk load failed",b["id"],e); continue
            if cs:
                # multiple requests can use different sections from the same real source book
                step=max(1,len(cs)//4)
                for i in range(min(4,len(cs))):
                    picked=cs[i*step:min(i*step+8,len(cs))]
                    if picked: tasks.append((domain,b["id"],picked))
    if not tasks:return

    remaining=TARGET-today
    max_calls=min(REQUESTS,(remaining+PER_REQUEST-1)//PER_REQUEST)
    # round-robin domains
    selected=[]
    for i in range(max_calls):
        selected.append(tasks[i%len(tasks)])

    sem=asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as hc:
        async def one(t):
            domain,bid,cs=t
            async with sem:
                try:return domain,bid,await call(hc,prompt(domain,cs,old))
                except RuntimeError as e:
                    if str(e)=="QUOTA": return domain,bid,{"quota":True}
                    print("generation error",e); return domain,bid,{}
                except Exception as e:
                    print("generation error",e); return domain,bid,{}
        results=await asyncio.gather(*(one(t) for t in selected))

    final=[]; seen=list(old)
    for domain,bid,data in results:
        if data.get("quota"): continue
        for q in data.get("questions",[]) if isinstance(data,dict) else []:
            if not valid(q): continue
            stem=q["question"].strip()
            if any(similar(stem,s)>=0.90 for s in seen): continue
            row={"book_id":bid,"exam_type":"AMC","question_type":"clinical",
                 "stem":stem,"option_a":q["option_a"].strip(),"option_b":q["option_b"].strip(),
                 "option_c":q["option_c"].strip(),"option_d":q["option_d"].strip(),
                 "option_e":q["option_e"].strip(),"correct_option":q["correct_option"].upper(),
                 "explanation":q["explanation"].strip(),"subject":domain,
                 "chapter":str(q.get("topic") or domain)[:200],
                 "topic":str(q.get("topic") or "")[:200],
                 "difficulty":str(q.get("difficulty") or "medium").lower()[:30],
                 "source_page":None,
                 "created_at":datetime.now(timezone.utc).isoformat()}
            final.append(row);seen.append(stem)
            if len(final)>=remaining:break
        if len(final)>=remaining:break

    print("Integrity-approved AMC questions:",len(final))
    for i in range(0,len(final),100):
        db.table("questions").insert(final[i:i+100]).execute()
    print("AMC created today after insert:",today+len(final))

if __name__=="__main__":
    asyncio.run(main())
