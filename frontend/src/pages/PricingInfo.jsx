import React from 'react'
import Navbar from '../components/Common/Navbar.jsx'
import Footer from '../components/Common/Footer.jsx'
import { Link } from '../routes/navigation.jsx'

export function PricingInfo() {
  return (
    <div className="bg-surface min-h-screen text-slate-900 flex flex-col font-sans antialiased">
      <Navbar />

      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8">
        <section className="relative border-b-2 border-slate-900 pb-10 pt-2 sm:pb-14">
          <div className="relative z-10 space-y-4 max-w-3xl">
            <div className="tg-kicker">
              <span className="material-symbols-outlined text-sm">payments</span>
              Pricing &amp; Fares
            </div>
            <h1 className="max-w-4xl font-display text-[40px] font-extrabold leading-[1.02] tracking-[-0.04em] text-slate-900 sm:text-[60px]">
              Pricing &amp; Fare Information
            </h1>
            <p className="max-w-2xl text-base leading-relaxed text-slate-600 sm:text-lg">
              Transparent information regarding ride fare processing, digital wallet transactions, and NFC card delivery on Tap&amp;Go.
            </p>
          </div>
        </section>

        {/* Fare Principles */}
        <div className="bg-white rounded-[22px] p-6 sm:p-10 border border-[#dcd4c6] space-y-8 text-slate-700 leading-relaxed text-sm sm:text-base">
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">1. Ride Fare Structure</h2>
            <p>
              Tap&amp;Go is a cashless digital payment facilitator for taxis and auto-rickshaws.
            </p>
            <ul className="list-disc list-inside space-y-2 pl-2 text-slate-600">
              <li>Ride fares are calculated based on the applicable transportation arrangement or driver meter calculation for the trip.</li>
              <li>Tap&amp;Go records and processes the exact fare amount agreed upon or entered during the payment interaction.</li>
              <li>The full ride fare is transferred directly from the passenger&apos;s digital wallet to the driver&apos;s digital wallet.</li>
            </ul>
          </section>

          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">2. Wallet Top-Up &amp; Fee Transparency</h2>
            <p>
              Tap&amp;Go displays wallet top-up details prior to confirmation.
            </p>
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 text-slate-700 text-xs sm:text-sm space-y-1 font-medium">
              <p className="font-bold text-slate-900">Fee Disclosure:</p>
              <p>
                Any applicable platform, payment processing, or withdrawal charges will be disclosed to the user before confirmation where applicable.
              </p>
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">3. Driver Wallet Settlement</h2>
            <p>
              Fares earned by drivers accumulate instantly in their Tap&amp;Go driver wallet. Drivers can review transaction receipts, track daily earnings, and request wallet balance withdrawals through supported withdrawal mechanisms.
            </p>
          </section>

          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">4. NFC Card &amp; Location-Based Delivery Charges</h2>
            <p>
              The customer-facing price of a physical Tap&amp;Go NFC card is <strong>₹50</strong>. An applicable location-based shipping fee is calculated separately based on the destination address (Local Mumbai / Maharashtra Regional / National). The exact price breakdown (Card ₹50 + Shipping ₹X = Total ₹Y) is clearly displayed before order confirmation.
            </p>
          </section>

          {/* Quick Actions */}
          <section className="pt-4 flex flex-wrap gap-4">
            <Link to="/shipping-policy" className="px-5 py-2.5 rounded-xl bg-slate-900 text-yellow-400 font-bold text-xs sm:text-sm hover:bg-slate-800 transition-colors">
              Shipping &amp; Delivery Policy
            </Link>
            <Link to="/contact" className="px-5 py-2.5 rounded-xl bg-slate-100 border border-slate-200 text-slate-800 font-bold text-xs sm:text-sm hover:bg-slate-200 transition-colors">
              Contact Support
            </Link>
          </section>
        </div>
      </main>

      <Footer />
    </div>
  )
}

export default PricingInfo
