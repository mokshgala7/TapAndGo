import { useState, useEffect } from 'react'
import { useAuth, resolveFileUrl, hasValidBankDetails, getDocumentDisplayName, isValidUpi } from '../../context/AuthContext.jsx'
import { useDriverData } from '../../context/DriverContext.jsx'
import DocumentViewerModal from '../../components/Common/DocumentViewerModal.jsx'
import DocumentUploadModal from '../../components/Common/DocumentUploadModal.jsx'
import { inr } from './format.js'

const Icon = ({ children, className = '' }) => (
  <span className={`material-symbols-outlined ${className}`} aria-hidden="true">
    {children}
  </span>
)

function FieldCard({ label, value, displayValue, editable, editing, onChange, placeholder, lockedReason }) {
  const isEditing = editable && editing
  return (
    <div className="field-card">
      <div className="field-top">
        <span className="field-label">{label}</span>
        <span className={`field-tag ${isEditing ? 'editable' : 'readonly'}`}>
          {isEditing ? 'Editable' : (lockedReason || 'Locked')}
        </span>
      </div>
      {isEditing ? (
        <input value={value} placeholder={placeholder || `Enter ${label}`} onChange={(e) => onChange(e.target.value)} autoComplete="off" />
      ) : (
        <span className="field-value">{displayValue !== undefined && displayValue !== null && displayValue !== '' ? displayValue : (value || '\u2014')}</span>
      )}
    </div>
  )
}

function DocCard({ title, path, type = 'Document', userName, onPreview }) {
  const { user } = useAuth()
  const nameToUse = (userName || user?.name || '').trim() || 'User'
  const displayName = getDocumentDisplayName(nameToUse, title)
  const fileUrl = resolveFileUrl(path)
  const cleanPath = (path ? path.split('?')[0].split('#')[0] : '').toLowerCase()
  const isImage = path && (
    cleanPath.endsWith('.png') ||
    cleanPath.endsWith('.jpg') ||
    cleanPath.endsWith('.jpeg') ||
    cleanPath.endsWith('.webp') ||
    cleanPath.endsWith('.gif') ||
    path.startsWith('data:image')
  )

  const handleOpen = (e) => {
    if (onPreview && path) {
      e.preventDefault()
      onPreview({ title, path, type, displayName, userName: nameToUse })
    }
  }

  return (
    <div
      className="field-card"
      style={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        minWidth: 0,
        boxSizing: 'border-box',
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div className="field-top">
          <span className="field-label">{title}</span>
          <span className={`field-tag ${path ? 'editable' : 'readonly'}`}>
            {path ? 'Verified' : 'Missing'}
          </span>
        </div>
        {path ? (
          <div
            style={{
              marginTop: 10,
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              minWidth: 0,
              cursor: onPreview ? 'pointer' : 'default',
            }}
            onClick={handleOpen}
          >
            {isImage ? (
              <img
                src={fileUrl}
                alt={title}
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: 8,
                  objectFit: 'cover',
                  border: '1px solid var(--line)',
                  flexShrink: 0,
                  background: '#f0ece4',
                }}
              />
            ) : (
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: 8,
                  background: '#f0ece4',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}
              >
                <Icon className="text-gray-500">description</Icon>
              </div>
            )}
            <div style={{ minWidth: 0, flex: 1 }}>
              <span
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: 'var(--text)',
                  display: 'block',
                  wordBreak: 'break-word',
                  lineHeight: 1.35,
                  maxWidth: '100%',
                }}
                title={displayName}
              >
                {displayName}
              </span>
              <span style={{ fontSize: 11, color: 'var(--muted)', display: 'block', marginTop: 3 }}>
                {isImage ? 'Image Document' : 'Document'}
              </span>
            </div>
          </div>
        ) : (
          <span className="field-value" style={{ marginTop: 8 }}>Not uploaded</span>
        )}
      </div>

      {path && (
        <a
          href={fileUrl}
          target="_blank"
          rel="noopener noreferrer"
          onClick={handleOpen}
          style={{
            marginTop: 12,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
            minHeight: 44,
            padding: '10px 14px',
            fontSize: 13,
            fontWeight: 800,
            color: 'var(--text)',
            background: 'var(--bg)',
            border: '1px solid var(--line)',
            borderRadius: 8,
            textDecoration: 'none',
            cursor: 'pointer',
            boxSizing: 'border-box',
            width: '100%',
          }}
        >
          <Icon style={{ fontSize: 17 }}>visibility</Icon> View {type}
        </a>
      )}
    </div>
  )
}

