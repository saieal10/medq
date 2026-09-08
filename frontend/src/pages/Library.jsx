import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bookmark,
  BookOpen,
  History as HistoryIcon,
  Brain,
  CheckCircle2,
  FileText,
  Loader2,
  LogOut,
  RotateCcw,
  Target,
  Upload,
  XCircle
} from 'lucide-react'
import { supabase } from '../lib/supabase'
import Logo from '../components/Logo'

const API_URL = import.meta.env.VITE_API_URL

// Only this account can upload books.
// Both MedQ users can see and use the shared library.
const ADMIN_EMAILS = [
  'saiealnaik17@gmail.com'
]

export default function Library({ session }) {
  const navigate = useNavigate()

  const [books, setBooks] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [file, setFile] = useState(null)
  const [title, setTitle] = useState('')
  const [subject, setSubject] = useState('Medicine')

  const [uploading, setUploading] = useState(false)
  const [uploadStage, setUploadStage] = useState('')
  const [success, setSuccess] = useState('')

  const isAdmin = useMemo(() => {
    const email = session?.user?.email?.toLowerCase()

    return ADMIN_EMAILS
      .map((item) => item.toLowerCase())
      .includes(email)
  }, [session])

  useEffect(() => {
    loadBooks()
  }, [])

  useEffect(() => {
    const hasActiveBook = books.some((book) => {
      const stage = (
        book.processing_stage ||
        book.status ||
        ''
      ).toLowerCase()

      return ![
        'ready',
        'failed'
      ].includes(stage)
    })

    if (!hasActiveBook) {
      return undefined
    }

    const timer = window.setInterval(() => {
      loadBooks({ silent: true })
    }, 10000)

    return () => {
      window.clearInterval(timer)
    }
  }, [books])

  async function loadBooks({ silent = false } = {}) {
    if (!silent) {
      setLoading(true)
    }

    setError('')

    try {
      const {
        data,
        error: booksError
      } = await supabase
        .from('books')
        .select(`
          id,
          title,
          subject,
          file_size_bytes,
          status,
          processing_stage,
          extraction_progress,
          question_progress,
          questions_generated,
          processed_pages,
          total_pages,
          page_count,
          error_message,
          created_at
        `)
        .order('created_at', { ascending: false })

      if (booksError) {
        throw booksError
      }

      setBooks(data || [])

    } catch (err) {
      setError(
        err.message ||
        'Unable to load the MedQ library.'
      )

    } finally {
      if (!silent) {
        setLoading(false)
      }
    }
  }

  function chooseFile(event) {
    const selected = event.target.files?.[0]

    setError('')
    setSuccess('')

    if (!selected) {
      setFile(null)
      return
    }

    const isPdf =
      selected.type === 'application/pdf' ||
      selected.name.toLowerCase().endsWith('.pdf')

    if (!isPdf) {
      setError('Please select a PDF file.')
      event.target.value = ''
      setFile(null)
      return
    }

    setFile(selected)

    if (!title.trim()) {
      const cleanTitle = selected.name
        .replace(/\.pdf$/i, '')
        .replace(/[-_]+/g, ' ')

      setTitle(cleanTitle)
    }
  }

  async function uploadBook(event) {
    event.preventDefault()

    if (!isAdmin) {
      setError('Only the MedQ administrator can upload books.')
      return
    }

    if (!file) {
      setError('Choose a PDF first.')
      return
    }

    if (!title.trim()) {
      setError('Enter a title for the book.')
      return
    }

    if (!API_URL) {
      setError('MedQ backend URL is not configured.')
      return
    }

    setUploading(true)
    setError('')
    setSuccess('')

    try {
      // ---------------------------------------------------
      // 1. Ask MedQ backend for a secure R2 upload URL
      // ---------------------------------------------------

      setUploadStage('Preparing secure upload…')

      const uploadUrlResponse = await fetch(
        `${API_URL}/api/books/upload-url`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            filename: file.name,
            content_type: 'application/pdf'
          })
        }
      )

      const uploadUrlResult =
        await uploadUrlResponse.json().catch(() => ({}))

      if (!uploadUrlResponse.ok) {
        throw new Error(
          uploadUrlResult.detail ||
          'Could not prepare the PDF upload.'
        )
      }

      const {
        upload_url,
        file_key
      } = uploadUrlResult

      // ---------------------------------------------------
      // 2. Upload PDF directly from browser to Cloudflare R2
      // ---------------------------------------------------

      setUploadStage(
        `Uploading ${formatBytes(file.size)} PDF to MedQ storage…`
      )

      const r2Response = await fetch(
        upload_url,
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/pdf'
          },
          body: file
        }
      )

      if (!r2Response.ok) {
        throw new Error(
          'The PDF could not be uploaded to Cloudflare R2.'
        )
      }

      // ---------------------------------------------------
      // 3. Register the shared book in Supabase
      // ---------------------------------------------------

      setUploadStage('Registering book in MedQ…')

      const registerResponse = await fetch(
        `${API_URL}/api/books/register`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            title: title.trim(),
            subject: subject || null,
            file_key,
            file_size_bytes: file.size,
            uploaded_by: session.user.id
          })
        }
      )

      const registerResult =
        await registerResponse.json().catch(() => ({}))

      if (!registerResponse.ok) {
        throw new Error(
          registerResult.detail ||
          'PDF uploaded, but MedQ could not register the book.'
        )
      }

      // ---------------------------------------------------
      // 4. Mark it for processing
      // ---------------------------------------------------

      const book = registerResult.book

      setUploadStage('Starting textbook extraction and knowledge-base processing…')

      const processResponse = await fetch(
        `${API_URL}/api/books/${book.id}/process`,
        {
          method: 'POST'
        }
      )

      if (!processResponse.ok) {
        console.warn(
          'Book uploaded but processing status could not be started.'
        )
      }

      setSuccess(
        'PDF uploaded successfully. MedQ is now extracting the textbook and building its knowledge base.'
      )

      setUploadStage('')
      setFile(null)
      setTitle('')

      const fileInput =
        document.getElementById('medq-pdf-input')

      if (fileInput) {
        fileInput.value = ''
      }

      await loadBooks()

    } catch (err) {
      setError(err.message)
      setUploadStage('')
    } finally {
      setUploading(false)
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
            onClick={() => navigate('/history')}
          >
            <HistoryIcon size={18} />
            History
          </button>

          <button className="side-active">
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
              SHARED MEDQ LIBRARY
            </div>

            <h1>
              Medical Library
            </h1>

            <p>
              One shared collection of books for both MedQ users.
            </p>
          </div>

          <div className="user-chip">
            {session.user.email}
          </div>

        </header>

        {isAdmin && (

          <section className="panel">

            <div className="panel-kicker">
              ADMIN UPLOAD
            </div>

            <h2>
              Add a medical PDF
            </h2>

            <p>
              Upload the PDF once. MedQ stores it securely and the
              processing system will convert its content into practice
              material automatically.
            </p>

            <form
              onSubmit={uploadBook}
              style={{
                display: 'grid',
                gap: '16px',
                marginTop: '24px'
              }}
            >

              <div>
                <label
                  style={{
                    display: 'block',
                    marginBottom: '7px'
                  }}
                >
                  PDF
                </label>

                <input
                  id="medq-pdf-input"
                  type="file"
                  accept="application/pdf,.pdf"
                  onChange={chooseFile}
                  disabled={uploading}
                />
              </div>

              {file && (

                <div
                  className="panel"
                  style={{
                    padding: '16px'
                  }}
                >

                  <FileText size={22} />

                  <strong
                    style={{
                      display: 'block',
                      marginTop: '8px'
                    }}
                  >
                    {file.name}
                  </strong>

                  <small>
                    {formatBytes(file.size)}
                  </small>

                </div>

              )}

              <div>

                <label
                  style={{
                    display: 'block',
                    marginBottom: '7px'
                  }}
                >
                  Book title
                </label>

                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. John Murtagh General Practice"
                  disabled={uploading}
                  style={{
                    width: '100%',
                    padding: '13px',
                    borderRadius: '10px'
                  }}
                />

              </div>

              <div>

                <label
                  style={{
                    display: 'block',
                    marginBottom: '7px'
                  }}
                >
                  Main subject
                </label>

                <select
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  disabled={uploading}
                  style={{
                    width: '100%',
                    padding: '13px',
                    borderRadius: '10px'
                  }}
                >

                  <option value="Medicine">
                    Medicine
                  </option>

                  <option value="Surgery">
                    Surgery
                  </option>

                  <option value="OBGYN">
                    OBGYN
                  </option>

                  <option value="Pediatrics">
                    Pediatrics
                  </option>

                  <option value="Psychiatry">
                    Psychiatry
                  </option>

                  <option value="Pharmacology">
                    Pharmacology
                  </option>

                  <option value="Pathology">
                    Pathology
                  </option>

                  <option value="Microbiology">
                    Microbiology
                  </option>

                  <option value="General">
                    General / Mixed
                  </option>

                </select>

              </div>

              <button
                className="btn btn-primary"
                type="submit"
                disabled={uploading || !file}
              >

                {uploading ? (
                  <>
                    <Loader2
                      size={18}
                      className="spin"
                    />
                    Uploading…
                  </>
                ) : (
                  <>
                    <Upload size={18} />
                    Upload PDF
                  </>
                )}

              </button>

            </form>

            {uploadStage && (

              <div
                style={{
                  marginTop: '18px'
                }}
              >
                <Loader2 size={18} />
                {' '}
                {uploadStage}
              </div>

            )}

            {success && (

              <div
                style={{
                  marginTop: '18px'
                }}
              >
                <CheckCircle2 size={18} />
                {' '}
                {success}
              </div>

            )}

            {error && (

              <div
                style={{
                  marginTop: '18px'
                }}
              >
                <XCircle size={18} />
                {' '}
                {error}
              </div>

            )}

          </section>

        )}

        {!isAdmin && (

          <section className="panel">

            <div className="panel-kicker">
              SHARED LIBRARY
            </div>

            <h2>
              Books are managed centrally.
            </h2>

            <p>
              You can use all books and questions in MedQ, while PDF
              uploads are restricted to the administrator account.
            </p>

          </section>

        )}

        <section
          className="panel"
          style={{
            marginTop: '20px'
          }}
        >

          <div className="panel-title-row">

            <div>

              <div className="panel-kicker">
                AVAILABLE BOOKS
              </div>

              <h2>
                Shared collection
              </h2>

            </div>

            <strong>
              {books.length} books
            </strong>

          </div>

          {loading ? (

            <p>
              Loading library…
            </p>

          ) : error && books.length === 0 ? (

            <p>
              {error}
            </p>

          ) : books.length === 0 ? (

            <div
              style={{
                padding: '30px 0'
              }}
            >

              <BookOpen size={38} />

              <h3>
                No books uploaded yet.
              </h3>

              <p>
                Your first uploaded PDF will appear here.
              </p>

            </div>

          ) : (

            <div
              style={{
                display: 'grid',
                gap: '12px',
                marginTop: '20px'
              }}
            >

              {books.map((book) => (

                <BookRow
                  key={book.id}
                  book={book}
                  onRefresh={() => loadBooks({ silent: true })}
                />

              ))}

            </div>

          )}

        </section>

      </main>

    </div>
  )
}


