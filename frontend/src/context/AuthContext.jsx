import { createContext, useContext, useEffect, useState } from 'react'
import { useLiveRefresh } from '../hooks/useLiveRefresh.js'

const STORAGE_KEY = 'tapgo_user'
const TOKEN_KEY = 'tapgo_token'
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'


const AuthContext = createContext(null)

export function resolveFileUrl(filePath) {
  if (!filePath) return null
  if (filePath.startsWith('http://') || filePath.startsWith('https://') || filePath.startsWith('data:')) {
    return filePath
  }
  const clean = filePath.replace(/^\/+/, '')
  if (clean.startsWith('uploads/')) {
    return `${API_BASE}/${clean}`
  }
  return `${API_BASE}/uploads/${clean}`
}

export function getDocumentDisplayLabel(typeOrTitle) {
  if (!typeOrTitle) return 'Verification Document'
  const normalized = String(typeOrTitle).toLowerCase().trim()

  if (normalized.includes('profile') || normalized.includes('photo') || normalized === 'profile_photo') {
    return 'Profile Photo'
  }
  if (
    normalized.includes('id') ||
    normalized.includes('aadhaar') ||
    normalized.includes('pan') ||
    normalized === 'id_document' ||
    normalized === 'government_id' ||
    normalized === 'govt id / aadhaar / pan'
  ) {
    return 'Government ID / Aadhaar / PAN'
  }
  if (normalized.includes('signature') || normalized === 'digital_signature' || normalized === 'signature_document') {
    return 'Digital Signature'
  }
  if (normalized.includes('rc') || normalized === 'rc_document') {
    return 'Vehicle RC Document'
  }
  if (normalized.includes('licence') || normalized.includes('license') || normalized === 'licence_document') {
    return 'Driving Licence'
  }
  if (normalized.includes('insurance') || normalized === 'insurance_document') {
    return 'Vehicle Insurance'
  }
  return typeOrTitle
}

export function getDocumentDisplayName(userName, typeOrTitle) {
  const name = (userName || '').trim() || 'User'
  const docLabel = getDocumentDisplayLabel(typeOrTitle)
  return `${name} — ${docLabel}`
}

export const UPI_REGEX = /^[a-zA-Z0-9.\-_]{2,50}@[a-zA-Z0-9.\-_]{2,50}$/

export function isValidUpi(val) {
  if (!val || typeof val !== 'string') return false
  return UPI_REGEX.test(val.trim())
}


function normalizeUser(userData) {
  if (!userData) return null
  const photoPath = userData.profile_photo || userData.photoUrl
  const photoUrl = resolveFileUrl(photoPath)

  return {
    ...userData,
    photoUrl,
    account: userData.email || userData.phone,
    role: userData.account_type === 'driver' ? 'driver' : 'passenger',
  }
}

function readStoredUser() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    // Clean up any legacy localStorage entry
    localStorage.removeItem(STORAGE_KEY)
    return raw ? normalizeUser(JSON.parse(raw)) : null
  } catch {
    return null
  }
}