function DriverAccount({ flash, dark, setDark, notifications, setNotifications, onLogout, openModal }) {
  const { user, saveProfileToDb, requestAdminAccess, refreshProfile } = useAuth()
  const { walletBalance } = useDriverData()

  const [editing, setEditing] = useState(false)
  const [requestingBank, setRequestingBank] = useState(false)
  const [requestingDoc, setRequestingDoc] = useState(false)
  const [requestingPhone, setRequestingPhone] = useState(false)
  const [previewDoc, setPreviewDoc] = useState(null)
  const [showDocUploadModal, setShowDocUploadModal] = useState(false)

  const [bankForm, setBankForm] = useState({
    bank_account_holder: user?.bank_account_holder || '',
    bank_account_number: user?.bank_account_number || '',
    bank_ifsc: user?.bank_ifsc || '',
    bank_upi_id: user?.bank_upi_id || '',
  })
  const [savingBank, setSavingBank] = useState(false)
  const [bankError, setBankError] = useState('')

  useEffect(() => {
    if (user) {
      setBankForm({
        bank_account_holder: user.bank_account_holder || '',
        bank_account_number: user.bank_account_number || '',
        bank_ifsc: user.bank_ifsc || '',
        bank_upi_id: user.bank_upi_id || '',
      })
    }
  }, [user?.bank_account_holder, user?.bank_account_number, user?.bank_ifsc, user?.bank_upi_id])

  const [form, setForm] = useState({
    name: '',
    email: '',
    phone: '',
    address: '',
    city: '',
    emergency_contact_name: '',
    emergency_contact_phone: '',
    bank_account_holder: '',
    bank_account_number: '',
    bank_ifsc: '',
    bank_upi_id: '',
  })

  const handleUseExistingDetails = () => {
    if (user) {
      setForm({
        name: user.name || '',
        email: user.email || '',
        phone: user.phone || '',
        address: user.address || '',
        city: user.city || '',
        emergency_contact_name: user.emergency_contact_name || '',
        emergency_contact_phone: user.emergency_contact_phone || '',
        bank_account_holder: user.bank_account_holder || '',
        bank_account_number: user.bank_account_number || '',
        bank_ifsc: user.bank_ifsc || '',
        bank_upi_id: user.bank_upi_id || '',
      })
    }
  }

  useEffect(() => {
    if (user?.id) {
      refreshProfile()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const set = (key) => (value) => setForm((current) => ({ ...current, [key]: value }))

  const hasBank = hasValidBankDetails(user)
  const isBankApproved = user?.bank_request_status === 'approved'
  const isBankPending = user?.bank_request_status === 'requested'
  const isBankLocked = hasBank && !isBankApproved

  const handleSaveBankDetails = async (e) => {
    e?.preventDefault()
    setBankError('')

    const holder = (bankForm.bank_account_holder !== undefined && bankForm.bank_account_holder !== null && bankForm.bank_account_holder !== '' ? bankForm.bank_account_holder : (user?.bank_account_holder || '')).trim()
    const number = (bankForm.bank_account_number !== undefined && bankForm.bank_account_number !== null && bankForm.bank_account_number !== '' ? bankForm.bank_account_number : (user?.bank_account_number || '')).trim()
    const ifsc = (bankForm.bank_ifsc !== undefined && bankForm.bank_ifsc !== null && bankForm.bank_ifsc !== '' ? bankForm.bank_ifsc : (user?.bank_ifsc || '')).trim().toUpperCase()
    const upi = (bankForm.bank_upi_id !== undefined && bankForm.bank_upi_id !== null && bankForm.bank_upi_id !== '' ? bankForm.bank_upi_id : (user?.bank_upi_id || '')).trim()

    if (!holder) {
      setBankError('Account Holder Name is required.')
      return
    }
    if (holder.length < 2) {
      setBankError('Please enter a valid Account Holder Name.')
      return
    }
    if (!number) {
      setBankError('Bank Account Number is required.')
      return
    }
    if (!/^\d{8,20}$/.test(number)) {
      setBankError('Enter a valid Bank Account Number (8-20 digits).')
      return
    }
    if (!ifsc) {
      setBankError('IFSC Code is required.')
      return
    }
    if (!/^[A-Z]{4}0[A-Z0-9]{6}$/.test(ifsc)) {
      setBankError('Enter a valid 11-character IFSC code (e.g. SBIN0001234).')
      return
    }
    if (!upi) {
      setBankError('UPI ID is required.')
      return
    }
    if (!isValidUpi(upi)) {
      setBankError('Enter a valid UPI ID (e.g. name@upi).')
      return
    }

    setSavingBank(true)
    try {
      const payload = {
        bank_account_holder: holder,
        bank_account_number: number,
        bank_ifsc: ifsc,
        bank_upi_id: upi,
      }
      const res = await saveProfileToDb(payload)
      setSavingBank(false)
      if (res.success) {
        await refreshProfile()
        flash('Bank details updated successfully.')
      } else {
        setBankError(res.message || 'Failed to update bank details.')
      }
    } catch {
      setSavingBank(false)
      setBankError('Failed to connect to server. Please try again.')
    }
  }

  const save = async () => {
    const payload = {
      name: form.name?.trim() ? form.name.trim() : user?.name,
      email: form.email?.trim() ? form.email.trim() : user?.email,
      address: form.address?.trim() ? form.address.trim() : user?.address,
      city: form.city?.trim() ? form.city.trim() : user?.city,
      emergency_contact_name: form.emergency_contact_name?.trim() ? form.emergency_contact_name.trim() : user?.emergency_contact_name,
      emergency_contact_phone: form.emergency_contact_phone?.trim() ? form.emergency_contact_phone.trim() : user?.emergency_contact_phone,
    }

    // Include phone if approved and changed
    if (user?.phone_request_status === 'approved' && form.phone && form.phone.trim() !== user?.phone) {
      payload.phone = form.phone.trim()
    }

    // Include bank details if bank was never locked OR permission is approved
    const canEditBank = !isBankLocked || isBankApproved
    if (canEditBank) {
      const bh = bankForm.bank_account_holder?.trim() || form.bank_account_holder?.trim()
      const bn = bankForm.bank_account_number?.trim() || form.bank_account_number?.trim()
      const bi = (bankForm.bank_ifsc?.trim() || form.bank_ifsc?.trim() || '').toUpperCase()
      const bu = bankForm.bank_upi_id?.trim() || form.bank_upi_id?.trim()
      if (bh) payload.bank_account_holder = bh
      if (bn) payload.bank_account_number = bn
      if (bi) payload.bank_ifsc = bi
      if (bu) {
        if (!isValidUpi(bu)) {
          flash('Enter a valid UPI ID (e.g. name@upi).')
          return
        }
        payload.bank_upi_id = bu
      }
    }

    const res = await saveProfileToDb(payload)
    if (res.success) {
      await refreshProfile()
      setEditing(false)
      setForm({
        name: user?.name || '',
        email: user?.email || '',
        phone: user?.phone || '',
        address: user?.address || '',
        city: user?.city || '',
        emergency_contact_name: user?.emergency_contact_name || '',
        emergency_contact_phone: user?.emergency_contact_phone || '',
        bank_account_holder: user?.bank_account_holder || '',
        bank_account_number: user?.bank_account_number || '',
        bank_ifsc: user?.bank_ifsc || '',
        bank_upi_id: user?.bank_upi_id || '',
      })
      flash('Account & profile details updated in database.')
    } else {
      flash(res.message || 'Failed to save profile.')
    }
  }

  const handleToggleEdit = () => {
    if (editing) {
      save()
    } else {
      setForm({
        name: user?.name || '',
        email: user?.email || '',
        phone: user?.phone || '',
        address: user?.address || '',
        city: user?.city || '',
        emergency_contact_name: user?.emergency_contact_name || '',
        emergency_contact_phone: user?.emergency_contact_phone || '',
        bank_account_holder: user?.bank_account_holder || '',
        bank_account_number: user?.bank_account_number || '',
        bank_ifsc: user?.bank_ifsc || '',
        bank_upi_id: user?.bank_upi_id || '',
      })
      setEditing(true)
    }
  }

  const handleAdminPhoneRequest = async () => {
    setRequestingPhone(true)
    const res = await requestAdminAccess('phone')
    setRequestingPhone(false)
    if (res.success) {
      flash('Admin access requested for phone number update.')
    } else {
      flash(res.message || 'Failed to send request.')
    }
  }

  const handleAdminBankRequest = async () => {
    setRequestingBank(true)
    const res = await requestAdminAccess('bank')
    setRequestingBank(false)
    if (res.success) {
      flash('Admin access requested for bank details change.')
    } else {
      flash(res.message || 'Failed to send request.')
    }
  }

  const handleAdminDocRequest = async () => {
    setRequestingDoc(true)
    const res = await requestAdminAccess('documents')
    setRequestingDoc(false)
    if (res.success) {
      flash('Admin access requested for document update.')
    } else {
      flash(res.message || 'Failed to send request.')
    }
  }

  const initials = (user?.name || 'Driver')
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  const registeredOn = user?.created_at
    ? new Date(user.created_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
    : 'Jul 2026'

  return (
    <>
      <div className="profile">
        {user?.photoUrl ? (
          <img src={user.photoUrl} alt="" style={{ width: 56, height: 56, borderRadius: '50%', objectFit: 'cover' }} />
        ) : (
          <b>{initials}</b>
        )}
        <div>
          <h1>{user?.name || 'Driver'}</h1>
          <span>
            Driver &middot; {user?.vehicle_type || 'Vehicle'} {user?.vehicle_registration ? `\u00b7 ${user.vehicle_registration}` : ''}
          </span>
        </div>
      </div>

      <div className="wallet-note" style={{ marginTop: 20 }}>
        <b>Wallet balance: {inr(walletBalance)}</b>
        <p className="muted" style={{ margin: '4px 0 0' }}>Manage payouts from the Dashboard or Earnings tab.</p>
      </div>

      <div className="section-head" style={{ marginTop: 34 }}>
        <h2 style={{ margin: 0 }}>Personal &amp; Contact</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {editing && (
            <>
              <button
                type="button"
                className="secondary-btn"
                style={{ padding: '6px 12px', fontSize: 12, fontWeight: 700, cursor: 'pointer', background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--line)', borderRadius: 8 }}
                onClick={handleUseExistingDetails}
              >
                Use existing details
              </button>
              <button
                type="button"
                className="secondary-btn"
                style={{ padding: '6px 12px', fontSize: 12, fontWeight: 700, cursor: 'pointer', background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--line)', borderRadius: 8 }}
                onClick={() => setEditing(false)}
              >
                Cancel
              </button>
            </>
          )}
          <button className="back" onClick={handleToggleEdit}>
            {editing ? 'Save changes' : 'Edit details'}
          </button>
        </div>
      </div>
      <div className="field-grid">
        <FieldCard label="Full Name" value={form.name} displayValue={user?.name} editable editing={editing} onChange={set('name')} />
        <FieldCard
          label="Mobile Number"
          value={form.phone}
          displayValue={user?.phone}
          editable={user?.phone_request_status === 'approved'}
          editing={editing && user?.phone_request_status === 'approved'}
          onChange={set('phone')}
          lockedReason={user?.phone_request_status === 'approved' ? 'Editable (Approved)' : 'Read-only'}
          placeholder="10-digit mobile number"
        />
        <FieldCard label="Email" value={form.email} displayValue={user?.email} editable editing={editing} onChange={set('email')} />
        <FieldCard label="Address" value={form.address} displayValue={user?.address} editable editing={editing} onChange={set('address')} />
        <FieldCard label="City" value={form.city} displayValue={user?.city} editable editing={editing} onChange={set('city')} />
      </div>

      <div style={{ marginTop: 10 }}>
        {user?.phone_request_status === 'requested' ? (
          <p className="muted" style={{ fontWeight: 700, color: '#8a6400', margin: '6px 0 0' }}>
            ⏳ Phone number change request submitted to Admin. Awaiting authorization.
          </p>
        ) : user?.phone_request_status === 'approved' ? (
          <p style={{ fontWeight: 700, color: '#177a47', margin: '6px 0 0' }}>
            ✅ Admin approval granted! Click &quot;Edit details&quot; above to change your phone number.
          </p>
        ) : (
          <div>
            {user?.phone_request_status === 'rejected' && (
              <p style={{ fontWeight: 700, color: '#a52b23', margin: '6px 0 6px' }}>
                ❌ Your previous phone change request was rejected by Admin.
              </p>
            )}
            <button
              className="secondary-btn"
              style={{ color: 'var(--text)', background: 'var(--card)', border: '1px solid var(--line)' }}
              disabled={requestingPhone}
              onClick={handleAdminPhoneRequest}
            >
              {requestingPhone ? 'Sending Request...' : 'Request Admin Access to Change Phone Number'}
            </button>
          </div>
        )}
      </div>

      <h2>Emergency Contact</h2>
      <div className="field-grid">
        <FieldCard
          label="Contact Name"
          value={form.emergency_contact_name}
          displayValue={user?.emergency_contact_name}
          editable
          editing={editing}
          onChange={set('emergency_contact_name')}
          placeholder="e.g. Parent / Spouse Name"
        />
        <FieldCard
          label="Contact Phone"
          value={form.emergency_contact_phone}
          displayValue={user?.emergency_contact_phone}
          editable
          editing={editing}
          onChange={set('emergency_contact_phone')}
          placeholder="10-digit mobile"
        />
      </div>

      <div className="section-head" style={{ marginTop: 34 }}>
        <h2 style={{ margin: 0 }}>Bank &amp; Payout Details</h2>
        {!hasBank ? (
          <button
            type="button"
            className="secondary-btn"
            style={{
              padding: '8px 16px',
              fontSize: 13,
              fontWeight: 800,
              color: '#1e1b16',
              background: '#FDD34D',
              border: 'none',
              borderRadius: 10,
              cursor: 'pointer',
            }}
            onClick={() => openModal?.('bank')}
          >
            Add Bank Details
          </button>
        ) : isBankApproved ? (
          <span className="field-tag editable" style={{ background: '#e2f3e8', color: '#177a47' }}>
            Admin Approval Granted
          </span>
        ) : isBankPending ? (
          <span className="field-tag readonly" style={{ background: '#FFF3C4', color: '#8a6400' }}>
            Request Pending Admin Review
          </span>
        ) : user?.bank_request_status === 'rejected' ? (
          <span className="field-tag readonly" style={{ background: '#fce8e5', color: '#a52b23' }}>
            Request Rejected
          </span>
        ) : (
          <span className="field-tag readonly">
            Locked
          </span>
        )}
      </div>

      <div className="field-grid" style={{ marginTop: 12 }}>
        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Account Holder</span>
            <span className={`field-tag ${isBankApproved ? 'editable' : 'readonly'}`}>
              {isBankApproved ? 'Editable' : 'Locked'}
            </span>
          </div>
          {isBankApproved ? (
            <input
              value={bankForm.bank_account_holder}
              onChange={(e) => {
                setBankError('')
                setBankForm(f => ({ ...f, bank_account_holder: e.target.value }))
              }}
              placeholder="Account Holder Name"
              autoComplete="off"
            />
          ) : (
            <span className="field-value">{user?.bank_account_holder || '—'}</span>
          )}
        </div>

        <div className="field-card">
          <div className="field-top">
            <span className="field-label">Account Number</span>
            <span className={`field-tag ${isBankApproved ? 'editable' : 'readonly'}`}>
              {isBankApproved ? 'Editable' : 'Locked'}
            </span>
          </div>
          {isBankApproved ? (
            <input
              value={bankForm.bank_account_number}
              onChange={(e) => {
                setBankError('')
                setBankForm(f => ({ ...f, bank_account_number: e.target.value }))
              }}
              placeholder="Bank Account Number"
              autoComplete="off"
            />
          ) : (
            <span className="field-value">
              {user?.bank_account_number
                ? user.bank_account_number.length > 4
                  ? `XXXX XXXX ${user.bank_account_number.slice(-4)}`
                  : user.bank_account_number
                : '—'}
            </span>
          )}
        </div>

        <div className="field-card">
          <div className="field-top">
            <span className="field-label">IFSC Code</span>
            <span className={`field-tag ${isBankApproved ? 'editable' : 'readonly'}`}>
              {isBankApproved ? 'Editable' : 'Locked'}
            </span>
          </div>
          {isBankApproved ? (
            <input
              value={bankForm.bank_ifsc}
              onChange={(e) => {
                setBankError('')
                setBankForm(f => ({ ...f, bank_ifsc: e.target.value.toUpperCase() }))
              }}
              placeholder="IFSC Code (e.g. SBIN0001234)"
              autoComplete="off"
            />
          ) : (
            <span className="field-value">{user?.bank_ifsc || '—'}</span>
          )}
        </div>

        <div className="field-card">
          <div className="field-top">
            <span className="field-label">UPI ID</span>
            <span className={`field-tag ${isBankApproved ? 'editable' : 'readonly'}`}>
              {isBankApproved ? 'Editable' : 'Locked'}
            </span>
          </div>
          {isBankApproved ? (
            <input
              value={bankForm.bank_upi_id}
              onChange={(e) => {
                setBankError('')
                setBankForm(f => ({ ...f, bank_upi_id: e.target.value }))
              }}
              placeholder="name@upi"
              autoComplete="off"
            />
          ) : (
            <span className="field-value">{user?.bank_upi_id || '—'}</span>
          )}
        </div>
      </div>

      {bankError && (
        <div style={{ marginTop: 10, padding: '10px 14px', borderRadius: 10, background: '#fce8e5', color: '#a52b23', fontSize: 13, fontWeight: 600 }}>
          ⚠️ {bankError}
        </div>
      )}

      {hasBank && (
        <div style={{ marginTop: 12 }}>
          {isBankPending ? (
            <p className="muted" style={{ fontWeight: 700, color: '#8a6400', margin: 0 }}>
              ⏳ Bank change request pending admin approval
            </p>
          ) : isBankApproved ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
              <p style={{ fontWeight: 700, color: '#177a47', margin: 0 }}>
                ✓ Admin approval granted
              </p>
              <div>
                <button
                  type="button"
                  className="primary-btn"
                  style={{
                    padding: '10px 24px',
                    fontSize: 14,
                    fontWeight: 800,
                    borderRadius: 10,
                    cursor: savingBank ? 'not-allowed' : 'pointer',
                    opacity: savingBank ? 0.7 : 1,
                  }}
                  disabled={savingBank}
                  onClick={handleSaveBankDetails}
                >
                  {savingBank ? 'Saving Bank Details...' : 'Save Bank Details'}
                </button>
              </div>
            </div>
          ) : (
            <div>
              {user?.bank_request_status === 'rejected' && (
                <p style={{ fontWeight: 700, color: '#a52b23', marginBottom: 6 }}>
                  ❌ Your previous bank edit request was rejected by Admin.
                </p>
              )}
              <button
                type="button"
                className="secondary-btn"
                style={{ color: 'var(--text)', background: 'var(--card)', border: '1px solid var(--line)', marginTop: 4 }}
                disabled={requestingBank}
                onClick={handleAdminBankRequest}
              >
                {requestingBank ? 'Sending Request...' : 'Request Bank Details Change'}
              </button>
            </div>
          )}
        </div>
      )}

      <h2>Uploaded Verification Documents</h2>
      <div className="field-grid">
        <DocCard title="Profile Photo" path={user?.profile_photo} type="Image" userName={user?.name} onPreview={setPreviewDoc} />
        <DocCard title="Govt ID / Aadhaar / PAN" path={user?.id_document} type="Document" userName={user?.name} onPreview={setPreviewDoc} />
        <DocCard title="Digital Signature" path={user?.signature_document} type="Signature" userName={user?.name} onPreview={setPreviewDoc} />
        <DocCard title="RC Book Document" path={user?.rc_document} type="Document" userName={user?.name} onPreview={setPreviewDoc} />
        <DocCard title="Driving Licence Document" path={user?.licence_document} type="Document" userName={user?.name} onPreview={setPreviewDoc} />
        <DocCard title="Insurance Document" path={user?.insurance_document} type="Document" userName={user?.name} onPreview={setPreviewDoc} />
      </div>

      <div style={{ marginTop: 12 }}>
        {user?.doc_request_status === 'requested' ? (
          <p className="muted" style={{ fontWeight: 700, color: '#8a6400' }}>
            ⏳ Document re-upload request submitted to Admin. Awaiting authorization.
          </p>
        ) : user?.doc_request_status === 'approved' ? (
          <div>
            <p style={{ fontWeight: 700, color: '#177a47', marginBottom: 8 }}>
              ✅ Admin approval granted! You can now upload replacement documents.
            </p>
            <button
              className="secondary-btn"
              style={{ color: '#1e1b16', background: '#FDD34D', border: 'none', fontWeight: 700, borderRadius: 8, padding: '8px 16px', cursor: 'pointer' }}
              onClick={() => setShowDocUploadModal(true)}
            >
              Upload Replacement Document
            </button>
          </div>
        ) : (
          <div>
            {user?.doc_request_status === 'rejected' && (
              <p style={{ fontWeight: 700, color: '#a52b23', marginBottom: 6 }}>
                ❌ Your previous document edit request was rejected by Admin.
              </p>
            )}
            <button
              className="secondary-btn"
              style={{ color: 'var(--text)', background: 'var(--card)', border: '1px solid var(--line)', marginTop: 8 }}
              disabled={requestingDoc}
              onClick={handleAdminDocRequest}
            >
              {requestingDoc ? 'Sending Request...' : 'Request Admin Access to Edit Documents'}
            </button>
          </div>
        )}
      </div>

      <h2>Vehicle &amp; Verification</h2>
      <div className="field-grid">
        <FieldCard label="Vehicle Number" value={user?.vehicle_registration} editable={false} />
        <FieldCard label="Vehicle Type" value={user?.vehicle_type} editable={false} />
        <FieldCard label="Vehicle Make &amp; Model" value={`${user?.vehicle_make || ''} ${user?.vehicle_model || ''}`.trim() || '—'} editable={false} />
        <FieldCard label="Driving Licence Number" value={user?.driving_licence_number} editable={false} />
      </div>

      <h2>Account Status</h2>
      <div className="field-grid">
        <FieldCard label="Driver ID" value={user?.id ? `T&G-${user.id}` : '—'} editable={false} />
        <FieldCard label="Registration Date" value={registeredOn} editable={false} />
        <FieldCard label="KYC Status" value="Verified" editable={false} />
        <FieldCard
          label="Aadhaar Verification"
          value={user?.aadhaar ? `Verified (XXXX XXXX ${user.aadhaar.slice(-4)})` : 'Pending Verification'}
          editable={false}
        />
      </div>

      <h2>Settings</h2>
      <div className="setting">
        <span>
          Notifications
          <small>Trip and payout updates</small>
        </span>
        <button className={notifications ? 'switch on' : 'switch'} onClick={() => setNotifications(!notifications)}>
          <i />
        </button>
      </div>
      <div className="setting">
        <span>
          Dark mode
          <small>Use the darker interface</small>
        </span>
        <button className={dark ? 'switch on' : 'switch'} onClick={() => setDark(!dark)}>
          <i />
        </button>
      </div>

      <button className="signout" onClick={onLogout}>
        <Icon>logout</Icon>
        Sign Out
      </button>

      {previewDoc && (
        <DocumentViewerModal doc={previewDoc} onClose={() => setPreviewDoc(null)} />
      )}

      {showDocUploadModal && (
        <DocumentUploadModal
          accountType="driver"
          onClose={() => setShowDocUploadModal(false)}
          flash={flash}
        />
      )}
    </>
  )
}

export default DriverAccount
