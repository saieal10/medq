
import os, re, json, hashlib, asyncio, httpx
from datetime import datetime, timezone
from collections import defaultdict

from supabase import create_client

SUPABASE_URL=os.environ["SUPABASE_URL"]
SUPABASE_KEY=os.environ["SUPABASE_SECRET_KEY"]
GEMINI_KEY=os.environ["GEMINI_API_KEY"]
MODEL=os.getenv("GEMINI_MODEL","gemini-3.5-flash")

DAILY_TARGET=int(os.getenv("AMC_DAILY_TARGET","1000"))
REQUESTS_PER_RUN=int(os.getenv("AMC_REQUESTS_PER_RUN","20"))
Q_PER_REQUEST=int(os.getenv("AMC_QUESTIONS_PER_REQUEST","20"))
CHUNKS_PER_REQUEST=int(os.getenv("AMC_CHUNKS_PER_REQUEST","6"))
CONCURRENCY=int(os.getenv("AMC_CONCURRENCY","5"))

DOMAINS=[
"Adult Health — Medicine",
"Adult Health — Surgery",
"Women's Health — Obstetrics & Gynaecology",
"Child Health — Paediatrics",
"Mental Health — Psychiatry",
"Population Health & Ethics",
]

BAD=re.compile(r"(preface|foreword|acknowledg|copyright|isbn|contents|index|bibliograph|reference|advertis|about the author|dedication)",re.I)

def norm(s):
    s=(s or "").lower()
    s=re.sub(r"\s+"," ",s)
    s=re.sub(r"[^a-z0-9 ]","",s)
    return s.strip()

def sim(a,b):
    a,b=norm(a),norm(b)
    if not a or not b:return 0
    if a==b:return 1
    return __import__("difflib").SequenceMatcher(None,a,b).ratio()

def today():
    return datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).isoformat()

def client():
    return create_client(SUPABASE_URL,SUPABASE_KEY)

def count_today(sb):
    r=sb.table("questions").select("id",count="exact").eq("exam_type","AMC").gte("created_at",today()).execute()
    return r.count or 0

def get_books(sb):
    return sb.table("books").select("id,title,subject,exam_track").execute().data or []

def get_chunks(sb,book_id):
    out=[]; off=0
    while len(out)<1000:
        r=sb.table("book_chunks").select("id,book_id,chapter,content").eq("book_id",book_id).range(off,off+999).execute()
        b=r.data or []
        out += b
        if len(b)<1000:break
        off+=1000
    return [x for x in out if len(x.get("content") or "")>=500 and not BAD.search(x.get("chapter") or "")]

def existing_stems(sb):
    out=[]; off=0
    while len(out)<100000:
        r=sb.table("questions").select("question,stem").eq("exam_type","AMC").range(off,off+999).execute()
        b=r.data or []
        out += [(x.get("question") or x.get("stem") or "") for x in b]
        if len(b)<1000:break
        off+=1000
    return [x for x in out if x]

async def gemini(client,prompt):
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload={"contents":[{"parts":[{"text":prompt}]}],
             "generationConfig":{"temperature":0.42,"responseMimeType":"application/json","maxOutputTokens":20000}}
    r=await client.post(url,headers={"x-goog-api-key":GEMINI_KEY},json=payload,timeout=180)
    if r.status_code in (429,403):
        raise RuntimeError("QUOTA")
    r.raise_for_status()
    return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])

def validate(q):
    stem=(q.get("question") or q.get("stem") or "").strip()
    opts=q.get("options")
    ans=(q.get("answer") or q.get("correct_answer") or "").strip().upper()
    exp=(q.get("explanation") or "").strip()
    if len(stem)<70:return False
    if not isinstance(opts,list) or len(opts)!=5:return False
    opts=[str(x).strip() for x in opts]
    if any(len(x)<1 for x in opts):return False
    if len(set(norm(x) for x in opts))<5:return False
    if ans not in "ABCDE":return False
    if len(exp)<40:return False
    low=norm(stem+" "+" ".join(opts))
    if "all of the above" in low or "none of the above" in low:return False
    return True

