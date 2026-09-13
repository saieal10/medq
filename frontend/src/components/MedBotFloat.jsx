import { Sparkles } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

export default function MedBotFloat() {
  const navigate = useNavigate()
  return (
    <button
      type="button"
      onClick={() => navigate('/ai-study')}
      aria-label="Open MedQ AI Study"
      title="Open MedQ AI Study"
      style={{
        position: 'fixed', right: 22, bottom: 22, zIndex: 50,
        border: '0', borderRadius: 999, padding: '13px 17px',
        background: 'linear-gradient(135deg,#5b5cf0,#7147df)', color: '#fff',
        display: 'flex', alignItems: 'center', gap: 8, fontWeight: 800,
        cursor: 'pointer', boxShadow: '0 12px 28px rgba(71,65,180,.28)'
      }}
    >
      <Sparkles size={17} /> AI Study
    </button>
  )
}
