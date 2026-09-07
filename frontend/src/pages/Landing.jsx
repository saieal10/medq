import { ArrowRight, BookOpen, Brain, ChartNoAxesCombined, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import Logo from '../components/Logo'

export default function Landing({ session }) {
  return (
    <div className="landing">
      <nav className="nav shell">
        <Logo />
        <div className="nav-actions">
          <a className="nav-link" href="#how">How it works</a>
          <Link className="btn btn-small btn-outline" to={session ? '/dashboard' : '/login'}>
            {session ? 'Dashboard' : 'Sign in'}
          </Link>
        </div>
      </nav>

      <main>
        <section className="hero shell">
          <div className="hero-copy">
            <div className="eyebrow">PRIVATE STUDY SPACE • BUILT FOR TWO</div>
            <h1>Your medical MCQs.<br/><span>Your progress.</span></h1>
            <p>
              A focused AMC and FMGE question-practice dashboard built around your own books,
              mistakes, subjects and daily progress.
            </p>
            <div className="hero-buttons">
              <Link className="btn btn-primary" to={session ? '/dashboard' : '/login'}>
                {session ? 'Continue practice' : 'Enter MedQ'} <ArrowRight size={18} />
              </Link>
              <a className="btn btn-ghost" href="#how">See how it works</a>
            </div>
            <div className="hero-note">No public profiles. No leaderboard. Just practice.</div>
          </div>

          <div className="preview-card">
            <div className="preview-top">
              <span>Today</span>
              <span className="live-dot">● LIVE</span>
            </div>
            <div className="preview-score">
              <div>
                <strong>74%</strong>
                <span>accuracy</span>
              </div>
              <div>
                <strong>82</strong>
                <span>questions</span>
              </div>
            </div>
            <div className="progress-row">
              <div><span>Medicine</span><span>72%</span></div>
              <div className="bar"><i style={{width:'72%'}} /></div>
            </div>
            <div className="progress-row">
              <div><span>Surgery</span><span>68%</span></div>
              <div className="bar"><i style={{width:'68%'}} /></div>
            </div>
            <div className="progress-row">
              <div><span>OBGYN</span><span>79%</span></div>
              <div className="bar"><i style={{width:'79%'}} /></div>
            </div>
            <button className="fake-practice">Start a practice session →</button>
          </div>
        </section>

        <section id="how" className="feature-section shell">
          <div className="section-head">
            <div className="eyebrow">SIMPLE BY DESIGN</div>
            <h2>Everything you actually need.</h2>
          </div>
          <div className="feature-grid">
            <Feature icon={<BookOpen />} title="Your library" text="Upload and organize your AMC/FMGE books and MCQ sources." />
            <Feature icon={<Brain />} title="Focused practice" text="Choose subject, chapter, difficulty and question count." />
            <Feature icon={<ChartNoAxesCombined />} title="Personal dashboard" text="Your attempts, accuracy and weak topics stay separate." />
            <Feature icon={<ShieldCheck />} title="Private" text="Designed for only you and your friend, with separate accounts." />
          </div>
        </section>
      </main>

      <footer className="footer shell">
        <Logo />
        <span>Personal medical study tool</span>
      </footer>
    </div>
  )
}

function Feature({ icon, title, text }) {
  return (
    <article className="feature-card">
      <div className="feature-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{text}</p>
    </article>
  )
}

