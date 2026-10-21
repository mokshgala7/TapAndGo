import { useState } from 'react'
import { useAuth } from '../../context/AuthContext.jsx'

export default function DocumentUploadModal({ onClose, flash, accountType = 'passenger' }) {
  const { uploadReplacementDocument, refreshProfile } = useAuth()
  const isDriver = accountType === 'driver'

  const docOptions = [
    { value: 'profile_photo', label: 'Profile Photo', accept: 'image/png,image/jpeg,image/webp' },
    { value: 'id_document', label: 'Govt ID / Aadhaar / PAN', accept: 'image/png,image/jpeg,image/webp,application/pdf' },
    { value: 'signature_document', label: 'Digital Signature', accept: 'image/png,image/jpeg,image/webp' },
    ...(isDriver
      ? [
          { value: 'rc_document', label: 'RC Book Document', accept: 'image/png,image/jpeg,image/webp,application/pdf' },
          { value: 'licence_document', label: 'Driving Licence Document', accept: 'image/png,image/jpeg,image/webp,application/pdf' },
          { value: 'insurance_document', label: 'Insurance Document', accept: 'image/png,image/jpeg,image/webp,application/pdf' },
        ]
      : []),
  ]

  const [selectedType, setSelectedType] = useState(docOptions[0].value)
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')

  const activeOption = docOptions.find((opt) => opt.value === selectedType) || docOptions[0]

  const handleFileChange = (e) => {
    setError('')
    const chosen = e.target.files?.[0]
    if (!chosen) {
      setFile(null)
      setPreview(null)
      return
    }

    if (chosen.size > 5 * 1024 * 1024) {
      setError('File size must not exceed 5 MB.')
      setFile(null)
      setPreview(null)
      return
    }

    setFile(chosen)
    if (chosen.type.startsWith('image/')) {
      const reader = new FileReader()
      reader.onload = () => setPreview(reader.result)
      reader.readAsDataURL(chosen)
    } else {
      setPreview(null)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!file) {
      setError('Please choose a file to upload.')
      return
    }

    setUploading(true)
    setError('')

    const res = await uploadReplacementDocument(selectedType, file)
    setUploading(false)

    if (res.success) {
      await refreshProfile()
      onClose()
      flash?.(res.message || 'Replacement document uploaded successfully.')
    } else {
      setError(res.message || 'Failed to upload document.')
    }
  }

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
          maxWidth: 480,
          boxShadow: '0 24px 60px rgba(30, 27, 22, 0.25)',
          overflow: 'hidden',
          animation: 'fadeScale 0.15s ease-out',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '16px 20px',
            borderBottom: '1px solid var(--line, #e7e1d6)',
          }}
        >
          <div>
            <h3 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>Upload Replacement Document</h3>
            <span style={{ fontSize: 12, color: 'var(--muted, #6b6458)' }}>Admin approval granted for document edit</span>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              fontSize: 22,
              cursor: 'pointer',
              color: 'var(--muted, #6b6458)',
              padding: '4px 8px',
              borderRadius: 8,
              lineHeight: 1,
            }}
          >
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '20px' }}>
          {error && (
            <div
              style={{
                background: '#fdf2f0',
                color: '#a52b23',
                border: '1px solid #f8cfc9',
                padding: '10px 14px',
                borderRadius: 10,
                fontSize: 13,
                marginBottom: 16,
                fontWeight: 600,
              }}
            >
              {error}
            </div>
          )}

          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 700, marginBottom: 6, color: 'var(--text, #1e1b16)' }}>
              Select Document to Replace
            </label>
            <select
              value={selectedType}
              onChange={(e) => {
                setSelectedType(e.target.value)
                setFile(null)
                setPreview(null)
              }}
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 10,
                border: '1px solid var(--line, #ddd5c8)',
                background: 'var(--bg, #fbf9f5)',
                color: 'var(--text, #1e1b16)',
                fontSize: 14,
                fontWeight: 500,
              }}
            >
              {docOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', fontSize: 13, fontWeight: 700, marginBottom: 6, color: 'var(--text, #1e1b16)' }}>
              Choose Replacement File (Max 5 MB)
            </label>
            <input
              type="file"
              accept={activeOption.accept}
              onChange={handleFileChange}
              style={{
                width: '100%',
                padding: '8px',
                fontSize: 13,
                border: '1px dashed var(--line, #ddd5c8)',
                borderRadius: 10,
                background: 'var(--bg, #fbf9f5)',
                boxSizing: 'border-box',
              }}
            />
          </div>

          {preview && (
            <div style={{ marginBottom: 16, textAlign: 'center' }}>
              <img
                src={preview}
                alt="Upload preview"
                style={{
                  maxHeight: 140,
                  maxWidth: '100%',
                  borderRadius: 10,
                  objectFit: 'contain',
                  border: '1px solid var(--line, #ddd5c8)',
                }}
              />
            </div>
          )}

          {file && !preview && (
            <div style={{ fontSize: 13, color: 'var(--muted, #6b6458)', marginBottom: 16 }}>
              Selected file: <b>{file.name}</b> ({(file.size / 1024).toFixed(1)} KB)
            </div>
          )}

          <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
            <button
              type="submit"
              disabled={uploading || !file}
              style={{
                flex: 1,
                padding: '12px 16px',
                borderRadius: 10,
                background: file ? '#FDD34D' : '#ddd5c8',
                color: '#1e1b16',
                border: 'none',
                fontWeight: 800,
                fontSize: 14,
                cursor: uploading || !file ? 'not-allowed' : 'pointer',
                opacity: uploading ? 0.7 : 1,
              }}
            >
              {uploading ? 'Uploading...' : 'Upload Replacement'}
            </button>
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: '12px 16px',
                borderRadius: 10,
                background: 'transparent',
                border: '1px solid var(--line, #ddd5c8)',
                color: 'var(--text, #1e1b16)',
                fontWeight: 600,
                fontSize: 14,
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