def prompt(domain,chunks,avoid):
    sources="\n\n".join(
        f"[SOURCE {i+1} | chapter={c.get('chapter') or 'Clinical knowledge'}]\n{c.get('content','')[:7000]}"
        for i,c in enumerate(chunks)
    )
    avoidtxt="\n".join(f"- {x[:240]}" for x in avoid[-300:])
    return f"""You are the senior AMC CAT MCQ author and medical quality reviewer for MedQ.

Generate {Q_PER_REQUEST} ORIGINAL AMC-style single-best-answer MCQs for:
DOMAIN: {domain}

Use the supplied medical text ONLY as factual grounding. Do not copy, lightly paraphrase, or reproduce existing questions.
The questions must test application of knowledge, clinical reasoning, diagnosis, investigation, management, emergency decisions, adverse effects, screening/prevention or ethics as appropriate.

AMC style:
- realistic clinical vignette
- one best answer
- EXACTLY 5 options A-E
- plausible distractors
- no all-of-the-above/none-of-the-above
- answer must be medically defensible from accepted clinical practice
- avoid obscure trivia unless clinically important
- avoid duplicated scenarios
- Australian spelling where natural
- do not mention the source text or that AI generated it

INTEGRITY:
Every question must be independently written. Do not reuse any question in the exclusion list.
If a source does not support a safe fact, choose another supported fact rather than inventing details.
Return ONLY JSON:
{{"questions":[{{"question":"...","options":["...","...","...","...","..."],"answer":"A","explanation":"...","topic":"...","difficulty":"Easy|Medium|Hard"}}]}}

EXCLUSION LIST:
{avoidtxt}

SOURCE TEXT:
{sources}
"""

async def main():
    sb=client()
    done=count_today(sb)
    print("AMC created today:",done,"target:",DAILY_TARGET)
    if done>=DAILY_TARGET:
        print("Daily target reached.")
        return

    books=get_books(sb)
    stems=existing_stems(sb)
    tasks=[]
    for domain in DOMAINS:
        candidates=[]
        hints=re.sub(r"[^a-z ]"," ",domain.lower()).split()
        scored=[]
        for b in books:
            text=f"{b.get('title','')} {b.get('subject','')}".lower()
            score=sum(1 for h in hints if len(h)>3 and h in text)
            scored.append((score,b))
        scored.sort(key=lambda x:x[0],reverse=True)
        selected=[b for _,b in scored[:6]]
        if not selected:selected=books[:6]
        chunks=[]
        for b in selected:
            try: chunks.extend(get_chunks(sb,b["id"])[:80])
            except Exception as e: print("chunk error",b["id"],e)
        # spread sources
        if chunks:
            step=max(1,len(chunks)//CHUNKS_PER_REQUEST)
            picked=[chunks[min(i*step,len(chunks)-1)] for i in range(CHUNKS_PER_REQUEST)]
            for p in picked:
                tasks.append((domain,picked))
    # round-robin domains, capped by remaining target
    max_requests=min(REQUESTS_PER_RUN,max(1,(DAILY_TARGET-done+Q_PER_REQUEST-1)//Q_PER_REQUEST))
    tasks=tasks[:max_requests]

    sem=asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as hc:
        async def run_one(domain,chunks):
            async with sem:
                try:
                    data=await gemini(hc,prompt(domain,chunks,stems))
                    return domain,data
                except RuntimeError as e:
                    if str(e)=="QUOTA":
                        print("Gemini quota reached; stopping this run cleanly.")
                        return domain,{"__quota__":True}
                    print("generation error",e); return domain,{}
                except Exception as e:
                    print("generation error",e); return domain,{}
        results=await asyncio.gather(*(run_one(d,c) for d,c in tasks))

    rows=[]; seen=list(stems)
    for domain,data in results:
        if data.get("__quota__"): continue
        qs=data.get("questions",[]) if isinstance(data,dict) else []
        for q in qs:
            if not validate(q): continue
            stem=q.get("question") or q.get("stem")
            if any(sim(stem,x)>=0.88 for x in seen): continue
            opts=[str(x).strip() for x in q["options"]]
            ans=q["answer"].upper()
            rows.append({
                "question":stem,
                "options":opts,
                "answer":ans,
                "explanation":q["explanation"].strip(),
                "exam_type":"AMC",
                "subject":domain,
                "chapter":str(q.get("topic") or domain)[:200],
                "topic":str(q.get("topic") or "")[:200],
                "difficulty":str(q.get("difficulty") or "Medium")[:30],
                "created_at":datetime.now(timezone.utc).isoformat()
            })
            seen.append(stem)
            if done+len(rows)>=DAILY_TARGET: break
        if done+len(rows)>=DAILY_TARGET: break

    # Final integrity pass against duplicates generated in same run
    final=[]
    for r in rows:
        if any(sim(r["question"],x["question"])>=0.88 for x in final): continue
        final.append(r)
    print("Validated new AMC questions:",len(final))
    for i in range(0,len(final),100):
        sb.table("questions").insert(final[i:i+100]).execute()
    print("AMC total created today after insert:",done+len(final))

if __name__=="__main__":
    asyncio.run(main())
