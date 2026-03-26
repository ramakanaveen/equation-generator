import { useEffect, useState } from 'react'
import { API } from '../config'

export default function CodePanel({ version, activeMeta }) {
  const [files, setFiles] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [content, setContent] = useState('')

  const isDone = activeMeta?.status === 'done'
  const isGenerating = activeMeta?.status === 'generating' || activeMeta?.status === 'coding'
  const canDownload = files.length > 0

  useEffect(() => {
    if (!version) return
    fetch(API.java(version))
      .then(r => r.json())
      .then(data => {
        setFiles(data)
        if (data.length > 0 && !selectedFile) setSelectedFile(data[0])
      })
      .catch(() => {})
  }, [version, activeMeta?.java_file_count])

  useEffect(() => {
    if (!version || !selectedFile) return
    fetch(API.javaFile(version, selectedFile))
      .then(r => r.ok ? r.text() : Promise.reject(r.status))
      .then(setContent)
      .catch(() => setContent(''))
  }, [version, selectedFile])

  const downloadFile = () => {
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = selectedFile
    a.click()
    URL.revokeObjectURL(url)
  }

  const downloadProject = () => {
    window.location.href = API.javaZip(version)
  }

  if (!version) return <div style={{ color: '#6b7280', fontSize: 13 }}>No version selected.</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>

      {/* Download Project button */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 10px', borderRadius: 6,
        background: isDone ? '#052e16' : '#111827',
        border: `1px solid ${isDone ? '#16a34a' : isGenerating ? '#b45309' : '#1f2937'}`,
      }}>
        <div style={{ fontSize: 12 }}>
          {isDone
            ? <span style={{ color: '#4ade80' }}>✓ Coding complete — {activeMeta.java_file_count} files</span>
            : isGenerating
              ? <span style={{ color: '#fbbf24' }}>Coding in progress — {activeMeta?.java_file_count ?? files.length} files so far</span>
              : <span style={{ color: '#9ca3af' }}>{files.length} file{files.length !== 1 ? 's' : ''} (interrupted)</span>
          }
        </div>
        <button
          onClick={downloadProject}
          disabled={!canDownload}
          title={!isDone && canDownload ? 'Run may be incomplete — downloading available files' : ''}
          style={{
            padding: '5px 12px', fontSize: 12, borderRadius: 4,
            background: canDownload ? (isDone ? '#16a34a' : '#854d0e') : '#1f2937',
            color: canDownload ? '#fff' : '#4b5563',
            border: 'none',
            cursor: canDownload ? 'pointer' : 'not-allowed',
            opacity: canDownload ? 1 : 0.5,
          }}
        >
          {isDone ? 'Download Project ZIP' : canDownload ? 'Download (partial)' : 'Download Project ZIP'}
        </button>
      </div>

      {/* File selector dropdown */}
      {files.length > 0 && (
        <select
          value={selectedFile ?? ''}
          onChange={e => setSelectedFile(e.target.value)}
          style={{
            width: '100%', padding: '6px 8px', fontSize: 12,
            background: '#1f2937', color: '#e0e0e0',
            border: '1px solid #374151', borderRadius: 4,
            cursor: 'pointer',
          }}
        >
          {files.map(f => <option key={f} value={f}>{f}</option>)}
        </select>
      )}

      {!files.length && (
        <div style={{ color: '#6b7280', fontSize: 13 }}>No Java files yet.</div>
      )}

      {/* Individual file download + preview */}
      {selectedFile && (
        <>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button className="btn-secondary" onClick={downloadFile} style={{ fontSize: 11, padding: '3px 10px' }}>
              Download {selectedFile}
            </button>
          </div>
          <pre style={{
            background: '#050505', borderRadius: 4, padding: 12,
            fontSize: 12, lineHeight: 1.6, overflowX: 'auto',
            color: '#93c5fd', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            border: '1px solid #1f2937',
          }}>
            {content}
          </pre>
        </>
      )}
    </div>
  )
}
