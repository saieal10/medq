import {
  useEffect,
  useMemo,
  useState
} from 'react'

import { useNavigate } from 'react-router-dom'

import {
  AlertCircle,
  ArrowLeft,
  BarChart3,
  BookOpen,
  Bookmark,
  Brain,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Filter,
  Flag,
  Home,
  Library,
  LogOut,
  Play,
  RotateCcw,
  Sparkles,
  Target,
  Timer,
  X,
  XCircle
} from 'lucide-react'

import { supabase } from '../lib/supabase'
import Logo from '../components/Logo'


const QUESTION_COUNT_OPTIONS = [
  10,
  20,
  50,
  100
]


function formatTime(seconds) {
  const safeSeconds = Math.max(
    0,
    Number(seconds) || 0
  )

  const hours = Math.floor(
    safeSeconds / 3600
  )

  const minutes = Math.floor(
    (safeSeconds % 3600) / 60
  )

  const secs = safeSeconds % 60

  if (hours > 0) {
    return [
      hours,
      minutes,
      secs
    ]
      .map((value) =>
        String(value).padStart(2, '0')
      )
      .join(':')
  }

  return [
    minutes,
    secs
  ]
    .map((value) =>
      String(value).padStart(2, '0')
    )
    .join(':')
}


function normalizeExamType(value) {
  return String(
    value || 'both'
  )
    .trim()
    .toUpperCase()
}


function shuffleArray(array) {
  const copied = [
    ...array
  ]

  for (
    let index = copied.length - 1;
    index > 0;
    index -= 1
  ) {
    const randomIndex = Math.floor(
      Math.random() * (index + 1)
    )

    const temporary =
      copied[index]

    copied[index] =
      copied[randomIndex]

    copied[randomIndex] =
      temporary
  }

  return copied
}