function BookRow({ book, onRefresh }) {
  const progress = getBookProgress(book)
  const statusInfo = getStatusInfo(book)

  return (
    <div
      className="panel"
      style={{
        padding: '18px',
        display: 'grid',
        gap: '14px'
      }}
    >

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          gap: '20px',
          alignItems: 'center'
        }}
      >

        <div
          style={{
            display: 'flex',
            gap: '14px',
            alignItems: 'center',
            minWidth: 0
          }}
        >

          <FileText size={28} />

          <div style={{ minWidth: 0 }}>

            <strong>
              {book.title}
            </strong>

            <div
              style={{
                marginTop: '5px'
              }}
            >
              <small>
                {book.subject || 'General'}
              </small>

              {book.file_size_bytes && (
                <small>
                  {' • '}
                  {formatBytes(book.file_size_bytes)}
                </small>
              )}
            </div>

          </div>

        </div>

        <StatusBadge book={book} />

      </div>

      {statusInfo.active && (
        <div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              gap: '12px',
              marginBottom: '7px'
            }}
          >
            <small>
              {statusInfo.detail}
            </small>

            {progress !== null && (
              <small>
                {progress}%
              </small>
            )}
          </div>

          {progress !== null && (
            <div
              style={{
                height: '7px',
                borderRadius: '999px',
                overflow: 'hidden',
                background: 'rgba(255,255,255,.08)'
              }}
            >
              <div
                style={{
                  width: `${progress}%`,
                  height: '100%',
                  borderRadius: '999px',
                  background: 'currentColor',
                  opacity: 0.75,
                  transition: 'width .3s ease'
                }}
              />
            </div>
          )}
        </div>
      )}

      {book.status === 'failed' && book.error_message && (
        <small>
          {book.error_message}
        </small>
      )}

      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '14px'
        }}
      >
        {getTotalPages(book) > 0 && (
          <small>
            {getProcessedPages(book).toLocaleString()}
            {' / '}
            {getTotalPages(book).toLocaleString()}
            {' pages processed'}
          </small>
        )}

        {Number(book.questions_generated) > 0 && (
          <small>
            {Number(book.questions_generated).toLocaleString()}
            {' starter questions'}
          </small>
        )}

        {statusInfo.active && (
          <button
            type="button"
            className="btn"
            onClick={onRefresh}
            style={{
              padding: '4px 9px',
              minHeight: 'auto'
            }}
          >
            Refresh
          </button>
        )}
      </div>

    </div>
  )
}