export function hasValidBankDetails(user) {
  if (!user) return false
  const holder = typeof user.bank_account_holder === 'string' ? user.bank_account_holder.trim() : ''
  const number = typeof user.bank_account_number === 'string' ? user.bank_account_number.trim() : ''
  const ifsc = typeof user.bank_ifsc === 'string' ? user.bank_ifsc.trim() : ''
  const upi = typeof user.bank_upi_id === 'string' ? user.bank_upi_id.trim() : ''

  if (!holder || holder === '—' || holder.toLowerCase() === 'null' || holder.toLowerCase() === 'undefined') {
    return false
  }
  if (!number || number === '—' || number.toLowerCase() === 'null' || number.toLowerCase() === 'undefined') {
    return false
  }
  if (!ifsc || ifsc === '—' || ifsc.toLowerCase() === 'null' || ifsc.toLowerCase() === 'undefined') {
    return false
  }
  if (!upi || upi === '—' || upi.toLowerCase() === 'null' || upi.toLowerCase() === 'undefined') {
    return false
  }
  return true
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => readStoredUser())

  useEffect(() => {
    if (user) {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(user))
    } else {
      sessionStorage.removeItem(STORAGE_KEY)
    }
    localStorage.removeItem(STORAGE_KEY)
  }, [user])

  // Automatically sync authenticated user details with database on initial mount
  useEffect(() => {
    const stored = readStoredUser()
    if (stored?.id) {
      const token = sessionStorage.getItem(TOKEN_KEY)
      const headers = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      fetch(`${API_BASE}/api/auth/profile/${stored.id}`, { headers })
        .then((res) => res.json())
        .then((data) => {
          if (data?.success && data?.user) {
            const nextUser = normalizeUser(data.user)
            sessionStorage.setItem(STORAGE_KEY, JSON.stringify(nextUser))
            setUser(nextUser)
          }
        })
        .catch(() => {})
    }
  }, [])

  // Pick up administrator actions on the account (edit request approved or rejected, status changes) without a
  // reload. The user state is replaced only when the server data actually differs.
  useLiveRefresh(async () => {
    const stored = readStoredUser()
    if (!stored?.id || stored.account_type === 'admin') return
    try {
      const token = sessionStorage.getItem(TOKEN_KEY)
      const res = await fetch(`${API_BASE}/api/auth/profile/${stored.id}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      const data = await res.json()
      if (res.ok && data?.success && data?.user) {
        const nextUser = normalizeUser(data.user)
        setUser((current) => (current && JSON.stringify(current) === JSON.stringify(nextUser) ? current : nextUser))
      }
    } catch {
      // Ignore background network failure
    }
  }, Boolean(user?.id))

  const login = async ({ account, password }) => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account, password }),
      })
      const data = await response.json()
      if (data.success && data.user) {
        const nextUser = normalizeUser(data.user)
        try {
          sessionStorage.setItem(STORAGE_KEY, JSON.stringify(nextUser))
          if (data.token) {
            sessionStorage.setItem(TOKEN_KEY, data.token)
          }
          if (nextUser.account_type === 'admin' || nextUser.role === 'admin') {
            sessionStorage.setItem('tapgo_admin_session', JSON.stringify({ email: nextUser.email, name: nextUser.name || 'Admin', id: nextUser.id }))
          }
        } catch {}
        setUser(nextUser)
        return { success: true, user: nextUser }
      } else {
        return { success: false, message: data.message || 'Invalid Credentials', redirect_admin: Boolean(data.redirect_admin) }
      }
    } catch (err) {
      return { success: false, message: 'Backend server unavailable.' }
    }
  }

  const register = async (formDataPayload) => {
    try {
      let bodyData = formDataPayload
      if (!(formDataPayload instanceof FormData)) {
        bodyData = new FormData()
        Object.keys(formDataPayload).forEach((key) => {
          if (formDataPayload[key] !== null && formDataPayload[key] !== undefined) {
            bodyData.append(key, formDataPayload[key])
          }
        })
      }

      const response = await fetch(`${API_BASE}/api/auth/register`, {
        method: 'POST',
        body: bodyData,
      })
      const data = await response.json()
      if (response.ok && data.success) {
        const nextUser = normalizeUser(data.user)
        return { success: true, user: nextUser, message: data.message, review_demo: Boolean(data.review_demo) }
      } else {
        let errorMsg = 'Registration failed'
        if (typeof data.detail === 'string') {
          errorMsg = data.detail
        } else if (Array.isArray(data.detail)) {
          errorMsg = data.detail.map((item) => item.msg || 'Invalid field').join('; ')
        } else if (data.message) {
          errorMsg = data.message
        }
        return { success: false, message: errorMsg }
      }
    } catch (err) {
      return { success: false, message: 'Backend server unavailable.' }
    }
  }

  const saveProfileToDb = async (patch) => {
    if (!user?.id) return { success: false, message: 'User not logged in' }
    try {
      const token = sessionStorage.getItem(TOKEN_KEY)
      const headers = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`

      const res = await fetch(`${API_BASE}/api/auth/profile`, {
        method: 'PUT',
        headers,
        body: JSON.stringify({ user_id: user.id, ...patch }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        const nextUser = normalizeUser(data.user)
        setUser(nextUser)
        return { success: true, user: nextUser }
      } else {
        return { success: false, message: data.detail || data.message || 'Failed to update profile' }
      }
    } catch (err) {
      return { success: false, message: 'Error saving profile to server.' }
    }
  }

  const requestAdminAccess = async (requestType, bankDetails) => {
    if (!user?.id) return { success: false, message: 'User not logged in' }
    try {
      const token = sessionStorage.getItem(TOKEN_KEY)
      const headers = { 'Content-Type': 'application/json' }
      if (token) headers['Authorization'] = `Bearer ${token}`

      const res = await fetch(`${API_BASE}/api/auth/request-admin-access`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ user_id: user.id, request_type: requestType, ...(bankDetails ? { bank_details: bankDetails } : {}) }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        const nextUser = normalizeUser(data.user)
        setUser(nextUser)
        return { success: true, message: data.message, user: nextUser }
      } else {
        return { success: false, message: data.detail || 'Request failed' }
      }
    } catch (err) {
      return { success: false, message: 'Server error' }
    }
  }

  const refreshProfile = async () => {
    if (!user?.id) return null
    try {
      const token = sessionStorage.getItem(TOKEN_KEY)
      const headers = {}
      if (token) headers['Authorization'] = `Bearer ${token}`

      const res = await fetch(`${API_BASE}/api/auth/profile/${user.id}`, { headers })
      const data = await res.json()
      if (res.ok && data.success && data.user) {
        const nextUser = normalizeUser(data.user)
        setUser(nextUser)
        return nextUser
      }
    } catch {
      // Ignore background network failure
    }
    return user
  }

  const uploadReplacementDocument = async (documentType, file) => {
    if (!user?.id) return { success: false, message: 'User not logged in' }
    try {
      const token = sessionStorage.getItem(TOKEN_KEY)
      const headers = {}
      if (token) headers['Authorization'] = `Bearer ${token}`

      const formData = new FormData()
      formData.append('document_type', documentType)
      formData.append('file', file)

      const res = await fetch(`${API_BASE}/api/auth/profile/document`, {
        method: 'POST',
        headers,
        body: formData,
      })
      const data = await res.json()
      if (res.ok && data.success) {
        const nextUser = normalizeUser(data.user)
        setUser(nextUser)
        return { success: true, message: data.message, user: nextUser }
      } else {
        return { success: false, message: data.detail || 'Document upload failed' }
      }
    } catch (err) {
      return { success: false, message: 'Server error uploading document' }
    }
  }

  const logout = async () => {
    try {
      const token = sessionStorage.getItem(TOKEN_KEY)
      if (token) {
        await fetch(`${API_BASE}/api/auth/logout`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${token}` }
        })
      }
    } catch {}
    
    setUser(null)
    try {
      sessionStorage.clear()
      localStorage.removeItem(STORAGE_KEY)
      localStorage.removeItem('tapgo_admin_session')
    } catch {
      // Ignore storage error
    }
  }

  const updateProfile = (patch) => {
    setUser((current) => (current ? normalizeUser({ ...current, ...patch }) : current))
  }

  return (
    <AuthContext.Provider value={{ user, login, register, logout, updateProfile, saveProfileToDb, requestAdminAccess, uploadReplacementDocument, refreshProfile }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside an AuthProvider')
  return ctx
}
