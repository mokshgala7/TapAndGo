import { useState } from 'react'
import { Link, useCurrentView, useNavigate } from '../../routes/navigation.jsx'
import { APP_DOWNLOAD_FILE_NAME, resolveAppDownloadUrl } from '../../config/appDownload.js'
import AppDownloadModal from './AppDownloadModal.jsx'
import './Navbar.css'

const contactDetails = [
  {
    label: 'General Support',
    value: '8779914564',
  },
  {
    label: 'Email',
    value: 'tapandgosupport@gmail.com',
  },
  {
    label: 'Lost Card Helpline',
    value: '9321768503',
  },
]

function Navbar() {
  const [isContactOpen, setIsContactOpen] = useState(false)
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [downloadUrl, setDownloadUrl] = useState(null) // null = dialog closed, '' = coming soon, else the APK link
  const view = useCurrentView()
  const navigate = useNavigate()

  const scrollToSection = (sectionId) => {
    const scroll = () => {
      document.getElementById(sectionId)?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      })
    }

    if (view !== 'home') {
      navigate('/')
      window.setTimeout(scroll, 80)
      return
    }

    scroll()
  }

  const handleSectionClick = (sectionId) => {
    setIsContactOpen(false)
    setIsMobileMenuOpen(false)
    scrollToSection(sectionId)
  }

  const handleContactClick = () => {
    setIsContactOpen((current) => !current)
  }

  // "Download the App": with a configured APK link the download starts at once and the install
  // guidance opens; without one only the "coming soon" message is shown (nothing is downloaded).
  const handleDownloadClick = () => {
    setIsContactOpen(false)
    setIsMobileMenuOpen(false)
    const url = resolveAppDownloadUrl()
    if (url) {
      const link = document.createElement('a')
      link.href = url
      link.download = APP_DOWNLOAD_FILE_NAME
      link.rel = 'noopener'
      document.body.appendChild(link)
      link.click()
      link.remove()
    }
    setDownloadUrl(url)
  }

  return (
    <header className="tapgo-header sticky top-0 z-50">
        <div className="tapgo-header-bar mx-auto flex max-w-7xl items-center justify-between px-container-padding py-3.5">
          <Link className="tapgo-wordmark text-[22px] sm:text-[26px]" to="/" aria-label="Tap&Go home">
            Tap<span className="tapgo-amp">&amp;</span>Go
          </Link>

          {/* Desktop Navigation */}
          <nav className="hidden gap-5 lg:gap-7 text-[15px] font-semibold md:flex items-center" aria-label="Primary navigation">
            <Link className={`tapgo-pill-link${view === 'home' ? ' is-active' : ''}`} to="/">Home</Link>
            <Link className={`tapgo-pill-link${view === 'about' ? ' is-active' : ''}`} to="/about">About Us</Link>
            <Link className={`tapgo-pill-link${view === 'payments' ? ' is-active' : ''}`} to="/payments">Payments</Link>
            <button className="tapgo-nav-link tapgo-pill-link" type="button" onClick={() => handleSectionClick('features')}>
              Features
            </button>
            <Link className={`tapgo-pill-link${view === 'faq' ? ' is-active' : ''}`} to="/faq">FAQ</Link>

            <div className="tapgo-contact-menu">
              <button
                className={`tapgo-nav-link tapgo-pill-link tapgo-contact-trigger${isContactOpen || view === 'contact' ? ' is-active' : ''}`}
                type="button"
                onClick={handleContactClick}
                aria-expanded={isContactOpen}
                aria-controls="contact-dropdown"
              >
                Contact Us
                <span className="material-symbols-outlined" aria-hidden="true">
                  expand_more
                </span>
              </button>

              {isContactOpen && (
                <div className="tapgo-contact-dropdown" id="contact-dropdown">
                  {contactDetails.map((detail) => (
                    <div className="tapgo-contact-row" key={detail.label}>
                      <span>{detail.label}</span>
                      <strong>{detail.value}</strong>
                    </div>
                  ))}
                  <div className="pt-3 text-center border-t border-slate-200 mt-1">
                    <Link to="/contact" onClick={() => setIsContactOpen(false)} className="text-xs text-[#8a6400] font-bold hover:underline">
                      View Full Contact Details →
                    </Link>
                  </div>
                </div>
              )}
            </div>

            <button
              className="tapgo-download-btn"
              type="button"
              onClick={handleDownloadClick}
              aria-label="Download the App"
              title="Download the App"
            >
              <span className="material-symbols-outlined" aria-hidden="true">
                download
              </span>
              <span className="tapgo-download-label">Download the App</span>
            </button>
          </nav>

          {/* Action Buttons & Mobile Hamburger */}
          <div className="flex items-center gap-2 sm:gap-3">
            <Link
              className="tapgo-btn-ghost px-3.5 sm:px-5 text-xs sm:text-sm"
              to="/login"
            >
              Login
            </Link>
            <Link className="tapgo-btn-yellow px-3.5 sm:px-5 text-xs sm:text-sm" to="/register">
              Register
            </Link>

            <button
              type="button"
              className="tapgo-menu-btn md:hidden"
              onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
              aria-label="Toggle mobile menu"
            >
              <span className="material-symbols-outlined text-2xl">
                {isMobileMenuOpen ? 'close' : 'menu'}
              </span>
            </button>
          </div>
        </div>

        {/* Mobile Navigation Drawer */}
        {isMobileMenuOpen && (
          <div className="tapgo-mobile-drawer md:hidden px-container-padding py-3 space-y-1 font-semibold text-[16px]">
            <Link to="/" onClick={() => setIsMobileMenuOpen(false)} className="tapgo-drawer-link">
              Home
            </Link>
            <Link to="/about" onClick={() => setIsMobileMenuOpen(false)} className="tapgo-drawer-link">
              About Us
            </Link>
            <Link to="/payments" onClick={() => setIsMobileMenuOpen(false)} className="tapgo-drawer-link">
              How Payments Work
            </Link>
            <Link to="/pricing" onClick={() => setIsMobileMenuOpen(false)} className="tapgo-drawer-link">
              Pricing &amp; Fares
            </Link>
            <Link to="/faq" onClick={() => setIsMobileMenuOpen(false)} className="tapgo-drawer-link">
              FAQ &amp; Support
            </Link>
            <Link to="/contact" onClick={() => setIsMobileMenuOpen(false)} className="tapgo-drawer-link font-bold">
              Contact Us
            </Link>
            <button type="button" onClick={handleDownloadClick} className="tapgo-download-btn tapgo-download-btn--block">
              <span className="material-symbols-outlined" aria-hidden="true">
                download
              </span>
              Download the App
            </button>
            <Link to="/lost-card" onClick={() => setIsMobileMenuOpen(false)} className="tapgo-drawer-link tapgo-drawer-link--alert">
              Lost Card Support (9321768503)
            </Link>
          </div>
        )}
      {downloadUrl !== null && <AppDownloadModal url={downloadUrl} onClose={() => setDownloadUrl(null)} />}
      </header>
  )
}

export default Navbar
