// Shared ReactMarkdown component overrides for dark-theme rendering.
// Used by StreamLog and PolicyEditor.
export const mdComponents = {
  h1: ({ children }) => <h1 style={{ color: '#60a5fa', fontSize: 17, fontWeight: 700, margin: '20px 0 8px', borderBottom: '1px solid #1f2937', paddingBottom: 4 }}>{children}</h1>,
  h2: ({ children }) => <h2 style={{ color: '#60a5fa', fontSize: 15, fontWeight: 700, margin: '18px 0 6px', borderBottom: '1px solid #1f2937', paddingBottom: 4 }}>{children}</h2>,
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
  ol: ({ children }) => <ol style={{ paddingLeft: 20, margin: '4px 0 8px' }}>{children}</ol>,
  li: ({ children }) => <li style={{ margin: '2px 0' }}>{children}</li>,
  blockquote: ({ children }) => <blockquote style={{ borderLeft: '3px solid #ef4444', paddingLeft: 12, margin: '8px 0', color: '#fca5a5', background: '#1c0a0a', borderRadius: '0 4px 4px 0', padding: '6px 12px' }}>{children}</blockquote>,
}
