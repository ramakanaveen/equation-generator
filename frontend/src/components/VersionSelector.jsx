export default function VersionSelector({ versions, selectedVersion, onSelect }) {
  if (!versions.length) return null

  return (
    <div style={{
      display: 'flex', flexWrap: 'wrap', gap: 4, padding: '8px 12px',
      borderBottom: '1px solid #1f2937', background: '#111827',
    }}>
      {versions.map(v => {
        const isSelected = v.version === selectedVersion
        const date = new Date(v.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
        return (
          <button
            key={v.version}
            onClick={() => onSelect(v.version)}
            style={{
              padding: '4px 10px',
              background: isSelected ? '#2563eb' : '#1f2937',
              color: isSelected ? '#fff' : '#9ca3af',
              borderRadius: 4,
              fontSize: 12,
              border: isSelected ? '1px solid #3b82f6' : '1px solid #374151',
            }}
          >
            {v.version} · {v.equation_count}eq · {v.java_file_count}java · {date}
          </button>
        )
      })}
    </div>
  )
}
