import React from 'react'
import Navbar from '../components/Common/Navbar.jsx'
import Footer from '../components/Common/Footer.jsx'
import { Link } from '../routes/navigation.jsx'

export function ContactUs() {
  return (
    <div className="bg-surface min-h-screen text-slate-900 flex flex-col font-sans antialiased">
      <Navbar />

      <main className="flex-1 max-w-6xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8 sm:space-y-12">
        {/* Header */}
        <section className="relative border-b-2 border-slate-900 pb-10 pt-2 sm:pb-14">
          <div className="relative z-10 space-y-4 max-w-3xl">
            <div className="tg-kicker">
              <span className="material-symbols-outlined text-sm">headset_mic</span>
              Customer Care
            </div>
            <h1 className="max-w-4xl font-display text-[40px] font-extrabold leading-[1.02] tracking-[-0.04em] text-slate-900 sm:text-[60px]">
              Contact Tap&amp;Go Support
            </h1>
            <p className="max-w-2xl text-base leading-relaxed text-slate-600 sm:text-lg">
              We are here to assist with wallet balance inquiries, card orders, driver onboarding, and payment support.
            </p>
          </div>
        </section>

        {/* Contact Cards Grid */}
        <section className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-white rounded-[22px] p-6 sm:p-9 border border-[#dcd4c6] space-y-4">
            <div className="w-12 h-12 rounded-xl bg-yellow-400 text-slate-900 flex items-center justify-center">
              <span className="material-symbols-outlined text-2xl">mail</span>
            </div>
            <h2 className="text-lg font-bold text-slate-900">Email Support</h2>
            <p className="text-xs text-slate-600">Send your queries, NFC card delivery requests, or dispute reports to our support team.</p>
            <div>
              <a href="mailto:tapandgosupport@gmail.com" className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-900 text-yellow-400 font-bold text-xs hover:bg-slate-800 transition-colors">
                <span className="material-symbols-outlined text-sm">mail</span>
                tapandgosupport@gmail.com
              </a>
            </div>
          </div>

          <div className="bg-white rounded-[22px] p-6 sm:p-9 border border-[#dcd4c6] space-y-4">
            <div className="w-12 h-12 rounded-xl bg-yellow-400 text-slate-900 flex items-center justify-center">
              <span className="material-symbols-outlined text-2xl">call</span>
            </div>
            <h2 className="text-lg font-bold text-slate-900">General &amp; Card Delivery Support</h2>
            <p className="text-xs text-slate-600">For general platform inquiries, card shipping status, and user support assistance.</p>
            <div>
              <a href="tel:8779914564" className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 text-white font-bold text-sm hover:bg-emerald-700 transition-colors">
                <span className="material-symbols-outlined text-sm">call</span>
                8779914564
              </a>
            </div>
          </div>

          <div className="bg-white rounded-[22px] p-6 sm:p-9 border border-[#dcd4c6] space-y-4">
            <div className="w-12 h-12 rounded-xl bg-yellow-400 text-slate-900 flex items-center justify-center">
              <span className="material-symbols-outlined text-2xl">credit_card_off</span>
            </div>
            <h2 className="text-lg font-bold text-slate-900">Lost Card / Wallet Support</h2>
            <p className="text-xs text-slate-600">Helpline for lost NFC cards or compromised wallet accounts.</p>
            <div>
              <a href="tel:9321768503" className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-500 text-slate-950 font-bold text-sm hover:bg-amber-400 transition-colors">
                <span className="material-symbols-outlined text-sm">phone_in_talk</span>
                9321768503
              </a>
            </div>
          </div>
        </section>

        {/* Physical Address Section */}
        <section className="bg-white rounded-[22px] p-6 sm:p-9 border border-[#dcd4c6] space-y-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-slate-100 text-slate-800 flex items-center justify-center font-bold text-lg">
              📍
            </div>
            <h2 className="text-xl sm:font-display text-[26px] sm:text-[30px] font-extrabold text-slate-900 tracking-[-0.03em]">Project Support Address</h2>
          </div>
          <div className="p-5 rounded-2xl bg-slate-50 border border-slate-200 text-slate-800 space-y-1 font-medium text-sm sm:text-base leading-relaxed">
            <p className="font-bold text-slate-900">Tap&amp;Go Project Support</p>
            <p>7/711, Rajni Mahal,</p>
            <p>Opp. AC Market, Tardeo,</p>
            <p>Mumbai – 400034,</p>
            <p>Maharashtra, India</p>
          </div>
        </section>

        {/* Quick Links Banner */}
        <section className="bg-yellow-400 rounded-[24px] p-7 sm:p-10 text-slate-900 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div>
            <h3 className="font-display text-[24px] sm:text-[28px] font-extrabold tracking-[-0.025em] text-slate-900">Need Immediate Help with a Lost Card?</h3>
            <p className="text-sm sm:text-base text-[#5e4a10]">Visit our dedicated lost card &amp; account protection support portal.</p>
          </div>
          <Link to="/lost-card" className="px-5 py-2.5 rounded-[12px] bg-slate-900 text-white font-bold text-xs sm:text-sm hover:bg-slate-800 transition-colors">
            Lost Card Assistance
          </Link>
        </section>
      </main>

      <Footer />
    </div>
  )
}

export default ContactUs
