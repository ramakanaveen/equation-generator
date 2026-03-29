import { useCallback, useEffect, useRef, useState } from 'react'
import { API } from './config'
import ControlBar from './components/ControlBar'
import StreamLog from './components/StreamLog'
import VersionSelector from './components/VersionSelector'
import EquationsPanel from './components/EquationsPanel'
import CodePanel from './components/CodePanel'

const MIN_RIGHT = 280
const MAX_RIGHT = 900
const DEFAULT_RIGHT = 420

export default function App() {
  const [ph1Running, setPh1Running] = useState(false)
  const [ph2Running, setPh2Running] = useState(false)
  const [activeVersion, setActiveVersion] = useState(null)
  const [selectedVersion, setSelectedVersion] = useState(null)
  const [versions, setVersions] = useState([])
  const [queueCounts, setQueueCounts] = useState({ pending: 0, processing: 0, done: 0, failed: 0 })
  const [ph1Log, setPh1Log] = useState([])
  const [ph2Log, setPh2Log] = useState([])
  const [rightWidth, setRightWidth] = useState(DEFAULT_RIGHT)

  const pollRef = useRef(null)
  const dragging = useRef(false)
  const dragStartX = useRef(0)
  const dragStartW = useRef(DEFAULT_RIGHT)

  // -------------------------------------------------------------------
  // Resizable right panel
  // -------------------------------------------------------------------
  const onDragStart = useCallback((e) => {
    dragging.current = true
    dragStartX.current = e.clientX
    dragStartW.current = rightWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [rightWidth])

  useEffect(() => {
    const onMove = (e) => {
      if (!dragging.current) return
      const delta = dragStartX.current - e.clientX
      setRightWidth(Math.min(MAX_RIGHT, Math.max(MIN_RIGHT, dragStartW.current + delta)))
    }
    const onUp = () => {
      dragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  // -------------------------------------------------------------------
  // Data fetching
  // -------------------------------------------------------------------
  const refreshVersions = useCallback(async () => {
    const res = await fetch(API.versions)
    if (!res.ok) return
    const data = await res.json()
    setVersions(data)
    // On first load (no active run), restore the most recent version
    setSelectedVersion(v => v ?? (data[0]?.version ?? null))
  }, [])

  const refreshQueue = useCallback(async (version) => {
    if (!version) return
    const res = await fetch(API.queueStatus(version))
    if (res.ok) setQueueCounts(await res.json())
  }, [])

  useEffect(() => { refreshVersions() }, [refreshVersions])

  useEffect(() => {
    if (!activeVersion) return
    clearInterval(pollRef.current)
    pollRef.current = setInterval(() => {
      refreshVersions()
      refreshQueue(activeVersion)
      if (activeMeta?.status === 'done' && !ph1Running && !ph2Running) {
        clearInterval(pollRef.current)
      }
    }, 3000)
    return () => clearInterval(pollRef.current)
  }, [activeVersion, activeMeta, ph1Running, ph2Running, refreshVersions, refreshQueue])

  // Keep queue badges current when user views a non-active version
  useEffect(() => {
    if (!selectedVersion || selectedVersion === activeVersion) return
    refreshQueue(selectedVersion)
  }, [selectedVersion, activeVersion, refreshQueue])

  useEffect(() => {
    if (activeVersion) setSelectedVersion(activeVersion)
  }, [activeVersion])

  // -------------------------------------------------------------------
  // Ph1 — Generate
  // -------------------------------------------------------------------
  const startGenerate = useCallback(async (objective) => {
    setPh1Log([])
    setPh1Running(true)

    const res = await fetch(API.generate, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ objective }),
    })

    if (!res.ok) { setPh1Running(false); return }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()

    const read = async () => {
      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          const lines = decoder.decode(value).split('\n')
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            try {
              const event = JSON.parse(line.slice(6))
              if (event.stage === 'start') setActiveVersion(event.version)
              if (event.stage === 'token') setPh1Log(l => [...l, event.text])
              if (event.stage === 'batch_done') {
                setPh1Log(l => [...l, `\n[Batch ${event.batch}: ${event.count} equations, total ${event.total}]\n`])
                refreshVersions()
              }
              if (event.stage === 'gen_complete') {
                setPh1Log(l => [...l, `\n[Generation complete — ${event.total} equations]\n`])
              }
            } catch { /* ignore parse errors */ }
          }
        }
      } catch {
        setPh1Log(l => [...l, '\n[Stream disconnected]\n'])
      } finally {
        setPh1Running(false)
        refreshVersions()
      }
    }
    read()
  }, [refreshVersions])

  const stopGenerate = useCallback(async () => {
    await fetch(API.generateStop, { method: 'POST' })
    setPh1Running(false)
  }, [])

  // -------------------------------------------------------------------
  // Ph2 — Code
  // -------------------------------------------------------------------
  const startCode = useCallback(async (version) => {
    setPh2Log([])
    setPh2Running(true)

    const res = await fetch(API.code(version), { method: 'POST' })
    if (!res.ok) { setPh2Running(false); return }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()

    const read = async () => {
      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          const lines = decoder.decode(value).split('\n')
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            try {
              const event = JSON.parse(line.slice(6))
              if (event.stage === 'recovered') setPh2Log(l => [...l, `\n[Recovered ${event.count} interrupted batch(es) → pending]\n`])
              if (event.stage === 'token') setPh2Log(l => [...l, event.text])
              if (event.stage === 'code_batch_done') {
                setPh2Log(l => [...l, `\n[Coded batch: ${event.count} files, total ${event.total}]\n`])
                refreshVersions()
                refreshQueue(version)
              }
              if (event.stage === 'code_complete') {
                setPh2Log(l => [...l, `\n[Coding complete — ${event.total} Java files]\n`])
              }
              if (event.stage === 'error') {
                setPh2Log(l => [...l, `\n> ⚠ ERROR: ${event.text}\n\n`])
              }
            } catch { /* ignore parse errors */ }
          }
        }
      } catch {
        setPh2Log(l => [...l, '\n[Stream disconnected]\n'])
      } finally {
        setPh2Running(false)
        refreshVersions()
      }
    }
    read()
  }, [refreshVersions, refreshQueue])

  const stopCode = useCallback(async () => {
    await fetch(API.codeStop, { method: 'POST' })
    setPh2Running(false)
  }, [])

  const retryFailed = useCallback(async (version) => {
    await fetch(API.queueRetry(version), { method: 'POST' })
    refreshQueue(version)
  }, [refreshQueue])

  const deleteVersion = useCallback(async (version) => {
    if (!confirm(`Delete ${version} and all its files? This cannot be undone.`)) return
    await fetch(API.deleteVersion(version), { method: 'DELETE' })
    setVersions(vs => vs.filter(v => v.version !== version))
    setSelectedVersion(v => v === version ? null : v)
  }, [])

  const activeMeta = versions.find(v => v.version === (selectedVersion || activeVersion))

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* Left: Control */}
      <div style={{ width: 240, flexShrink: 0, borderRight: '1px solid #1f2937', padding: 16, overflowY: 'auto' }}>
        <ControlBar
          ph1Running={ph1Running}
          ph2Running={ph2Running}
          activeVersion={activeVersion}
          selectedVersion={selectedVersion}
          queueCounts={queueCounts}
          activeMeta={activeMeta}
          onGenerate={startGenerate}
          onStopGenerate={stopGenerate}
          onStartCode={() => startCode(selectedVersion || activeVersion)}
          onStopCode={stopCode}
          onRetryFailed={() => retryFailed(selectedVersion || activeVersion)}
        />
      </div>

      {/* Center: Logs */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <StreamLog
          ph1Log={ph1Log}
          ph2Log={ph2Log}
          ph1Running={ph1Running}
          ph2Running={ph2Running}
          onClearPh1={() => setPh1Log([])}
          onClearPh2={() => setPh2Log([])}
        />
      </div>

      {/* Drag handle */}
      <div
        onMouseDown={onDragStart}
        style={{
          width: 5, flexShrink: 0, cursor: 'col-resize',
          background: 'transparent',
          borderLeft: '1px solid #1f2937',
          transition: 'background 0.15s',
        }}
        onMouseEnter={e => e.currentTarget.style.background = '#2563eb44'}
        onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
      />

      {/* Right: Outputs */}
      <div style={{ width: rightWidth, flexShrink: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <VersionSelector
          versions={versions}
          selectedVersion={selectedVersion}
          activeVersion={activeVersion}
          onSelect={setSelectedVersion}
          onDelete={deleteVersion}
        />
        <RightPanel
          selectedVersion={selectedVersion}
          queueCounts={queueCounts}
          activeMeta={activeMeta}
          onStartCode={startCode}
        />
      </div>
    </div>
  )
}

function RightPanel({ selectedVersion, queueCounts, activeMeta, onStartCode }) {
  const [tab, setTab] = useState('equations')

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ display: 'flex', borderBottom: '1px solid #1f2937' }}>
        {['equations', 'java'].map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              flex: 1, padding: '8px 0',
              background: tab === t ? '#1f2937' : 'transparent',
              color: tab === t ? '#e0e0e0' : '#6b7280',
              borderRadius: 0,
              borderBottom: tab === t ? '2px solid #2563eb' : '2px solid transparent',
            }}
          >
            {t === 'equations' ? 'Equations' : 'Java'}
          </button>
        ))}
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
        {tab === 'equations'
          ? <EquationsPanel version={selectedVersion} equationCount={activeMeta?.equation_count ?? 0} />
          : <CodePanel version={selectedVersion} activeMeta={activeMeta} onRegenerate={(v) => onStartCode(v)} />
        }
      </div>
    </div>
  )
}
