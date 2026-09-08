import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bookmark,
  BookOpen,
  Brain,
  History as HistoryIcon,
  LogOut,
  RotateCcw,
  Sparkles,
  Target,
  Trash2
} from 'lucide-react'

import { supabase } from '../lib/supabase'
import Logo from '../components/Logo'


export default function Bookmarks({ session }) {

  const navigate = useNavigate()

  const [rows, setRows] = useState([])
  const [questions, setQuestions] = useState([])
  const [books, setBooks] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [removingId, setRemovingId] = useState(null)


  useEffect(() => {
    loadBookmarks()
  }, [session])


  async function loadBookmarks() {

    setLoading(true)
    setError('')

    const userId = session.user.id

    const {
      data: bookmarkRows,
      error: bookmarkError
    } = await supabase
      .from('bookmarks')
      .select('user_id, question_id, created_at')
      .eq('user_id', userId)
      .order('created_at', {
        ascending: false
      })

    if (bookmarkError) {
      setError(bookmarkError.message)
      setLoading(false)
      return
    }

    const cleanRows = bookmarkRows || []
    setRows(cleanRows)

    const questionIds = [
      ...new Set(
        cleanRows
          .map((row) => row.question_id)
          .filter(Boolean)
      )
    ]

    if (!questionIds.length) {
      setQuestions([])
      setBooks([])
      setLoading(false)
      return
    }

    const [
      {
        data: questionRows,
        error: questionError
      },
      {
        data: bookRows,
        error: bookError
      }
    ] = await Promise.all([
      supabase
        .from('questions')
        .select('*')
        .in('id', questionIds),

      supabase
        .from('books')
        .select('id, title')
    ])

    if (questionError) {
      setError(questionError.message)
      setLoading(false)
      return
    }

    if (bookError) {
      setError(bookError.message)
      setLoading(false)
      return
    }

    setQuestions(questionRows || [])
    setBooks(bookRows || [])
    setLoading(false)
  }


  const questionMap = useMemo(() => {
    return new Map(
      questions.map(
        (question) => [
          question.id,
          question
        ]
      )
    )
  }, [questions])


  const bookMap = useMemo(() => {
    return new Map(
      books.map(
        (book) => [
          book.id,
          book.title
        ]
      )
    )
  }, [books])


  const savedQuestions = useMemo(() => {
    return rows
      .map((row) => ({
        row,
        question:
          questionMap.get(
            row.question_id
          )
      }))
      .filter(
        (item) =>
          Boolean(item.question)
      )
  }, [
    rows,
    questionMap
  ])


  async function removeBookmark(questionId) {

    setRemovingId(questionId)
    setError('')

    const {
      error: deleteError
    } = await supabase
      .from('bookmarks')
      .delete()
      .eq(
        'user_id',
        session.user.id
      )
      .eq(
        'question_id',
        questionId
      )

    if (deleteError) {
      setError(deleteError.message)
      setRemovingId(null)
      return
    }

    setRows(
      (previous) =>
        previous.filter(
          (row) =>
            row.question_id !== questionId
        )
    )

    setRemovingId(null)
  }


  async function signOut() {
    await supabase.auth.signOut()
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
            <Target size={18} />
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
            onClick={() =>
              navigate('/mistakes')
            }
          >
            <RotateCcw size={18} />
            Mistakes
          </button>

          <button
            className="side-active"
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
              MEDQ REVIEW
            </div>

            <h1>
              Bookmarks
            </h1>

            <p>
              Questions you save for later review appear here.
            </p>

          </div>

          <div className="user-chip">
            {session.user.email}
          </div>

        </header>


        {error && (
          <div
            style={{
              border: '1px solid rgba(255, 120, 120, 0.35)',
              borderRadius: '14px',
              padding: '14px 16px',
              marginBottom: '20px'
            }}
          >
            {error}
          </div>
        )}


        {loading ? (

          <div className="dash-loading">
            Loading your bookmarks…
          </div>

        ) : savedQuestions.length === 0 ? (

          <section className="panel">

            <Bookmark size={34} />

            <h2>
              No bookmarks yet
            </h2>

            <p>
              Save useful MCQs while practicing and they will appear here.
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

        ) : (

          <>

            <section
              className="panel"
              style={{
                marginBottom: '18px'
              }}
            >

              <div className="panel-kicker">
                SAVED QUESTIONS
              </div>

              <h2
                style={{
                  marginBottom: 0
                }}
              >
                {savedQuestions.length}
              </h2>

            </section>


            <div
              style={{
                display: 'grid',
                gap: '18px'
              }}
            >

              {savedQuestions.map(
                ({
                  row,
                  question
                }, index) => {

                  const tags = [
                    question.subject,
                    question.chapter,
                    question.topic
                  ]
                    .filter(Boolean)
                    .filter(
                      (value, tagIndex, array) =>
                        array.indexOf(value) === tagIndex
                    )

                  const sourceTitle =
                    bookMap.get(
                      question.book_id
                    ) || ''

                  return (
                    <section
                      className="panel"
                      key={`${row.question_id}-${index}`}
                    >

                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          gap: '16px',
                          alignItems: 'flex-start'
                        }}
                      >

                        <div>

                          <div className="panel-kicker">
                            BOOKMARK {index + 1}
                          </div>

                          {tags.length > 0 && (
                            <div
                              className="question-tags"
                              style={{
                                marginTop: '10px'
                              }}
                            >
                              {tags.map(
                                (tag) => (
                                  <span key={tag}>
                                    {tag}
                                  </span>
                                )
                              )}
                            </div>
                          )}

                        </div>

                        <button
                          className="btn"
                          disabled={
                            removingId ===
                            question.id
                          }
                          onClick={() =>
                            removeBookmark(
                              question.id
                            )
                          }
                        >
                          <Trash2 size={16} />
                          {removingId ===
                          question.id
                            ? 'Removing…'
                            : 'Remove'}
                        </button>

                      </div>


                      <h2
                        style={{
                          marginTop: '18px'
                        }}
                      >
                        {question.stem}
                      </h2>


                      {question.explanation && (
                        <div
                          className="question-source-card"
                          style={{
                            marginTop: '18px'
                          }}
                        >

                          <div className="panel-kicker">
                            EXPLANATION
                          </div>

                          <strong>
                            Why this answer is correct
                          </strong>

                          <p>
                            {question.explanation}
                          </p>

                        </div>
                      )}


                      {sourceTitle && (
                        <div
                          className="question-source-card"
                          style={{
                            marginTop: '14px'
                          }}
                        >

                          <div className="panel-kicker">
                            SOURCE
                          </div>

                          <strong>
                            {sourceTitle}
                          </strong>

                        </div>
                      )}


                      <div
                        style={{
                          display: 'flex',
                          gap: '12px',
                          flexWrap: 'wrap',
                          marginTop: '16px'
                        }}
                      >

                        <button
                          className="btn btn-primary"
                          onClick={() =>
                            navigate(
                              `/medbot?question=${encodeURIComponent(
                                question.id
                              )}`
                            )
                          }
                        >
                          <Sparkles size={17} />
                          Ask MedBot
                        </button>

                        <button
                          className="btn"
                          onClick={() =>
                            navigate('/practice')
                          }
                        >
                          <Brain size={17} />
                          Practice
                        </button>

                      </div>

                    </section>
                  )
                }
              )}

            </div>

          </>

        )}

      </main>

    </div>
  )
}