function StatusBadge({ book }) {
  const info = getStatusInfo(book)

  return (
    <span className="user-chip">
      {info.label}
    </span>
  )
}


function getStatusInfo(book) {
  const stage = (
    book.processing_stage ||
    book.status ||
    ''
  ).toLowerCase()

  if (book.status === 'failed' || stage === 'failed') {
    return {
      label: 'Failed',
      detail: 'Processing stopped',
      active: false
    }
  }

  if (
    book.status === 'ready' &&
    [
      'ready',
      'knowledge_ready'
    ].includes(stage)
  ) {
    return {
      label: 'Ready',
      detail: 'Knowledge base ready',
      active: false
    }
  }

  const stages = {
    uploaded: {
      label: 'Uploaded',
      detail: 'Waiting to start processing'
    },
    queued: {
      label: 'Queued',
      detail: 'Waiting for processing worker'
    },
    downloading: {
      label: 'Downloading',
      detail: 'Preparing the stored PDF'
    },
    extracting: {
      label: 'Extracting',
      detail: 'Reading the complete textbook'
    },
    building_knowledge_base: {
      label: 'Building knowledge',
      detail: 'Organising textbook content for MedBot and practice'
    },
    knowledge_ready: {
      label: 'Knowledge ready',
      detail: 'Textbook knowledge base is available'
    },
    generating_seed_questions: {
      label: 'Generating questions',
      detail: 'Creating a distributed starter question set'
    },
    processing: {
      label: 'Processing',
      detail: 'Processing textbook'
    }
  }

  const info =
    stages[stage] ||
    stages[(book.status || '').toLowerCase()] ||
    {
      label: 'Processing',
      detail: 'Processing textbook'
    }

  return {
    ...info,
    active: true
  }
}


