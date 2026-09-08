import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bookmark,
  BookOpen,
  Brain,
  History as HistoryIcon,
  LogOut,
  RotateCcw,
  Target,
  Clock3,
  CalendarDays,
  Activity
} from 'lucide-react'

import { supabase } from '../lib/supabase'
import Logo from '../components/Logo'

export default function Dashboard({ session }) {
  const navigate = useNavigate()

  const [profile, setProfile] = useState(null)
  const [stats, setStats] = useState({
    attempted: 0,
    correct: 0
  })

  const [subjectPerformance, setSubjectPerformance] = useState([])
  const [practiceSessions, setPracticeSessions] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      const userId = session.user.id

      const [
        { data: profileData },
        { data: attempts },
        { data: books },
        { data: sessionsData }
      ] = await Promise.all([
        supabase
          .from('profiles')
          .select('*')
          .eq('id', userId)
          .maybeSingle(),

        supabase
          .from('attempts')
          .select('question_id, is_correct')
          .eq('user_id', userId),

        supabase
          .from('books')
          .select('id'),

        supabase
          .from('practice_sessions')
          .select('*')
          .eq('user_id', userId)
          .not('finished_at', 'is', null)
          .order('finished_at', { ascending: false })
          .limit(50)
      ])

      setProfile(profileData)
      setPracticeSessions(sessionsData || [])

      const questionIds = [
        ...new Set(
          (attempts || [])
            .map((attempt) => attempt.question_id)
            .filter(Boolean)
        )
      ]

      let questionSubjectMap = {}

      if (questionIds.length > 0) {
        const { data: questionRows } = await supabase
          .from('questions')
          .select('id, subject')
          .in('id', questionIds)

        questionSubjectMap = Object.fromEntries(
          (questionRows || []).map((question) => [
            question.id,
            question.subject || 'General'
          ])
        )
      }

      const performanceMap = {}

      ;(attempts || []).forEach((attempt) => {
        const subject =
          questionSubjectMap[attempt.question_id] || 'General'

        if (!performanceMap[subject]) {
          performanceMap[subject] = {
            subject,
            attempted: 0,
            correct: 0
          }
        }

        performanceMap[subject].attempted += 1

        if (attempt.is_correct) {
          performanceMap[subject].correct += 1
        }
      })

      const performance = Object.values(performanceMap)
        .map((item) => ({
          ...item,
          accuracy: item.attempted
            ? Math.round((item.correct / item.attempted) * 100)
            : 0
        }))
        .sort((a, b) => {
          if (b.attempted !== a.attempted) {
            return b.attempted - a.attempted
          }

          return b.accuracy - a.accuracy
        })

      setSubjectPerformance(performance)

      const attempted =
        attempts?.length || 0

      const correct =
        attempts?.filter(
          (attempt) => attempt.is_correct
        ).length || 0

      setStats({
        attempted,
        correct,
        books: books?.length || 0
      })

      setLoading(false)
    }

    load()
  }, [session])

  const accuracy = useMemo(() => {
    if (!stats.attempted) {
      return 0
    }

    return Math.round(
      (stats.correct / stats.attempted) * 100
    )
  }, [stats])

  const sessionAnalytics = useMemo(() => {
    const now = new Date()
    const startOfToday = new Date(
      now.getFullYear(),
      now.getMonth(),
      now.getDate()
    )

    const sevenDaysAgo = new Date(startOfToday)
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 6)

    const finishedSessions = practiceSessions.filter(
      (item) => item.finished_at
    )

    const todaySessions = finishedSessions.filter(
      (item) =>
        new Date(item.finished_at) >= startOfToday
    )

    const weekSessions = finishedSessions.filter(
      (item) =>
        new Date(item.finished_at) >= sevenDaysAgo
    )

    function summarize(items) {
      const answered = items.reduce(
        (sum, item) =>
          sum + (Number(item.answered_count) || 0),
        0
      )

      const correct = items.reduce(
        (sum, item) =>
          sum + (Number(item.correct_count) || 0),
        0
      )

      const seconds = items.reduce(
        (sum, item) =>
          sum + (Number(item.duration_seconds) || 0),
        0
      )

      return {
        sessions: items.length,
        answered,
        correct,
        accuracy:
          answered > 0
            ? Math.round((correct / answered) * 100)
            : 0,
        seconds
      }
    }

    return {
      today: summarize(todaySessions),
      week: summarize(weekSessions),
      recent: finishedSessions.slice(0, 5)
    }
  }, [practiceSessions])

  function formatStudyTime(seconds) {
    const total = Number(seconds) || 0

    if (total < 60) {
      return `${total}s`
    }

    const minutes = Math.floor(total / 60)

    if (minutes < 60) {
      return `${minutes}m`
    }

    const hours = Math.floor(minutes / 60)
    const remainingMinutes = minutes % 60

    return remainingMinutes
      ? `${hours}h ${remainingMinutes}m`
      : `${hours}h`
  }

  function formatSessionDate(value) {
    if (!value) {
      return '—'
    }

    return new Date(value).toLocaleString([], {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit'
    })
  }

  const firstName =
    profile?.display_name ||
    session.user.email?.split('@')[0] ||
    'Student'

  const rankedSubjects = useMemo(() => {
    return [...subjectPerformance]
      .filter((item) => item.attempted > 0)
      .sort((a, b) => {
        if (b.accuracy !== a.accuracy) {
          return b.accuracy - a.accuracy
        }

        return b.attempted - a.attempted
      })
  }, [subjectPerformance])

  const strongestSubject =
    rankedSubjects.length > 0
      ? rankedSubjects[0]
      : null

  const weakestSubject =
    rankedSubjects.length > 1
      ? rankedSubjects[rankedSubjects.length - 1]
      : null

  async function signOut() {
    await supabase.auth.signOut()
  }

  return (
    <div className="app-shell">

      <aside className="sidebar">

        <Logo />

        <div className="side-nav">

          <button className="side-active">
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
              YOUR STUDY DASHBOARD
            </div>

            <h1>
              Welcome, {firstName}.
            </h1>

            <p>
              This dashboard belongs only to your account.
            </p>

          </div>

          <div className="user-chip">
            {session.user.email}
          </div>

        </header>

        {loading ? (

          <div className="dash-loading">
            Loading your progress…
          </div>

        ) : (

          <>

            <section className="stat-grid">

              <Stat
                label="Questions attempted"
                value={stats.attempted}
                meta="All time"
              />

              <Stat
                label="Correct answers"
                value={stats.correct}
                meta="All time"
              />

              <Stat
                label="Accuracy"
                value={`${accuracy}%`}
                meta={
                  stats.attempted
                    ? 'Based on your attempts'
                    : 'Start practicing'
                }
              />

              <Stat
                label="Books ready"
                value={stats.books || 0}
                meta="Shared MedQ library"
              />

            </section>

            <section className="dashboard-grid">

              <div className="panel primary-panel">

                <div className="panel-kicker">
                  START PRACTICE
                </div>

                <h2>
                  Start answering medical MCQs.
                </h2>

                <p>
                  Practice questions generated from your
                  shared MedQ medical library. Every answer
                  is stored separately for your account.
                </p>

                <button
                  className="btn btn-primary"
                  onClick={() =>
                    navigate('/practice')
                  }
                >
                  Start Practice
                </button>

              </div>

              <div className="panel">

                <div className="panel-kicker">
                  MEDICAL LIBRARY
                </div>

                <h2>
                  Shared PDF collection.
                </h2>

                <p>
                  Both users use the same uploaded medical
                  books while keeping their study progress
                  separate.
                </p>

                <button
                  className="btn"
                  onClick={() =>
                    navigate('/library')
                  }
                >
                  Open Library
                </button>

              </div>

            </section>

            <section className="panel subjects-panel">
              <div className="panel-title-row">
                <div>
                  <div className="panel-kicker">
                    TODAY
                  </div>
                  <h2>
                    Your study activity today.
                  </h2>
                </div>
                <Activity size={21} />
              </div>

              <div
                className="stat-grid"
                style={{ marginTop: '20px' }}
              >
                <Stat
                  label="Questions today"
                  value={sessionAnalytics.today.answered}
                  meta={`${sessionAnalytics.today.sessions} session${sessionAnalytics.today.sessions === 1 ? '' : 's'}`}
                />
                <Stat
                  label="Today's accuracy"
                  value={`${sessionAnalytics.today.accuracy}%`}
                  meta={`${sessionAnalytics.today.correct}/${sessionAnalytics.today.answered || 0} correct`}
                />
                <Stat
                  label="Study time"
                  value={formatStudyTime(sessionAnalytics.today.seconds)}
                  meta="Completed sessions"
                />
                <Stat
                  label="Sessions today"
                  value={sessionAnalytics.today.sessions}
                  meta="Finished practice"
                />
              </div>
            </section>

            <section className="panel subjects-panel">
              <div className="panel-title-row">
                <div>
                  <div className="panel-kicker">
                    LAST 7 DAYS
                  </div>
                  <h2>
                    Your recent practice momentum.
                  </h2>
                </div>
                <CalendarDays size={21} />
              </div>

              <div
                className="stat-grid"
                style={{ marginTop: '20px' }}
              >
                <Stat
                  label="Questions"
                  value={sessionAnalytics.week.answered}
                  meta="Last 7 days"
                />
                <Stat
                  label="Accuracy"
                  value={`${sessionAnalytics.week.accuracy}%`}
                  meta={`${sessionAnalytics.week.correct}/${sessionAnalytics.week.answered || 0} correct`}
                />
                <Stat
                  label="Study time"
                  value={formatStudyTime(sessionAnalytics.week.seconds)}
                  meta="Last 7 days"
                />
                <Stat
                  label="Sessions"
                  value={sessionAnalytics.week.sessions}
                  meta="Last 7 days"
                />
              </div>
            </section>

            <section className="panel subjects-panel">
              <div className="panel-title-row">
                <div>
                  <div className="panel-kicker">
                    RECENT SESSIONS
                  </div>
                  <h2>
                    Your latest completed practice sessions.
                  </h2>
                </div>
                <Clock3 size={21} />
              </div>

              {sessionAnalytics.recent.length === 0 ? (
                <div
                  className="subject-placeholder"
                  style={{ marginTop: '20px' }}
                >
                  <div>
                    <span>No completed sessions yet</span>
                    <b>—</b>
                  </div>
                </div>
              ) : (
                <div
                  style={{
                    display: 'grid',
                    gap: '12px',
                    marginTop: '20px'
                  }}
                >
                  {sessionAnalytics.recent.map((item) => (
                    <div
                      key={item.id}
                      className="stat-card"
                      style={{
                        display: 'grid',
                        gridTemplateColumns:
                          'minmax(130px, 1.1fr) minmax(110px, 1fr) minmax(90px, .8fr) minmax(90px, .8fr)',
                        alignItems: 'center',
                        gap: '14px'
                      }}
                    >
                      <div>
                        <span>
                          {(item.exam_mode || 'mixed').toUpperCase()}
                          {' · '}
                          {item.practice_mode === 'exam'
                            ? 'Exam'
                            : 'Tutor'}
                        </span>
                        <strong
                          style={{
                            display: 'block',
                            fontSize: '16px',
                            marginTop: '4px'
                          }}
                        >
                          {item.subject || 'All subjects'}
                        </strong>
                        <small>
                          {formatSessionDate(item.finished_at)}
                        </small>
                      </div>

                      <div>
                        <span>RESULT</span>
                        <strong
                          style={{
                            display: 'block',
                            fontSize: '20px',
                            marginTop: '4px'
                          }}
                        >
                          {item.correct_count}/{item.answered_count}
                        </strong>
                        <small>
                          {item.unanswered_count} unanswered
                        </small>
                      </div>

                      <div>
                        <span>ACCURACY</span>
                        <strong
                          style={{
                            display: 'block',
                            fontSize: '20px',
                            marginTop: '4px'
                          }}
                        >
                          {item.accuracy}%
                        </strong>
                      </div>

                      <div>
                        <span>TIME</span>
                        <strong
                          style={{
                            display: 'block',
                            fontSize: '20px',
                            marginTop: '4px'
                          }}
                        >
                          {formatStudyTime(item.duration_seconds)}
                        </strong>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            <section className="panel subjects-panel">

              <div className="panel-title-row">

                <div>

                  <div className="panel-kicker">
                    SUBJECT PERFORMANCE
                  </div>

                  <h2>
                    See where you are strongest and where
                    you need more practice.
                  </h2>

                </div>

              </div>

              {subjectPerformance.length === 0 ? (

                <div className="subject-placeholder">

                  <div>
                    <span>
                      No subject data yet
                    </span>

                    <div className="bar muted">
                      <i style={{ width: '0%' }} />
                    </div>

                    <b>
                      —
                    </b>
                  </div>

                </div>

              ) : (

                <>

                  <div
                    className="dashboard-grid"
                    style={{
                      marginTop: '20px',
                      marginBottom: '24px'
                    }}
                  >

                    <div className="panel">

                      <div className="panel-kicker">
                        STRONGEST SUBJECT
                      </div>

                      <h3>
                        {strongestSubject?.subject || '—'}
                      </h3>

                      <p>
                        {strongestSubject
                          ? `${strongestSubject.accuracy}% accuracy · ${strongestSubject.correct}/${strongestSubject.attempted} correct`
                          : 'Keep practicing to build your subject profile.'}
                      </p>

                    </div>

                    <div className="panel">

                      <div className="panel-kicker">
                        NEEDS MOST WORK
                      </div>

                      <h3>
                        {weakestSubject?.subject || '—'}
                      </h3>

                      <p>
                        {weakestSubject
                          ? `${weakestSubject.accuracy}% accuracy · ${weakestSubject.correct}/${weakestSubject.attempted} correct`
                          : 'Practice more than one subject to compare performance.'}
                      </p>

                    </div>

                  </div>

                  <div className="subject-placeholder">

                    {subjectPerformance.map((item) => (

                      <div key={item.subject}>

                        <span>
                          {item.subject}
                          <small
                            style={{
                              display: 'block',
                              marginTop: '3px'
                            }}
                          >
                            {item.correct}/{item.attempted} correct · {item.attempted} attempted
                          </small>
                        </span>

                        <div className="bar">
                          <i
                            style={{
                              width: `${item.accuracy}%`
                            }}
                          />
                        </div>

                        <b>
                          {item.accuracy}%
                        </b>

                      </div>

                    ))}

                  </div>

                </>

              )}

            </section>

          </>

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
