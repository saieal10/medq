import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bookmark,
  BookOpen,
  Brain,
  CheckCircle2,
  Clock3,
  Filter,
  History as HistoryIcon,
  LogOut,
  RotateCcw,
  Sparkles,
  Target,
  XCircle
} from 'lucide-react'

import { supabase } from '../lib/supabase'
import Logo from '../components/Logo'

export default function History({ session }) {
  const navigate = useNavigate()

  const [attempts, setAttempts] = useState([])
  const [questions, setQuestions] = useState({})
  const [books, setBooks] = useState({})
  const [filter, setFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    loadHistory()
  }, [session])

  async function loadHistory() {
    setLoading(true)
    setError('')

    try {
      const userId = session.user.id

      const { data: attemptRows, error: attemptError } = await supabase
        .from('attempts')
        .select('id, question_id, selected_option, is_correct, created_at')
        .eq('user_id', userId)
        .order('created_at', { ascending: false })

      if (attemptError) {
        throw attemptError
      }

      const safeAttempts = attemptRows || []
      setAttempts(safeAttempts)

      const questionIds = [
        ...new Set(
          safeAttempts
            .map((attempt) => attempt.question_id)
            .filter(Boolean)
        )
      ]

      if (questionIds.length === 0) {
        setQuestions({})
        setBooks({})
        setLoading(false)
        return
      }

      const { data: questionRows, error: questionError } = await supabase
        .from('questions')
        .select(`
          id,
          stem,
          option_a,
          option_b,
          option_c,
          option_d,
          correct_option,
          explanation,
          subject,
          topic,
          chapter,
          exam_type,
          book_id
        `)
        .in('id', questionIds)

      if (questionError) {
        throw questionError
      }

      const questionMap = Object.fromEntries(
        (questionRows || []).map((question) => [
          question.id,
          question
        ])
      )

      setQuestions(questionMap)

      const bookIds = [
        ...new Set(
          (questionRows || [])
            .map((question) => question.book_id)
            .filter(Boolean)
        )
      ]

      if (bookIds.length > 0) {
        const { data: bookRows } = await supabase
          .from('books')
          .select('id, title')
          .in('id', bookIds)

        setBooks(
          Object.fromEntries(
            (bookRows || []).map((book) => [
              book.id,
              book.title
            ])
          )
        )
      } else {
        setBooks({})
      }

    } catch (err) {
      setError(
        err?.message ||
        'Unable to load your practice history.'
      )
    } finally {
      setLoading(false)
    }
  }

  const filteredAttempts = useMemo(() => {
    if (filter === 'correct') {
      return attempts.filter(
        (attempt) => attempt.is_correct === true
      )
    }

    if (filter === 'incorrect') {
      return attempts.filter(
        (attempt) => attempt.is_correct === false
      )
    }

    return attempts
  }, [attempts, filter])

  const correctCount = useMemo(() => {
    return attempts.filter(
      (attempt) => attempt.is_correct === true
    ).length
  }, [attempts])

  const incorrectCount = attempts.length - correctCount

  async function signOut() {
    await supabase.auth.signOut()
  }

  function optionText(question, option) {
    if (!question || !option) return ''

    const key =
      `option_${String(option).toLowerCase()}`

    return question[key] || ''
  }

  function formatDate(value) {
    if (!value) return 'Date unavailable'

    const date = new Date(value)

    if (Number.isNaN(date.getTime())) {
      return 'Date unavailable'
    }

    return date.toLocaleString([], {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  return (
    <div className="app-shell">

      <aside className="sidebar">

        <Logo />

        <div className="side-nav">

          <button
            onClick={() => navigate('/dashboard')}
          >
            <Target size={18} />
            Dashboard
          </button>

          <button
            onClick={() => navigate('/practice')}
          >
            <Brain size={18} />
            Practice
          </button>

          <button
            onClick={() => navigate('/mistakes')}
          >
            <RotateCcw size={18} />
            Mistakes
          </button>

          <button
            onClick={() => navigate('/bookmarks')}
          >
            <Bookmark size={18} />
            Bookmarks
          </button>

          <button
            className="side-active"
          >
            <HistoryIcon size={18} />
            History
          </button>

          <button
            onClick={() => navigate('/library')}
          >
            <BookOpen size={18} />
            Library
          </button>

        </div>

        <button
          className="logout"
          onClick={signOut}
        >
          <LogOut size={18} />
          Sign out
        </button>

      </aside>

      <main className="dashboard-main">

        <header className="dash-head">

          <div>

            <div className="eyebrow">
              PRACTICE HISTORY
            </div>

            <h1>
              Your answer history
            </h1>

            <p>
              Review every answer you have submitted on MedQ.
            </p>

          </div>

          <div className="user-chip">
            {session.user.email}
          </div>

        </header>

        <section className="stat-grid">

          <Stat
            label="Total attempts"
            value={attempts.length}
            meta="All recorded answers"
          />

          <Stat
            label="Correct"
            value={correctCount}
            meta="All time"
          />

          <Stat
            label="Incorrect"
            value={incorrectCount}
            meta="All time"
          />

          <Stat
            label="Accuracy"
            value={
              attempts.length
                ? `${Math.round(
                    (correctCount / attempts.length) * 100
                  )}%`
                : '0%'
            }
            meta="Based on attempt history"
          />

        </section>

        <section
          className="panel"
          style={{
            marginTop: '20px'
          }}
        >

          <div className="panel-title-row">

            <div>

              <div className="panel-kicker">
                FILTER HISTORY
              </div>

              <h2>
                Choose which answers to review
              </h2>

            </div>

            <Filter size={20} />

          </div>

          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: '10px',
              marginTop: '18px'
            }}
          >

            <FilterButton
              active={filter === 'all'}
              onClick={() => setFilter('all')}
              label={`All (${attempts.length})`}
            />

            <FilterButton
              active={filter === 'correct'}
              onClick={() => setFilter('correct')}
              label={`Correct (${correctCount})`}
            />

            <FilterButton
              active={filter === 'incorrect'}
              onClick={() => setFilter('incorrect')}
              label={`Incorrect (${incorrectCount})`}
            />

          </div>

        </section>

        {loading ? (

          <div className="dash-loading">
            Loading your history…
          </div>

        ) : error ? (

          <section
            className="panel"
            style={{
              marginTop: '20px'
            }}
          >
            <XCircle size={20} />
            <p>{error}</p>
          </section>

        ) : filteredAttempts.length === 0 ? (

          <section
            className="panel"
            style={{
              marginTop: '20px'
            }}
          >

            <div className="panel-kicker">
              NO ATTEMPTS FOUND
            </div>

            <h2>
              Nothing to review here yet.
            </h2>

            <p>
              Start a practice session and your answers will
              automatically appear in History.
            </p>

            <button
              className="btn btn-primary"
              onClick={() => navigate('/practice')}
            >
              Start Practice
            </button>

          </section>

        ) : (

          <div
            style={{
              display: 'grid',
              gap: '16px',
              marginTop: '20px'
            }}
          >

            {filteredAttempts.map((attempt, index) => {

              const question =
                questions[attempt.question_id]

              if (!question) {
                return (
                  <section
                    key={attempt.id}
                    className="panel"
                  >
                    <div className="panel-kicker">
                      ATTEMPT {filteredAttempts.length - index}
                    </div>

                    <p>
                      This question is no longer available in
                      the current question bank.
                    </p>
                  </section>
                )
              }

              const userOption =
                String(attempt.selected_option || '')
                  .toUpperCase()

              const correctOption =
                String(question.correct_option || '')
                  .toUpperCase()

              const bookTitle =
                books[question.book_id] || ''

              return (
                <section
                  key={attempt.id}
                  className="panel"
                >

                  <div className="panel-title-row">

                    <div>

                      <div className="panel-kicker">
                        {attempt.is_correct
                          ? 'CORRECT ATTEMPT'
                          : 'INCORRECT ATTEMPT'}
                      </div>

                      <div
                        style={{
                          display: 'flex',
                          flexWrap: 'wrap',
                          gap: '8px',
                          marginTop: '10px'
                        }}
                      >

                        {question.subject && (
                          <span className="user-chip">
                            {question.subject}
                          </span>
                        )}

                        {question.exam_type && (
                          <span className="user-chip">
                            {String(question.exam_type).toUpperCase()}
                          </span>
                        )}

                        {question.topic && (
                          <span className="user-chip">
                            {question.topic}
                          </span>
                        )}

                      </div>

                    </div>

                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px'
                      }}
                    >
                      {attempt.is_correct ? (
                        <CheckCircle2 size={22} />
                      ) : (
                        <XCircle size={22} />
                      )}
                    </div>

                  </div>

                  <h2
                    style={{
                      marginTop: '20px'
                    }}
                  >
                    {question.stem}
                  </h2>

                  <div
                    className="dashboard-grid"
                    style={{
                      marginTop: '18px'
                    }}
                  >

                    <div className="panel">

                      <div className="panel-kicker">
                        YOUR ANSWER
                      </div>

                      <strong>
                        {userOption || '—'}
                        {userOption &&
                          optionText(question, userOption)
                          ? ` — ${optionText(question, userOption)}`
                          : ''}
                      </strong>

                    </div>

                    <div className="panel">

                      <div className="panel-kicker">
                        CORRECT ANSWER
                      </div>

                      <strong>
                        {correctOption || '—'}
                        {correctOption &&
                          optionText(question, correctOption)
                          ? ` — ${optionText(question, correctOption)}`
                          : ''}
                      </strong>

                    </div>

                  </div>

                  {question.explanation && (

                    <div
                      className="panel"
                      style={{
                        marginTop: '16px'
                      }}
                    >

                      <div className="panel-kicker">
                        EXPLANATION
                      </div>

                      <p>
                        {question.explanation}
                      </p>

                    </div>

                  )}

                  {bookTitle && (

                    <div
                      className="panel"
                      style={{
                        marginTop: '16px'
                      }}
                    >

                      <div className="panel-kicker">
                        SOURCE
                      </div>

                      <strong>
                        {bookTitle}
                      </strong>

                    </div>

                  )}

                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: '12px',
                      marginTop: '18px'
                    }}
                  >

                    <button
                      className="btn btn-primary"
                      onClick={() =>
                        navigate(
                          `/medbot?question=${question.id}`
                        )
                      }
                    >
                      <Sparkles size={18} />
                      Ask MedBot
                    </button>

                    <button
                      className="btn"
                      onClick={() =>
                        navigate('/practice')
                      }
                    >
                      <Brain size={18} />
                      Practice
                    </button>

                  </div>

                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '7px',
                      marginTop: '18px',
                      opacity: 0.7
                    }}
                  >
                    <Clock3 size={15} />
                    <small>
                      {formatDate(attempt.created_at)}
                    </small>
                  </div>

                </section>
              )
            })}

          </div>

        )}

      </main>

    </div>
  )
}


function Stat({
  label,
  value,
  meta
}) {
  return (
    <div className="stat-card">

      <span>
        {label}
      </span>

      <strong>
        {value}
      </strong>

      <small>
        {meta}
      </small>

    </div>
  )
}


function FilterButton({
  active,
  onClick,
  label
}) {
  return (
    <button
      className={
        active
          ? 'btn btn-primary'
          : 'btn'
      }
      type="button"
      onClick={onClick}
    >
      {label}
    </button>
  )
}
