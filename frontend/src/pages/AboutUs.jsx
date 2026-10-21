import React from 'react'
import Navbar from '../components/Common/Navbar.jsx'
import Footer from '../components/Common/Footer.jsx'
import { Link } from '../routes/navigation.jsx'

export function AboutUs() {
  return (
    <div className="bg-surface min-h-screen text-slate-900 flex flex-col font-sans antialiased">
      <Navbar />

      <main className="flex-1 max-w-6xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8 sm:space-y-12">
        {/* Header */}
        <section className="relative border-b-2 border-slate-900 pb-10 pt-2 sm:pb-14">
          <div className="relative z-10 space-y-4 max-w-3xl">
            <div className="tg-kicker">
              <span className="material-symbols-outlined text-sm">info</span>
              About Tap&amp;Go
            </div>
            <h1 className="max-w-4xl font-display text-[40px] font-extrabold leading-[1.02] tracking-[-0.04em] text-slate-900 sm:text-[60px]">
              Smart Cashless Payment Platform for Mobility
            </h1>
            <p className="max-w-2xl text-base leading-relaxed text-slate-600 sm:text-lg">
              Tap&amp;Go is a modern digital payment system designed specifically for taxis and auto-rickshaws, creating an effortless cashless ecosystem connecting passengers and drivers.
            </p>
          </div>
        </section>

        {/* Core Vision & Overview */}
        <section className="bg-white rounded-[22px] p-6 sm:p-9 border border-[#dcd4c6] space-y-4">
          <h2 className="font-display text-[26px] sm:text-[30px] font-extrabold text-slate-900 tracking-[-0.03em] flex items-center gap-3">
            <span className="w-10 h-10 rounded-xl bg-yellow-400 text-slate-900 flex items-center justify-center text-[22px]">
              🎯
            </span>
            Platform Overview
          </h2>
          <p className="text-slate-700 leading-relaxed text-sm sm:text-base">
            Tap&amp;Go simplifies daily travel payments by enabling instant cashless transactions between passengers and drivers. Using custom ESP32-S3-based smart POS terminal hardware, high-speed NFC interaction, and dynamic QR code generation, Tap&amp;Go reduces reliance on physical cash and exact-change transactions in urban transport.
          </p>
        </section>

        {/* Core Capabilities Grid */}
        <section className="space-y-6">
          <h2 className="font-display text-[26px] sm:text-[30px] font-extrabold text-slate-900 tracking-[-0.03em] flex items-center gap-3">
            <span className="w-10 h-10 rounded-xl bg-yellow-400 text-slate-900 flex items-center justify-center text-[22px]">
              ⚡
            </span>
            Core Capabilities
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            <div className="p-6 rounded-[18px] bg-white border border-[#dcd4c6] space-y-2">
              <span className="material-symbols-outlined text-slate-900 text-2xl">account_balance_wallet</span>
              <h3 className="font-bold text-slate-900 text-lg">Passenger &amp; Driver Wallets</h3>
              <p className="text-xs text-slate-600 leading-relaxed">
                Dedicated digital wallet accounts for passengers and drivers with real-time balance tracking and instant wallet-to-wallet fare settlements.
              </p>
            </div>

            <div className="p-6 rounded-[18px] bg-white border border-[#dcd4c6] space-y-2">
              <span className="material-symbols-outlined text-slate-900 text-2xl">contactless</span>
              <h3 className="font-bold text-slate-900 text-lg">NFC &amp; QR Interaction</h3>
              <p className="text-xs text-slate-600 leading-relaxed">
                Dual payment support featuring instant tap-and-go NFC card scanning alongside dynamic UPI/QR code payment options.
              </p>
            </div>

            <div className="p-6 rounded-[18px] bg-white border border-[#dcd4c6] space-y-2">
              <span className="material-symbols-outlined text-slate-900 text-2xl">hardware</span>
              <h3 className="font-bold text-slate-900 text-lg">Smart POS Terminal</h3>
              <p className="text-xs text-slate-600 leading-relaxed">
                Custom ESP32-S3 based hardware POS concept designed specifically for vehicle dashboard deployment and driver convenience.
              </p>
            </div>

            <div className="p-6 rounded-[18px] bg-white border border-[#dcd4c6] space-y-2">
              <span className="material-symbols-outlined text-slate-900 text-2xl">security</span>
              <h3 className="font-bold text-slate-900 text-lg">AI Fraud Detection</h3>
              <p className="text-xs text-slate-600 leading-relaxed">
                Automated risk scoring and intelligent transaction analysis to detect anomaly patterns and protect user balances.
              </p>
            </div>

            <div className="p-6 rounded-[18px] bg-white border border-[#dcd4c6] space-y-2">
              <span className="material-symbols-outlined text-slate-900 text-2xl">lock_reset</span>
              <h3 className="font-bold text-slate-900 text-lg">OTP Security Verification</h3>
              <p className="text-xs text-slate-600 leading-relaxed">
                Multi-factor OTP verification step for suspicious transactions, profile edits, and high-value wallet actions.
              </p>
            </div>

            <div className="p-6 rounded-[18px] bg-white border border-[#dcd4c6] space-y-2">
              <span className="material-symbols-outlined text-slate-900 text-2xl">dns</span>
              <h3 className="font-bold text-slate-900 text-lg">FastAPI Backend</h3>
              <p className="text-xs text-slate-600 leading-relaxed">
                High-performance Python FastAPI REST architecture backed by database transaction recording and administrative management tools.
              </p>
            </div>
          </div>
        </section>

        {/* Project Background */}
        <section className="bg-white rounded-[22px] p-6 sm:p-9 border border-[#dcd4c6] space-y-4">
          <h2 className="font-display text-[26px] sm:text-[30px] font-extrabold text-slate-900 tracking-[-0.03em] flex items-center gap-3">
            <span className="w-10 h-10 rounded-xl bg-yellow-400 text-slate-900 flex items-center justify-center text-[22px]">
              🎓
            </span>
            Project Background
          </h2>
          <p className="text-slate-700 leading-relaxed text-sm sm:text-base">
            Tap&amp;Go is a student / final-year project developed by <strong>Moksh Gala,Arham Fofriya and Vansh Gala</strong>, a Diploma student in Computer Science &amp; Engineering at <strong>SVKM’s Shri Bhagubai Mafatlal Polytechnic</strong> (Mumbai, Maharashtra).
          </p>
          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 text-slate-700 text-xs sm:text-sm leading-relaxed space-y-1">
            <p className="font-bold text-slate-900">Academic Project Disclosure:</p>
            <p>
              Tap&amp;Go is created strictly for academic research, technological evaluation, and demonstration of digital payment systems in public transportation. It is not a registered commercial entity or licensed payment aggregator.
            </p>
          </div>
        </section>

        {/* Navigation Quick Actions */}
        <section className="bg-yellow-400 rounded-[24px] p-7 sm:p-10 text-slate-900 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div>
            <h3 className="font-display text-[24px] sm:text-[28px] font-extrabold tracking-[-0.025em] text-slate-900">Explore Tap&amp;Go Features</h3>
            <p className="text-sm sm:text-base text-[#5e4a10]">Learn how wallet funding, payments, and driver withdrawals operate on Tap&amp;Go.</p>
          </div>
          <div className="flex gap-3">
            <Link to="/payments" className="px-5 py-2.5 rounded-[12px] bg-slate-900 text-white font-bold text-xs sm:text-sm hover:bg-slate-800 transition-colors">
              How Payments Work
            </Link>
            <Link to="/contact" className="px-5 py-2.5 rounded-[12px] bg-white text-slate-900 font-bold text-xs sm:text-sm hover:bg-yellow-50 transition-colors">
              Contact Support
            </Link>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  )
}

export default AboutUs
