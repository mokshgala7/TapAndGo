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
    <header className="sticky top-0 z-50 border-b border-gray-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-3 sm:px-6 py-3 sm:py-4">
          <Link className="text-xl sm:text-2xl font-bold text-black" to="/" aria-label="Tap&Go home">
            Tap<span className="text-yellow-500">&amp;</span>Go
          </Link>

          {/* Desktop Navigation */}
          <nav className="hidden gap-6 lg:gap-8 text-sm font-semibold md:flex items-center" aria-label="Primary navigation">
            <Link to="/">Home</Link>
            <Link to="/about">About Us</Link>
            <Link to="/payments">Payments</Link>
            <button className="tapgo-nav-link" type="button" onClick={() => handleSectionClick('features')}>
              Features
            </button>
            <Link to="/faq">FAQ</Link>

            <div className="tapgo-contact-menu">
              <button
                className="tapgo-nav-link tapgo-contact-trigger"
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
                  <div className="pt-2 text-center border-t border-slate-100 mt-1">
                    <Link to="/contact" onClick={() => setIsContactOpen(false)} className="text-xs text-slate-900 font-bold hover:underline">
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
              className="rounded-lg border border-slate-800 bg-transparent px-3 sm:px-4 py-1.5 sm:py-2 text-xs sm:text-sm font-semibold text-slate-900 hover:bg-slate-50 transition-colors"
              to="/login"
            >
              Login
            </Link>
            <Link className="rounded-lg bg-yellow-400 hover:bg-yellow-500 px-3 sm:px-4 py-1.5 sm:py-2 text-xs sm:text-sm font-semibold text-black transition-colors" to="/register">
              Register
            </Link>

            <button
              type="button"
              className="md:hidden p-1.5 text-slate-700 hover:text-black rounded-lg focus:outline-none"
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
          <div className="md:hidden border-t border-slate-200 bg-white px-4 py-4 space-y-3 font-semibold text-sm">
            <Link to="/" onClick={() => setIsMobileMenuOpen(false)} className="block py-1">
              Home
            </Link>
            <Link to="/about" onClick={() => setIsMobileMenuOpen(false)} className="block py-1">
              About Us
            </Link>
            <Link to="/payments" onClick={() => setIsMobileMenuOpen(false)} className="block py-1">
              How Payments Work
            </Link>
            <Link to="/pricing" onClick={() => setIsMobileMenuOpen(false)} className="block py-1">
              Pricing &amp; Fares
            </Link>
            <Link to="/faq" onClick={() => setIsMobileMenuOpen(false)} className="block py-1">
              FAQ &amp; Support
            </Link>
            <Link to="/contact" onClick={() => setIsMobileMenuOpen(false)} className="block py-1 text-slate-900 font-bold">
              Contact Us
            </Link>
            <button type="button" onClick={handleDownloadClick} className="tapgo-download-btn tapgo-download-btn--block">
              <span className="material-symbols-outlined" aria-hidden="true">
                download
              </span>
              Download the App
            </button>
            <Link to="/lost-card" onClick={() => setIsMobileMenuOpen(false)} className="block py-1 text-amber-600 font-bold">
              Lost Card Support (9321768503)
            </Link>
          </div>
        )}
      {downloadUrl !== null && <AppDownloadModal url={downloadUrl} onClose={() => setDownloadUrl(null)} />}
      </header>
  )
}

export default Navbar
