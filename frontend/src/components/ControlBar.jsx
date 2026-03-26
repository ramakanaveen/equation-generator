import { useState } from 'react'
import PolicyEditor from './PolicyEditor'

export default function ControlBar({
  ph1Running, ph2Running,
  activeVersion, selectedVersion,
  queueCounts, activeMeta,
  onGenerate, onStopGenerate,
  onStartCode, onStopCode,
  onRetryFailed,
}) {
  const [showPolicyEditor, setShowPolicyEditor] = useState(false)
  const [objective, setObjective] = useState('')

  const version = selectedVersion || activeVersion
  const eqCount = activeMeta?.equation_count ?? 0
  const javaCount = activeMeta?.java_file_count ?? 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: '#f9fafb' }}>Equation Generator</div>

      {/* Objective input */}
      <div>
        <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Objective (optional)</div>
        <textarea
          value={objective}
          onChange={e => setObjective(e.target.value)}
          placeholder="e.g. focus on mean-reversion"
          rows={3}
          style={{
            width: '100%', background: '#1f2937', color: '#e0e0e0',
            border: '1px solid #374151', borderRadius: 4, padding: '6px 8px',
            fontSize: 12, resize: 'vertical',
          }}
        />
      </div>

      {/* Ph1 controls */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ fontSize: 11, color: '#6b7280', textTransform: 'uppercase', letterSpacing: 1 }}>Phase 1 — Equations</div>
        {!ph1Running
          ? <button className="btn-primary" onClick={() => onGenerate(objective)}>Generate ▶</button>
          : <button className="btn-danger" onClick={onStopGenerate}>Stop Ph1</button>
        }
      </div>

      {/* Ph2 controls */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ fontSize: 11, color: '#6b7280', textTransform: 'uppercase', letterSpacing: 1 }}>Phase 2 — Java Code</div>
        {!ph2Running
          ? <button className="btn-primary" onClick={onStartCode} disabled={!version}>Start Coding ▶</button>
          : <button className="btn-danger" onClick={onStopCode}>Stop Ph2</button>
        }
        <button className="btn-ghost" onClick={onRetryFailed} disabled={!version || (queueCounts.failed === 0)}>
          Retry Failed ({queueCounts.failed ?? 0})
        </button>
      </div>

      {/* Live counters */}
      {version && (
        <div style={{ fontSize: 12, color: '#9ca3af', paddingTop: 4, borderTop: '1px solid #1f2937' }}>
          <div style={{ fontWeight: 600, color: '#d1d5db', marginBottom: 4 }}>{version}</div>
          <div>{eqCount} equations · {javaCount} java files</div>
        </div>
      )}

      {/* Queue badges */}
      {version && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          <span className="badge badge-pending">pending {queueCounts.pending ?? 0}</span>
          <span className="badge badge-processing">active {queueCounts.processing ?? 0}</span>
          <span className="badge badge-done">done {queueCounts.done ?? 0}</span>
          <span className="badge badge-failed">failed {queueCounts.failed ?? 0}</span>
        </div>
      )}

      {/* Policy editor */}
      <div style={{ paddingTop: 4, borderTop: '1px solid #1f2937' }}>
        <button
          className="btn-ghost"
          onClick={() => setShowPolicyEditor(true)}
          style={{ width: '100%', fontSize: 12 }}
        >
          Edit Policies
        </button>
      </div>

      {showPolicyEditor && <PolicyEditor onClose={() => setShowPolicyEditor(false)} />}
    </div>
  )
}
