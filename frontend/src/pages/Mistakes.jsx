import {
  useEffect,
  useMemo,
  useState
} from 'react'

import { useNavigate } from 'react-router-dom'

import {
  AlertCircle,
  ArrowLeft,
  BookOpen,
  Bookmark,
  Brain,
  History as HistoryIcon,
  CheckCircle2,
  Home,
  Library,
  LogOut,
  RotateCcw,
  Sparkles,
  XCircle
} from 'lucide-react'

import { supabase } from '../lib/supabase'
import Logo from '../components/Logo'


export default function Mistakes({
  session
}) {

  const navigate = useNavigate()

  const [attempts, setAttempts] =
    useState([])

  const [questions, setQuestions] =
    useState([])

  const [books, setBooks] =
    useState([])

  const [loading, setLoading] =
    useState(true)

  const [error, setError] =
    useState('')


  useEffect(() => {
    loadMistakes()
  }, [])


  async function loadMistakes() {

    setLoading(true)
    setError('')

    const {
      data: attemptData,
      error: attemptError
    } = await supabase
      .from('attempts')
      .select('*')
      .eq(
        'user_id',
        session.user.id
      )
      .eq(
        'is_correct',
        false
      )
      .order(
        'created_at',
        {
          ascending: false
        }
      )


    if (attemptError) {
      setError(
        attemptError.message
      )
      setLoading(false)
      return
    }


    const wrongAttempts =
      attemptData || []

    setAttempts(
      wrongAttempts
    )


    const questionIds = [
      ...new Set(
        wrongAttempts
          .map(
            item => item.question_id
          )
          .filter(Boolean)
      )
    ]


    if (questionIds.length > 0) {

      const {
        data: questionData,
        error: questionError
      } = await supabase
        .from('questions')
        .select('*')
        .in(
          'id',
          questionIds
        )


      if (questionError) {

        setError(
          questionError.message
        )

        setQuestions([])

      } else {

        setQuestions(
          questionData || []
        )

      }

    } else {

      setQuestions([])

    }


    const {
      data: bookData,
      error: bookError
    } = await supabase
      .from('books')
      .select(
        'id,title'
      )


    if (bookError) {

      console.error(
        'Books load error:',
        bookError
      )

      setBooks([])

    } else {

      setBooks(
        bookData || []
      )

    }


    setLoading(false)

  }


  const questionMap =
    useMemo(() => {

      const map = {}

      questions.forEach(
        question => {
          map[
            question.id
          ] = question
        }
      )

      return map

    }, [questions])


  const bookMap =
    useMemo(() => {

      const map = {}

      books.forEach(
        book => {
          map[
            book.id
          ] = book
        }
      )

      return map

    }, [books])


  function optionText(question, letter) {

    if (!question || !letter) {
      return ''
    }

    const key =
      `option_${letter.toLowerCase()}`

    return question[key] || ''

  }


  function formatAnswer(question, letter) {

    if (!letter) {
      return '—'
    }

    const text =
      optionText(
        question,
        letter
      )

    return text
      ? `${letter} — ${text}`
      : letter

  }


  const uniqueMistakes =
    useMemo(() => {

      const seen =
        new Set()

      const rows = []

      attempts.forEach(
        attempt => {

          if (
            seen.has(
              attempt.question_id
            )
          ) {
            return
          }

          const question =
            questionMap[
              attempt.question_id
            ]

          if (!question) {
            return
          }

          seen.add(
            attempt.question_id
          )

          rows.push({
            attempt,
            question
          })

        }
      )

      return rows

    }, [
      attempts,
      questionMap
    ])


  async function signOut() {
    await supabase.auth.signOut()
  }


  if (loading) {

    return (
      <div className="page-center">
        <div className="loader" />
      </div>
    )

  }


  return (

    <div className="app-shell">

      <aside className="sidebar">

        <Logo />

        <div className="side-nav">

          <button
            onClick={() =>
              navigate('/dashboard')
            }
          >
            <Home size={18} />
            Dashboard
          </button>


          <button
            onClick={() =>
              navigate('/practice')
            }
          >
            <Brain size={18} />
            Practice
          </button>


          <button
            className="side-active"
          >
            <RotateCcw size={18} />
            Mistakes
          </button>


          <button
            onClick={() =>
              navigate('/bookmarks')
            }
          >
            <Bookmark size={18} />
            Bookmarks
          </button>

          <button
            onClick={() =>
              navigate('/history')
            }
          >
            <HistoryIcon size={18} />
            History
          </button>

          <button
            onClick={() =>
              navigate('/library')
            }
          >
            <Library size={18} />
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


      <main className="dashboard-main mistakes-page">

        <header className="dash-head">

          <div>

            <div className="eyebrow">
              MEDQ REVIEW
            </div>

            <h1>
              Mistakes
            </h1>

            <p>
              Review questions you answered incorrectly and turn weak areas into strengths.
            </p>

          </div>

          <div className="user-chip">
            {session.user.email}
          </div>

        </header>


        {error && (

          <div className="practice-error">
            <AlertCircle size={18} />
            {error}
          </div>

        )}


        <section className="panel mistakes-summary">

          <div>

            <span>
              UNIQUE QUESTIONS TO REVIEW
            </span>

            <div style={{
              marginTop: '8px',
              fontSize: '28px',
              fontWeight: 800
            }}>
              {uniqueMistakes.length}
            </div>

          </div>

          <button
            className="btn btn-outline"
            onClick={() =>
              navigate('/practice')
            }
          >
            <ArrowLeft size={18} />
            Back to Practice
          </button>

        </section>


        {uniqueMistakes.length === 0
          ? (

            <section className="panel mistakes-empty">

              <CheckCircle2 size={36} />

              <h2>
                No mistakes to review
              </h2>

              <p>
                Incorrect answers from your practice sessions will appear here automatically.
              </p>

              <button
                className="btn btn-primary"
                onClick={() =>
                  navigate('/practice')
                }
              >
                Start Practice
              </button>

            </section>

          )
          : (

            <div className="mistakes-list">

              {uniqueMistakes.map(
                ({
                  attempt,
                  question
                }, index) => {

                  const correctOption =
                    question
                      .correct_option
                      ?.toUpperCase()

                  const selectedOption =
                    attempt
                      .selected_option
                      ?.toUpperCase()

                  const sourceTitle =
                    question.book_id
                    && bookMap[
                      question.book_id
                    ]
                      ? bookMap[
                          question.book_id
                        ].title
                      : 'Uploaded textbook'

                  return (

                    <section
                      key={
                        question.id
                      }
                      className="panel mistake-card"
                    >

                      <div className="mistake-card-head">

                        <div>

                          <span className="mistake-number">
                            Mistake {index + 1}
                          </span>

                          <div className="question-tags">

                            {[
                              question.subject,
                              question.chapter,
                              question.topic
                            ]
                              .filter(Boolean)
                              .filter(
                                (value, tagIndex, array) =>
                                  array.indexOf(value) === tagIndex
                              )
                              .map((value) => (
                                <span key={value}>
                                  {value}
                                </span>
                              ))}

                          </div>

                        </div>

                        <XCircle size={23} />

                      </div>


                      <h2 className="professional-question-stem">
                        {question.stem}
                      </h2>


                      <div className="mistake-answer-grid">

                        <div className="mistake-answer wrong">

                          <span>
                            YOUR ANSWER
                          </span>

                          <strong style={{
                            display: 'block',
                            marginTop: '8px'
                          }}>
                            {formatAnswer(
                              question,
                              selectedOption
                            )}
                          </strong>

                        </div>


                        <div className="mistake-answer correct">

                          <span>
                            CORRECT ANSWER
                          </span>

                          <strong style={{
                            display: 'block',
                            marginTop: '8px'
                          }}>
                            {formatAnswer(
                              question,
                              correctOption
                            )}
                          </strong>

                        </div>

                      </div>


                      {question.explanation && (

                        <div className="professional-explanation">

                          <div className="explanation-heading">

                            <Brain size={20} />

                            <div>

                              <span>
                                EXPLANATION
                              </span>

                              <strong>
                                Why this is the best answer
                              </strong>

                            </div>

                          </div>

                          <p>
                            {question.explanation}
                          </p>

                        </div>

                      )}


                      <div className="question-source-card">

                        <BookOpen size={19} />

                        <div>

                          <span>
                            SOURCE
                          </span>

                          <strong>
                            {sourceTitle}
                          </strong>

                        </div>

                      </div>


                      <div className="mistake-actions">

                        <button
                          className="ask-medbot-button"
                          onClick={() =>
                            navigate(
                              `/medbot?question=${encodeURIComponent(
                                question.id
                              )}`
                            )
                          }
                        >
                          <Sparkles size={19} />
                          Ask MedBot
                        </button>

                        <button
                          className="btn btn-outline"
                          onClick={() =>
                            navigate('/practice')
                          }
                        >
                          Practice again
                        </button>

                      </div>

                    </section>

                  )

                }
              )}

            </div>

          )}

      </main>

    </div>

  )

}
