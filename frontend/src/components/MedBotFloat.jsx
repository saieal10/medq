import {
  useEffect,
  useMemo,
  useRef,
  useState
} from 'react'
import {
  Bot,
  ExternalLink,
  Loader2,
  MessageCircle,
  Send,
  Trash2,
  X
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'

const API_URL =
  import.meta.env.VITE_API_URL ||
  'https://medq-api-6vm5.onrender.com'

const STORAGE_KEY = 'medq-medbot-floating-chat-v1'

export default function MedBotFloat({ session }) {
  const navigate = useNavigate()
  const bottomRef = useRef(null)

  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [questionId, setQuestionId] = useState(null)
  const [messages, setMessages] = useState(() => {
    try {
      const saved = JSON.parse(
        localStorage.getItem(STORAGE_KEY) || '[]'
      )
      if (Array.isArray(saved) && saved.length) {
        return saved.slice(-12)
      }
    } catch {}

    return [
      {
        role: 'assistant',
        content:
          'Hi, I’m MedBot — your AI medical tutor. Ask me anything in medicine, AMC, FMGE or NEET-PG. I can use your MedQ library when it is helpful.'
      }
    ]
  })

  const hiddenPath = useMemo(() => {
    const path = window.location.pathname
    return path === '/' || path === '/login' || path === '/medbot'
  }, [window.location.pathname])

  useEffect(() => {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(messages.slice(-12))
      )
    } catch {}

    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading, open])

  useEffect(() => {
    function openFromQuestion(event) {
      const id = event?.detail?.questionId || null
      setQuestionId(id)
      setOpen(true)
      setError('')

      if (id) {
        setInput(
          'Explain this question step by step. Tell me why the correct answer is best, why the distractors are wrong, and the AMC/FMGE exam takeaway.'
        )
      }
    }

    window.addEventListener('medq:open-medbot', openFromQuestion)
    return () => {
      window.removeEventListener('medq:open-medbot', openFromQuestion)
    }
  }, [])

  async function sendMessage() {
    const text = input.trim()
    if (!text || loading) return

    setError('')
    const userMessage = { role: 'user', content: text }
    const conversation = messages
      .filter((item) => item.role === 'user' || item.role === 'assistant')
      .slice(-6)
      .map((item) => ({ role: item.role, content: item.content }))

    // Add an empty assistant bubble immediately; streamed text fills it.
    setMessages((current) => [
      ...current,
      userMessage,
      { role: 'assistant', content: '', sources: [] }
    ])
    setInput('')
    setLoading(true)

    try {
      const accessToken = session?.access_token
      if (!accessToken) throw new Error('Your login session has expired.')

      const response = await fetch(`${API_URL}/api/medbot/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${accessToken}`
        },
        body: JSON.stringify({
          message: text,
          book_id: null,
          question_id: questionId,
          conversation
        })
      })

      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data?.detail || 'MedBot could not answer right now.')
      }
      if (!response.body) throw new Error('Streaming is unavailable in this browser.')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let serverError = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const event of events) {
          const line = event.split('\n').find((item) => item.startsWith('data:'))
          if (!line) continue
          let payload = null
          try { payload = JSON.parse(line.slice(5).trim()) } catch { continue }

          if (payload.type === 'ready' && Array.isArray(payload.sources)) {
            setMessages((current) => {
              const next = [...current]
              const last = next[next.length - 1]
              if (last?.role === 'assistant') next[next.length - 1] = { ...last, sources: payload.sources }
              return next
            })
          }

          if (payload.type === 'delta' && payload.text) {
            setMessages((current) => {
              const next = [...current]
              const last = next[next.length - 1]
              if (last?.role === 'assistant') {
                next[next.length - 1] = { ...last, content: `${last.content || ''}${payload.text}` }
              }
              return next
            })
          }

          if (payload.type === 'error') serverError = payload.message || 'MedBot could not answer.'
        }
      }

      if (serverError) throw new Error(serverError)
      setQuestionId(null)
    } catch (err) {
      setMessages((current) => {
        const next = [...current]
        if (next[next.length - 1]?.role === 'assistant' && !next[next.length - 1].content) next.pop()
        return next
      })
      setError(err?.message || 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  function clearChat() {
    setMessages([
      {
        role: 'assistant',
        content:
          'Chat cleared. Ask me any medical, AMC, FMGE or NEET-PG question.'
      }
    ])
    setQuestionId(null)
    setError('')
  }

  function keyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      sendMessage()
    }
  }

  if (hiddenPath) return null

  return (
    <>
      {open && (
        <section style={styles.window} aria-label="MedBot chat">
          <header style={styles.header}>
            <div style={styles.headerIdentity}>
              <span style={styles.botIcon}>
                <Bot size={20} />
              </span>
              <div>
                <strong style={styles.title}>MedBot</strong>
                <small style={styles.subtitle}>
                  Fast AI medical tutor • AMC + FMGE + NEET-PG
                </small>
              </div>
            </div>

            <div style={styles.headerActions}>
              <button
                type="button"
                style={styles.iconButton}
                title="Open full MedBot"
                onClick={() => navigate('/medbot')}
              >
                <ExternalLink size={17} />
              </button>
              <button
                type="button"
                style={styles.iconButton}
                title="Close"
                onClick={() => setOpen(false)}
              >
                <X size={18} />
              </button>
            </div>
          </header>

          {questionId && (
            <div style={styles.contextBanner}>
              Practice question attached
            </div>
          )}

          <div style={styles.messages}>
            {messages.map((message, index) => (
              <div
                key={`${message.role}-${index}`}
                style={
                  message.role === 'user'
                    ? styles.userRow
                    : styles.assistantRow
                }
              >
                <div
                  style={
                    message.role === 'user'
                      ? styles.userBubble
                      : styles.assistantBubble
                  }
                >
                  <div style={styles.messageText}>
                    {message.content}
                  </div>

                  {Array.isArray(message.sources) &&
                    message.sources.length > 0 && (
                      <div style={styles.sources}>
                        {message.sources.slice(0, 3).map((source, i) => (
                          <span
                            key={`${source.book_title}-${source.chapter}-${i}`}
                            style={styles.sourceChip}
                          >
                            {source.book_title}
                            {source.chapter ? ` · ${source.chapter}` : ''}
                          </span>
                        ))}
                      </div>
                    )}
                </div>
              </div>
            ))}

            {loading && messages[messages.length - 1]?.content === '' && (
              <div style={styles.assistantRow}>
                <div style={styles.thinking}>
                  <Loader2 size={16} />
                  Connecting to Gemini…
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {error && (
            <div style={styles.error}>{error}</div>
          )}

          <div style={styles.composer}>
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={keyDown}
              placeholder="Ask a medical question…"
              rows={2}
              style={styles.textarea}
              disabled={loading}
            />

            <button
              type="button"
              onClick={sendMessage}
              disabled={loading || !input.trim()}
              style={styles.sendButton}
              title="Send"
            >
              <Send size={18} />
            </button>
          </div>

          <footer style={styles.footer}>
            <button
              type="button"
              onClick={clearChat}
              style={styles.clearButton}
            >
              <Trash2 size={14} />
              Clear
            </button>

            <span>
              Gemini AI • live
            </span>
          </footer>
        </section>
      )}

      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        style={styles.floatingButton}
        title="Ask MedBot"
        aria-label="Ask MedBot"
      >
        {open ? <X size={25} /> : <MessageCircle size={27} />}
        {!open && <span style={styles.floatingLabel}>MedBot</span>}
      </button>
    </>
  )
}

const styles = {
  floatingButton: {
    position: 'fixed',
    right: '24px',
    bottom: '24px',
    zIndex: 5000,
    border: 'none',
    borderRadius: '999px',
    minWidth: '58px',
    height: '58px',
    padding: '0 18px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '9px',
    cursor: 'pointer',
    background: '#1f6feb',
    color: '#fff',
    boxShadow: '0 18px 45px rgba(0,0,0,.28)',
    fontWeight: 700
  },
  floatingLabel: {
    fontSize: '14px'
  },
  window: {
    position: 'fixed',
    right: '24px',
    bottom: '94px',
    width: 'min(410px, calc(100vw - 28px))',
    height: 'min(650px, calc(100vh - 130px))',
    zIndex: 4999,
    display: 'grid',
    gridTemplateRows: 'auto auto 1fr auto auto auto',
    overflow: 'hidden',
    border: '1px solid rgba(148,163,184,.24)',
    borderRadius: '20px',
    background: '#0f172a',
    color: '#e5e7eb',
    boxShadow: '0 28px 80px rgba(0,0,0,.42)'
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '12px',
    padding: '15px 16px',
    borderBottom: '1px solid rgba(148,163,184,.16)',
    background: '#111c31'
  },
  headerIdentity: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px'
  },
  botIcon: {
    width: '38px',
    height: '38px',
    display: 'grid',
    placeItems: 'center',
    borderRadius: '12px',
    background: 'rgba(59,130,246,.16)',
    color: '#93c5fd'
  },
  title: {
    display: 'block',
    color: '#fff'
  },
  subtitle: {
    display: 'block',
    marginTop: '2px',
    color: '#94a3b8'
  },
  headerActions: {
    display: 'flex',
    gap: '6px'
  },
  iconButton: {
    width: '34px',
    height: '34px',
    display: 'grid',
    placeItems: 'center',
    borderRadius: '10px',
    border: '1px solid rgba(148,163,184,.16)',
    background: 'transparent',
    color: '#cbd5e1',
    cursor: 'pointer'
  },
  contextBanner: {
    padding: '8px 14px',
    background: 'rgba(59,130,246,.12)',
    color: '#bfdbfe',
    fontSize: '12px',
    borderBottom: '1px solid rgba(59,130,246,.18)'
  },
  messages: {
    overflowY: 'auto',
    padding: '16px',
    display: 'flex',
    flexDirection: 'column',
    gap: '12px'
  },
  userRow: {
    display: 'flex',
    justifyContent: 'flex-end'
  },
  assistantRow: {
    display: 'flex',
    justifyContent: 'flex-start'
  },
  userBubble: {
    maxWidth: '88%',
    padding: '11px 13px',
    borderRadius: '15px 15px 4px 15px',
    background: '#1f6feb',
    color: '#fff'
  },
  assistantBubble: {
    maxWidth: '92%',
    padding: '12px 13px',
    borderRadius: '15px 15px 15px 4px',
    background: '#172238',
    border: '1px solid rgba(148,163,184,.12)',
    color: '#e5e7eb'
  },
  messageText: {
    whiteSpace: 'pre-wrap',
    lineHeight: 1.55,
    fontSize: '14px'
  },
  sources: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '6px',
    marginTop: '9px'
  },
  sourceChip: {
    padding: '4px 7px',
    borderRadius: '999px',
    background: 'rgba(148,163,184,.09)',
    color: '#94a3b8',
    fontSize: '10px'
  },
  thinking: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '10px 12px',
    color: '#94a3b8',
    fontSize: '13px'
  },
  error: {
    margin: '0 14px 10px',
    padding: '9px 10px',
    borderRadius: '10px',
    background: 'rgba(239,68,68,.11)',
    color: '#fecaca',
    fontSize: '12px'
  },
  composer: {
    display: 'grid',
    gridTemplateColumns: '1fr auto',
    gap: '8px',
    padding: '12px',
    borderTop: '1px solid rgba(148,163,184,.14)',
    background: '#111827'
  },
  textarea: {
    resize: 'none',
    width: '100%',
    border: '1px solid rgba(148,163,184,.2)',
    outline: 'none',
    borderRadius: '12px',
    background: '#0b1220',
    color: '#fff',
    padding: '10px 11px',
    font: 'inherit'
  },
  sendButton: {
    width: '42px',
    height: '42px',
    alignSelf: 'end',
    display: 'grid',
    placeItems: 'center',
    border: 'none',
    borderRadius: '12px',
    background: '#2563eb',
    color: '#fff',
    cursor: 'pointer'
  },
  footer: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '10px',
    padding: '8px 12px 10px',
    background: '#111827',
    color: '#64748b',
    fontSize: '10px'
  },
  clearButton: {
    display: 'flex',
    alignItems: 'center',
    gap: '5px',
    border: 'none',
    padding: 0,
    background: 'transparent',
    color: '#94a3b8',
    cursor: 'pointer',
    fontSize: '11px'
  }
}
