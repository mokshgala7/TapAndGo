import React from 'react'
import { Link } from '../../routes/navigation.jsx'

function Footer() {
  return (
    <footer
      id="footer"
      className="mt-auto w-full border-t-2 border-slate-900 bg-white text-slate-600"
    >
      <div className="relative mx-auto max-w-7xl px-container-padding py-12 sm:py-14 space-y-10">
        {/* Top Grid Section */}
        <div className="relative grid grid-cols-1 md:grid-cols-4 gap-8">
          {/* Col 1: Brand & Contact Info */}
          <div className="md:col-span-1 space-y-3">
            <Link to="/" className="font-display text-[28px] font-extrabold tracking-tight text-slate-900 hover:opacity-90 transition-opacity">
              Tap<span className="text-yellow-500">&amp;</span>Go
            </Link>
            <p className="text-sm text-slate-600 leading-relaxed font-medium">
              Smart cashless payment platform for taxis and auto-rickshaws.
            </p>
            <div className="pt-2 text-[13px] text-slate-700 space-y-1.5 font-medium">
              <p>
                <strong className="text-slate-500">Email:</strong>{' '}
                <a href="mailto:tapandgosupport@gmail.com" className="font-semibold text-[#8a6400] hover:underline">
                  tapandgosupport@gmail.com
                </a>
              </p>
              <p>
                <strong className="text-slate-500">Support:</strong>{' '}
                <a href="tel:8779914564" className="font-semibold text-slate-900 hover:underline">
                  8779914564
                </a>
              </p>
              <p className="pt-1 text-xs text-slate-500 leading-normal">
                <strong className="text-slate-600">Project Support Address:</strong> 7/711, Rajni Mahal, Opp. AC Market, Tardeo, Mumbai – 400034, Maharashtra, India
              </p>
            </div>
          </div>

          {/* Col 2: Quick Links */}
          <div className="space-y-3">
            <h4 className="text-[11px] font-extrabold uppercase tracking-[0.14em] text-[#8a6400]">Platform</h4>
            <ul className="space-y-2.5 text-sm font-semibold text-slate-700">
              <li>
                <Link to="/about" className="hover:text-slate-900 transition-colors">
                  About Us
                </Link>
              </li>
              <li>
                <Link to="/payments" className="hover:text-slate-900 transition-colors">
                  Wallet &amp; Payments
                </Link>
              </li>
              <li>
                <Link to="/pricing" className="hover:text-slate-900 transition-colors">
                  Pricing / Fare Information
                </Link>
              </li>
              <li>
                <Link to="/faq" className="hover:text-slate-900 transition-colors">
                  FAQ / Support
                </Link>
              </li>

            </ul>
          </div>

          {/* Col 3: Support & Assistance */}
          <div className="space-y-3">
            <h4 className="text-[11px] font-extrabold uppercase tracking-[0.14em] text-[#8a6400]">Support &amp; Emergency</h4>
            <ul className="space-y-2.5 text-sm font-semibold text-slate-700">
              <li>
                <Link to="/contact" className="hover:text-slate-900 transition-colors">
                  Contact Us
                </Link>
              </li>
              <li>
                <Link to="/lost-card" className="text-[#c8372d] hover:text-[#a52b23] transition-colors flex items-center gap-1 font-bold">
                  <span className="material-symbols-outlined text-sm">warning</span>
                  Lost Card Support
                </Link>
              </li>
              <li>
                <Link to="/refund-policy" className="hover:text-slate-900 transition-colors">
                  Refund &amp; Cancellation Policy
                </Link>
              </li>
              <li>
                <Link to="/shipping-policy" className="hover:text-slate-900 transition-colors">
                  Shipping &amp; Delivery Policy
                </Link>
              </li>
            </ul>
          </div>

          {/* Col 4: Legal Compliance */}
          <div className="space-y-3">
            <h4 className="text-[11px] font-extrabold uppercase tracking-[0.14em] text-[#8a6400]">Legal &amp; Policy</h4>
            <ul className="space-y-2.5 text-sm font-semibold text-slate-700">
              <li>
                <Link to="/privacy" className="hover:text-slate-900 transition-colors">
                  Privacy Policy
                </Link>
              </li>
              <li>
                <Link to="/terms" className="hover:text-slate-900 transition-colors">
                  Terms &amp; Conditions
                </Link>
              </li>
              <li>
                <Link to="/login" className="hover:text-slate-900 transition-colors">
                  Portal Login
                </Link>
              </li>
              <li>
                <Link to="/register" className="hover:text-slate-900 transition-colors">
                  Register Account
                </Link>
              </li>
            </ul>
          </div>
        </div>

        {/* Bottom Bar */}
        <div className="relative border-t border-slate-200 pt-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-slate-500">
          <p>© 2026 Tap&amp;Go. Student / Final-Year Academic Project by Moksh Gala,Arham Fofaria and Vansh Gala(SVKM Bhagubai Polytechnic).</p>
          <div className="flex gap-4">
            <Link to="/privacy" className="font-semibold hover:text-slate-900">Privacy</Link>
            <Link to="/terms" className="font-semibold hover:text-slate-900">Terms</Link>
            <Link to="/contact" className="font-semibold hover:text-slate-900">Contact</Link>
          </div>
        </div>
      </div>
    </footer>
  )
}

export default Footer
