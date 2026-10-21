import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from '../../routes/navigation.jsx'
import logo from '../../assets/images/tapgo-logo.png'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'


const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const phoneRegex = /^[0-9]{10}$/

function CheckIcon({ className = 'w-4 h-4' }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M5 13l4 4L19 7" />
    </svg>
  )
}

function SvgIcon({ className = 'w-6 h-6', children }) {
  return (
    <svg className={className} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      {children}
    </svg>
  )
}

function ProgressTracker({ step }) {
  const percent = [0, 0, 33, 66, 100][step]
  const steps = ['Request Submitted', 'OTP Sent', 'OTP Verified', 'Password Updated']

  return (
    <div className="relative z-10 mt-10 bg-white border border-[#dcd4c6] p-6 lg:p-8 rounded-[22px] w-full">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-xs font-extrabold uppercase tracking-[0.18em] text-gray-500">Recovery Status</h3>
        <div className="relative w-12 h-12 flex items-center justify-center">
          <svg className="absolute inset-0 w-full h-full transform -rotate-90" viewBox="0 0 100 100">
            <circle cx="50" cy="50" r="44" fill="none" stroke="rgba(0,0,0,0.05)" strokeWidth="8"></circle>
            <circle cx="50" cy="50" r="44" fill="none" stroke={percent === 100 ? '#2e9560' : '#fdd34d'} strokeWidth="8" strokeDasharray="276" strokeDashoffset={276 - (276 * percent) / 100} strokeLinecap="round" className="transition-all duration-700 ease-out"></circle>
          </svg>
          <span className="text-xs font-black text-gray-800">{percent}%</span>
        </div>
      </div>

      <div className="relative pl-2">
        <div className="absolute left-[17px] top-4 bottom-4 w-[2px] bg-gray-100">
          <div className="w-full transition-all duration-700 ease-out" style={{ height: `${percent}%`, backgroundColor: percent === 100 ? '#2e9560' : '#fdd34d' }}></div>
        </div>
        <div className="space-y-6">
          {steps.map((label, index) => {
            const current = index + 1
            const isCompleted = current < step
            const isActive = current === step
            return (
              <div className="flex items-center gap-5 relative z-10" key={label}>
                <div className={`w-8 h-8 rounded-full border-[2px] transition-all duration-500 flex items-center justify-center bg-white ${isCompleted ? 'border-green-500 bg-green-50' : isActive ? 'border-gray-900 bg-yellow-400' : 'border-[#d6cfc2]'}`}>
                  <CheckIcon className={`w-4 h-4 transition-opacity duration-300 ${isCompleted ? 'text-green-500 opacity-100' : 'opacity-0'}`} />
                </div>
                <span className={`text-[0.85rem] font-semibold transition-colors duration-300 tracking-wide ${isCompleted || isActive ? 'text-gray-900' : 'text-gray-400'}`}>{label}</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function PasswordStrength({ password }) {
  const checks = {
    len: password.length >= 8,
    up: /[A-Z]/.test(password),
    low: /[a-z]/.test(password),
    num: /[0-9]/.test(password),
    spc: /[^A-Za-z0-9]/.test(password),
  }
  const strength = Number(checks.len) + Number(checks.up && checks.low) + Number(checks.num) + Number(checks.spc)
  
  // Adjusted colors for light theme (removed heavy glowing shadows)
  const colors = ['bg-gray-200', 'bg-red-500', 'bg-orange-400', 'bg-yellow-400', 'bg-green-500']
  const texts = ['Strength', 'Weak', 'Medium', 'Strong', 'Very Strong']
  const textColors = ['text-gray-500', 'text-red-500', 'text-orange-500', 'text-yellow-600', 'text-green-600']

  return (
    <div className="bg-white rounded-[18px] p-5 border border-[#dcd4c6]">
      <div className="flex justify-between items-center mb-3">
        <span className={`text-xs font-black uppercase tracking-widest ${textColors[strength]}`}>{texts[strength]}</span>
      </div>
      <div className="flex gap-2 mb-4">
        {[0, 1, 2, 3].map((item) => (
          <div key={item} className={`h-1.5 flex-1 rounded-full transition-all duration-500 ${item < strength ? colors[strength] : 'bg-gray-100'}`}></div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-y-3 text-[0.75rem] font-bold text-gray-500">
        {[
          ['len', '8+ Characters'],
          ['up', 'Uppercase'],
          ['low', 'Lowercase'],
          ['num', 'Number'],
          ['spc', 'Special Character'],
        ].map(([key, label]) => (
          <div className={`flex items-center gap-2 ${key === 'spc' ? 'col-span-2' : ''} ${checks[key] ? 'text-gray-900' : 'text-gray-400'}`} key={key}>
            <CheckIcon className={`w-4 h-4 ${checks[key] ? 'text-green-500' : 'text-gray-300'}`} />
            {label}
          </div>
        ))}
      </div>
    </div>
  )
}

function ForgotPassword() {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [account, setAccount] = useState('')
  const [otp, setOtp] = useState(['', '', '', '', '', ''])
  const [timer, setTimer] = useState(60)
  const [loading, setLoading] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [resolvedEmail, setResolvedEmail] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [otpError, setOtpError] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const otpRefs = useRef([])

  const validAccount = emailRegex.test(account.trim()) || phoneRegex.test(account.trim())
  const validOtp = otp.every((digit) => digit.length === 1)
  const passwordChecks = {
    len: newPassword.length >= 8,
    up: /[A-Z]/.test(newPassword),
    low: /[a-z]/.test(newPassword),
    num: /[0-9]/.test(newPassword),
    spc: /[^A-Za-z0-9]/.test(newPassword),
  }
  const validPassword = Object.values(passwordChecks).every(Boolean)
  const validConfirm = confirmPassword.length > 0 && confirmPassword === newPassword

  const displayAccount = useMemo(() => {
    const value = account.trim()
    return phoneRegex.test(value) ? `+91 ${value}` : value
  }, [account])

  useEffect(() => {
    if (step !== 2 || timer <= 0) return undefined
    const interval = window.setInterval(() => {
      setTimer((current) => Math.max(0, current - 1))
    }, 1000)
    return () => window.clearInterval(interval)
  }, [step, timer])

  const submitAccount = async (event) => {
    event.preventDefault()
    if (!validAccount) return
    setLoading('account')
    setOtpError('')
    
    try {
      const res = await fetch(`${API_BASE}/api/auth/forgot-password-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account: account.trim() })
      })
      const data = await res.json()
      
      setLoading('')
      if (res.ok && data.success) {
        if (data.email) setResolvedEmail(data.email)
        setStep(2)
        setTimer(60)
        window.setTimeout(() => otpRefs.current[0]?.focus(), 20)
      } else {
        setOtpError(data.detail || "Failed to process request. Please check your account details.")
      }
    } catch (err) {
      setLoading('')
      setOtpError("Error connecting to server. Please try again.")
    }
  }

  const updateOtp = (index, value) => {
    const digit = value.replace(/\D/g, '').slice(-1)
    setOtp((current) => current.map((item, itemIndex) => (itemIndex === index ? digit : item)))
    setOtpError('')
    if (digit && index < 5) otpRefs.current[index + 1]?.focus()
  }

  const handleOtpKey = (index, event) => {
    if (event.key === 'Backspace' && !otp[index] && index > 0) {
      otpRefs.current[index - 1]?.focus()
    }
  }

  const handleOtpPaste = (event) => {
    event.preventDefault()
    const pasted = event.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    setOtp((current) => current.map((item, index) => pasted[index] || item))
    setOtpError('')
    otpRefs.current[Math.min(pasted.length, 5)]?.focus()
  }

  const submitOtp = async (event) => {
    event.preventDefault()
    if (!validOtp) return
    setLoading('otp')
    setOtpError('')

    try {
      const res = await fetch(`${API_BASE}/api/auth/verify-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          email: (resolvedEmail || account).trim(), 
          otp: otp.join(''),
          purpose: "forgot_password"
        })
      })
      const data = await res.json()
      setLoading('')

      if (res.ok && data.success) {
        setStep(3)
      } else {
        setOtpError(data.detail || "Invalid verification code. Please check and try again.")
      }
    } catch (err) {
      setLoading('')
      setOtpError("Error connecting to server. Please check backend.")
    }
  }

  const resendOtp = async () => {
    if (timer > 0) return
    setOtp(['', '', '', '', '', ''])
    setOtpError('')
    setLoading('resend')
    try {
      const res = await fetch(`${API_BASE}/api/auth/forgot-password-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account: account.trim() })
      })
      const data = await res.json()
      setLoading('')
      if (res.ok && data.success) {
        setTimer(60)
        window.setTimeout(() => otpRefs.current[0]?.focus(), 20)
      } else {
        setOtpError(data.detail || "Failed to resend verification code.")
      }
    } catch (e) {
      setLoading('')
      setOtpError("Error connecting to server.")
    }
  }

  const submitPassword = async (event) => {
    event.preventDefault()
    if (!validPassword || !validConfirm) return
    setLoading('password')
    
    try {
      const res = await fetch(`${API_BASE}/api/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          email: (resolvedEmail || account).trim(), 
          otp: otp.join(''),
          new_password: newPassword
        })
      })
      const data = await res.json()
      setLoading('')
      if (res.ok) {
        setStep(4)
      } else {
        alert(data.detail || "Failed to reset password.")
        if (data.detail === "Invalid OTP." || data.detail === "OTP has expired.") {
          setStep(2)
        }
      }
    } catch (err) {
      setLoading('')
      alert("Error resetting password.")
    }
  }

  return (
    <div className="bg-surface text-gray-900 min-h-screen flex flex-col lg:flex-row overflow-x-hidden antialiased font-sans">
      <aside className="w-full lg:w-[40%] bg-white relative flex flex-col justify-between p-8 lg:p-14 overflow-hidden border-b-2 lg:border-b-0 lg:border-r-2 border-gray-900 z-10 lg:min-h-screen">
        <Link to="/" className="relative z-10 flex items-center gap-4">
          <img src={logo} alt="Tap&Go" className="h-16 w-auto object-contain" />
          <span className="hidden">Tap&Go</span>
        </Link><br/><br/>

        <div className="relative z-10 mt-12 lg:mt-0 lg:my-auto hidden md:block">
          <div className="tg-kicker mb-6">
            <SvgIcon className="hidden">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </SvgIcon>
            <span>Secure Password Recovery</span>
          </div>
          <h1 className="font-display text-[40px] lg:text-[56px] font-extrabold text-gray-900 tracking-[-0.035em] leading-[1.02] mb-6">
            Recover your account <span className="whitespace-nowrap">safely.</span>
          </h1>
          <p className="text-gray-600 text-lg font-medium leading-relaxed max-w-md">
            AI-powered identity verification ensures only you can access your Tap&Go wallet.
          </p>
          <div className="grid grid-cols-2 gap-4 mt-10">
            {['Bank Grade Encryption', 'AI Fraud Protection', 'OTP Verification', 'Secure Recovery'].map((badge) => (
              <div className="flex items-center gap-3 text-sm font-semibold text-gray-600" key={badge}>
                <div className="w-8 h-8 rounded-full bg-yellow-400 flex items-center justify-center text-gray-900">
                  <CheckIcon />
                </div>
                {badge}
              </div>
            ))}
          </div>
        </div>

        <ProgressTracker step={step} />
      </aside>

      <main className="w-full lg:w-[60%] bg-surface flex flex-col justify-center items-center p-4 sm:p-12 lg:p-24 min-h-[70vh] lg:min-h-screen relative z-0">
        <div className="w-full max-w-xl relative">
          {step === 1 && (
            <div className="transition-all duration-500">
              <div className="mb-10 text-center lg:text-left">
                <h2 className="font-display text-[34px] lg:text-[44px] font-extrabold text-gray-900 tracking-[-0.03em] mb-4 leading-[1.05]">Forgot Password?</h2>
                <p className="text-gray-600 text-[1rem] font-medium leading-relaxed">
                  Enter your registered email address or mobile number.<br />
                  We'll send you a secure OTP to reset your password.
                </p>
              </div>
              <form className="space-y-8" noValidate onSubmit={submitAccount}>
                <div className="relative group">
                  <div className={`relative bg-white border focus-within:border-gray-900 focus-within:ring-4 focus-within:ring-yellow-400/40 rounded-[14px] transition-all duration-300 border-[1.5px] ${account && validAccount ? 'border-green-500' : account && !validAccount ? 'border-red-500' : 'border-[#d6cfc2]'}`}>
                    <div className="absolute left-4 top-1/2 transform -translate-y-1/2 text-gray-400 z-10">
                      <SvgIcon>
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                      </SvgIcon>
                    </div>
                    <input className="peer w-full bg-transparent px-12 py-4 pt-8 pb-3 text-gray-900 font-medium focus:outline-none" placeholder=" " value={account} onChange={(event) => setAccount(event.target.value)} />
                    <label className="absolute left-12 top-4 text-gray-400 text-xs font-semibold transition-all peer-placeholder-shown:text-sm peer-placeholder-shown:top-1/2 peer-placeholder-shown:-translate-y-1/2 peer-focus:top-4 peer-focus:-translate-y-0 peer-focus:text-xs peer-focus:text-gray-900 pointer-events-none">Email Address OR Mobile Number</label>
                    {validAccount && (
                      <div className="absolute right-5 top-1/2 transform -translate-y-1/2 text-green-500 z-10">
                        <CheckIcon className="w-6 h-6 bg-green-50 rounded-full p-1" />
                      </div>
                    )}
                  </div>
                  {account && !validAccount && <p className="text-red-500 text-xs font-semibold pl-2 pt-2">Enter a valid email or 10-digit number.</p>}
                </div>
                <button type="submit" className="w-full py-4 rounded-[14px] font-extrabold text-[1.05rem] tracking-[0.01em] flex items-center justify-center gap-3 relative group bg-yellow-400 text-gray-900 hover:bg-yellow-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed" disabled={!validAccount || loading === 'account'}>
                  <span className="relative z-10">{loading === 'account' ? 'Verifying...' : 'Send Secure OTP'}</span>
                  {loading === 'account' ? <div className="w-5 h-5 border-2 border-gray-900 border-t-transparent rounded-full animate-spin relative z-10"></div> : (
                    <SvgIcon className="w-6 h-6 transition-transform duration-300 group-hover:translate-x-2 relative z-10">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M14 5l7 7m0 0l-7 7m7-7H3" />
                    </SvgIcon>
                  )}
                </button>
                <div className="text-center mt-8">
                  <Link to="/login" className="text-[0.9rem] font-bold text-gray-500 hover:text-gray-900 transition-colors flex items-center justify-center gap-2">
                    <SvgIcon className="w-4 h-4">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                    </SvgIcon>
                    Back to Login
                  </Link>
                </div>
              </form>
            </div>
          )}

          {step === 2 && (
            <div className="transition-all duration-500">
              <div className="mb-10 text-center lg:text-left">
                <button type="button" className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-white border border-[#dcd4c6] mb-6 text-gray-600 hover:bg-yellow-50 hover:text-gray-900 transition-colors" onClick={() => setStep(1)}>
                  <SvgIcon className="w-4 h-4">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                  </SvgIcon>
                  <span className="text-xs font-bold uppercase tracking-widest">Change Account</span>
                </button>
                <h2 className="font-display text-[34px] lg:text-[44px] font-extrabold text-gray-900 tracking-[-0.03em] mb-4 leading-[1.05]">OTP Verification</h2>
                <p className="text-gray-600 text-[1rem] font-medium leading-relaxed">
                  Enter the 6-digit verification code sent to <br />
                  <span className="text-gray-900 font-bold underline decoration-yellow-400 decoration-[3px] underline-offset-4">{displayAccount}</span>
                </p>
              </div>
              <form className="space-y-8" noValidate onSubmit={submitOtp}>
                <div className="flex justify-between gap-1 sm:gap-4">
                  {otp.map((digit, index) => (
                    <input
                      key={index}
                      ref={(node) => {
                        otpRefs.current[index] = node
                      }}
                      className="w-9 h-12 sm:w-14 sm:h-16 bg-white border-[1.5px] border-[#d6cfc2] rounded-[12px] text-center text-xl sm:text-2xl font-bold text-gray-900 focus:outline-none focus:border-gray-900 focus:ring-4 focus:ring-yellow-400/40 transition-all"
                      type="text"
                      maxLength={1}
                      inputMode="numeric"
                      value={digit}
                      onChange={(event) => updateOtp(index, event.target.value)}
                      onKeyDown={(event) => handleOtpKey(index, event)}
                      onPaste={handleOtpPaste}
                    />
                  ))}
                </div>
                {otpError && (
                  <div className="p-3 bg-red-50 border border-red-200 rounded-[12px] text-red-700 font-bold text-xs">
                    ⚠️ {otpError}
                  </div>
                )}
                <div className="flex items-center justify-between px-1">
                  <div className="flex items-center gap-2 text-sm font-bold text-gray-500">
                    <SvgIcon className="w-4 h-4 animate-spin text-yellow-500">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </SvgIcon>
                    <span>{`00:${timer < 10 ? '0' : ''}${timer}`}</span>
                  </div>
                  <button type="button" className={`text-sm font-bold transition-colors ${timer > 0 ? 'text-gray-400 cursor-not-allowed' : 'text-gray-700 hover:text-gray-900'}`} disabled={timer > 0} onClick={resendOtp}>
                    Resend Code
                  </button>
                </div>
                <button type="submit" className="w-full py-4 rounded-[14px] font-extrabold text-[1.05rem] tracking-[0.01em] flex items-center justify-center gap-3 relative group bg-yellow-400 text-gray-900 hover:bg-yellow-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed" disabled={!validOtp || loading === 'otp'}>
                  <span className="relative z-10">{loading === 'otp' ? 'Authenticating...' : 'Verify Identity'}</span>
                  {loading === 'otp' && <div className="w-5 h-5 border-2 border-gray-900 border-t-transparent rounded-full animate-spin relative z-10"></div>}
                </button>
              </form>
            </div>
          )}

          {step === 3 && (
            <div className="transition-all duration-500">
              <div className="mb-10 text-center lg:text-left">
                <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-green-50 border border-green-200 mb-6 text-green-700">
                  <CheckIcon />
                  <span className="text-xs font-bold uppercase tracking-widest">Identity Verified</span>
                </div>
                <h2 className="font-display text-[34px] lg:text-[44px] font-extrabold text-gray-900 tracking-[-0.03em] mb-4 leading-[1.05]">Reset Password</h2>
                <p className="text-gray-600 text-[1rem] font-medium leading-relaxed">
                  Create a strong, unique password to secure your Tap&Go digital wallet.
                </p>
              </div>
              <form className="space-y-6" noValidate onSubmit={submitPassword}>
                <div className="relative group">
                  <div className="relative bg-white border-[#d6cfc2] focus-within:border-gray-900 focus-within:ring-4 focus-within:ring-yellow-400/40 rounded-[14px] transition-all duration-300 border-[1.5px]">
                    <div className="absolute left-4 top-1/2 transform -translate-y-1/2 text-gray-400 z-10">
                      <SvgIcon>
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                      </SvgIcon>
                    </div>
                    <input type={showPassword ? 'text' : 'password'} className="peer w-full bg-transparent px-12 py-4 pt-6 text-gray-900 font-mono tracking-wider focus:outline-none" placeholder=" " value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
                    <label className="absolute left-12 top-4 text-gray-400 text-xs font-semibold transition-all peer-placeholder-shown:text-sm peer-placeholder-shown:top-1/2 peer-placeholder-shown:-translate-y-1/2 peer-focus:top-4 peer-focus:-translate-y-0 peer-focus:text-xs peer-focus:text-gray-900 pointer-events-none">New Password</label>
                    <button type="button" className="absolute right-4 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-900 transition-colors z-20 text-sm font-bold" onClick={() => setShowPassword((current) => !current)}>
                      {showPassword ? 'Hide' : 'Show'}
                    </button>
                  </div>
                </div>
                <PasswordStrength password={newPassword} />
                <div className="relative group">
                  <div className={`relative bg-white border focus-within:border-gray-900 focus-within:ring-4 focus-within:ring-yellow-400/40 rounded-[14px] transition-all duration-300 border-[1.5px] ${validConfirm ? 'border-green-500' : confirmPassword && !validConfirm ? 'border-red-500' : 'border-[#d6cfc2]'}`}>
                    <div className="absolute left-4 top-1/2 transform -translate-y-1/2 text-gray-400 z-10">
                      <SvgIcon>
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                      </SvgIcon>
                    </div>
                    <input type="password" className="peer w-full bg-transparent px-12 py-4 pt-6 text-gray-900 font-mono tracking-wider focus:outline-none" placeholder=" " value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
                    <label className="absolute left-12 top-4 text-gray-400 text-xs font-semibold transition-all peer-placeholder-shown:text-sm peer-placeholder-shown:top-1/2 peer-placeholder-shown:-translate-y-1/2 peer-focus:top-4 peer-focus:-translate-y-0 peer-focus:text-xs peer-focus:text-gray-900 pointer-events-none">Confirm Password</label>
                    {validConfirm && <CheckIcon className="absolute right-4 top-1/2 transform -translate-y-1/2 w-6 h-6 text-green-500 bg-green-50 rounded-full p-1 z-10" />}
                  </div>
                  {confirmPassword && !validConfirm && <p className="text-red-500 text-xs font-semibold pl-2 pt-2">Passwords do not match.</p>}
                </div>
                <button type="submit" className="w-full py-4 rounded-[14px] font-extrabold text-[1.05rem] tracking-[0.01em] flex items-center justify-center gap-3 relative group bg-yellow-400 text-gray-900 hover:bg-yellow-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed" disabled={!validPassword || !validConfirm || loading === 'password'}>
                  <span className="relative z-10">{loading === 'password' ? 'Securing Vault...' : 'Update Password'}</span>
                  {loading === 'password' && <div className="w-5 h-5 border-2 border-gray-900 border-t-transparent rounded-full animate-spin relative z-10"></div>}
                </button>
              </form>
            </div>
          )}

          {step === 4 && (
            <div className="flex flex-col items-center justify-center text-center py-10 transition-all duration-500">
              <div className="relative w-32 h-32 flex items-center justify-center mb-8">
                <div className="w-24 h-24 bg-green-600 rounded-full flex items-center justify-center text-white ring-8 ring-green-50 relative z-10">
                  <CheckIcon className="w-12 h-12" />
                </div>
              </div>
              <h2 className="font-display text-[34px] lg:text-[44px] font-extrabold text-gray-900 tracking-[-0.03em] mb-4 leading-[1.05]">
                Password Reset Successfully
              </h2>
              <p className="text-gray-500 text-[1.05rem] font-medium leading-relaxed mb-10 max-w-[300px]">
                Your Tap&amp;Go account security settings have been updated successfully.
              </p>
              <div className="w-full space-y-4">
                <button type="button" className="w-full py-4 rounded-[14px] font-extrabold text-[1.05rem] tracking-[0.01em] relative overflow-hidden bg-yellow-400 text-gray-900 hover:bg-yellow-500 transition-all" onClick={() => navigate('/')}>
                  Go to Home
                </button>
                <button type="button" className="w-full py-4 rounded-[14px] font-bold text-gray-900 bg-white border-[1.5px] border-gray-900 hover:bg-yellow-50 transition-all text-[1.05rem] tracking-wide" onClick={() => navigate('/login')}>
                  Go to Login
                </button>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

export default ForgotPassword
