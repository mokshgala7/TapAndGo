import { useEffect, useState } from 'react'
import { Link, useNavigate } from '../routes/navigation.jsx'
import { useAuth } from '../context/AuthContext.jsx'
import Footer from '../components/Common/Footer.jsx'
import Navbar from '../components/Common/Navbar.jsx'
import illustration from '../assets/images/login-illustration.png'
import logo from '../assets/images/tapgo-logo.png'
import '../styles/Login.css'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'

const trustBadges = ['🔒 Secure Login', '🛡 AI Powered', '🚖 Trusted by Taxi Drivers']

const initialErrors = {
  account: '',
  password: '',
}

function validateLogin({ account, password }) {
  const nextErrors = { ...initialErrors }
  const accountValue = account.trim()
  const validEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(accountValue)
  const validMobile = /^[0-9]{10}$/.test(accountValue)

  if (!accountValue) {
    nextErrors.account = 'Email or mobile number is required.'
  } else if (!validEmail && !validMobile) {
    nextErrors.account = 'Enter a valid email or 10-digit mobile number.'
  }

  if (!password) {
    nextErrors.password = 'Password is required.'
  } else if (password.length < 3) {
    nextErrors.password = 'Password must be at least 3 characters.'
  }

  return nextErrors
}

function Login() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [formData, setFormData] = useState({ account: '', password: '' })
  const [rememberMe, setRememberMe] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [errors, setErrors] = useState(initialErrors)
  const [successMessage, setSuccessMessage] = useState('')


  useEffect(() => {
    const reviewNotice = sessionStorage.getItem('tapgo_registration_notice')
    if (reviewNotice) {
      setSuccessMessage(reviewNotice)
      sessionStorage.removeItem('tapgo_registration_notice')
    }
  }, [])

  const updateField = (event) => {
    const { name, value } = event.target

    setFormData((current) => ({
      ...current,
      [name]: value,
    }))

    if (errors[name]) {
      setErrors((current) => ({
        ...current,
        [name]: '',
      }))
    }
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setSuccessMessage('')

    const validationErrors = validateLogin(formData)
    setErrors(validationErrors)

    if (validationErrors.account || validationErrors.password) {
      return
    }

    setIsLoading(true)

    const res = await login(formData)
    setIsLoading(false)

    if (res.success && res.user) {
      setSuccessMessage(rememberMe ? 'Login validated. This device will be remembered.' : 'Login validated securely.')
      const targetRole = (res.user.account_type || res.user.role || '').toLowerCase()
      if (targetRole === 'admin') {
        sessionStorage.setItem('tapgo_admin_session', JSON.stringify({ email: res.user.email, name: res.user.name || 'Admin', id: res.user.id }))
        navigate('/admin')
      } else if (targetRole === 'driver') {
        navigate('/driver')
      } else {
        navigate('/passenger')
      }
    } else if (res.redirect_admin) {
      // User typed admin credentials manually — call admin API to get real admin id
      try {
        const adminRes = await fetch(`${API_BASE}/api/admin/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: formData.account, password: formData.password }),
        })
        const adminData = await adminRes.json()
        if (adminData.success && adminData.admin) {
          sessionStorage.setItem('tapgo_admin_session', JSON.stringify(adminData.admin))
          navigate('/admin')
        } else {
          setErrors((current) => ({ ...current, password: 'Admin login failed. Use the Admin Console.' }))
        }
      } catch {
        setErrors((current) => ({ ...current, password: 'Backend unavailable.' }))
      }
    } else {
      setErrors((current) => ({
        ...current,
        password: res.message || 'Invalid Credentials',
      }))
    }
  }

  return (
    <div className="tapgo-login tapgo-shell font-body-lg antialiased selection:bg-secondary-container selection:text-on-secondary-container">
      <Navbar />

      <main className="login-main">
        <div className="login-background" aria-hidden="true">
          <div className="login-blob login-blob-primary"></div>
          <div className="login-blob login-blob-secondary"></div>
          <div className="login-dot login-dot-one"></div>
          <div className="login-dot login-dot-two"></div>
          <div className="login-dot login-dot-three"></div>
        </div>

        <section className="login-layout" aria-label="Tap&Go login">
          <div className="login-visual" aria-hidden="true">
            <div className="login-illustration-wrap">
              <img
                className="login-illustration"
                src={illustration}
                alt="Tap&Go smart mobility illustration"
              />
            </div>
          </div>

          <div className="login-panel">
            <Link className="login-brand" to="/" aria-label="Tap&Go home">
              <img className="login-brand-logo" src={logo} alt="" />
              <span className="login-brand-name">
                Tap<span>&amp;</span>Go
              </span>
            </Link>

            <article className="login-card">
              <div
                className={`login-progress ${isLoading ? 'login-progress-active' : ''}`}
                aria-hidden="true"
              ></div>

              <header className="login-header">
                <h1>Welcome Back</h1>
                <p>Sign in to continue using Tap&Go.</p>
              </header>

              <form className="login-form" onSubmit={handleSubmit} noValidate>
                <div className="login-field">
                  <label htmlFor="account">Email Address or Mobile Number</label>
                  <div className={`login-input-box ${errors.account ? 'login-input-box-error' : ''}`}>
                    <span className="material-symbols-outlined login-input-icon" aria-hidden="true">
                      mail
                    </span>
                    <input
                      className="login-input-field"
                      id="account"
                      name="account"
                      type="text"
                      autoComplete="username"
                      placeholder="name@example.com or 9876543210"
                      value={formData.account}
                      onChange={updateField}
                      aria-invalid={Boolean(errors.account)}
                      aria-describedby={errors.account ? 'account-error' : undefined}
                    />
                  </div>
                  <p className="login-error" id="account-error" role="alert">
                    {errors.account}
                  </p>
                </div>

                <div className="login-field">
                  <label htmlFor="password">Password</label>
                  <div className={`login-input-box ${errors.password ? 'login-input-box-error' : ''}`}>
                    <span className="material-symbols-outlined login-input-icon" aria-hidden="true">
                      lock
                    </span>
                    <input
                      className="login-input-field"
                      id="password"
                      name="password"
                      type={showPassword ? 'text' : 'password'}
                      autoComplete="current-password"
                      placeholder="••••••••"
                      value={formData.password}
                      onChange={updateField}
                      aria-invalid={Boolean(errors.password)}
                      aria-describedby={errors.password ? 'password-error' : undefined}
                    />
                    <button
                      className="login-password-toggle"
                      type="button"
                      onClick={() => setShowPassword((current) => !current)}
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                    >
                      <span className="material-symbols-outlined" aria-hidden="true">
                        {showPassword ? 'visibility_off' : 'visibility'}
                      </span>
                    </button>
                  </div>
                  <p className="login-error" id="password-error" role="alert">
                    {errors.password}
                  </p>
                </div>

                <div className="login-options">
                  <label className="login-checkbox">
                    <input
                      type="checkbox"
                      checked={rememberMe}
                      onChange={(event) => setRememberMe(event.target.checked)}
                    />
                    <span className="login-checkbox-box" aria-hidden="true">
                      <span className="material-symbols-outlined">check</span>
                    </span>
                    <span>Remember Me</span>
                  </label>

                  <Link className="login-forgot" to="/forgot-password">
                    Forgot Password?
                  </Link>
                </div>

                <button className="login-button" type="submit" disabled={isLoading}>
                  <span>{isLoading ? 'Signing In...' : 'Login'}</span>
                  {isLoading && (
                    <span className="material-symbols-outlined login-spinner" aria-hidden="true">
                      progress_activity
                    </span>
                  )}
                </button>


              </form>

              <div className="login-card-footer">
                <p>
                  Don&apos;t have an account? <Link to="/register">Sign Up</Link>
                </p>
                {successMessage && (
                  <p className="login-success" role="status">
                    {successMessage}
                  </p>
                )}
              </div>
            </article>



            <div className="login-trust" aria-label="Security badges">
              {trustBadges.map((badge, index) => (
                <div className="login-trust-item" key={badge}>
                  <span>{badge}</span>
                  {index < trustBadges.length - 1 && (
                    <span className="login-trust-divider" aria-hidden="true"></span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  )
}

export default Login
