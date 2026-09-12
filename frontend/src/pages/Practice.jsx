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
  History as HistoryIcon,
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

const API_URL =
  import.meta.env.VITE_API_URL ||
  'https://medq-api-6vm5.onrender.com'


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



function cleanFilterLabel(value, kind = 'topic') {
  const label = String(value || '').replace(/\s+/g, ' ').trim()

  if (!label) return null
  if (label.length < 3 || label.length > 110) return null

  const lower = label.toLowerCase()

  const exactJunk = new Set([
    'preface',
    'foreword',
    'contents',
    'table of contents',
    'contributors',
    'acknowledgments',
    'acknowledgements',
    'copyright',
    'index',
    'part 1',
    'part i'
  ])

  if (exactJunk.has(lower)) return null

  // Common extraction artefacts such as e42, e46, e49, etc.
  if (/^e\d+[a-z]?$/i.test(label)) return null
  if (/^(part|section|chapter)\s*[ivxlcdm\d]+$/i.test(label)) return null
  if (/^part\s+[ivxlcdm\d]+\s*[:.\-–—]/i.test(label)) return null
  if (/^\d+(\.\d+)*$/.test(label)) return null

  const genericLabels = new Set([
    'medicine',
    'surgery',
    'gastroenterology',
    'clinical medicine',
    'general medicine',
    'general'
  ])
  if (genericLabels.has(lower)) return null

  // Non-clinical front/back matter and media/atlas artefacts.
  const junkPhrases = [
    'video library',
    'atlas of',
    'about the author',
    'about the editor',
    'editorial board',
    'list of contributors',
    'list of authors',
    'permissions',
    'disclaimer',
    'dedication',
    'abbreviations',
    'appendix',
    'bibliography'
  ]

  if (junkPhrases.some((phrase) => lower.includes(phrase))) return null

  // Topics should be concise clinical labels rather than extracted sentences.
  if (kind === 'topic') {
    const words = label.split(' ').filter(Boolean)
    if (words.length > 12) return null
    if (/[?!]$/.test(label)) return null
  }

  return label
}

