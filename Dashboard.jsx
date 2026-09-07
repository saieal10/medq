import { useEffect, useMemo, useState } from 'react'
import { BookOpen, Brain, LogOut, RotateCcw, Target } from 'lucide-react'
import { supabase } from '../lib/supabase'
import Logo from '../components/Logo'

export default function Dashboard({ session }) {
  const [profile, setProfile] = useState(null)
  const [stats, setStats] = useState({ attempted: 0, correct: 0 })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      const userId = session.user.id
      const [{ data: profileData }, { data: attempts }] = await Promise.all([
        supabase.from('profiles').select('*').eq('id', userId).maybeSingle(),
        supabase.from('attempts').select('is_correct').eq('user_id', userId)
      ])

      setProfile(profileData)
      const attempted = attempts?.length || 0
      const correct = attempts?.filter(a => a.is_correct).length || 0
      setStats({ attempted, correct })
      setLoading(false)
    }
    load()
  }, [session])

  const accuracy = useMemo(() => stats.attempted ? Math.round((stats.correct / stats.attempted) * 100) : 0, [stats])
  const firstName = profile?.display_name || session.user.email?.split('@')[0] || 'Student'

  async function signOut() {
    await supabase.auth.signOut()
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Logo />
        <div className="side-nav">
          <button className="side-active"><Target size={18}/> Dashboard</button>
          <button><Brain size={18}/> Practice <span className="soon">soon</span></button>
          <button><RotateCcw size={18}/> Mistakes <span className="soon">soon</span></button>
          <button><BookOpen size={18}/> Library <span className="soon">next</span></button>
        </div>
        <button className="logout" onClick={signOut}><LogOut size={18}/> Sign out</button>
      </aside>

      <main className="dashboard-main">
        <header className="dash-head">
          <div>
            <div className="eyebrow">YOUR STUDY DASHBOARD</div>
            <h1>Welcome, {firstName}.</h1>
            <p>This dashboard belongs only to your account.</p>
          </div>
          <div className="user-chip">{session.user.email}</div>
        </header>

        {loading ? <div className="dash-loading">Loading your progress…</div> : (
          <>
            <section className="stat-grid">
              <Stat label="Questions attempted" value={stats.attempted} meta="All time" />
              <Stat label="Correct answers" value={stats.correct} meta="All time" />
              <Stat label="Accuracy" value={`${accuracy}%`} meta={stats.attempted ? 'Based on your attempts' : 'Start practicing soon'} />
              <Stat label="Books ready" value="0" meta="Library comes next" />
            </section>

            <section className="dashboard-grid">
              <div className="panel primary-panel">
                <div className="panel-kicker">NEXT STEP</div>
                <h2>Build your medical library.</h2>
                <p>
                  The next screen we add will let the admin account upload large PDF books,
                  track processing status and make them available for practice.
                </p>
                <button className="btn btn-primary" disabled>Library coming next</button>
              </div>

              <div className="panel">
                <div className="panel-kicker">TODAY</div>
                <h2>No practice session yet.</h2>
                <p>Once question practice is connected, today's attempts and accuracy will appear here automatically.</p>
                <div className="empty-chart">
                  <span>0</span>
                  <small>questions today</small>
                </div>
              </div>
            </section>

            <section className="panel subjects-panel">
              <div className="panel-title-row">
                <div>
                  <div className="panel-kicker">SUBJECT PERFORMANCE</div>
                  <h2>Your weak and strong subjects will appear here.</h2>
                </div>
              </div>
              <div className="subject-placeholder">
                {['Medicine','Surgery','OBGYN','Pediatrics','Pharmacology','Pathology'].map(s => (
                  <div key={s}><span>{s}</span><div className="bar muted"><i style={{width:'0%'}} /></div><b>—</b></div>
                ))}
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  )
}

function Stat({ label, value, meta }) {
  return (
    <div className="stat-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{meta}</small>
    </div>
  )
}
