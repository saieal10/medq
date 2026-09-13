import { useEffect, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { supabase } from './lib/supabase'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Practice from './pages/Practice'
import Library from './pages/Library'
import AIStudy from './pages/AIStudy'
import Mistakes from './pages/Mistakes'
import Bookmarks from './pages/Bookmarks'

function ProtectedRoute({ session, children }) {
  if (!session) return <Navigate to="/login" replace />
  return children
}

export default function App() {
  const [session, setSession] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session)
      setLoading(false)
    })

    const { data: listener } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession)
    })

    return () => listener.subscription.unsubscribe()
  }, [])

  if (loading) {
    return <div className="page-center"><div className="loader" /></div>
  }

  return (
    <Routes>
      <Route path="/" element={<Landing session={session} />} />
      <Route path="/login" element={session ? <Navigate to="/dashboard" replace /> : <Login />} />
      <Route path="/dashboard" element={<ProtectedRoute session={session}><Dashboard session={session} /></ProtectedRoute>} />
      <Route path="/practice" element={<ProtectedRoute session={session}><Practice session={session} /></ProtectedRoute>} />
      <Route path="/mistakes" element={<ProtectedRoute session={session}><Mistakes session={session} /></ProtectedRoute>} />
      <Route path="/bookmarks" element={<ProtectedRoute session={session}><Bookmarks session={session} /></ProtectedRoute>} />
      <Route path="/library" element={<ProtectedRoute session={session}><Library session={session} /></ProtectedRoute>} />

      {/* New primary AI experience. */}
      <Route path="/ai-study" element={<ProtectedRoute session={session}><AIStudy session={session} /></ProtectedRoute>} />
      {/* Existing MedBot links now open the improved AI Study workspace. */}
      <Route path="/medbot" element={<ProtectedRoute session={session}><AIStudy session={session} /></ProtectedRoute>} />

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
