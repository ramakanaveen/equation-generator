import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API } from '../config'
import { mdComponents } from '../mdComponents'

const POLICIES = [
  { key: 'policy.md', label: 'Equation Policy' },
  { key: 'code.md',   label: 'Code Policy' },
]

export default function PolicyEditor({ onClose }) {
  const [tab, setTab] = useState('policy.md')
  const [contents, setContents] = useState({ 'policy.md': '', 'code.md': '' })
  const [savedContents, setSavedContents] = useState({ 'policy.md': '', 'code.md': '' })
  const [viewMode, setViewMode] = useState('edit')
  const [feedback, setFeedback] = useState('')
  const [improving, setImproving] = useState(false)
  const [improveError, setImproveError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const abortRef = useRef(null)

  // Cancel any in-flight stream when modal unmounts
  useEffect(() => () => abortRef.current?.abort(), [])

  // Load both policies on mount
  useEffect(() => {
    POLICIES.forEach(({ key }) => {
      fetch(API.policy(key))
        .then(r => r.text())
        .then(text => {
          setContents(c => ({ ...c, [key]: text }))
          setSavedContents(c => ({ ...c, [key]: text }))
        })
        .catch(() => {})
    })
  }, [])

  const canRevert = contents[tab] !== savedContents[tab]

  const save = async () => {
    setSaving(true)
    setSaved(false)
    await fetch(API.policy(tab), { method: 'PUT', body: contents[tab] })
    setSavedContents(c => ({ ...c, [tab]: contents[tab] }))
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const revert = () => {
    setContents(c => ({ ...c, [tab]: savedContents[tab] }))
  }

  const improveWithAI = async () => {
    if (!feedback.trim() || improving) return
    const ctrl = new AbortController()
    abortRef.current = ctrl
    const snapshot = contents[tab]
    setImproving(true)
    setImproveError(null)
    setContents(c => ({ ...c, [tab]: '' }))

    try {
      const res = await fetch(API.improvePolicy(tab), {
        method: 'POST',
        signal: ctrl.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback, current_content: snapshot }),
      })
      if (!res.ok) throw new Error(`Server error ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        for (const line of decoder.decode(value).split('\n')) {
          if (!line.startsWith('data: ')) continue
          try {
            const ev = JSON.parse(line.slice(6))
            if (ev.stage === 'token') setContents(c => ({ ...c, [tab]: c[tab] + ev.text }))
            if (ev.stage === 'error') setImproveError(ev.text)
          } catch { /* ignore parse errors */ }
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        setImproveError(e.message || 'Stream failed')
        setContents(c => ({ ...c, [tab]: snapshot }))
      }
    } finally {
      setImproving(false)
    }
  }

  const stopImproving = () => {
    abortRef.current?.abort()
    setImproving(false)
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div style={{
        background: '#111827', borderRadius: 8, width: '70vw', height: '85vh',
        display: 'flex', flexDirection: 'column',
        border: '1px solid #374151', overflow: 'hidden',
      }}>

        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 16px', borderBottom: '1px solid #1f2937', flexShrink: 0,
        }}>
          <span style={{ fontWeight: 600, fontSize: 14, color: '#f9fafb' }}>Edit Policies</span>
          <button onClick={onClose} style={{ background: 'transparent', color: '#9ca3af', fontSize: 18, padding: '0 4px' }}>✕</button>
        </div>

        {/* Policy tabs + Edit/Preview toggle */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          borderBottom: '1px solid #1f2937', flexShrink: 0,
        }}>
          <div style={{ display: 'flex' }}>
            {POLICIES.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => { if (!improving) { setTab(key); setSaved(false) } }}
                disabled={improving}
                style={{
                  padding: '8px 20px', fontSize: 13,
                  background: tab === key ? '#1f2937' : 'transparent',
                  color: improving ? '#4b5563' : (tab === key ? '#e0e0e0' : '#6b7280'),
                  borderRadius: 0,
                  borderBottom: tab === key ? '2px solid #2563eb' : '2px solid transparent',
                  cursor: improving ? 'not-allowed' : 'pointer',
                }}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Edit / Preview toggle */}
          <div style={{ display: 'flex', gap: 2, marginRight: 12 }}>
            {['edit', 'preview'].map(mode => (
              <button
                key={mode}
                onClick={() => setViewMode(mode)}
                style={{
                  padding: '4px 12px', fontSize: 11, borderRadius: 3,
                  background: viewMode === mode ? '#2563eb' : '#1f2937',
                  color: viewMode === mode ? '#fff' : '#9ca3af',
                  border: '1px solid ' + (viewMode === mode ? '#3b82f6' : '#374151'),
                }}
              >
                {mode === 'edit' ? 'Edit' : 'Preview'}
              </button>
            ))}
          </div>
        </div>

        {/* Content area */}
        {viewMode === 'edit' ? (
          <textarea
            value={contents[tab]}
            onChange={e => setContents(c => ({ ...c, [tab]: e.target.value }))}
            disabled={improving}
            spellCheck={false}
            style={{
              flex: 1, resize: 'none', padding: 16,
              background: '#0d1117',
              color: improving ? '#6b7280' : '#e0e0e0',
              fontFamily: 'monospace', fontSize: 13, lineHeight: 1.6,
              border: 'none', outline: 'none',
              cursor: improving ? 'not-allowed' : 'text',
            }}
          />
        ) : (
          <div style={{
            flex: 1, overflowY: 'auto', padding: '12px 20px',
            background: '#0d1117', color: '#e0e0e0',
            fontSize: 13, lineHeight: 1.6,
          }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
              {contents[tab]}
            </ReactMarkdown>
          </div>
        )}

        {/* AI Improve section */}
        <div style={{
          borderTop: '1px solid #1f2937', padding: '10px 16px',
          background: '#0d1117', flexShrink: 0,
        }}>
          <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 1 }}>
            Improve with AI
          </div>
          <textarea
            value={feedback}
            onChange={e => setFeedback(e.target.value)}
            placeholder="Describe what to change… e.g. Add a rule to require momentum signals to include a volatility filter"
            rows={3}
            disabled={improving}
            style={{
              width: '100%', background: '#111827', color: '#e0e0e0',
              border: '1px solid #374151', borderRadius: 4,
              padding: '6px 8px', fontSize: 12, resize: 'none',
              fontFamily: 'inherit',
              cursor: improving ? 'not-allowed' : 'text',
            }}
          />
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
            <button
              onClick={improving ? stopImproving : improveWithAI}
              disabled={!improving && !feedback.trim()}
              style={{
                padding: '5px 14px', fontSize: 12, borderRadius: 4,
                background: improving ? '#1f2937' : (feedback.trim() ? '#1e3a5f' : '#111827'),
                color: improving ? '#f87171' : (feedback.trim() ? '#93c5fd' : '#4b5563'),
                border: '1px solid ' + (improving ? '#ef4444' : (feedback.trim() ? '#1d4ed8' : '#374151')),
                cursor: (!improving && !feedback.trim()) ? 'not-allowed' : 'pointer',
              }}
            >
              {improving ? '■ Stop' : 'Improve with AI ✦'}
            </button>
            {improving && (
              <span style={{ fontSize: 11, color: '#60a5fa' }}>
                Generating…
              </span>
            )}
            {improveError && (
              <span style={{ fontSize: 11, color: '#f87171', flex: 1 }}>
                Error: {improveError}
              </span>
            )}
          </div>
        </div>

        {/* Footer */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 16px', borderTop: '1px solid #1f2937', flexShrink: 0,
        }}>
          <div>
            {canRevert && (
              <button
                onClick={revert}
                disabled={improving}
                className="btn-ghost"
                style={{ fontSize: 12, color: '#f87171' }}
              >
                ↩ Revert
              </button>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {saved && <span style={{ color: '#4ade80', fontSize: 12 }}>Saved ✓</span>}
            <button onClick={onClose} className="btn-ghost" style={{ fontSize: 12 }}>Cancel</button>
            <button
              onClick={save}
              disabled={saving || improving}
              className="btn-primary"
              style={{ fontSize: 12 }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>

      </div>
    </div>
  )
}
