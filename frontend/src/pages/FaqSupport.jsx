import React, { useState } from 'react'
import Navbar from '../components/Common/Navbar.jsx'
import Footer from '../components/Common/Footer.jsx'

export function FaqSupport() {
  const [openIdx, setOpenIdx] = useState(null)

  const faqs = [
    {
      q: 'What is Tap&Go?',
      a: 'Tap&Go is a smart cashless payment platform designed for taxis and auto-rickshaws. It enables passengers to pay fares using NFC card taps or QR code scans, while providing drivers with digital wallet balances and real-time transaction records.',
    },
    {
      q: 'Who can use Tap&Go?',
      a: 'Tap&Go is designed for both passengers and drivers in public transportation. Passengers use it for cashless fare payments, while drivers use it to receive payments, track earnings, and manage wallet withdrawals.',
    },
    {
      q: 'How much does the NFC card cost?',
      a: 'Each physical Tap&Go NFC card is priced at ₹50. Applicable shipping and delivery charges are calculated based on your delivery location (Local / Regional / National) and displayed before payment confirmation.',
    },
    {
      q: 'Is delivery included in ₹50?',
      a: 'No. The ₹50 is the physical NFC card price. Applicable delivery charges are calculated separately based on the recipient delivery location.',
    },
    {
      q: 'How is delivery calculated?',
      a: 'Delivery charges depend on the delivery location (Local Mumbai Metro, Regional Maharashtra, or Rest of India) and applicable delivery service. The exact charge is displayed on the order review screen before confirmation.',
    },
    {
      q: 'Where will my NFC card be delivered?',
      a: 'Your NFC card will be delivered via postal/courier service to the destination shipping address provided during the card ordering process.',
    },
    {
      q: 'How long does NFC card delivery take?',
      a: 'Delivery timelines vary depending on the destination address and courier logistics service. Delivery tracking details will be communicated upon dispatch where applicable.',
    },
    {
      q: 'What happens if I enter the wrong address?',
      a: 'Please ensure your delivery address is accurate and complete. Tap&Go is not responsible for shipping delays or failed delivery caused by inaccurate address details, and re-delivery may require additional delivery arrangements.',
    },
    {
      q: 'How do I add money to my wallet?',
      a: 'You can add funds to your Tap&Go digital wallet by clicking "Recharge" or "Add Money" inside your passenger or driver dashboard. Top-ups are processed using supported payment gateways via UPI, debit/credit card, or netbanking.',
    },
    {
      q: 'How do I pay for a ride?',
      a: 'When your ride is complete, tap your Tap&Go NFC card on the driver’s smart POS terminal or scan the driver’s dynamic QR code using your smartphone. The fare is transferred from your passenger wallet to the driver’s wallet.',
    },
    {
      q: 'Do I need physical cash for travel?',
      a: 'No. Tap&Go is built to reduce reliance on physical cash and exact-change friction during taxi and auto-rickshaw rides.',
    },
    {
      q: 'What happens if a wallet funding transaction fails?',
      a: 'If a payment is debited from your bank account but the Tap&Go wallet is not credited, the transaction will be checked against the payment status/callback information and the applicable payment provider’s refund process. You can contact support at tapandgosupport@gmail.com with transaction details.',
    },
    {
      q: 'What happens if I see a suspicious transaction?',
      a: 'Tap&Go incorporates AI-assisted fraud detection monitoring. If a transaction appears unusual, an email OTP verification is triggered. You can also report disputed transactions immediately to our support team.',
    },
    {
      q: 'What should I do if I lose my Tap&Go card?',
      a: 'If you lose your physical Tap&Go card, immediately call our dedicated lost card support helpline at 9321768503 or email tapandgosupport@gmail.com to report the card and protect your account.',
    },
    {
      q: 'How do I contact Tap&Go support?',
      a: 'You can reach us via email at tapandgosupport@gmail.com, call general support at 8779914564, call lost card helpline at 9321768503, or reach Tap&Go Project Support at 7/711, Rajni Mahal, Opp. AC Market, Tardeo, Mumbai – 400034, Maharashtra, India.',
    },
  ]

  const toggle = (idx) => {
    setOpenIdx(openIdx === idx ? null : idx)
  }

  return (
    <div className="bg-surface min-h-screen text-slate-900 flex flex-col font-sans antialiased">
      <Navbar />

      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8">
        {/* Header */}
        <section className="relative border-b-2 border-slate-900 pb-10 pt-2 sm:pb-14">
          <div className="relative z-10 space-y-4 max-w-3xl">
            <div className="tg-kicker">
              <span className="material-symbols-outlined text-sm">help</span>
              Help &amp; Support
            </div>
            <h1 className="max-w-4xl font-display text-[40px] font-extrabold leading-[1.02] tracking-[-0.04em] text-slate-900 sm:text-[60px]">
              Frequently Asked Questions
            </h1>
            <p className="max-w-2xl text-base leading-relaxed text-slate-600 sm:text-lg">
              Find answers to common questions about Tap&amp;Go wallets, payments, NFC travel, card shipping, and support.
            </p>
          </div>
        </section>

        {/* FAQ Accordion List */}
        <section className="space-y-4">
          {faqs.map((faq, idx) => {
            const isOpen = openIdx === idx
            return (
              <div key={idx} className="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm transition-all duration-200">
                <button
                  type="button"
                  onClick={() => toggle(idx)}
                  className="w-full text-left p-5 sm:p-6 flex items-center justify-between gap-4 focus:outline-none"
                >
                  <span className="font-bold text-slate-900 text-base sm:text-lg">{faq.q}</span>
                  <span className="material-symbols-outlined text-slate-900 shrink-0">
                    {isOpen ? 'expand_less' : 'expand_more'}
                  </span>
                </button>
                {isOpen && (
                  <div className="px-5 pb-6 sm:px-6 text-xs sm:text-sm text-slate-600 leading-relaxed border-t border-slate-100 pt-4">
                    {faq.a}
                  </div>
                )}
              </div>
            )
          })}
        </section>

        {/* Support Contact Box */}
        <section className="bg-white rounded-[22px] p-6 sm:p-9 border border-[#dcd4c6] space-y-4">
          <h2 className="font-display text-[26px] sm:text-[30px] font-extrabold text-slate-900 tracking-[-0.03em] flex items-center gap-3">
            <span className="w-10 h-10 rounded-xl bg-yellow-400 text-slate-900 flex items-center justify-center text-[22px]">
              📞
            </span>
            Still Need Help?
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs sm:text-sm text-slate-700">
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-2">
              <span className="font-bold block text-slate-900">Email Support</span>
              <a href="mailto:tapandgosupport@gmail.com" className="inline-flex items-center gap-1.5 text-slate-900 font-bold break-all hover:underline">
                <span className="material-symbols-outlined text-sm">mail</span>
                tapandgosupport@gmail.com
              </a>
            </div>
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-2">
              <span className="font-bold block text-slate-900">General Support</span>
              <a href="tel:8779914564" className="inline-flex items-center gap-1.5 text-emerald-600 font-bold hover:underline">
                <span className="material-symbols-outlined text-sm">call</span>
                8779914564
              </a>
            </div>
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 space-y-2">
              <span className="font-bold block text-slate-900">Lost Card Support</span>
              <a href="tel:9321768503" className="inline-flex items-center gap-1.5 text-amber-600 font-bold hover:underline">
                <span className="material-symbols-outlined text-sm">phone_in_talk</span>
                9321768503
              </a>
            </div>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  )
}

export default FaqSupport
