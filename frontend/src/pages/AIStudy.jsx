import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, BookOpen, Check, ChevronRight, Flame, Library, RotateCcw, Send, Sparkles, Target, X } from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || 'https://medq-api-6vm5.onrender.com'

const chips = [
  'DKA',
  'Atrial fibrillation',
  'Heart murmurs',
  'Nephrotic syndrome',
  'Cranial nerves',
  'Thyroid disorders',
  'Acute abdomen',
  'Preeclampsia'
]

const styles = `
.ai-study-page{min-height:100vh;background:radial-gradient(circle at 20% 0%,rgba(99,102,241,.12),transparent 32%),radial-gradient(circle at 90% 15%,rgba(16,185,129,.10),transparent 30%),#f7f8fc;color:#182033;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.ai-study-shell{max-width:1180px;margin:0 auto;padding:22px 22px 44px}
.ai-study-top{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:22px}
.ai-study-brand{display:flex;align-items:center;gap:12px}.ai-study-brand-mark{width:42px;height:42px;border-radius:14px;background:linear-gradient(135deg,#5b5cf0,#7c3aed);color:white;display:grid;place-items:center;box-shadow:0 10px 30px rgba(91,92,240,.25)}
.ai-study-brand h1{font-size:19px;margin:0;font-weight:800}.ai-study-brand p{margin:2px 0 0;color:#68738a;font-size:12px}
.ai-study-back{border:1px solid #e1e5ef;background:white;border-radius:12px;padding:10px 13px;display:flex;align-items:center;gap:7px;color:#465066;cursor:pointer;font-weight:700}
.ai-study-layout{display:grid;grid-template-columns:280px minmax(0,1fr);gap:18px;align-items:start}
.ai-study-panel{background:rgba(255,255,255,.92);border:1px solid #e5e8f0;border-radius:22px;box-shadow:0 14px 40px rgba(27,38,70,.06)}
.ai-study-controls{padding:18px;position:sticky;top:18px}.ai-study-label{font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#7a8498;margin-bottom:8px}
.ai-study-select,.ai-study-input{width:100%;box-sizing:border-box;border:1px solid #dfe3ed;border-radius:13px;background:#fff;padding:12px 13px;color:#20283a;font-size:14px;outline:none}.ai-study-input:focus,.ai-study-select:focus{border-color:#6c63ef;box-shadow:0 0 0 3px rgba(108,99,239,.10)}
.ai-study-group{margin-bottom:17px}.ai-study-mode-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.ai-study-mode{border:1px solid #e2e5ee;background:white;border-radius:11px;padding:9px 4px;font-weight:800;font-size:12px;cursor:pointer}.ai-study-mode.active{background:#eeedff;border-color:#8177f4;color:#4d46c7}
.ai-study-source-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}.ai-study-source{border:1px solid #e2e5ee;background:white;border-radius:11px;padding:10px;font-weight:750;font-size:12px;cursor:pointer;text-align:left}.ai-study-source.active{background:#ecfdf5;border-color:#6ee7b7;color:#087a50}
.ai-study-chips{display:flex;flex-wrap:wrap;gap:6px}.ai-study-chip{border:1px solid #e1e5ee;background:#fff;border-radius:999px;padding:7px 9px;font-size:11px;font-weight:700;cursor:pointer;color:#586276}.ai-study-chip:hover{border-color:#9a93f7;color:#5149c9}
.ai-study-start{width:100%;border:0;border-radius:14px;padding:13px 14px;background:linear-gradient(135deg,#5b5cf0,#7147df);color:#fff;font-weight:850;font-size:14px;cursor:pointer;display:flex;justify-content:center;align-items:center;gap:8px;box-shadow:0 10px 24px rgba(91,92,240,.22)}.ai-study-start:disabled{opacity:.6;cursor:wait}
.ai-study-main{min-width:0}.ai-study-hero{padding:28px 30px 22px;background:linear-gradient(135deg,#171d35,#272b55);color:#fff;border-radius:22px 22px 0 0}.ai-study-hero small{color:#b9c0dc;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.ai-study-hero h2{font-size:31px;line-height:1.08;margin:9px 0 9px;max-width:720px}.ai-study-hero p{margin:0;color:#cbd1e4;max-width:700px;line-height:1.55;font-size:14px}
.ai-study-chat{padding:24px 30px 30px}.ai-study-empty{padding:44px 22px;text-align:center;color:#6d778b}.ai-study-empty-icon{width:58px;height:58px;margin:0 auto 14px;border-radius:18px;background:#eeedff;color:#5b55d9;display:grid;place-items:center}.ai-study-empty h3{color:#273047;margin:0 0 7px;font-size:19px}.ai-study-empty p{margin:0 auto 18px;max-width:560px;line-height:1.55;font-size:13px}
.ai-study-loading{display:flex;align-items:center;gap:10px;padding:16px;border:1px solid #e5e8f0;border-radius:15px;background:#fbfbff;color:#626d82;font-size:13px}.ai-study-spinner{width:16px;height:16px;border:2px solid #dddafe;border-top-color:#635bdb;border-radius:50%;animation:ai-spin .7s linear infinite}@keyframes ai-spin{to{transform:rotate(360deg)}}
.ai-study-qmeta{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px}.ai-study-pills{display:flex;flex-wrap:wrap;gap:6px}.ai-study-pill{font-size:11px;font-weight:800;padding:6px 9px;border-radius:999px;background:#f1f3f8;color:#687287}.ai-study-pill.primary{background:#eeedff;color:#5148c7}.ai-study-q{font-size:22px;line-height:1.42;margin:0 0 19px;color:#1c2539}.ai-study-option{width:100%;display:flex;gap:13px;align-items:flex-start;text-align:left;border:1px solid #e0e4ed;background:#fff;border-radius:15px;padding:14px;margin:8px 0;cursor:pointer;color:#273047;transition:.15s}.ai-study-option:hover{border-color:#9b95f4;transform:translateY(-1px)}.ai-study-option.selected{border-color:#7168ec;background:#f5f4ff}.ai-study-option.correct{border-color:#55c993;background:#effcf6}.ai-study-option.wrong{border-color:#f08a8a;background:#fff3f3}.ai-study-letter{width:30px;height:30px;flex:0 0 30px;border-radius:10px;background:#f0f2f7;display:grid;place-items:center;font-weight:900;font-size:12px}.ai-study-option.correct .ai-study-letter{background:#c9f5df;color:#08784e}.ai-study-option.wrong .ai-study-letter{background:#ffd5d5;color:#b72f2f}.ai-study-option-text{line-height:1.5;font-size:14px;padding-top:4px}.ai-study-option-icon{margin-left:auto;flex:0 0 auto}
.ai-study-result{margin-top:18px;border-radius:17px;border:1px solid #e1e5ee;overflow:hidden}.ai-study-result-head{padding:14px 16px;display:flex;align-items:center;gap:9px;font-weight:900}.ai-study-result-head.good{background:#ecfdf5;color:#08784e}.ai-study-result-head.bad{background:#fff1f1;color:#b62e2e}.ai-study-result-body{padding:16px;background:#fff}.ai-study-result-body h4{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#788297;margin:0 0 6px}.ai-study-result-body p{margin:0 0 14px;line-height:1.62;font-size:14px;color:#3c465a}.ai-study-pearl{border-left:3px solid #6c63ef;background:#f6f5ff;padding:12px 13px;border-radius:0 11px 11px 0}.ai-study-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}.ai-study-next{border:0;border-radius:12px;background:#1e2740;color:#fff;padding:12px 16px;font-weight:850;cursor:pointer;display:flex;align-items:center;gap:7px}.ai-study-reset{border:1px solid #dfe3ed;background:#fff;color:#4e586d;border-radius:12px;padding:11px 14px;font-weight:800;cursor:pointer}.ai-study-error{margin:14px 0;padding:12px 14px;border-radius:12px;background:#fff0f0;color:#a92d2d;border:1px solid #ffd0d0;font-size:13px}
.ai-study-footer{padding:14px 30px 24px;color:#8992a4;font-size:11px;line-height:1.5}
@media(max-width:820px){.ai-study-layout{grid-template-columns:1fr}.ai-study-controls{position:static}.ai-study-hero h2{font-size:25px}.ai-study-chat{padding:20px}.ai-study-hero{padding:23px 20px}.ai-study-footer{padding:14px 20px 22px}}
`

