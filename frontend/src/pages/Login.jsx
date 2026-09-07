import { useState } from 'react'
import { Link } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import Logo from '../components/Logo'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mode, setMode] = useState('login')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setMessage('')

    const action = mode === 'login'
      ? supabase.auth.signInWithPassword({ email, password })
      : supabase.auth.signUp({ email, password })

    const { error } = await action
    setBusy(false)

    if (error) {
      setMessage(error.message)
      return
    }

    if (mode === 'signup') {
      setMessage('Account created. If email confirmation is enabled, check your inbox.')
    }
  }

  return (
    <div className="auth-page">
      <Link className="auth-logo" to="/"><Logo /></Link>
      <div className="auth-card">
        <div className="eyebrow">{mode === 'login' ? 'WELCOME BACK' : 'CREATE ACCOUNT'}</div>
        <h1>{mode === 'login' ? 'Continue studying.' : 'Join your study space.'}</h1>
        <p>{mode === 'login' ? 'Sign in to your personal dashboard.' : 'Only create accounts for the two intended users.'}</p>

        <form onSubmit={submit}>
          <label>Email</label>
          <input type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" />
          <label>Password</label>
          <input type="password" minLength="6" required value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" />
          <button className="btn btn-primary auth-submit" disabled={busy}>
            {busy ? 'Please wait...' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        {message && <div className="auth-message">{message}</div>}

        <button className="switch-mode" onClick={() => {setMode(mode === 'login' ? 'signup' : 'login'); setMessage('')}}>
          {mode === 'login' ? 'Need to create the second account?' : 'Already have an account? Sign in'}
        </button>
      </div>
    </div>
  )
}
