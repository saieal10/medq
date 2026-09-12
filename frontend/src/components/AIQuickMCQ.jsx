import React, { useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'https://medq-api-6vm5.onrender.com'

const DOMAINS = [
  'Adult Health — Medicine',
  'Adult Health — Surgery',
  "Women's Health — Obstetrics & Gynaecology",
  'Child Health — Paediatrics',
  'Mental Health — Psychiatry',
  'Population Health & Ethics'
]

export default function AIQuickMCQ() {
  const [count, setCount] = useState(10)
  const [subject, setSubject] = useState(DOMAINS[0])
  const [difficulty, setDifficulty] = useState('Medium')
  const [questions, setQuestions] = useState([])
  const [index, setIndex] = useState(0)
  const [picked, setPicked] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function generate() {
    setLoading(true)
    setError('')
    setQuestions([])
    setIndex(0)
    setPicked(null)
    try {
      const stored = await import('../lib/supabase')
      const { data: auth } = await stored.supabase.auth.getSession()
      const token = auth?.session?.access_token
      const response = await fetch(`${API_URL}/api/medbot/quick-mcq`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {})
        },
        body: JSON.stringify({ count: Number(count), subject, difficulty, exam_type: 'AMC' })
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data?.detail || 'Could not generate AI Quick MCQs.')
      setQuestions(data.questions || [])
    } catch (e) {
      setError(e?.message || 'Could not generate AI Quick MCQs.')
    } finally {
      setLoading(false)
    }
  }

  const q = questions[index]

  return (
    <section className="panel">
      <div className="panel-kicker">AMC AI PRACTICE</div>
      <h2>AI Quick MCQ</h2>
      <p>Generate a short AMC-style set instantly. These questions are temporary and are never added to the permanent question bank.</p>

      <div className="practice-filter-grid mt-4">
        <div className="practice-field">
          <label>AMC domain</label>
          <select value={subject} onChange={e => setSubject(e.target.value)}>
            {DOMAINS.map(x => <option key={x} value={x}>{x}</option>)}
          </select>
        </div>
        <div className="practice-field">
          <label>Difficulty</label>
          <select value={difficulty} onChange={e => setDifficulty(e.target.value)}>
            <option>Easy</option><option>Medium</option><option>Hard</option>
          </select>
        </div>
        <div className="practice-field">
          <label>Questions</label>
          <select value={count} onChange={e => setCount(e.target.value)}>
            <option value="5">5</option><option value="10">10</option><option value="20">20</option>
          </select>
        </div>
      </div>

      <button type="button" className="btn btn-primary mt-4" onClick={generate} disabled={loading}>
        {loading ? 'Generating…' : 'Generate AI MCQs'}
      </button>

      {error && <div className="practice-error mt-4">{error}</div>}

      {q && (
        <div className="mt-6">
          <div className="panel-kicker">QUESTION {index + 1} OF {questions.length}</div>
          <h3 className="mt-2 text-lg font-semibold">{q.question}</h3>
          <div className="space-y-2 mt-4">
            {(q.options || []).map((option, i) => {
              const letter = 'ABCDE'[i]
              const chosen = picked === letter
              const correct = q.answer === letter
              return (
                <button
                  type="button"
                  key={letter}
                  onClick={() => setPicked(letter)}
                  className="w-full text-left border rounded-xl p-3"
                >
                  <b>{letter}.</b> {option}
                  {picked && correct ? ' ✓' : ''}
                  {chosen && !correct ? ' ✕' : ''}
                </button>
              )
            })}
          </div>
          {picked && <div className="panel mt-4"><b>Explanation:</b> {q.explanation}</div>}
          <div className="flex gap-2 mt-4">
            <button type="button" className="btn" disabled={index === 0} onClick={() => { setIndex(index - 1); setPicked(null) }}>Previous</button>
            <button type="button" className="btn" disabled={index >= questions.length - 1} onClick={() => { setIndex(index + 1); setPicked(null) }}>Next</button>
          </div>
        </div>
      )}
    </section>
  )
}