function getTotalPages(book) {
  return Number(
    book.total_pages ||
    book.page_count ||
    0
  )
}


function getProcessedPages(book) {
  return Number(
    book.processed_pages ||
    0
  )
}


function getBookProgress(book) {
  const stage = (
    book.processing_stage ||
    book.status ||
    ''
  ).toLowerCase()

  if (
    stage === 'extracting' ||
    stage === 'downloading'
  ) {
    return clampPercent(
      book.extraction_progress
    )
  }

  if (
    stage === 'building_knowledge_base' ||
    stage === 'knowledge_ready'
  ) {
    return 100
  }

  if (stage === 'generating_seed_questions') {
    return clampPercent(
      book.question_progress
    )
  }

  if (book.status === 'ready') {
    return 100
  }

  return null
}


function clampPercent(value) {
  const number = Number(value)

  if (!Number.isFinite(number)) {
    return null
  }

  return Math.max(
    0,
    Math.min(100, Math.round(number))
  )
}


function formatBytes(bytes) {
  if (!bytes) return '0 B'

  const units = [
    'B',
    'KB',
    'MB',
    'GB'
  ]

  let value = bytes
  let unitIndex = 0

  while (
    value >= 1024 &&
    unitIndex < units.length - 1
  ) {
    value /= 1024
    unitIndex += 1
  }

  return `${value.toFixed(
    unitIndex === 0 ? 0 : 1
  )} ${units[unitIndex]}`
}
