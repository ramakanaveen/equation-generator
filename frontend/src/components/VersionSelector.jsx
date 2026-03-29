export default function VersionSelector({ versions, selectedVersion, activeVersion, onSelect, onDelete }) {
  if (!versions.length) return null

  return (
    <div style={{
      display: 'flex', flexWrap: 'nowrap', overflowX: 'auto', gap: 4, padding: '8px 12px',
      borderBottom: '1px solid #1f2937', background: '#111827',
    }}>
      {versions.map(v => {
        const isSelected = v.version === selectedVersion
        const isActive = v.version === activeVersion
        const date = new Date(v.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
        return (
          <div key={v.version} style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
            <button
              onClick={() => onSelect(v.version)}
              style={{
                padding: '4px 8px 4px 10px',
                background: isSelected ? '#2563eb' : '#1f2937',
                color: isSelected ? '#fff' : '#9ca3af',
                borderRadius: '4px 0 0 4px',
                fontSize: 12,
                border: isSelected ? '1px solid #3b82f6' : '1px solid #374151',
                borderRight: 'none',
              }}
            >
              {v.version} · {v.equation_count}eq · {v.java_file_count}java · {date}
            </button>
            <button
              onClick={() => onDelete(v.version)}
              disabled={isActive}
              title={isActive ? 'Cannot delete the active run' : `Delete ${v.version}`}
              style={{
                padding: '4px 6px',
                background: isSelected ? '#2563eb' : '#1f2937',
                color: isActive ? '#4b5563' : (isSelected ? '#fca5a5' : '#6b7280'),
                borderRadius: '0 4px 4px 0',
                fontSize: 11,
                border: isSelected ? '1px solid #3b82f6' : '1px solid #374151',
                cursor: isActive ? 'not-allowed' : 'pointer',
                lineHeight: 1,
              }}
              onMouseEnter={e => { if (!isActive) e.currentTarget.style.color = '#ef4444' }}
              onMouseLeave={e => { if (!isActive) e.currentTarget.style.color = isSelected ? '#fca5a5' : '#6b7280' }}
            >
              ×
            </button>
          </div>
        )
      })}
    </div>
  )
}