export default function AIStudy({ session }) {
  const navigate = useNavigate()
  const [examMode, setExamMode] = useState('amc')
  const [difficulty, setDifficulty] = useState('mixed')
  const [sourceMode, setSourceMode] = useState('ai')
  const [useLibrary, setUseLibrary] = useState(true)
  const [prompt, setPrompt] = useState('')
  const [question, setQuestion] = useState(null)
  const [selected, setSelected] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [explaining, setExplaining] = useState(false)
  const [error, setError] = useState('')
  const [askedStems, setAskedStems] = useState([])
  const [score, setScore] = useState({ correct: 0, answered: 0 })

  const accessToken = session?.access_token

  const options = useMemo(() => {
    if (!question?.options) return []
    return Object.entries(question.options).filter(([, value]) => String(value || '').trim())
  }, [question])

  async function generateQuestion(nextPrompt = prompt) {
    const clean = String(nextPrompt || '').trim()
    if (!clean || loading) return
    if (!accessToken) {
      setError('Your login session has expired. Please sign in again.')
      return
    }
    setLoading(true)
    setError('')
    setSelected('')
    setSubmitted(false)
    try {
      const avoid = askedStems.slice(-5).map((item) => item.slice(0, 280)).join('\n- ')
      const finalPrompt = `${clean}${avoid ? `\n\nAvoid repeating these recent questions:\n- ${avoid}` : ''}`
      const response = await fetch(`${API_URL}/api/ai-study/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
        body: JSON.stringify({
          prompt: finalPrompt,
          exam_mode: examMode,
          difficulty,
          source_mode: sourceMode,
          use_library: useLibrary
        })
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data?.detail || 'MedQ could not create the question.')
      const item = data?.question
      if (!item?.stem || !item?.correct_option) throw new Error('The AI returned an incomplete question. Please try again.')
      setQuestion(item)
      setAskedStems((current) => [...current.slice(-7), item.stem])
    } catch (err) {
      setError(err?.message || 'Could not generate a question.')
    } finally {
      setLoading(false)
    }
  }

  async function submitAnswer() {
    if (!question || !selected || submitted || explaining) return
    setSubmitted(true)
    const isCorrect = selected.toUpperCase() === String(question.correct_option || '').toUpperCase()
    setScore((current) => ({ answered: current.answered + 1, correct: current.correct + (isCorrect ? 1 : 0) }))

    if (!question.explanation && accessToken) {
      setExplaining(true)
      try {
        const response = await fetch(`${API_URL}/api/tutor/explain`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${accessToken}` },
          body: JSON.stringify({
            stem: question.stem,
            options: question.options,
            selected_option: selected,
            correct_option: question.correct_option,
            explanation: question.explanation || ''
          })
        })
        const data = await response.json().catch(() => ({}))
        if (response.ok) setQuestion((current) => ({ ...current, explanation: data.explanation, why_other_options_are_wrong: data.why_wrong, exam_pearl: data.exam_pearl }))
      } catch {
        // The answer is already graded locally; do not block the student if AI explanation fails.
      } finally {
        setExplaining(false)
      }
    }
  }

  function startFromChip(chip) {
    setPrompt(chip)
    generateQuestion(chip)
  }

  function reset() {
    setQuestion(null)
    setSelected('')
    setSubmitted(false)
    setError('')
    setScore({ correct: 0, answered: 0 })
    setAskedStems([])
  }

  const answeredPercent = score.answered ? Math.round((score.correct / score.answered) * 100) : 0

  return (
    <div className="ai-study-page">
      <style>{styles}</style>
      <div className="ai-study-shell">
        <div className="ai-study-top">
          <div className="ai-study-brand">
            <div className="ai-study-brand-mark"><Sparkles size={21} /></div>
            <div><h1>MedQ AI Study</h1><p>Spontaneous MCQs · Tutor mode · AMC + FMGE</p></div>
          </div>
          <button className="ai-study-back" type="button" onClick={() => navigate('/dashboard')}><ArrowLeft size={16} /> Dashboard</button>
        </div>

        <div className="ai-study-layout">
          <aside className="ai-study-panel ai-study-controls">
            <div className="ai-study-group">
              <div className="ai-study-label">Exam</div>
              <div className="ai-study-mode-grid">
                {['amc', 'fmge', 'mixed'].map((mode) => <button key={mode} className={`ai-study-mode ${examMode === mode ? 'active' : ''}`} onClick={() => setExamMode(mode)} type="button">{mode.toUpperCase()}</button>)}
              </div>
            </div>

            <div className="ai-study-group">
              <div className="ai-study-label">Difficulty</div>
              <select className="ai-study-select" value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
                <option value="mixed">Adaptive / mixed</option><option value="easy">Easy</option><option value="medium">Medium</option><option value="hard">Hard</option>
              </select>
            </div>

            <div className="ai-study-group">
              <div className="ai-study-label">Question source</div>
              <div className="ai-study-source-grid">
                <button type="button" className={`ai-study-source ${sourceMode === 'ai' ? 'active' : ''}`} onClick={() => setSourceMode('ai')}><Sparkles size={14} /> Fresh Gemini</button>
                <button type="button" className={`ai-study-source ${sourceMode === 'bank' ? 'active' : ''}`} onClick={() => setSourceMode('bank')}><Target size={14} /> Question bank</button>
              </div>
            </div>

            <label className="ai-study-group" style={{display:'flex',gap:9,alignItems:'flex-start',cursor:'pointer'}}>
              <input type="checkbox" checked={useLibrary} onChange={(e) => setUseLibrary(e.target.checked)} style={{marginTop:3}} />
              <span><strong style={{fontSize:13}}>Use my MedQ books</strong><span style={{display:'block',fontSize:11,color:'#7a8498',lineHeight:1.4,marginTop:3}}>Ground the question in your shared textbook library when relevant.</span></span>
            </label>

            <div className="ai-study-group">
              <div className="ai-study-label">Try a topic</div>
              <div className="ai-study-chips">{chips.map((chip) => <button key={chip} type="button" className="ai-study-chip" onClick={() => startFromChip(chip)}>{chip}</button>)}</div>
            </div>

            <div style={{fontSize:11,color:'#7b8497',marginBottom:8}}>Your session: <strong style={{color:'#414b61'}}>{score.correct}/{score.answered}</strong> correct{score.answered ? ` · ${answeredPercent}%` : ''}</div>
            <button type="button" className="ai-study-reset" style={{width:'100%'}} onClick={reset}><RotateCcw size={14} /> Reset session</button>
          </aside>

          <main className="ai-study-panel ai-study-main">
            <div className="ai-study-hero">
              <small>AI-FIRST MEDICAL QUIZ</small>
              <h2>Tell MedQ what you want to revise. It will quiz you immediately.</h2>
              <p>No 29K-question download. No leaving MedQ for Gemini. One question at a time, instant grading, correction and explanation.</p>
            </div>

            <div className="ai-study-chat">
              {!question && !loading && (
                <div className="ai-study-empty">
                  <div className="ai-study-empty-icon"><Flame size={25} /></div>
                  <h3>What do you feel like answering right now?</h3>
                  <p>Try “DKA”, “hard cardiology”, “give me an AMC next-best-step question”, or simply choose a topic above.</p>
                </div>
              )}

              {loading && <div className="ai-study-loading"><span className="ai-study-spinner" /> Creating one high-quality {examMode.toUpperCase()} question…</div>}
              {error && <div className="ai-study-error">{error}</div>}

              {question && !loading && (
                <>
                  <div className="ai-study-qmeta">
                    <div className="ai-study-pills"><span className="ai-study-pill primary">{question.exam_type || examMode.toUpperCase()}</span><span className="ai-study-pill">{question.difficulty || difficulty}</span>{question.topic && <span className="ai-study-pill">{question.topic}</span>}</div>
                    <span style={{fontSize:11,color:'#8992a4'}}>Question {score.answered + (submitted ? 0 : 1)}</span>
                  </div>

                  <h3 className="ai-study-q">{question.stem}</h3>

                  {options.map(([letter, text]) => {
                    const isSelected = selected === letter
                    const isCorrect = submitted && letter === question.correct_option
                    const isWrong = submitted && isSelected && !isCorrect
                    return <button key={letter} type="button" className={`ai-study-option ${isSelected ? 'selected' : ''} ${isCorrect ? 'correct' : ''} ${isWrong ? 'wrong' : ''}`} onClick={() => !submitted && setSelected(letter)}>
                      <span className="ai-study-letter">{letter}</span><span className="ai-study-option-text">{text}</span><span className="ai-study-option-icon">{isCorrect ? <Check size={19} /> : isWrong ? <X size={19} /> : null}</span>
                    </button>
                  })}

                  {!submitted && <button className="ai-study-start" type="button" disabled={!selected || explaining} onClick={submitAnswer}><Check size={17} /> Submit answer</button>}

                  {submitted && (
                    <div className="ai-study-result">
                      <div className={`ai-study-result-head ${selected === question.correct_option ? 'good' : 'bad'}`}>
                        {selected === question.correct_option ? <Check size={19} /> : <X size={19} />} {selected === question.correct_option ? 'Correct' : `Incorrect · Correct answer: ${question.correct_option}`}
                      </div>
                      <div className="ai-study-result-body">
                        <h4>Explanation</h4>
                        {explaining ? <div className="ai-study-loading"><span className="ai-study-spinner" /> Generating the missing explanation…</div> : <p>{question.explanation || 'Explanation unavailable for this question.'}</p>}
                        {selected !== question.correct_option && question.why_other_options_are_wrong && <><h4>Correction</h4><p>{question.why_other_options_are_wrong}</p></>}
                        {question.exam_pearl && <div className="ai-study-pearl"><h4>Exam pearl</h4><p style={{margin:0}}>{question.exam_pearl}</p></div>}
                        {question.sources?.length > 0 && <div style={{marginTop:14,fontSize:11,color:'#758095'}}><BookOpen size={13} style={{verticalAlign:'-2px'}} /> Grounded in your MedQ library</div>}
                      </div>
                    </div>
                  )}

                  {submitted && <div className="ai-study-actions"><button className="ai-study-reset" type="button" onClick={() => generateQuestion(prompt || question.topic || 'another question on this topic')}>Another one</button><button className="ai-study-next" type="button" onClick={() => generateQuestion(prompt || question.topic || 'another question on this topic')}><Sparkles size={16} /> Next question <ChevronRight size={16} /></button></div>}
                </>
              )}
            </div>

            <div className="ai-study-footer">MedQ AI Study uses your existing Gemini backend and your shared MedQ library. It does not ask either student for a Gemini password or API key. A normal Gemini subscription is not automatically the same thing as Gemini API access, so MedQ keeps the secure backend model approach.</div>
          </main>
        </div>
      </div>
    </div>
  )
}
