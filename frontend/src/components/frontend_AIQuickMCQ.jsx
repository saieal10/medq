
import React, {useState} from "react";

export default function AIQuickMCQ(){
  const [count,setCount]=useState(10),[subject,setSubject]=useState("Adult Health — Medicine");
  const [difficulty,setDifficulty]=useState("Medium"),[loading,setLoading]=useState(false);
  const [questions,setQuestions]=useState([]),[idx,setIdx]=useState(0),[picked,setPicked]=useState(null);
  const [error,setError]=useState("");

  const domains=[
    "Adult Health — Medicine","Adult Health — Surgery",
    "Women's Health — Obstetrics & Gynaecology","Child Health — Paediatrics",
    "Mental Health — Psychiatry","Population Health & Ethics"
  ];

  async function generate(){
    setLoading(true);setError("");setQuestions([]);setIdx(0);setPicked(null);
    try{
      const api=import.meta.env.VITE_API_URL || "";
      const r=await fetch(`${api}/api/medbot/quick-mcq`,{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({count:Number(count),subject,difficulty,exam_type:"AMC"})
      });
      if(!r.ok) throw new Error("Quick MCQ service is unavailable.");
      const d=await r.json();
      if(!Array.isArray(d.questions)||!d.questions.length) throw new Error("No questions returned.");
      setQuestions(d.questions);
    }catch(e){setError(e.message||"Failed to generate questions.");}
    finally{setLoading(false)}
  }
  const q=questions[idx];
  return <div className="space-y-5">
    <div className="rounded-2xl border p-5">
      <div className="text-lg font-semibold">AI Quick MCQ</div>
      <div className="text-sm opacity-70 mt-1">Generate a short AMC-style practice set instantly. These questions are practice-only and are not added to the permanent question bank.</div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4">
        <select value={subject} onChange={e=>setSubject(e.target.value)} className="border rounded-xl p-3">{domains.map(x=><option key={x}>{x}</option>)}</select>
        <select value={difficulty} onChange={e=>setDifficulty(e.target.value)} className="border rounded-xl p-3"><option>Easy</option><option>Medium</option><option>Hard</option></select>
        <select value={count} onChange={e=>setCount(e.target.value)} className="border rounded-xl p-3"><option value="5">5</option><option value="10">10</option><option value="20">20</option></select>
      </div>
      <button type="button" onClick={generate} disabled={loading} className="mt-4 px-5 py-3 rounded-xl border font-semibold">{loading?"Generating…":"Generate AI MCQs"}</button>
      {error&&<div className="mt-3 text-sm">{error}</div>}
    </div>
    {q&&<div className="rounded-2xl border p-5">
      <div className="text-sm opacity-60">Question {idx+1} / {questions.length}</div>
      <div className="font-semibold text-lg mt-2">{q.question}</div>
      <div className="space-y-2 mt-4">{(q.options||[]).map((o,i)=>{
        const letter="ABCDE"[i], chosen=picked===letter, correct=q.answer===letter;
        return <button type="button" key={letter} onClick={()=>setPicked(letter)} className="w-full text-left border rounded-xl p-3">
          <b>{letter}.</b> {o} {picked && correct?" ✓":""} {picked===letter&&!correct?" ✕":""}
        </button>
      })}</div>
      {picked&&<div className="mt-4 rounded-xl border p-4"><b>Explanation:</b> {q.explanation}</div>}
      <div className="flex gap-2 mt-4"><button type="button" className="border rounded-xl px-4 py-2" onClick={()=>{setIdx(Math.max(0,idx-1));setPicked(null)}}>Previous</button><button type="button" className="border rounded-xl px-4 py-2" onClick={()=>{setIdx(Math.min(questions.length-1,idx+1));setPicked(null)}}>Next</button></div>
    </div>}
  </div>
}
