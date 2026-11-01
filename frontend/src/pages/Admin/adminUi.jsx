// Small presentational components shared by the newer admin pages (same look as the helpers inside Admin.jsx).
export function LoadState({ error, children }) { return error ? <p className="admin-error">{error}</p> : children }
export function Badge({ value }) { return <span className={`status status-${String(value || 'unknown').toLowerCase()}`}>{value || 'unknown'}</span> }
export function Empty({ text = 'No live records yet.' }) { return <div className="empty-state">{text}</div> }
