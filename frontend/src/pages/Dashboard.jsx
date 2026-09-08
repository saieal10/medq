import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bookmark,
  BookOpen,
  Brain,
  LogOut,
  RotateCcw,
  Target
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
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      const userId = session.user.id

      const [
        { data: profileData },
        { data: attempts },
        { data: books }
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
          .select('id')
      ])

      setProfile(profileData)

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
