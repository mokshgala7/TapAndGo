import React from 'react'
import Navbar from '../components/Common/Navbar.jsx'
import Footer from '../components/Common/Footer.jsx'

export function RefundPolicy() {
  return (
    <div className="bg-surface min-h-screen text-slate-900 flex flex-col font-sans antialiased">
      <Navbar />

      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8">
        {/* Header */}
        <section className="relative border-b-2 border-slate-900 pb-10 pt-2 sm:pb-14 space-y-3">
          <div className="tg-kicker">
            <span className="material-symbols-outlined text-sm">currency_exchange</span>
            Refund &amp; Cancellation Policy
          </div>
          <h1 className="max-w-4xl font-display text-[40px] font-extrabold leading-[1.02] tracking-[-0.04em] text-slate-900 sm:text-[60px]">
            Refund &amp; Cancellation Policy
          </h1>
          <p className="text-slate-500 text-xs sm:text-sm">
            Last Updated: August 2026
          </p>
        </section>

        {/* Content Body */}
        <div className="bg-white rounded-[22px] p-6 sm:p-10 border border-[#dcd4c6] space-y-8 text-slate-700 leading-relaxed text-sm sm:text-base">
          {/* Section 1: Ride Cancellations */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">1. Ride Cancellations</h2>
            <p>
              Tap&amp;Go processes fare payments at the point of interaction (NFC tap or QR scan) between passenger and driver upon ride completion. If a ride is cancelled before payment interaction occurs, no wallet deduction takes place.
            </p>
          </section>

          {/* Section 2: Wallet Transactions */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">2. Wallet Transactions</h2>
            <p>
              Completed wallet top-up transactions and internal passenger-to-driver wallet transfers are processed in real time and are not automatically reversible through the application. Users who encounter incorrect fare deductions or disputed transfers should contact support for manual review.
            </p>
          </section>

          {/* Section 3: Failed Transactions */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">3. Failed Wallet Top-Ups</h2>
            <p>
              If a payment is debited from a user&apos;s bank account or UPI application during a wallet top-up but the Tap&amp;Go wallet is not credited, the transaction will be checked against the payment status/callback information and the applicable payment provider&apos;s refund/reversal process. Users can contact support with transaction details.
            </p>
          </section>

          {/* Section 4: Duplicate Transactions */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">4. Duplicate Transactions</h2>
            <p>
              In the event of a technical glitch causing duplicate fare deductions for a single trip, users should report the transaction reference IDs to our support team. Once verified against backend logs, appropriate wallet adjustments will be initiated.
            </p>
          </section>

          {/* Section 5: NFC Card Orders */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">5. NFC Card Orders &amp; Cancellations</h2>
            <p>
              Users may request cancellation of a physical NFC card order subject to its current processing or dispatch status. If an NFC card order has already been dispatched for shipping, cancellation may no longer be possible. Refund handling for card orders depends on the order status and payment verification. Any applicable delivery charges are disclosed prior to order confirmation. If a card shipment is returned due to an incomplete or incorrect address provided by the user, re-delivery charges may apply.
            </p>
          </section>

          {/* Section 6: Refund Request Process */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">6. How to Request Support or Refund Assistance</h2>
            <p>
              To lodge a dispute or request assistance regarding a wallet transaction or NFC card order, please contact us with your account email, registered phone number, transaction ID, and details:
            </p>
            <div className="p-5 rounded-2xl bg-slate-50 border border-slate-200 text-slate-800 space-y-3 font-medium text-sm">
              <p className="font-bold text-slate-900">Tap&amp;Go Refund Support</p>
              <div className="flex flex-wrap gap-3 pt-1">
                <a href="mailto:tapandgosupport@gmail.com" className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-900 text-yellow-400 font-bold text-xs hover:bg-slate-800 transition-colors">
                  <span className="material-symbols-outlined text-sm">mail</span>
                  Email Support (tapandgosupport@gmail.com)
                </a>
                <a href="tel:8779914564" className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-600 text-white font-bold text-xs hover:bg-emerald-700 transition-colors">
                  <span className="material-symbols-outlined text-sm">call</span>
                  General Support (8779914564)
                </a>
                <a href="tel:9321768503" className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-500 text-slate-950 font-bold text-xs hover:bg-amber-400 transition-colors">
                  <span className="material-symbols-outlined text-sm">phone_in_talk</span>
                  Lost Card Helpline (9321768503)
                </a>
              </div>
              <p className="text-xs text-slate-600 pt-1">
                Address: 7/711, Rajni Mahal, Opp. AC Market, Tardeo, Mumbai – 400034, Maharashtra, India
              </p>
            </div>
          </section>
        </div>
      </main>

      <Footer />
    </div>
  )
}

export default RefundPolicy
