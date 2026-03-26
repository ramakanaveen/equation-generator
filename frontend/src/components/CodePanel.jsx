import { useEffect, useState } from 'react'
import { API } from '../config'

export default function CodePanel({ version, activeMeta, onRegenerate }) {
  const [files, setFiles] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [content, setContent] = useState('')
  const [archives, setArchives] = useState([])
  const [regenerating, setRegenerating] = useState(false)

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
    fetch(API.javaArchives(version))
      .then(r => r.json())
      .then(setArchives)
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

  const downloadProject = () => { window.location.href = API.javaZip(version) }

  const regenerate = async () => {
    if (!confirm(`Archive existing Java files for ${version} and regenerate from equations?`)) return
    setRegenerating(true)
    const res = await fetch(API.javaRegenerate(version), { method: 'POST' })
    const data = await res.json()
    setFiles([])
    setSelectedFile(null)
    setContent('')
    setRegenerating(false)
    onRegenerate?.(version, data)
  }

  if (!version) return <div style={{ color: '#6b7280', fontSize: 13 }}>No version selected.</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>

      {/* Status + Download + Regenerate */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 10px', borderRadius: 6,
        background: isDone ? '#052e16' : '#111827',
        border: `1px solid ${isDone ? '#16a34a' : isGenerating ? '#b45309' : '#1f2937'}`,
      }}>
        <div style={{ fontSize: 12 }}>
          {isDone
            ? <span style={{ color: '#4ade80' }}>✓ Complete — {activeMeta.java_file_count} files</span>
            : isGenerating
              ? <span style={{ color: '#fbbf24' }}>In progress — {activeMeta?.java_file_count ?? files.length} files</span>
              : <span style={{ color: '#9ca3af' }}>{files.length} file{files.length !== 1 ? 's' : ''}</span>
          }
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button
            onClick={downloadProject}
            disabled={!canDownload}
            title={!isDone && canDownload ? 'Run may be incomplete' : ''}
            style={{
              padding: '4px 10px', fontSize: 11, borderRadius: 4,
              background: canDownload ? (isDone ? '#16a34a' : '#854d0e') : '#1f2937',
              color: canDownload ? '#fff' : '#4b5563',
              border: 'none', cursor: canDownload ? 'pointer' : 'not-allowed',
              opacity: canDownload ? 1 : 0.5,
            }}
          >
            {isDone ? 'Download ZIP' : canDownload ? 'Download (partial)' : 'Download ZIP'}
          </button>
          <button
            onClick={regenerate}
            disabled={regenerating || isGenerating}
            title="Archive current files and regenerate from equations using current code.md"
            style={{
              padding: '4px 10px', fontSize: 11, borderRadius: 4,
              background: '#1e3a5f', color: '#93c5fd',
              border: '1px solid #1d4ed8',
              cursor: regenerating || isGenerating ? 'not-allowed' : 'pointer',
              opacity: regenerating || isGenerating ? 0.5 : 1,
            }}
          >
            {regenerating ? 'Archiving…' : 'Regenerate Java'}
          </button>
        </div>
      </div>

      {/* Archive history */}
      {archives.length > 0 && (
        <div style={{ fontSize: 11, color: '#6b7280', padding: '4px 2px' }}>
          Archives: {archives.map(a => (
            <span key={a.run} style={{ marginRight: 8 }}>
              {a.run} ({a.files} files)
            </span>
          ))}
        </div>
      )}

      {/* File selector dropdown */}
      {files.length > 0 && (
        <select
          value={selectedFile ?? ''}
          onChange={e => setSelectedFile(e.target.value)}
          style={{
            width: '100%', padding: '6px 8px', fontSize: 12,
            background: '#1f2937', color: '#e0e0e0',
            border: '1px solid #374151', borderRadius: 4, cursor: 'pointer',
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