export default function Practice({
  session
}) {
  const navigate = useNavigate()


  // =======================================================
  // DATABASE DATA
  // =======================================================

  const [
    questions,
    setQuestions
  ] = useState([])

  const [
    books,
    setBooks
  ] = useState([])

  const [
    loading,
    setLoading
  ] = useState(true)

  const [
    error,
    setError
  ] = useState('')


  // =======================================================
  // SETUP FILTERS
  // =======================================================

  const [
    examMode,
    setExamMode
  ] = useState('mixed')

  const [
    subject,
    setSubject
  ] = useState('all')

  const [
    bookId,
    setBookId
  ] = useState('all')

  const [
    chapter,
    setChapter
  ] = useState('all')

  const [
    topic,
    setTopic
  ] = useState('all')

  const [
    difficulty,
    setDifficulty
  ] = useState('all')

  const [
    practiceMode,
    setPracticeMode
  ] = useState('tutor')

  const [
    requestedCount,
    setRequestedCount
  ] = useState(20)


  // =======================================================
  // SESSION STATE
  // =======================================================

  const [
    sessionStarted,
    setSessionStarted
  ] = useState(false)

  const [
    sessionFinished,
    setSessionFinished
  ] = useState(false)

  const [
    sessionQuestions,
    setSessionQuestions
  ] = useState([])

  const [
    currentIndex,
    setCurrentIndex
  ] = useState(0)

  const [
    answers,
    setAnswers
  ] = useState({})

  const [
    submittedQuestions,
    setSubmittedQuestions
  ] = useState({})

  const [
    savedAttempts,
    setSavedAttempts
  ] = useState({})

  const [
    flags,
    setFlags
  ] = useState({})

  const [
    elapsedSeconds,
    setElapsedSeconds
  ] = useState(0)

  const [
    saving,
    setSaving
  ] = useState(false)

  const [
    bookmarkedQuestionIds,
    setBookmarkedQuestionIds
  ] = useState({})

  const [
    bookmarkSavingId,
    setBookmarkSavingId
  ] = useState(null)


  // =======================================================
  // LOAD DATA
  // =======================================================

  useEffect(() => {
    loadPracticeData()
    loadBookmarks()
  }, [])


  async function loadBookmarks() {

    const {
      data,
      error: bookmarkError
    } = await supabase
      .from('bookmarks')
      .select('question_id')
      .eq(
        'user_id',
        session.user.id
      )

    if (bookmarkError) {
      console.error(
        'Unable to load bookmarks:',
        bookmarkError.message
      )
      return
    }

    const next = {}

    ;(data || []).forEach(
      (row) => {
        if (row.question_id) {
          next[row.question_id] = true
        }
      }
    )

    setBookmarkedQuestionIds(next)
  }


  async function toggleBookmark(question) {

    if (!question?.id) {
      return
    }

    const questionId = question.id
    const isBookmarked =
      Boolean(
        bookmarkedQuestionIds[
          questionId
        ]
      )

    setBookmarkSavingId(
      questionId
    )
    setError('')

    if (isBookmarked) {

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
        setError(
          deleteError.message
        )
        setBookmarkSavingId(null)
        return
      }

      setBookmarkedQuestionIds(
        (previous) => {
          const next = {
            ...previous
          }

          delete next[
            questionId
          ]

          return next
        }
      )

    } else {

      const {
        error: insertError
      } = await supabase
        .from('bookmarks')
        .insert({
          user_id:
            session.user.id,
          question_id:
            questionId
        })

      if (insertError) {
        setError(
          insertError.message
        )
        setBookmarkSavingId(null)
        return
      }

      setBookmarkedQuestionIds(
        (previous) => ({
          ...previous,
          [questionId]: true
        })
      )
    }

    setBookmarkSavingId(null)
  }


  async function loadPracticeData() {
    setLoading(true)
    setError('')

    const [
      questionResponse,
      bookResponse
    ] = await Promise.all([
      supabase
        .from('questions')
        .select('*')
        .order(
          'created_at',
          {
            ascending: false
          }
        ),

      supabase
        .from('books')
        .select(
          'id,title,subject,status'
        )
        .order(
          'created_at',
          {
            ascending: false
          }
        )
    ])

    if (questionResponse.error) {
      setError(
        questionResponse.error.message
      )

      setQuestions([])
    } else {
      setQuestions(
        questionResponse.data || []
      )
    }

    if (bookResponse.error) {
      console.error(
        'Books load error:',
        bookResponse.error
      )

      setBooks([])
    } else {
      setBooks(
        bookResponse.data || []
      )
    }

    setLoading(false)
  }


  // =======================================================
  // TIMER
  // =======================================================

  useEffect(() => {
    if (
      !sessionStarted ||
      sessionFinished
    ) {
      return undefined
    }

    const interval = setInterval(
      () => {
        setElapsedSeconds(
          (value) => value + 1
        )
      },
      1000
    )

    return () => {
      clearInterval(interval)
    }
  }, [
    sessionStarted,
    sessionFinished
  ])


  // =======================================================
  // BOOK LOOKUP
  // =======================================================

  const bookMap = useMemo(() => {
    const map = {}

    books.forEach((book) => {
      map[book.id] = book
    })

    return map
  }, [books])


  // =======================================================
  // AVAILABLE FILTER VALUES
  // =======================================================

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


  const eligibleBooks = useMemo(() => {
    if (subject === 'all') {
      return books
    }

    return books.filter(
      (book) =>
        !book.subject ||
        book.subject === subject
    )
  }, [
    books,
    subject
  ])


  const baseFilteredQuestions =
    useMemo(() => {
      return questions.filter(
        (question) => {

          // -----------------------------------------------
          // EXAM TYPE
          // -----------------------------------------------

          const questionExam =
            normalizeExamType(
              question.exam_type
            )

          let examMatches = true

          if (examMode === 'amc') {
            examMatches =
              questionExam === 'AMC' ||
              questionExam === 'BOTH'
          }

          if (examMode === 'fmge') {
            examMatches =
              questionExam === 'FMGE' ||
              questionExam === 'BOTH'
          }

          if (examMode === 'mixed') {
            examMatches = true
          }


          // -----------------------------------------------
          // SUBJECT
          // -----------------------------------------------

          const subjectMatches =
            subject === 'all' ||
            question.subject === subject


          // -----------------------------------------------
          // BOOK
          // -----------------------------------------------

          const bookMatches =
            bookId === 'all' ||
            question.book_id === bookId


          // -----------------------------------------------
          // DIFFICULTY
          // -----------------------------------------------

          const difficultyMatches =
            difficulty === 'all' ||
            question.difficulty ===
              difficulty


          return (
            examMatches &&
            subjectMatches &&
            bookMatches &&
            difficultyMatches
          )
        }
      )
    }, [
      questions,
      examMode,
      subject,
      bookId,
      difficulty
    ])


  const chapters = useMemo(() => {
    return [
      ...new Set(
        baseFilteredQuestions
          .map(
            (question) =>
              question.chapter
          )
          .filter(Boolean)
      )
    ].sort()
  }, [
    baseFilteredQuestions
  ])


  const chapterFilteredQuestions =
    useMemo(() => {
      if (chapter === 'all') {
        return baseFilteredQuestions
      }

      return baseFilteredQuestions.filter(
        (question) =>
          question.chapter === chapter
      )
    }, [
      baseFilteredQuestions,
      chapter
    ])


  const topics = useMemo(() => {
    return [
      ...new Set(
        chapterFilteredQuestions
          .map(
            (question) =>
              question.topic
          )
          .filter(Boolean)
      )
    ].sort()
  }, [
    chapterFilteredQuestions
  ])


  const finalFilteredQuestions =
    useMemo(() => {

      if (topic === 'all') {
        return chapterFilteredQuestions
      }

      return chapterFilteredQuestions.filter(
        (question) =>
          question.topic === topic
      )

    }, [
      chapterFilteredQuestions,
      topic
    ])


  // =======================================================
  // RESET DEPENDENT FILTERS
  // =======================================================

  useEffect(() => {
    setBookId('all')
    setChapter('all')
    setTopic('all')
  }, [
    subject
  ])


  useEffect(() => {
    setChapter('all')
    setTopic('all')
  }, [
    bookId
  ])


  useEffect(() => {
    setTopic('all')
  }, [
    chapter
  ])


  // =======================================================
  // START SESSION
  // =======================================================

  function startPractice() {
    if (
      finalFilteredQuestions.length === 0
    ) {
      return
    }

    const shuffled = shuffleArray(
      finalFilteredQuestions
    )

    const count = Math.min(
      requestedCount,
      shuffled.length
    )

    setSessionQuestions(
      shuffled.slice(
        0,
        count
      )
    )

    setCurrentIndex(0)
    setAnswers({})
    setSubmittedQuestions({})
    setSavedAttempts({})
    setFlags({})
    setElapsedSeconds(0)

    setSessionFinished(false)
    setSessionStarted(true)

    setError('')
  }


  // =======================================================
  // CURRENT QUESTION
  // =======================================================

  const currentQuestion =
    sessionQuestions[
      currentIndex
    ] || null


  const currentAnswer =
    currentQuestion
      ? answers[
          currentQuestion.id
        ] || null
      : null


  const currentSubmitted =
    currentQuestion
      ? Boolean(
          submittedQuestions[
            currentQuestion.id
          ]
        )
      : false


  const correctOption =
    currentQuestion
      ?.correct_option
      ?.toUpperCase()


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
          ([, text]) =>
            Boolean(text)
        )
      : []


  // =======================================================
  // SELECT ANSWER
  // =======================================================

  function chooseAnswer(letter) {
    if (!currentQuestion) {
      return
    }

    if (
      practiceMode === 'tutor' &&
      currentSubmitted
    ) {
      return
    }

    setAnswers(
      (previous) => ({
        ...previous,
        [currentQuestion.id]:
          letter
      })
    )
  }


  // =======================================================
  // SAVE ONE ATTEMPT
  // =======================================================

  async function saveAttempt(
    question,
    selectedOption
  ) {
    if (
      !question ||
      !selectedOption
    ) {
      return
    }

    if (
      savedAttempts[
        question.id
      ]
    ) {
      return
    }

    const answerIsCorrect =
      selectedOption ===
      question
        .correct_option
        ?.toUpperCase()

    const {
      error: attemptError
    } = await supabase
      .from('attempts')
      .insert({
        user_id:
          session.user.id,

        question_id:
          question.id,

        selected_option:
          selectedOption,

        is_correct:
          answerIsCorrect
      })

    if (attemptError) {
      throw attemptError
    }

    setSavedAttempts(
      (previous) => ({
        ...previous,
        [question.id]: true
      })
    )
  }


  // =======================================================
  // TUTOR MODE SUBMIT
  // =======================================================

  async function submitCurrentAnswer() {
    if (
      !currentQuestion ||
      !currentAnswer ||
      currentSubmitted
    ) {
      return
    }

    setSaving(true)
    setError('')

    try {

      await saveAttempt(
        currentQuestion,
        currentAnswer
      )

      setSubmittedQuestions(
        (previous) => ({
          ...previous,
          [currentQuestion.id]:
            true
        })
      )

    } catch (submitError) {

      console.error(
        submitError
      )

      setError(
        submitError.message ||
        'Could not save your answer.'
      )

    } finally {

      setSaving(false)
    }
  }


  // =======================================================
  // NAVIGATION
  // =======================================================

  function goToQuestion(index) {
    if (
      index < 0 ||
      index >=
        sessionQuestions.length
    ) {
      return
    }

    setCurrentIndex(index)
    setError('')
  }


  function previousQuestion() {
    goToQuestion(
      currentIndex - 1
    )
  }


  function nextQuestion() {
    if (
      currentIndex <
      sessionQuestions.length - 1
    ) {
      goToQuestion(
        currentIndex + 1
      )
    }
  }


  // =======================================================
  // FLAG QUESTION
  // =======================================================

  function toggleFlag() {
    if (!currentQuestion) {
      return
    }

    setFlags(
      (previous) => ({
        ...previous,

        [currentQuestion.id]:
          !previous[
            currentQuestion.id
          ]
      })
    )
  }


  // =======================================================
  // FINISH SESSION
  // =======================================================

  async function finishSession() {
    if (
      sessionQuestions.length === 0
    ) {
      return
    }

    setSaving(true)
    setError('')

    try {

      const unsavedAttempts = []

      sessionQuestions.forEach(
        (question) => {

          const selected =
            answers[
              question.id
            ]

          if (
            selected &&
            !savedAttempts[
              question.id
            ]
          ) {

            unsavedAttempts.push({
              user_id:
                session.user.id,

              question_id:
                question.id,

              selected_option:
                selected,

              is_correct:
                selected ===
                question
                  .correct_option
                  ?.toUpperCase()
            })
          }
        }
      )

      if (
        unsavedAttempts.length > 0
      ) {

        const {
          error: attemptsError
        } = await supabase
          .from('attempts')
          .insert(
            unsavedAttempts
          )

        if (attemptsError) {
          throw attemptsError
        }
      }

      setSessionFinished(true)

    } catch (finishError) {

      console.error(
        finishError
      )

      setError(
        finishError.message ||
        'Could not save the session.'
      )

    } finally {

      setSaving(false)
    }
  }


  // =======================================================
  // SESSION STATS
  // =======================================================

  const sessionStats = useMemo(() => {

    let answered = 0
    let correct = 0
    let incorrect = 0

    sessionQuestions.forEach(
      (question) => {

        const selected =
          answers[
            question.id
          ]

        if (!selected) {
          return
        }

        answered += 1

        if (
          selected ===
          question
            .correct_option
            ?.toUpperCase()
        ) {
          correct += 1
        } else {
          incorrect += 1
        }
      }
    )

    const unanswered =
      sessionQuestions.length -
      answered

    const accuracy =
      answered > 0
        ? Math.round(
            (
              correct /
              answered
            ) * 100
          )
        : 0

    return {
      answered,
      correct,
      incorrect,
      unanswered,
      accuracy
    }

  }, [
    sessionQuestions,
    answers
  ])


  // =======================================================
  // RESTART
  // =======================================================

  function newSession() {
    setSessionStarted(false)
    setSessionFinished(false)
    setSessionQuestions([])
    setAnswers({})
    setSubmittedQuestions({})
    setSavedAttempts({})
    setFlags({})
    setCurrentIndex(0)
    setElapsedSeconds(0)
    setError('')
  }


  async function signOut() {
    await supabase.auth.signOut()
  }


  // =======================================================
  // LOADING
  // =======================================================

  if (loading) {
    return (
      <div className="page-center">
        <div className="loader" />
      </div>
    )
  }


  // =======================================================
  // MAIN SHELL
  // =======================================================

  return (
    <div className="app-shell">

      <aside className="sidebar">

        <Logo />

        <div className="side-nav">

          <button
            onClick={() =>
              navigate(
                '/dashboard'
              )
            }
          >
            <Home size={18} />
            Dashboard
          </button>

          <button
            className="side-active"
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
            onClick={() =>
              navigate(
                '/bookmarks'
              )
            }
          >
            <Bookmark size={18} />
            Bookmarks
          </button>

          <button
            onClick={() =>
              navigate(
                '/library'
              )
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


      <main className="dashboard-main practice-page">


        {/* =================================================
            SETUP SCREEN
        ================================================= */}

        {!sessionStarted && (

          <>

            <header className="dash-head">

              <div>

                <div className="eyebrow">
                  MEDQ PRACTICE
                </div>

                <h1>
                  Build your session
                </h1>

                <p>
                  Practice specifically for AMC,
                  FMGE, or combine both patterns.
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


            <section className="exam-selector">

              <button
                className={
                  examMode === 'amc'
                    ? 'exam-card active'
                    : 'exam-card'
                }
                onClick={() =>
                  setExamMode('amc')
                }
              >

                <span className="exam-flag">
                  🇦🇺
                </span>

                <div>

                  <strong>
                    AMC
                  </strong>

                  <small>
                    Clinical reasoning
                    & next-best-step
                  </small>

                </div>

                {examMode === 'amc' && (
                  <CheckCircle2
                    size={20}
                  />
                )}

              </button>


              <button
                className={
                  examMode === 'fmge'
                    ? 'exam-card active'
                    : 'exam-card'
                }
                onClick={() =>
                  setExamMode('fmge')
                }
              >

                <span className="exam-flag">
                  🇮🇳
                </span>

                <div>

                  <strong>
                    FMGE
                  </strong>

                  <small>
                    High-yield MBBS
                    + clinical application
                  </small>

                </div>

                {examMode === 'fmge' && (
                  <CheckCircle2
                    size={20}
                  />
                )}

              </button>


              <button
                className={
                  examMode === 'mixed'
                    ? 'exam-card active'
                    : 'exam-card'
                }
                onClick={() =>
                  setExamMode('mixed')
                }
              >

                <span className="exam-flag">
                  🔀
                </span>

                <div>

                  <strong>
                    Mixed
                  </strong>

                  <small>
                    AMC + FMGE
                    together
                  </small>

                </div>

                {examMode === 'mixed' && (
                  <CheckCircle2
                    size={20}
                  />
                )}

              </button>

            </section>


            <section className="panel practice-setup-panel">

              <div className="practice-section-title">

                <div>

                  <div className="panel-kicker">
                    SESSION FILTERS
                  </div>

                  <h2>
                    Choose what to practise
                  </h2>

                </div>

                <Filter size={21} />

              </div>


              <div className="practice-filter-grid">


                <div className="practice-field">

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


                <div className="practice-field">

                  <label>
                    Book
                  </label>

                  <select
                    value={bookId}
                    onChange={
                      (event) =>
                        setBookId(
                          event.target.value
                        )
                    }
                  >

                    <option value="all">
                      All books
                    </option>

                    {eligibleBooks.map(
                      (book) => (

                        <option
                          key={book.id}
                          value={book.id}
                        >
                          {book.title}
                        </option>

                      )
                    )}

                  </select>

                </div>


                <div className="practice-field">

                  <label>
                    Chapter
                  </label>

                  <select
                    value={chapter}
                    onChange={
                      (event) =>
                        setChapter(
                          event.target.value
                        )
                    }
                  >

                    <option value="all">
                      All chapters
                    </option>

                    {chapters.map(
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


                <div className="practice-field">

                  <label>
                    Topic
                  </label>

                  <select
                    value={topic}
                    onChange={
                      (event) =>
                        setTopic(
                          event.target.value
                        )
                    }
                  >

                    <option value="all">
                      All topics
                    </option>

                    {topics.map(
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


                <div className="practice-field">

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


                <div className="practice-field">

                  <label>
                    Questions
                  </label>

                  <select
                    value={requestedCount}
                    onChange={
                      (event) =>
                        setRequestedCount(
                          Number(
                            event.target.value
                          )
                        )
                    }
                  >

                    {
                      QUESTION_COUNT_OPTIONS
                        .map(
                          (count) => (

                            <option
                              key={count}
                              value={count}
                            >
                              {count} questions
                            </option>

                          )
                        )
                    }

                  </select>

                </div>


              </div>


              <div className="practice-mode-section">

                <div>

                  <div className="panel-kicker">
                    PRACTICE STYLE
                  </div>

                  <h3>
                    Choose your mode
                  </h3>

                </div>


                <div className="practice-mode-grid">


                  <button
                    className={
                      practiceMode ===
                      'tutor'
                        ? 'practice-mode-card active'
                        : 'practice-mode-card'
                    }
                    onClick={() =>
                      setPracticeMode(
                        'tutor'
                      )
                    }
                  >

                    <Brain size={24} />

                    <div>

                      <strong>
                        Tutor Mode
                      </strong>

                      <span>
                        See the answer and
                        explanation immediately.
                      </span>

                    </div>

                  </button>


                  <button
                    className={
                      practiceMode ===
                      'exam'
                        ? 'practice-mode-card active'
                        : 'practice-mode-card'
                    }
                    onClick={() =>
                      setPracticeMode(
                        'exam'
                      )
                    }
                  >

                    <Timer size={24} />

                    <div>

                      <strong>
                        Exam Mode
                      </strong>

                      <span>
                        Answer the whole session
                        before seeing results.
                      </span>

                    </div>

                  </button>


                </div>

              </div>


              <div className="practice-start-bar">

                <div>

                  <span>
                    Available questions
                  </span>

                  <strong>
                    {
                      finalFilteredQuestions
                        .length
                    }
                  </strong>

                </div>


                <button
                  className="btn btn-primary practice-start-button"
                  disabled={
                    finalFilteredQuestions
                      .length === 0
                  }
                  onClick={
                    startPractice
                  }
                >

                  <Play size={19} />

                  Start Practice

                </button>

              </div>

            </section>

          </>

        )}


        {/* =================================================
            ACTIVE SESSION
        ================================================= */}

        {
          sessionStarted &&
          !sessionFinished &&
          currentQuestion &&
          (

            <div className="mcq-workspace">


              {/* ==========================================
                  SESSION HEADER
              ========================================== */}

              <section className="mcq-session-header">

                <div className="mcq-session-title">

                  <button
                    className="icon-button"
                    onClick={
                      newSession
                    }
                    title="Exit session"
                  >
                    <ArrowLeft size={19} />
                  </button>

                  <div>

                    <span>
                      {
                        examMode === 'amc'
                          ? 'AMC Practice'
                          : examMode === 'fmge'
                            ? 'FMGE Practice'
                            : 'Mixed Practice'
                      }
                    </span>

                    <strong>
                      Question {
                        currentIndex + 1
                      } of {
                        sessionQuestions.length
                      }
                    </strong>

                  </div>

                </div>


                <div className="mcq-header-stats">

                  <div>

                    <Clock3 size={17} />

                    <span>
                      {
                        formatTime(
                          elapsedSeconds
                        )
                      }
                    </span>

                  </div>

                  <div>

                    <Target size={17} />

                    <span>
                      {
                        sessionStats
                          .answered
                      } answered
                    </span>

                  </div>

                </div>

              </section>


              <div className="mcq-progress-track">

                <div
                  style={{
                    width:
                      `${
                        (
                          (
                            currentIndex + 1
                          ) /
                          sessionQuestions
                            .length
                        ) * 100
                      }%`
                  }}
                />

              </div>


              <div className="mcq-layout">


                {/* ========================================
                    QUESTION
                ======================================== */}

                <section className="mcq-main">


                  <div className="mcq-question-card">


                    <div className="mcq-question-meta">

                      <div className="question-tags">

                        <span className="exam-question-tag">

                          {
                            normalizeExamType(
                              currentQuestion
                                .exam_type
                            )
                          }

                        </span>


                        {
                          currentQuestion
                            .subject &&
                          (

                            <span>
                              {
                                currentQuestion
                                  .subject
                              }
                            </span>

                          )
                        }


                        {
                          currentQuestion
                            .difficulty &&
                          (

                            <span>
                              {
                                currentQuestion
                                  .difficulty
                              }
                            </span>

                          )
                        }


                        {
                          currentQuestion
                            .question_type &&
                          (

                            <span>
                              {
                                currentQuestion
                                  .question_type
                              }
                            </span>

                          )
                        }

                      </div>


                      <button
                        className={
                          flags[
                            currentQuestion.id
                          ]
                            ? 'question-action active'
                            : 'question-action'
                        }
                        onClick={
                          toggleFlag
                        }
                      >

                        <Flag size={18} />

                        {
                          flags[
                            currentQuestion.id
                          ]
                            ? 'Flagged'
                            : 'Flag'
                        }

                      </button>

                    </div>


                    <div className="mcq-source-line">

                      {
                        currentQuestion
                          .chapter &&
                        (
                          <span>
                            {
                              currentQuestion
                                .chapter
                            }
                          </span>
                        )
                      }

                      {
                        currentQuestion
                          .topic &&
                        (
                          <>
                            <ChevronRight
                              size={14}
                            />

                            <span>
                              {
                                currentQuestion
                                  .topic
                              }
                            </span>
                          </>
                        )
                      }

                    </div>


                    <h2 className="professional-question-stem">

                      {
                        currentQuestion
                          .stem
                      }

                    </h2>


                    <div className="professional-options">

                      {
                        options.map(
                          (
                            [
                              letter,
                              text
                            ]
                          ) => {

                            const selected =
                              currentAnswer ===
                              letter

                            const isCorrectOption =
                              currentSubmitted &&
                              letter ===
                                correctOption

                            const isWrongSelected =
                              currentSubmitted &&
                              selected &&
                              letter !==
                                correctOption

                            return (

                              <button
                                key={letter}
                                className={[
                                  'professional-option',

                                  selected
                                    ? 'selected'
                                    : '',

                                  isCorrectOption
                                    ? 'correct'
                                    : '',

                                  isWrongSelected
                                    ? 'wrong'
                                    : ''
                                ].join(' ')}
                                onClick={() =>
                                  chooseAnswer(
                                    letter
                                  )
                                }
                              >

                                <span className="professional-option-letter">
                                  {letter}
                                </span>

                                <span className="professional-option-text">
                                  {text}
                                </span>


                                {
                                  isCorrectOption &&
                                  (
                                    <CheckCircle2
                                      size={21}
                                    />
                                  )
                                }


                                {
                                  isWrongSelected &&
                                  (
                                    <XCircle
                                      size={21}
                                    />
                                  )
                                }

                              </button>

                            )
                          }
                        )
                      }

                    </div>


                    {/* ====================================
                        TUTOR SUBMIT
                    ==================================== */}

                    {
                      practiceMode ===
                        'tutor' &&
                      !currentSubmitted &&
                      (

                        <button
                          className="btn btn-primary mcq-submit-button"
                          disabled={
                            !currentAnswer ||
                            saving
                          }
                          onClick={
                            submitCurrentAnswer
                          }
                        >

                          {
                            saving
                              ? 'Saving...'
                              : 'Submit answer'
                          }

                        </button>

                      )
                    }


                    {/* ====================================
                        TUTOR RESULT
                    ==================================== */}

                    {
                      practiceMode ===
                        'tutor' &&
                      currentSubmitted &&
                      (

                        <div className="tutor-result">


                          <div
                            className={
                              currentAnswer ===
                              correctOption
                                ? 'answer-status success'
                                : 'answer-status error'
                            }
                          >

                            {
                              currentAnswer ===
                              correctOption
                                ? (
                                  <>
                                    <CheckCircle2
                                      size={22}
                                    />

                                    Correct
                                  </>
                                )
                                : (
                                  <>
                                    <XCircle
                                      size={22}
                                    />

                                    Incorrect

                                    <span>
                                      Correct answer:
                                      {' '}
                                      {
                                        correctOption
                                      }
                                    </span>
                                  </>
                                )
                            }

                          </div>


                          {
                            currentQuestion
                              .explanation &&
                            (

                              <div className="professional-explanation">

                                <div className="explanation-heading">

                                  <Brain size={20} />

                                  <div>

                                    <span>
                                      EXPLANATION
                                    </span>

                                    <strong>
                                      Why this is
                                      the best answer
                                    </strong>

                                  </div>

                                </div>

                                <p>
                                  {
                                    currentQuestion
                                      .explanation
                                  }
                                </p>

                              </div>

                            )
                          }


                          <div className="question-source-card">

                            <BookOpen
                              size={19}
                            />

                            <div>

                              <span>
                                SOURCE
                              </span>

                              <strong>

                                {
                                  currentQuestion
                                    .book_id &&
                                  bookMap[
                                    currentQuestion
                                      .book_id
                                  ]
                                    ? bookMap[
                                        currentQuestion
                                          .book_id
                                      ].title

                                    : 'Uploaded textbook'
                                }

                              </strong>


                              {
                                currentQuestion
                                  .source_page &&
                                (

                                  <small>

                                    Page {
                                      currentQuestion
                                        .source_page
                                    }

                                    {
                                      currentQuestion
                                        .source_page_end &&
                                      currentQuestion
                                        .source_page_end !==
                                        currentQuestion
                                          .source_page
                                        ? `–${
                                            currentQuestion
                                              .source_page_end
                                          }`
                                        : ''
                                    }

                                  </small>

                                )
                              }

                            </div>

                          </div>


                          <button
                            className="ask-medbot-button"
                            disabled={
                              bookmarkSavingId ===
                              currentQuestion.id
                            }
                            onClick={() =>
                              toggleBookmark(
                                currentQuestion
                              )
                            }
                          >

                            <Bookmark
                              size={19}
                              fill={
                                bookmarkedQuestionIds[
                                  currentQuestion.id
                                ]
                                  ? 'currentColor'
                                  : 'none'
                              }
                            />

                            {
                              bookmarkSavingId ===
                              currentQuestion.id
                                ? 'Saving...'
                                : bookmarkedQuestionIds[
                                    currentQuestion.id
                                  ]
                                  ? 'Remove Bookmark'
                                  : 'Save Bookmark'
                            }

                          </button>


                          <button
                            className="ask-medbot-button"
                            onClick={() =>
                              navigate(
                                `/medbot?question=${encodeURIComponent(
                                  currentQuestion.id
                                )}`
                              )
                            }
                          >

                            <Sparkles
                              size={19}
                            />

                            Ask MedBot about
                            this question

                          </button>

                        </div>

                      )
                    }


                  </div>


                  {/* ====================================
                      BOTTOM NAV
                  ==================================== */}

                  <div className="mcq-navigation">

                    <button
                      className="btn btn-outline"
                      disabled={
                        currentIndex === 0
                      }
                      onClick={
                        previousQuestion
                      }
                    >

                      <ChevronLeft
                        size={18}
                      />

                      Previous

                    </button>


                    {
                      currentIndex ===
                      sessionQuestions.length - 1
                        ? (

                          <button
                            className="btn btn-primary"
                            disabled={
                              saving
                            }
                            onClick={
                              finishSession
                            }
                          >

                            <Check
                              size={18}
                            />

                            Finish Session

                          </button>

                        )
                        : (

                          <button
                            className="btn btn-primary"
                            onClick={
                              nextQuestion
                            }
                          >

                            Next

                            <ChevronRight
                              size={18}
                            />

                          </button>

                        )
                    }

                  </div>


                  {
                    error &&
                    (

                      <div className="practice-error">

                        <AlertCircle
                          size={18}
                        />

                        {error}

                      </div>

                    )
                  }


                </section>


                {/* ========================================
                    QUESTION NAVIGATOR
                ======================================== */}

                <aside className="question-navigator">

                  <div className="navigator-head">

                    <div>

                      <span>
                        SESSION
                      </span>

                      <strong>
                        Question Navigator
                      </strong>

                    </div>

                    <BarChart3
                      size={20}
                    />

                  </div>


                  <div className="navigator-stats">

                    <div>

                      <strong>
                        {
                          sessionStats
                            .answered
                        }
                      </strong>

                      <span>
                        Answered
                      </span>

                    </div>

                    <div>

                      <strong>
                        {
                          sessionStats
                            .unanswered
                        }
                      </strong>

                      <span>
                        Remaining
                      </span>

                    </div>

                  </div>


                  <div className="question-number-grid">

                    {
                      sessionQuestions.map(
                        (
                          question,
                          index
                        ) => {

                          const answered =
                            Boolean(
                              answers[
                                question.id
                              ]
                            )

                          const flagged =
                            Boolean(
                              flags[
                                question.id
                              ]
                            )

                          const submitted =
                            Boolean(
                              submittedQuestions[
                                question.id
                              ]
                            )

                          return (

                            <button
                              key={
                                question.id
                              }
                              className={[
                                'question-number',

                                index ===
                                currentIndex
                                  ? 'current'
                                  : '',

                                answered
                                  ? 'answered'
                                  : '',

                                flagged
                                  ? 'flagged'
                                  : '',

                                submitted
                                  ? 'submitted'
                                  : ''
                              ].join(' ')}
                              onClick={() =>
                                goToQuestion(
                                  index
                                )
                              }
                            >

                              {index + 1}

                              {
                                flagged &&
                                (
                                  <i />
                                )
                              }

                            </button>

                          )
                        }
                      )
                    }

                  </div>


                  <div className="navigator-legend">

                    <span>
                      <i className="legend-current" />
                      Current
                    </span>

                    <span>
                      <i className="legend-answered" />
                      Answered
                    </span>

                    <span>
                      <i className="legend-flagged" />
                      Flagged
                    </span>

                  </div>


                  <button
                    className="finish-session-button"
                    onClick={
                      finishSession
                    }
                    disabled={
                      saving
                    }
                  >

                    Finish session

                  </button>

                </aside>


              </div>

            </div>

          )
        }


        {/* =================================================
            RESULT SCREEN
        ================================================= */}

        {
          sessionStarted &&
          sessionFinished &&
          (

            <section className="results-screen">


              <div className="results-hero">

                <div className="result-icon">

                  {
                    sessionStats
                      .accuracy >= 70
                      ? (
                        <CheckCircle2
                          size={36}
                        />
                      )
                      : (
                        <Target
                          size={36}
                        />
                      )
                  }

                </div>


                <div className="eyebrow">
                  SESSION COMPLETE
                </div>


                <h1>
                  {
                    sessionStats
                      .accuracy
                  }%
                </h1>


                <h2>
                  {
                    sessionStats
                      .accuracy >= 80
                      ? 'Excellent session'
                      : sessionStats
                          .accuracy >= 60
                        ? 'Good progress'
                        : 'Keep building'
                  }
                </h2>


                <p>
                  You completed {
                    sessionQuestions.length
                  } questions in {
                    formatTime(
                      elapsedSeconds
                    )
                  }.
                </p>

              </div>


              <div className="result-stat-grid">


                <div className="result-stat">

                  <span>
                    SCORE
                  </span>

                  <strong>
                    {
                      sessionStats
                        .correct
                    } / {
                      sessionQuestions
                        .length
                    }
                  </strong>

                </div>


                <div className="result-stat correct">

                  <span>
                    CORRECT
                  </span>

                  <strong>
                    {
                      sessionStats
                        .correct
                    }
                  </strong>

                </div>


                <div className="result-stat wrong">

                  <span>
                    INCORRECT
                  </span>

                  <strong>
                    {
                      sessionStats
                        .incorrect
                    }
                  </strong>

                </div>


                <div className="result-stat">

                  <span>
                    UNANSWERED
                  </span>

                  <strong>
                    {
                      sessionStats
                        .unanswered
                    }
                  </strong>

                </div>


                <div className="result-stat">

                  <span>
                    ACCURACY
                  </span>

                  <strong>
                    {
                      sessionStats
                        .accuracy
                    }%
                  </strong>

                </div>


                <div className="result-stat">

                  <span>
                    TIME
                  </span>

                  <strong>
                    {
                      formatTime(
                        elapsedSeconds
                      )
                    }
                  </strong>

                </div>


              </div>


              <section className="panel result-review-panel">

                <div className="practice-section-title">

                  <div>

                    <div className="panel-kicker">
                      QUESTION REVIEW
                    </div>

                    <h2>
                      Review your session
                    </h2>

                  </div>

                </div>


                <div className="result-question-list">

                  {
                    sessionQuestions.map(
                      (
                        question,
                        index
                      ) => {

                        const selected =
                          answers[
                            question.id
                          ]

                        const correct =
                          selected &&
                          selected ===
                          question
                            .correct_option
                            ?.toUpperCase()

                        return (

                          <button
                            key={
                              question.id
                            }
                            className="result-question-row"
                            onClick={() => {

                              setSessionFinished(
                                false
                              )

                              setPracticeMode(
                                'tutor'
                              )

                              setSubmittedQuestions(
                                (previous) => ({
                                  ...previous,
                                  [question.id]:
                                    true
                                })
                              )

                              setCurrentIndex(
                                index
                              )

                            }}
                          >

                            <span className="result-question-number">
                              {index + 1}
                            </span>


                            <div>

                              <strong>

                                {
                                  question.stem
                                    .length > 95
                                    ? `${
                                        question.stem.slice(
                                          0,
                                          95
                                        )
                                      }...`
                                    : question.stem
                                }

                              </strong>

                              <small>

                                {
                                  selected
                                    ? `Your answer: ${selected}`
                                    : 'Unanswered'
                                }

                              </small>

                            </div>


                            {
                              !selected
                                ? (
                                  <AlertCircle
                                    size={20}
                                  />
                                )
                                : correct
                                  ? (
                                    <CheckCircle2
                                      size={20}
                                    />
                                  )
                                  : (
                                    <XCircle
                                      size={20}
                                    />
                                  )
                            }

                          </button>

                        )
                      }
                    )
                  }

                </div>

              </section>


              <div className="results-actions">

                <button
                  className="btn btn-outline"
                  onClick={() =>
                    navigate(
                      '/dashboard'
                    )
                  }
                >

                  <Home size={18} />

                  Dashboard

                </button>


                <button
                  className="btn btn-primary"
                  onClick={
                    newSession
                  }
                >

                  <RotateCcw
                    size={18}
                  />

                  New Practice Session

                </button>

              </div>


            </section>

          )
        }


      </main>

    </div>
  )
}
