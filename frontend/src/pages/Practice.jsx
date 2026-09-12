import {
  useEffect,
  useMemo,
  useState
} from 'react'

import { useNavigate } from 'react-router-dom'

import {
  ArrowLeft,
  BookOpen,
  Brain,
  CheckCircle2,
  ChevronRight,
  Home,
  LogOut,
  RotateCcw,
  Target,
  XCircle
} from 'lucide-react'

import { supabase } from '../lib/supabase'
import Logo from '../components/Logo'

export default function Practice({ session }) {
  const navigate = useNavigate()

  const [
    questions,
    setQuestions
  ] = useState([])

  const [
    loading,
    setLoading
  ] = useState(true)

  const [
    error,
    setError
  ] = useState('')

  const [
    subject,
    setSubject
  ] = useState('all')

  const [
    difficulty,
    setDifficulty
  ] = useState('all')

  const [
    search,
    setSearch
  ] = useState('')

  const [
    currentIndex,
    setCurrentIndex
  ] = useState(0)

  const [
    selectedOption,
    setSelectedOption
  ] = useState(null)

  const [
    submitted,
    setSubmitted
  ] = useState(false)

  const [
    saving,
    setSaving
  ] = useState(false)

  useEffect(() => {
    loadQuestions()
  }, [])

  async function loadQuestions() {
    setLoading(true)
    setError('')

    try {
      // Supabase/PostgREST returns at most 1,000 rows per request by default.
      // Practice therefore loads the complete bank in 1,000-row pages.
      const columns = [
        'id',
        'book_id',
        'exam_type',
        'question_type',
        'stem',
        'option_a',
        'option_b',
        'option_c',
        'option_d',
        'option_e',
        'correct_option',
        'explanation',
        'subject',
        'chapter',
        'topic',
        'difficulty',
        'source_page',
        'created_at'
      ].join(',')

      const pageSize = 1000
      const first = await supabase
        .from('questions')
        .select(columns, { count: 'exact' })
        .order('created_at', { ascending: true })
        .range(0, pageSize - 1)

      if (first.error) throw first.error

      const total = first.count || (first.data || []).length
      const firstPage = first.data || []

      if (total <= pageSize) {
        setQuestions(firstPage)
        return
      }

      const pageStarts = []
      for (let start = pageSize; start < total; start += pageSize) {
        pageStarts.push(start)
      }

      const allRows = [...firstPage]
      // Five concurrent pages gives a large speed-up without flooding Supabase.
      const concurrency = 5
      for (let i = 0; i < pageStarts.length; i += concurrency) {
        const batch = pageStarts.slice(i, i + concurrency)
        const results = await Promise.all(
          batch.map((start) =>
            supabase
              .from('questions')
              .select(columns)
              .order('created_at', { ascending: true })
              .range(start, Math.min(start + pageSize - 1, total - 1))
          )
        )

        for (const result of results) {
          if (result.error) throw result.error
          allRows.push(...(result.data || []))
        }
      }

      // De-duplicate by ID in case a row changes while pages are loading.
      const unique = Array.from(
        new Map(allRows.map((row) => [row.id, row])).values()
      )

      setQuestions(unique)
    } catch (loadError) {
      console.error(loadError)
      setQuestions([])
      setError(
        loadError?.message ||
        'Could not load the complete question bank.'
      )
    } finally {
      setLoading(false)
    }
  }

  const subjects = useMemo(() => {
    return [
      ...new Set(
        questions
          .map(
            (question) =>
              question.subject
          )
          .filter(Boolean)
      )
    ].sort()
  }, [questions])

  const filteredQuestions =
    useMemo(() => {

      return questions.filter(
        (question) => {

          const subjectMatch =
            subject === 'all' ||
            question.subject === subject

          const difficultyMatch =
            difficulty === 'all' ||
            question.difficulty === difficulty

          const searchText = search.trim().toLowerCase()
          const searchMatch =
            !searchText ||
            [
              question.stem,
              question.subject,
              question.chapter,
              question.topic,
              question.explanation,
              question.option_a,
              question.option_b,
              question.option_c,
              question.option_d,
              question.option_e
            ]
              .filter(Boolean)
              .some((value) =>
                String(value).toLowerCase().includes(searchText)
              )

          return (
            subjectMatch &&
            difficultyMatch &&
            searchMatch
          )
        }
      )

    }, [
      questions,
      subject,
      difficulty,
      search
    ])

  useEffect(() => {
    setCurrentIndex(0)
    setSelectedOption(null)
    setSubmitted(false)
  }, [
    subject,
    difficulty
  ])

  const currentQuestion =
    filteredQuestions[
      currentIndex
    ] || null

  const options =
    currentQuestion
      ? [
          [
            'A',
            currentQuestion.option_a
          ],
          [
            'B',
            currentQuestion.option_b
          ],
          [
            'C',
            currentQuestion.option_c
          ],
          [
            'D',
            currentQuestion.option_d
          ],
          [
            'E',
            currentQuestion.option_e
          ]
        ].filter(
          ([, text]) => text
        )
      : []

  const correctOption =
    currentQuestion
      ?.correct_option
      ?.toUpperCase()

  const isCorrect =
    submitted &&
    selectedOption === correctOption

  async function submitAnswer() {
    if (
      !currentQuestion ||
      !selectedOption ||
      submitted
    ) {
      return
    }

    setSaving(true)
    setError('')

    const answerIsCorrect =
      selectedOption === correctOption

    const {
      error
    } = await supabase
      .from('attempts')
      .insert({
        user_id:
          session.user.id,

        question_id:
          currentQuestion.id,

        selected_option:
          selectedOption,

        is_correct:
          answerIsCorrect
      })

    if (error) {
      setError(
        error.message
      )

      setSaving(false)

      return
    }

    setSubmitted(true)
    setSaving(false)
  }

  function nextQuestion() {
    if (
      currentIndex <
      filteredQuestions.length - 1
    ) {
      setCurrentIndex(
        (index) => index + 1
      )

      setSelectedOption(null)
      setSubmitted(false)
      setError('')
    }
  }

  function previousQuestion() {
    if (currentIndex > 0) {
      setCurrentIndex(
        (index) => index - 1
      )

      setSelectedOption(null)
      setSubmitted(false)
      setError('')
    }
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

          <button className="side-active">
            <Brain size={18} />
            Practice
          </button>

          <button>
            <RotateCcw size={18} />
            Mistakes

            <span className="soon">
              soon
            </span>
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
              MEDQ PRACTICE
            </div>

            <h1>
              Question Practice
            </h1>

            <p>
              Every answer is saved to
              your personal account.
            </p>

          </div>

          <div className="user-chip">
            {session.user.email}
          </div>

        </header>

        <section className="panel" style={{ marginBottom: '14px' }}>
          <label style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>
            Search the full question bank
          </label>
          <input
            type="search"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value)
              setCurrentIndex(0)
            }}
            placeholder="Search diagnosis, drug, topic, chapter, question or option…"
            aria-label="Search the full question bank"
            style={{
              width: '100%',
              padding: '12px 14px',
              border: '1px solid #d1d5db',
              borderRadius: '10px',
              fontSize: '16px',
              boxSizing: 'border-box'
            }}
          />
          {search.trim() && (
            <div style={{ marginTop: '8px', fontSize: '13px', opacity: 0.75 }}>
              {filteredQuestions.length.toLocaleString()} matches in the complete bank
            </div>
          )}
        </section>

        <section className="practice-filter-panel panel">

          <div>

            <label>
              Subject
            </label>

            <select
              value={subject}
              onChange={
                (event) =>
                  setSubject(
                    event.target.value
                  )
              }
            >

              <option value="all">
                All subjects
              </option>

              {subjects.map(
                (item) => (

                  <option
                    key={item}
                    value={item}
                  >
                    {item}
                  </option>

                )
              )}

            </select>

          </div>

          <div>

            <label>
              Difficulty
            </label>

            <select
              value={difficulty}
              onChange={
                (event) =>
                  setDifficulty(
                    event.target.value
                  )
              }
            >

              <option value="all">
                All difficulties
              </option>

              <option value="easy">
                Easy
              </option>

              <option value="medium">
                Medium
              </option>

              <option value="hard">
                Hard
              </option>

            </select>

          </div>

          <div className="practice-count">

            <span>
              Questions
            </span>

            <strong>
              {filteredQuestions.length}
            </strong>

          </div>

        </section>

        {loading ? (

          <div className="panel">
            Loading questions…
          </div>

        ) : error ? (

          <div className="panel">

            <h2>
              Something went wrong
            </h2>

            <p>
              {error}
            </p>

          </div>

        ) : filteredQuestions.length === 0 ? (

          <section className="panel empty-practice">

            <Brain size={38} />

            <h2>
              No questions available yet.
            </h2>

            <p>
              Upload medical PDFs into
              the shared MedQ Library.
              Once automatic processing
              creates questions, they will
              appear here.
            </p>

            <button
              className="btn btn-primary"
              onClick={() =>
                navigate('/library')
              }
            >
              <BookOpen size={18} />
              Open Library
            </button>

          </section>

        ) : (

          <>

            <section className="panel practice-card">

              <div className="practice-top">

                <div>

                  <div className="panel-kicker">
                    QUESTION {currentIndex + 1}
                    {' '}OF{' '}
                    {filteredQuestions.length}
                  </div>

                  <div className="question-tags">

                    {currentQuestion.subject && (
                      <span>
                        {currentQuestion.subject}
                      </span>
                    )}

                    {currentQuestion.chapter && (
                      <span>
                        {currentQuestion.chapter}
                      </span>
                    )}

                    {currentQuestion.topic && (
                      <span>
                        {currentQuestion.topic}
                      </span>
                    )}

                    {currentQuestion.difficulty && (
                      <span>
                        {currentQuestion.difficulty}
                      </span>
                    )}

                  </div>

                </div>

                {currentQuestion.source_page && (

                  <div className="source-page">
                    Page{' '}
                    {currentQuestion.source_page}
                  </div>

                )}

              </div>

              <h2 className="question-stem">
                {currentQuestion.stem}
              </h2>

              <div className="option-list">

                {options.map(
                  ([letter, text]) => {

                    const selected =
                      selectedOption === letter

                    const correct =
                      submitted &&
                      letter === correctOption

                    const wrong =
                      submitted &&
                      selected &&
                      letter !== correctOption

                    return (

                      <button
                        key={letter}
                        className={[
                          'option-button',
                          selected
                            ? 'selected'
                            : '',
                          correct
                            ? 'correct'
                            : '',
                          wrong
                            ? 'wrong'
                            : ''
                        ].join(' ')}
                        onClick={() => {
                          if (!submitted) {
                            setSelectedOption(
                              letter
                            )
                          }
                        }}
                      >

                        <span className="option-letter">
                          {letter}
                        </span>

                        <span className="option-text">
                          {text}
                        </span>

                        {correct && (
                          <CheckCircle2
                            size={20}
                          />
                        )}

                        {wrong && (
                          <XCircle
                            size={20}
                          />
                        )}

                      </button>

                    )
                  }
                )}

              </div>

              {!submitted ? (

                <button
                  className="btn btn-primary submit-answer"
                  disabled={
                    !selectedOption ||
                    saving
                  }
                  onClick={
                    submitAnswer
                  }
                >
                  {
                    saving
                      ? 'Saving…'
                      : 'Submit answer'
                  }
                </button>

              ) : (

                <div className="answer-result">

                  <div
                    className={
                      isCorrect
                        ? 'answer-banner correct-banner'
                        : 'answer-banner wrong-banner'
                    }
                  >

                    {isCorrect ? (
                      <>
                        <CheckCircle2
                          size={22}
                        />
                        Correct
                      </>
                    ) : (
                      <>
                        <XCircle
                          size={22}
                        />
                        Incorrect —
                        correct answer is{' '}
                        {correctOption}
                      </>
                    )}

                  </div>

                  {
                    currentQuestion.explanation &&
                    (

                      <div className="explanation-box">

                        <div className="panel-kicker">
                          EXPLANATION
                        </div>

                        <p>
                          {
                            currentQuestion.explanation
                          }
                        </p>

                      </div>

                    )
                  }

                </div>

              )}

            </section>

            <div className="practice-navigation">

              <button
                className="btn"
                disabled={
                  currentIndex === 0
                }
                onClick={
                  previousQuestion
                }
              >
                <ArrowLeft size={18} />
                Previous
              </button>

              <button
                className="btn btn-primary"
                disabled={
                  !submitted ||
                  currentIndex ===
                    filteredQuestions.length - 1
                }
                onClick={
                  nextQuestion
                }
              >
                Next question
                <ChevronRight size={18} />
              </button>

            </div>

          </>

        )}

      </main>

    </div>
  )
}