function uniqueCleanLabels(values, kind) {
  const seen = new Map()

  values.forEach((value) => {
    const cleaned = cleanFilterLabel(value, kind)
    if (!cleaned) return

    const key = cleaned.toLowerCase()
    if (!seen.has(key)) {
      seen.set(key, cleaned)
    }
  })

  return [...seen.values()].sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: 'base' })
  )
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
    bookChunks,
    setBookChunks
  ] = useState([])

  const [
    generatingQuestions,
    setGeneratingQuestions
  ] = useState(false)

  const [
    generationMessage,
    setGenerationMessage
  ] = useState('')

  const [
    generationCount,
    setGenerationCount
  ] = useState(20)

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
    practiceSessionId,
    setPracticeSessionId
  ] = useState(null)

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

    try {
      // Load the essential Practice data first so the page never waits
      // for the much larger textbook chapter catalogue.
      const [
        questionResponse,
        bookResponse
      ] = await Promise.all([
        supabase
          .from('questions')
          .select('*')
          .order(
            'created_at',
            { ascending: false }
          ),

        supabase
          .from('books')
          .select('id,title,subject,status')
          .order(
            'created_at',
            { ascending: false }
          )
      ])

      if (questionResponse.error) {
        throw questionResponse.error
      }

      setQuestions(
        questionResponse.data || []
      )

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

    } catch (loadError) {
      console.error(
        'Practice load error:',
        loadError
      )

      setQuestions([])
      setError(
        loadError?.message ||
        'Could not load the Practice question bank.'
      )

    } finally {
      // Never leave the whole Practice page stuck behind a spinner.
      setLoading(false)
    }

    // Chapter catalogue is secondary. Load it after Practice is usable.
    loadChapterCatalogue()
  }


  async function loadChapterCatalogue() {
    try {
      const { data, error: chunkError } =
        await supabase
          .from('book_chunks')
          .select('book_id,chapter,chunk_index')
          .not('chapter', 'is', null)
          .range(0, 9999)

      if (chunkError) {
        throw chunkError
      }

      setBookChunks(
        data || []
      )

    } catch (chunkError) {
      console.error(
        'Chapter catalogue load error:',
        chunkError
      )

      // Existing question chapters remain available as the fallback.
      setBookChunks([])
    }
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
    // Professional hierarchy: chapters only belong to one selected book.
    // Never mix Harrison, Gastroenterology, etc. in the same chapter menu.
    if (bookId === 'all') {
      return []
    }

    const firstChunkByChapter = new Map()

    bookChunks
      .filter((chunk) => chunk.book_id === bookId)
      .forEach((chunk) => {
        const cleaned = cleanFilterLabel(
          chunk.chapter,
          'chapter'
        )

        if (!cleaned) return

        const key = cleaned.toLowerCase()
        const index = Number(chunk.chunk_index) || 0

        if (
          !firstChunkByChapter.has(key) ||
          index < firstChunkByChapter.get(key).index
        ) {
          firstChunkByChapter.set(key, {
            label: cleaned,
            index
          })
        }
      })

    // Fallback for old/small books whose chunks do not yet have clean chapters.
    baseFilteredQuestions
      .filter((question) => question.book_id === bookId)
      .forEach((question) => {
        const cleaned = cleanFilterLabel(
          question.chapter,
          'chapter'
        )

        if (!cleaned) return

        const key = cleaned.toLowerCase()
        if (!firstChunkByChapter.has(key)) {
          firstChunkByChapter.set(key, {
            label: cleaned,
            index: 999999
          })
        }
      })

    return [...firstChunkByChapter.values()]
      .sort((a, b) => {
        if (a.index !== b.index) {
          return a.index - b.index
        }
        return a.label.localeCompare(b.label)
      })
      .map((item) => item.label)
  }, [
    bookChunks,
    bookId,
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
    if (
      bookId === 'all' ||
      chapter === 'all'
    ) {
      return []
    }

    return uniqueCleanLabels(
      chapterFilteredQuestions
        .filter((question) => question.book_id === bookId)
        .map((question) => question.topic),
      'topic'
    )
  }, [
    bookId,
    chapter,
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

  useEffect(() => {
    if (
      chapter !== 'all' &&
      !chapters.includes(chapter)
    ) {
      setChapter('all')
    }
  }, [
    chapter,
    chapters
  ])


  useEffect(() => {
    if (
      topic !== 'all' &&
      !topics.includes(topic)
    ) {
      setTopic('all')
    }
  }, [
    topic,
    topics
  ])



  function questionCountForChapter(chapterName) {
    return questions.filter((question) => {
      const examMatches =
        examMode === 'mixed' ||
        question.exam_type === examMode ||
        question.exam_type === 'both'

      const bookMatches =
        bookId === 'all' ||
        question.book_id === bookId

      const subjectMatches =
        subject === 'all' ||
        question.subject === subject

      return (
        examMatches &&
        bookMatches &&
        subjectMatches &&
        question.chapter === chapterName
      )
    }).length
  }


  async function generateQuestionsForChapter() {
    if (bookId === 'all' || chapter === 'all') {
      setGenerationMessage(
        'Choose one book and one chapter first.'
      )
      return
    }

    setGeneratingQuestions(true)
    setGenerationMessage('')
    setError('')

    try {
      const response = await fetch(
        `${API_URL}/api/questions/generate`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization:
              `Bearer ${session.access_token}`
          },
          body: JSON.stringify({
            book_id: bookId,
            chapter,
            exam_mode: examMode,
            count: generationCount
          })
        }
      )

      const data = await response.json().catch(() => ({}))

      if (!response.ok) {
        throw new Error(
          data?.detail ||
          'Could not start question generation.'
        )
      }

      setGenerationMessage(
        `Generation started for ${generationCount} ${examMode.toUpperCase()} question${generationCount === 1 ? '' : 's'}. MedQ will add them when the worker finishes.`
      )

      // Poll the question bank while the GitHub worker runs.
      let checks = 0
      const startingCount = questionCountForChapter(chapter)

      const timer = window.setInterval(async () => {
        checks += 1

        const { data: freshQuestions } = await supabase
          .from('questions')
          .select('*')
          .eq('book_id', bookId)
          .eq('chapter', chapter)
          .order('created_at', { ascending: false })

        if (Array.isArray(freshQuestions)) {
          setQuestions((current) => {
            const other = current.filter(
              (item) => !(
                item.book_id === bookId &&
                item.chapter === chapter
              )
            )
            return [...freshQuestions, ...other]
          })

          if (freshQuestions.length > startingCount) {
            window.clearInterval(timer)
            setGeneratingQuestions(false)
            setGenerationMessage(
              `${freshQuestions.length - startingCount} new question${freshQuestions.length - startingCount === 1 ? '' : 's'} added. You can start practising now.`
            )
          }
        }

        // Stop browser polling after 10 minutes. The worker may still finish later.
        if (checks >= 40) {
          window.clearInterval(timer)
          setGeneratingQuestions(false)
          setGenerationMessage(
            'Generation is still running or the AI provider is busy. The questions will appear automatically after the worker succeeds.'
          )
        }
      }, 15000)

    } catch (generationError) {
      setGeneratingQuestions(false)
      setGenerationMessage('')
      setError(
        generationError?.message ||
        'Could not start question generation.'
      )
    }
  }


  // =======================================================
  // START SESSION
  // =======================================================

  async function startPractice() {
    if (finalFilteredQuestions.length === 0) {
      return
    }

    setSaving(true)
    setError('')

    try {
      const shuffled = shuffleArray(finalFilteredQuestions)
      const count = Math.min(requestedCount, shuffled.length)
      const selectedQuestions = shuffled.slice(0, count)

      const {
        data: createdSession,
        error: sessionError
      } = await supabase
        .from('practice_sessions')
        .insert({
          user_id: session.user.id,
          exam_mode: examMode,
          practice_mode: practiceMode,
          subject: subject === 'all' ? null : subject,
          book_id: bookId === 'all' ? null : bookId,
          chapter: chapter === 'all' ? null : chapter,
          topic: topic === 'all' ? null : topic,
          difficulty: difficulty === 'all' ? null : difficulty,
          requested_count: requestedCount,
          question_count: selectedQuestions.length
        })
        .select('id')
        .single()

      if (sessionError) {
        throw sessionError
      }

      setPracticeSessionId(createdSession.id)
      setSessionQuestions(selectedQuestions)
      setCurrentIndex(0)
      setAnswers({})
      setSubmittedQuestions({})
      setSavedAttempts({})
      setFlags({})
      setElapsedSeconds(0)
      setSessionFinished(false)
      setSessionStarted(true)

    } catch (startError) {
      console.error(startError)
      setError(
        startError.message ||
        'Could not start the practice session.'
      )
    } finally {
      setSaving(false)
    }
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
          answerIsCorrect,

        session_id:
          practiceSessionId
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
                  ?.toUpperCase(),

              session_id:
                practiceSessionId
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

      if (practiceSessionId) {
        const {
          error: sessionUpdateError
        } = await supabase
          .from('practice_sessions')
          .update({
            answered_count: sessionStats.answered,
            correct_count: sessionStats.correct,
            incorrect_count: sessionStats.incorrect,
            unanswered_count: sessionStats.unanswered,
            accuracy: sessionStats.accuracy,
            duration_seconds: elapsedSeconds,
            finished_at: new Date().toISOString()
          })
          .eq('id', practiceSessionId)
          .eq('user_id', session.user.id)

        if (sessionUpdateError) {
          throw sessionUpdateError
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
    setPracticeSessionId(null)
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
                '/history'
              )
            }
          >
            <HistoryIcon size={18} />
            History
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
                          {item} ({questionCountForChapter(item)})
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


              {bookId !== 'all' && chapter !== 'all' && (
                <div
                  className="panel"
                  style={{
                    marginTop: '18px',
                    padding: '16px',
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: '12px',
                    alignItems: 'center',
                    justifyContent: 'space-between'
                  }}
                >
                  <div>
                    <div className="panel-kicker">
                      BUILD THIS CHAPTER
                    </div>
                    <strong>
                      Need more questions from {chapter}?
                    </strong>
                    <small style={{ display: 'block', marginTop: '4px' }}>
                      MedQ uses this chapter's processed textbook chunks and avoids existing question stems.
                    </small>
                  </div>

                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: '8px',
                      alignItems: 'center'
                    }}
                  >
                    <select
                      value={generationCount}
                      onChange={(event) =>
                        setGenerationCount(Number(event.target.value))
                      }
                      disabled={generatingQuestions}
                    >
                      <option value={10}>Generate 10</option>
                      <option value={20}>Generate 20</option>
                      <option value={50}>Generate 50</option>
                    </select>

                    <button
                      className="btn"
                      type="button"
                      disabled={generatingQuestions}
                      onClick={generateQuestionsForChapter}
                    >
                      {generatingQuestions
                        ? 'Generating…'
                        : `Generate ${generationCount}`}
                    </button>
                  </div>
                </div>
              )}

              {generationMessage && (
                <div
                  className="panel"
                  style={{
                    marginTop: '12px',
                    padding: '12px 16px'
                  }}
                >
                  <small>{generationMessage}</small>
                </div>
              )}

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
                              window.dispatchEvent(
                                new CustomEvent(
                                  'medq:open-medbot',
                                  {
                                    detail: {
                                      questionId: currentQuestion.id
                                    }
                                  }
                                )
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
