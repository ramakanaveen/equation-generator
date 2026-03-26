import { useEffect, useState } from 'react'
import { API } from '../config'

const POLICIES = [
  { key: 'policy.md', label: 'Equation Policy' },
  { key: 'code.md',   label: 'Code Policy' },
]

export default function PolicyEditor({ onClose }) {
  const [tab, setTab] = useState('policy.md')
  const [contents, setContents] = useState({ 'policy.md': '', 'code.md': '' })
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    POLICIES.forEach(({ key }) => {
      fetch(API.policy(key))
        .then(r => r.text())
        .then(text => setContents(c => ({ ...c, [key]: text })))
        .catch(() => {})
    })
  }, [])

  const save = async () => {
    setSaving(true)
    setSaved(false)
    await fetch(API.policy(tab), {
      method: 'PUT',
      body: contents[tab],
    })
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div style={{
        background: '#111827', borderRadius: 8, width: '70vw', height: '80vh',
        display: 'flex', flexDirection: 'column',
        border: '1px solid #374151', overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 16px', borderBottom: '1px solid #1f2937',
        }}>
          <span style={{ fontWeight: 600, fontSize: 14, color: '#f9fafb' }}>Edit Policies</span>
          <button onClick={onClose} style={{ background: 'transparent', color: '#9ca3af', fontSize: 18, padding: '0 4px' }}>✕</button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', borderBottom: '1px solid #1f2937' }}>
          {POLICIES.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => { setTab(key); setSaved(false) }}
              style={{
                padding: '8px 20px', fontSize: 13,
                background: tab === key ? '#1f2937' : 'transparent',
                color: tab === key ? '#e0e0e0' : '#6b7280',
                borderRadius: 0,
                borderBottom: tab === key ? '2px solid #2563eb' : '2px solid transparent',
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Editor */}
        <textarea
          value={contents[tab]}
          onChange={e => setContents(c => ({ ...c, [tab]: e.target.value }))}
          spellCheck={false}
          style={{
            flex: 1, resize: 'none', padding: 16,
            background: '#0d1117', color: '#e0e0e0',
            fontFamily: 'monospace', fontSize: 13, lineHeight: 1.6,
            border: 'none', outline: 'none',
          }}
        />

        {/* Footer */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 10,
          padding: '10px 16px', borderTop: '1px solid #1f2937',
        }}>
          {saved && <span style={{ color: '#4ade80', fontSize: 12 }}>Saved</span>}
          <button onClick={onClose} className="btn-ghost" style={{ fontSize: 12 }}>Cancel</button>
          <button
            onClick={save}
            disabled={saving}
            className="btn-primary"
            style={{ fontSize: 12 }}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
