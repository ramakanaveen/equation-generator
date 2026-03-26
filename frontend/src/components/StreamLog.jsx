import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function StreamLog({ ph1Log, ph2Log, ph1Running, ph2Running, onClearPh1, onClearPh2 }) {
  const [tab, setTab] = useState('ph1')
  const bottomRef = useRef(null)

  const log = tab === 'ph1' ? ph1Log : ph2Log
  const content = log.join('')

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [content])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Tab bar */}
      <div style={{ display: 'flex', borderBottom: '1px solid #1f2937', flexShrink: 0, alignItems: 'center' }}>
        {[
          { key: 'ph1', label: `Ph1 Equations${ph1Running ? ' ●' : ''}` },
          { key: 'ph2', label: `Ph2 Java${ph2Running ? ' ●' : ''}` },
        ].map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            style={{
              flex: 1,
              padding: '8px 0',
              background: tab === key ? '#1f2937' : 'transparent',
              color: tab === key ? '#e0e0e0' : '#6b7280',
              borderRadius: 0,
              borderBottom: tab === key ? '2px solid #2563eb' : '2px solid transparent',
              fontSize: 13,
            }}
          >
            {label}
          </button>
        ))}
        <button
          onClick={() => tab === 'ph1' ? onClearPh1() : onClearPh2()}
          title="Clear log"
          style={{
            padding: '4px 10px', marginRight: 8,
            background: 'transparent', color: '#6b7280',
            border: '1px solid #374151', borderRadius: 3,
            fontSize: 11, flexShrink: 0,
          }}
        >
          Clear
        </button>
      </div>

      {/* Markdown render area */}
      <div style={{
        flex: 1, overflowY: 'auto', padding: '12px 16px',
        background: '#050505', color: '#e0e0e0',
        fontSize: 13, lineHeight: 1.7,
      }}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h3: ({ children }) => <h3 style={{ color: '#60a5fa', fontSize: 15, fontWeight: 700, margin: '20px 0 6px', borderBottom: '1px solid #1f2937', paddingBottom: 4 }}>{children}</h3>,
            h4: ({ children }) => <h4 style={{ color: '#93c5fd', fontSize: 13, fontWeight: 600, margin: '10px 0 4px' }}>{children}</h4>,
            p:  ({ children }) => <p style={{ margin: '4px 0 8px' }}>{children}</p>,
            strong: ({ children }) => <strong style={{ color: '#f9fafb' }}>{children}</strong>,
            em: ({ children }) => <em style={{ color: '#d1d5db' }}>{children}</em>,
            code: ({ inline, children }) => inline
              ? <code style={{ background: '#1f2937', padding: '1px 5px', borderRadius: 3, fontSize: 12, color: '#a3e635' }}>{children}</code>
              : <pre style={{ background: '#111827', padding: '10px 12px', borderRadius: 4, overflowX: 'auto', fontSize: 12, color: '#a3e635', margin: '8px 0' }}><code>{children}</code></pre>,
            table: ({ children }) => <table style={{ borderCollapse: 'collapse', width: '100%', margin: '8px 0', fontSize: 12 }}>{children}</table>,
            th: ({ children }) => <th style={{ border: '1px solid #374151', padding: '5px 10px', background: '#1f2937', color: '#d1d5db', textAlign: 'left' }}>{children}</th>,
            td: ({ children }) => <td style={{ border: '1px solid #374151', padding: '5px 10px' }}>{children}</td>,
            hr: () => <hr style={{ border: 'none', borderTop: '1px solid #1f2937', margin: '16px 0' }} />,
            ul: ({ children }) => <ul style={{ paddingLeft: 20, margin: '4px 0 8px' }}>{children}</ul>,
            li: ({ children }) => <li style={{ margin: '2px 0' }}>{children}</li>,
          }}
        >
          {content}
        </ReactMarkdown>
        {/* Status indicator appended below markdown */}
        {log.filter(l => l.startsWith('\n[')).map((l, i) => (
          <div key={i} style={{ color: '#6b7280', fontSize: 11, fontFamily: 'monospace', margin: '4px 0' }}>{l.trim()}</div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
