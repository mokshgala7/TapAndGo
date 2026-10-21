import React from 'react'
import Navbar from '../components/Common/Navbar.jsx'
import Footer from '../components/Common/Footer.jsx'
import { Link } from '../routes/navigation.jsx'

export function LostCardSupport() {
  return (
    <div className="bg-surface min-h-screen text-slate-900 flex flex-col font-sans antialiased">
      <Navbar />

      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8">
        {/* Header */}
        <section className="relative border-b-2 border-slate-900 pb-10 pt-2 sm:pb-14">
          <div className="relative z-10 space-y-4 max-w-3xl">
            <div className="tg-kicker">
              <span className="material-symbols-outlined text-sm">warning</span>
              Emergency Helpline
            </div>
            <h1 className="max-w-4xl font-display text-[40px] font-extrabold leading-[1.02] tracking-[-0.04em] text-slate-900 sm:text-[60px]">
              Lost Card &amp; Account Assistance
            </h1>
            <p className="max-w-2xl text-base leading-relaxed text-slate-600 sm:text-lg">
              If you have lost your physical Tap&amp;Go NFC card or suspect unauthorized wallet activity, take immediate action by contacting support.
            </p>
          </div>
        </section>

        {/* Emergency Call Box */}
        <section className="bg-white rounded-2xl p-6 sm:p-10 shadow-sm border border-rose-200 space-y-6 text-center">
          <div className="w-16 h-16 rounded-full bg-rose-100 text-rose-700 flex items-center justify-center mx-auto text-3xl">
            <span className="material-symbols-outlined text-3xl">phone_in_talk</span>
          </div>

          <div className="space-y-2">
            <h2 className="text-xs uppercase font-extrabold tracking-widest text-slate-500">Dedicated Lost Card Support Helpline</h2>
            <a href="tel:9321768503" className="inline-block text-4xl sm:text-5xl font-black text-rose-600 hover:text-rose-700 tracking-tight">
              9321768503
            </a>
            <p className="text-xs sm:text-sm text-slate-600 font-medium pt-1">
              Call immediately for account assistance and lost card support.
            </p>
          </div>

          <div className="flex justify-center gap-3 pt-2">
            <a href="tel:9321768503" className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-rose-600 text-white font-bold text-sm hover:bg-rose-700 transition-colors shadow-sm">
              <span className="material-symbols-outlined">call</span>
              Call Lost Card Support Now
            </a>
            <a href="mailto:tapandgosupport@gmail.com" className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-slate-800 text-white font-bold text-sm hover:bg-slate-700 transition-colors shadow-sm">
              <span className="material-symbols-outlined">mail</span>
              Email Support
            </a>
          </div>

          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 text-slate-700 text-xs sm:text-sm max-w-2xl mx-auto space-y-1">
            <p className="font-bold text-slate-900">Email Support Backup:</p>
            <p>
              Send an urgent report to <a href="mailto:tapandgosupport@gmail.com" className="text-slate-900 font-bold hover:underline">tapandgosupport@gmail.com</a> with your registered phone number and account email.
            </p>
          </div>
        </section>

        {/* Recommended Action Steps */}
        <section className="bg-white rounded-[22px] p-6 sm:p-9 border border-[#dcd4c6] space-y-4">
          <h2 className="font-display text-[26px] sm:text-[30px] font-extrabold text-slate-900 tracking-[-0.03em] flex items-center gap-3">
            <span className="w-10 h-10 rounded-xl bg-yellow-400 text-slate-900 flex items-center justify-center text-[22px]">
              🛡️
            </span>
            Steps to Take Immediately
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            <div className="p-5 rounded-2xl bg-slate-50 border border-slate-200 space-y-2">
              <span className="font-extrabold text-rose-600 text-base block">1. Call Support</span>
              <p className="text-xs text-slate-600 leading-relaxed">
                Dial <strong>9321768503</strong> to report a lost card and request account assistance.
              </p>
            </div>

            <div className="p-5 rounded-2xl bg-slate-50 border border-slate-200 space-y-2">
              <span className="font-extrabold text-slate-900 text-base block">2. Lock Account Session</span>
              <p className="text-xs text-slate-600 leading-relaxed">
                Log into your Tap&amp;Go portal and update your password or lock your active browser session.
              </p>
            </div>

            <div className="p-5 rounded-2xl bg-slate-50 border border-slate-200 space-y-2">
              <span className="font-extrabold text-emerald-600 text-base block">3. Support Replacement</span>
              <p className="text-xs text-slate-600 leading-relaxed">
                Request replacement card linkage assistance from the Tap&amp;Go support team.
              </p>
            </div>
          </div>
        </section>

        {/* Quick Return Action */}
        <section className="bg-yellow-400 rounded-[24px] p-7 sm:p-10 text-slate-900 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div>
            <h3 className="font-display text-[24px] sm:text-[28px] font-extrabold tracking-[-0.025em] text-slate-900">Account Access</h3>
            <p className="text-sm sm:text-base text-[#5e4a10]">Access your dashboard to view active wallet sessions and transaction history.</p>
          </div>
          <Link to="/login" className="px-5 py-2.5 rounded-[12px] bg-slate-900 text-white font-bold text-xs sm:text-sm hover:bg-slate-800 transition-colors">
            Go to Login
          </Link>
        </section>
      </main>

      <Footer />
    </div>
  )
}

export default LostCardSupport
