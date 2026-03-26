import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API } from '../config'

export default function EquationsPanel({ version, equationCount }) {
  const [files, setFiles] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [content, setContent] = useState('')

  // Refresh file list whenever equation_count increases or version changes
  useEffect(() => {
    if (!version) return
    fetch(API.equations(version))
      .then(r => r.json())
      .then(data => {
        setFiles(data)
        if (data.length > 0) setSelectedFile(f => f && data.includes(f) ? f : data[data.length - 1])
      })
      .catch(() => {})
  }, [version, equationCount])

  // Load selected file content
  useEffect(() => {
    if (!version || !selectedFile) return
    fetch(API.equationFile(version, selectedFile))
      .then(r => r.ok ? r.text() : Promise.reject(r.status))
      .then(setContent)
      .catch(() => setContent(''))
  }, [version, selectedFile])

  if (!version) return <div style={{ color: '#6b7280', fontSize: 13 }}>No version selected.</div>
  if (!files.length) return <div style={{ color: '#6b7280', fontSize: 13 }}>No equation batches yet.</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {/* Batch selector */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {files.map(f => (
          <button
            key={f}
            onClick={() => setSelectedFile(f)}
            style={{
              padding: '3px 8px', fontSize: 11,
              background: selectedFile === f ? '#2563eb' : '#1f2937',
              color: selectedFile === f ? '#fff' : '#9ca3af',
              border: '1px solid #374151', borderRadius: 3,
            }}
          >
            {f.replace('.md', '')}
          </button>
        ))}
      </div>

      {/* Markdown content */}
      <div style={{
        background: '#111827', borderRadius: 4, padding: 12,
        fontSize: 13, lineHeight: 1.7, color: '#e0e0e0',
      }}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h3: ({children}) => <h3 style={{ color: '#60a5fa', fontSize: 15, fontWeight: 700, margin: '16px 0 6px' }}>{children}</h3>,
            h4: ({children}) => <h4 style={{ color: '#93c5fd', fontSize: 13, fontWeight: 600, margin: '10px 0 4px' }}>{children}</h4>,
            p:  ({children}) => <p style={{ margin: '4px 0 8px' }}>{children}</p>,
            strong: ({children}) => <strong style={{ color: '#f9fafb' }}>{children}</strong>,
            code: ({children}) => <code style={{ background: '#1f2937', padding: '1px 5px', borderRadius: 3, fontSize: 12, color: '#a3e635' }}>{children}</code>,
            table: ({children}) => <table style={{ borderCollapse: 'collapse', width: '100%', margin: '8px 0', fontSize: 12 }}>{children}</table>,
            th: ({children}) => <th style={{ border: '1px solid #374151', padding: '4px 8px', background: '#1f2937', color: '#d1d5db' }}>{children}</th>,
            td: ({children}) => <td style={{ border: '1px solid #374151', padding: '4px 8px' }}>{children}</td>,
            hr: () => <hr style={{ border: 'none', borderTop: '1px solid #1f2937', margin: '12px 0' }} />,
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  )
}
