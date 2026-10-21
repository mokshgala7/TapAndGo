import { useEffect } from 'react'
import { resolveFileUrl, getDocumentDisplayName } from '../../context/AuthContext.jsx'

export default function DocumentViewerModal({ doc, onClose }) {
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  if (!doc || !doc.path) return null

  const fileUrl = resolveFileUrl(doc.path)
  const cleanPath = (doc.path ? doc.path.split('?')[0].split('#')[0] : '').toLowerCase()
  const isImage =
    cleanPath.endsWith('.png') ||
    cleanPath.endsWith('.jpg') ||
    cleanPath.endsWith('.jpeg') ||
    cleanPath.endsWith('.webp') ||
    cleanPath.endsWith('.gif') ||
    doc.path.startsWith('data:image')
  const isPdf = cleanPath.endsWith('.pdf')

  const fileName = (() => {
    try {
      const withoutQuery = doc.path.split('?')[0].split('#')[0]
      const raw = withoutQuery.split('/').pop() || 'document'
      return decodeURIComponent(raw)
    } catch {
      return 'document'
    }
  })()

  const displayName = doc.displayName || getDocumentDisplayName(doc.userName, doc.title)

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        background: 'rgba(20, 18, 16, 0.75)',
        backdropFilter: 'blur(4px)',
        WebkitBackdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '16px',
        boxSizing: 'border-box',
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: 'var(--card, #ffffff)',
          color: 'var(--text, #1e1b16)',
          borderRadius: 20,
          border: '1px solid var(--line, #e7e1d6)',
          width: '100%',
          maxWidth: 520,
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 20px 60px rgba(30,27,22,0.25)',
          overflow: 'hidden',
          boxSizing: 'border-box',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '16px 20px',
            borderBottom: '1px solid var(--line, #e7e1d6)',
            gap: 12,
          }}
        >
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <h3 style={{ margin: 0, fontSize: 17, fontWeight: 800, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {doc.title || 'Verification Document'}
              </h3>
              <span style={{ fontSize: 10, fontWeight: 800, padding: '2px 8px', borderRadius: 99, background: 'rgba(23, 122, 71, 0.12)', color: '#177a47' }}>
                Verified
              </span>
            </div>
            <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--muted, #6b6458)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {displayName}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close document preview"
            style={{
              border: 0,
              background: 'var(--bg, #f6f3ee)',
              color: 'var(--text, #1e1b16)',
              borderRadius: '50%',
              width: 44,
              height: 44,
              minWidth: 44,
              minHeight: 44,
              display: 'grid',
              placeItems: 'center',
              cursor: 'pointer',
              fontSize: 20,
              padding: 0,
            }}
          >
            ✕
          </button>
        </div>

        {/* Modal Body */}
        <div
          style={{
            padding: 16,
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'var(--bg, #f6f3ee)',
            minHeight: 220,
            maxHeight: '65vh',
            boxSizing: 'border-box',
          }}
        >
          {isImage ? (
            <img
              src={fileUrl}
              alt={doc.title}
              style={{
                maxWidth: '100%',
                maxHeight: '58vh',
                objectFit: 'contain',
                borderRadius: 12,
                boxShadow: '0 4px 16px rgba(30,27,22,0.08)',
                background: '#fff',
              }}
            />
          ) : isPdf ? (
            <div style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, textAlign: 'center', padding: '24px 12px' }}>
              <div style={{ width: 64, height: 64, borderRadius: 16, background: 'rgba(239, 68, 68, 0.12)', display: 'grid', placeItems: 'center', color: '#c8372d', fontSize: 28 }}>
                📄
              </div>
              <div>
                <strong style={{ display: 'block', fontSize: 15, marginBottom: 4, wordBreak: 'break-word' }}>{displayName}</strong>
                <span style={{ fontSize: 12, color: 'var(--muted, #6b6458)' }}>PDF Document · Click below to view full document</span>
              </div>
              <a
                href={fileUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 8,
                  minHeight: 44,
                  padding: '10px 20px',
                  borderRadius: 12,
                  background: 'var(--yellow, #fdd34d)',
                  color: '#22201b',
                  fontWeight: 800,
                  fontSize: 14,
                  textDecoration: 'none',
                  boxShadow: '0 2px 8px rgba(30,27,22,0.08)',
                }}
              >
                Open PDF Document ↗
              </a>
            </div>
          ) : (
            <div style={{ width: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, textAlign: 'center', padding: '24px 12px' }}>
              <div style={{ width: 64, height: 64, borderRadius: 16, background: 'rgba(59, 130, 246, 0.12)', display: 'grid', placeItems: 'center', color: '#8a6400', fontSize: 28 }}>
                📎
              </div>
              <div>
                <strong style={{ display: 'block', fontSize: 15, marginBottom: 4, wordBreak: 'break-word' }}>{displayName}</strong>
                <span style={{ fontSize: 12, color: 'var(--muted, #6b6458)' }}>Verification Document</span>
              </div>
              <a
                href={fileUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 8,
                  minHeight: 44,
                  padding: '10px 20px',
                  borderRadius: 12,
                  background: 'var(--yellow, #fdd34d)',
                  color: '#22201b',
                  fontWeight: 800,
                  fontSize: 14,
                  textDecoration: 'none',
                }}
              >
                Open File ↗
              </a>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div
          style={{
            padding: '12px 16px',
            borderTop: '1px solid var(--line, #e7e1d6)',
            display: 'flex',
            gap: 10,
            justifyContent: 'flex-end',
            flexWrap: 'wrap',
          }}
        >
          {fileUrl && (
            <a
              href={fileUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: 44,
                padding: '0 16px',
                borderRadius: 10,
                border: '1px solid var(--line, #e7e1d6)',
                background: 'var(--card, #fff)',
                color: 'var(--text, #1e1b16)',
                fontSize: 13,
                fontWeight: 700,
                textDecoration: 'none',
                cursor: 'pointer',
                flex: 1,
                textAlign: 'center',
                boxSizing: 'border-box',
              }}
            >
              Open in New Tab ↗
            </a>
          )}
          <button
            type="button"
            onClick={onClose}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: 44,
              padding: '0 20px',
              borderRadius: 10,
              border: 0,
              background: 'var(--yellow, #fdd34d)',
              color: '#22201b',
              fontSize: 13,
              fontWeight: 800,
              cursor: 'pointer',
              flex: 1,
              boxSizing: 'border-box',
            }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
