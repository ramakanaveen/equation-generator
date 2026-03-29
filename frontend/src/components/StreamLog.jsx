import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { mdComponents } from '../mdComponents'

export default function StreamLog({ ph1Log, ph2Log, ph1Running, ph2Running, onClearPh1, onClearPh2 }) {
  const [tab, setTab] = useState('ph1')
  const bottomRef = useRef(null)

  const log = tab === 'ph1' ? ph1Log : ph2Log
  const content = log.join('')
  const isRunning = tab === 'ph1' ? ph1Running : ph2Running

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
        position: 'relative',
      }}>
        {!content && !isRunning ? (
          <div style={{
            position: 'absolute', inset: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#374151', fontSize: 13, fontStyle: 'italic', userSelect: 'none',
          }}>
            No log output yet — start a run to see streaming output here.
          </div>
        ) : (
          <>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
              {content}
            </ReactMarkdown>
            {/* Status indicators appended below markdown */}
            {log.filter(l => l.startsWith('\n[')).map((l, i) => (
              <div key={i} style={{ color: '#6b7280', fontSize: 11, fontFamily: 'monospace', margin: '4px 0' }}>{l.trim()}</div>
            ))}
            <div ref={bottomRef} />
          </>
        )}
      </div>
    </div>
  )
}
