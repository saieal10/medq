import {
  useEffect,
  useRef,
  useState
} from 'react'

import { Link, useSearchParams } from 'react-router-dom'


const API_URL =
  import.meta.env.VITE_API_URL
  || 'https://medq-api-6vm5.onrender.com'


export default function MedBot({
  session
}) {

  const [searchParams] = useSearchParams()

  const questionId =
    searchParams.get('question')

  const [messages, setMessages] =
    useState([
      {
        role: 'assistant',
        content:
          'Hi, I’m MedBot. Ask me anything from the textbooks processed in your MedQ library. I’ll explain it in an AMC/FMGE-focused way.'
      }
    ])


  const [input, setInput] =
    useState('')


  const [loading, setLoading] =
    useState(false)


  const [error, setError] =
    useState('')


  const bottomRef =
    useRef(null)


  useEffect(() => {

    if (
      questionId
      && !input.trim()
    ) {
      setInput(
        'Explain this practice question, why the correct answer is correct, why the other options are wrong, and give me the key AMC/FMGE exam points.'
      )
    }

  }, [questionId])


  useEffect(() => {

    bottomRef.current
      ?.scrollIntoView({
        behavior: 'smooth'
      })

  }, [
    messages,
    loading
  ])


  async function sendMessage() {

    const text =
      input.trim()


    if (
      !text
      || loading
    ) {
      return
    }


    setError('')


    const userMessage = {
      role: 'user',
      content: text
    }


    const previousConversation =
      messages
        .filter(
          message =>
            message.role === 'user'
            || message.role === 'assistant'
        )
        .slice(-6)
        .map(
          message => ({
            role: message.role,
            content: message.content
          })
        )


    setMessages(
      current => [
        ...current,
        userMessage
      ]
    )


    setInput('')

    setLoading(true)


    try {

      let accessToken =
        session?.access_token


      if (!accessToken) {

        throw new Error(
          'Your login session has expired. Please sign in again.'
        )

      }


      const response =
        await fetch(
          `${API_URL}/api/medbot/chat`,
          {
            method: 'POST',

            headers: {
              'Content-Type':
                'application/json',

              Authorization:
                `Bearer ${accessToken}`
            },

            body: JSON.stringify({
              message: text,

              book_id: null,

              question_id: questionId || null,

              conversation:
                previousConversation
            })
          }
        )


      let data = null


      try {

        data =
          await response.json()

      } catch {

        data = null

      }


      if (!response.ok) {

        throw new Error(
          data?.detail
          || 'MedBot could not answer right now.'
        )

      }


      const assistantMessage = {
        role: 'assistant',

        content:
          data?.answer
          || 'I could not generate an answer.',

        sources:
          Array.isArray(
            data?.sources
          )
            ? data.sources
            : [],

        grounded:
          data?.grounded
      }


      setMessages(
        current => [
          ...current,
          assistantMessage
        ]
      )


    } catch (err) {

      console.error(
        'MedBot error:',
        err
      )


      setError(
        err?.message
        || 'Something went wrong.'
      )


    } finally {

      setLoading(false)

    }

  }


  function handleKeyDown(event) {

    if (
      event.key === 'Enter'
      && !event.shiftKey
    ) {

      event.preventDefault()

      sendMessage()

    }

  }


  function clearChat() {

    setMessages([
      {
        role: 'assistant',
        content:
          'Chat cleared. Ask me anything from your processed MedQ textbooks.'
      }
    ])

    setError('')

  }


  return (

    <div className="medbot-page">

      <header className="medbot-header">

        <div>

          <Link
            to={
              questionId
                ? '/practice'
                : '/dashboard'
            }
            className="medbot-back"
          >
            {questionId
              ? '← Practice'
              : '← Dashboard'}
          </Link>

          <div className="medbot-title-row">

            <div className="medbot-logo">
              M
            </div>

            <div>

              <h1>
                MedBot
              </h1>

              <p>
                Textbook-grounded AMC & FMGE assistant
              </p>

            </div>

          </div>

        </div>


        <button
          type="button"
          className="medbot-clear-button"
          onClick={clearChat}
        >
          Clear chat
        </button>

      </header>


      <main className="medbot-shell">

        <section className="medbot-chat">

          {questionId && (
            <div className="medbot-context-banner">
              Practice question context attached
            </div>
          )}

          <div className="medbot-messages">

            {messages.map(
              (
                message,
                index
              ) => (

                <div
                  key={index}
                  className={
                    message.role === 'user'
                      ? 'medbot-message medbot-message-user'
                      : 'medbot-message medbot-message-assistant'
                  }
                >

                  <div className="medbot-message-label">

                    {message.role === 'user'
                      ? 'You'
                      : 'MedBot'}

                  </div>


                  <div className="medbot-message-content">

                    {message.content}

                  </div>


                  {message.role === 'assistant'
                    && message.sources?.length > 0
                    && (

                      <div className="medbot-sources">

                        <div className="medbot-sources-title">
                          Based on
                        </div>

                        {message.sources.map(
                          (
                            source,
                            sourceIndex
                          ) => (

                            <div
                              key={
                                `${source.book_title}-${sourceIndex}`
                              }
                              className="medbot-source"
                            >

                              <strong>
                                {source.book_title}
                              </strong>

                              {source.chapter
                                ? (
                                  <span>
                                    {' '}
                                    · {source.chapter}
                                  </span>
                                )
                                : null}

                            </div>

                          )
                        )}

                      </div>

                    )}

                </div>

              )
            )}


            {loading && (

              <div className="medbot-message medbot-message-assistant">

                <div className="medbot-message-label">
                  MedBot
                </div>

                <div className="medbot-thinking">

                  <span />
                  <span />
                  <span />

                  <small>
                    Searching your textbook library...
                  </small>

                </div>

              </div>

            )}


            <div ref={bottomRef} />

          </div>


          {error && (

            <div className="medbot-error">

              {error}

            </div>

          )}


          <div className="medbot-composer">

            <textarea
              value={input}

              onChange={
                event =>
                  setInput(
                    event.target.value
                  )
              }

              onKeyDown={
                handleKeyDown
              }

              placeholder="Ask a medical question..."

              rows={3}

              disabled={loading}
            />


            <button
              type="button"

              onClick={
                sendMessage
              }

              disabled={
                loading
                || !input.trim()
              }

              className="medbot-send-button"
            >

              {loading
                ? 'Thinking...'
                : 'Ask MedBot'}

            </button>

          </div>


          <div className="medbot-hint">

            Enter to send · Shift + Enter for a new line

          </div>

        </section>


        <aside className="medbot-sidebar">

          <div className="medbot-info-card">

            <h3>
              Try asking
            </h3>

            <button
              type="button"
              onClick={() =>
                setInput(
                  'Explain achalasia in simple terms and tell me the important AMC points.'
                )
              }
            >
              Explain achalasia
            </button>


            <button
              type="button"
              onClick={() =>
                setInput(
                  'How do I differentiate ulcerative colitis from Crohn disease for exams?'
                )
              }
            >
              UC vs Crohn disease
            </button>


            <button
              type="button"
              onClick={() =>
                setInput(
                  'Explain Wilson disease diagnosis and management step by step.'
                )
              }
            >
              Wilson disease
            </button>

          </div>


          <div className="medbot-info-card">

            <h3>
              How MedBot works
            </h3>

            <p>
              MedBot searches the processed books in your shared MedQ library and sends the most relevant textbook sections to the AI.
            </p>

            <p>
              It does not send the whole PDF for every question.
            </p>

            <p>
              Sources show the textbook and chapter only. Page numbers stay hidden.
            </p>

          </div>


          <div className="medbot-info-card">

            <h3>
              Library
            </h3>

            <p>
              More processed textbooks will give MedBot a larger medical knowledge base.
            </p>

            <Link
              to="/library"
              className="medbot-library-link"
            >
              Open PDF Library →
            </Link>

          </div>

        </aside>

      </main>

    </div>

  )

}
