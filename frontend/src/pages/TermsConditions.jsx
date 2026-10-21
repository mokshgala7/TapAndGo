import React from 'react'
import Navbar from '../components/Common/Navbar.jsx'
import Footer from '../components/Common/Footer.jsx'

export function TermsConditions() {
  return (
    <div className="bg-surface min-h-screen text-slate-900 flex flex-col font-sans antialiased">
      <Navbar />

      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8">
        {/* Header */}
        <section className="relative border-b-2 border-slate-900 pb-10 pt-2 sm:pb-14 space-y-3">
          <div className="tg-kicker">
            <span className="material-symbols-outlined text-sm">gavel</span>
            Terms &amp; Conditions
          </div>
          <h1 className="max-w-4xl font-display text-[40px] font-extrabold leading-[1.02] tracking-[-0.04em] text-slate-900 sm:text-[60px]">
            Terms of Service &amp; User Agreement
          </h1>
          <p className="text-slate-500 text-xs sm:text-sm">
            Last Updated: August 2026
          </p>
        </section>

        {/* Terms Body */}
        <div className="bg-white rounded-[22px] p-6 sm:p-10 border border-[#dcd4c6] space-y-8 text-slate-700 leading-relaxed text-sm sm:text-base">
          {/* Section 1 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">1. Scope &amp; Nature of Service</h2>
            <p>
              Welcome to Tap&amp;Go. Tap&amp;Go is a smart cashless payment technology platform designed for taxi and auto-rickshaw transport payments.
            </p>
            <div className="p-4 rounded-xl bg-amber-50 border border-amber-200 text-amber-950 text-xs sm:text-sm font-semibold space-y-1">
              <p className="font-bold text-amber-900">Academic Project Notice:</p>
              <p>
                Tap&amp;Go is a student / final-year project developed by Moksh Gala,Arham Fofaria and Vansh Gala, a Diploma student in Computer Science &amp; Engineering at SVKM’s Shri Bhagubai Mafatlal Polytechnic. It is designed for demonstration and technological evaluation purposes and is not a licensed financial institution or RBI-regulated payment aggregator.
              </p>
            </div>
          </section>

          {/* Section 2 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">2. Account Registration</h2>
            <p>
              Users may register for either a <strong>Passenger Account</strong> or a <strong>Driver Account</strong>. By registering, users agree to provide accurate, current, and complete personal information. Users are responsible for safeguarding login credentials and session integrity.
            </p>
          </section>

          {/* Section 3 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">3. Wallet Architecture &amp; Usage</h2>
            <ul className="list-disc list-inside space-y-2 pl-2 text-slate-600">
              <li><strong>Adding Money:</strong> Users may add balance to their Tap&amp;Go digital wallet using supported external payment gateway channels.</li>
              <li><strong>Ride Payments:</strong> Standard ride payments between passengers and drivers are executed as internal wallet-to-wallet transfers. The external payment gateway is not invoked for individual ride payments.</li>
              <li><strong>Driver Withdrawals:</strong> Drivers with verified balances can request wallet funds withdrawal through supported withdrawal mechanisms.</li>
            </ul>
          </section>

          {/* Section 4 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">4. NFC Card Terms &amp; Hardware Distinction</h2>
            <ul className="list-disc list-inside space-y-2 pl-2 text-slate-600">
              <li><strong>NFC User Card:</strong> The physical Tap&amp;Go NFC card is a transit access card issued to users for tap-and-go fare transfers within the platform.</li>
              <li><strong>Delivery &amp; Shipping Charges:</strong> Users ordering an NFC card must supply an accurate shipping address. Applicable delivery fees are disclosed before checkout.</li>
              <li><strong>Lost &amp; Damaged Cards:</strong> Users are responsible for reporting lost or damaged NFC cards immediately to support at 9321768503 or tapandgosupport@gmail.com.</li>
              <li><strong>ESP32-S3 POS Terminal:</strong> The ESP32-S3 POS terminal is a prototype component developed for academic demonstration and is not a consumer e-commerce product.</li>
            </ul>
          </section>

          {/* Section 5 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">5. User Responsibilities &amp; Security</h2>
            <p>
              Users agree not to engage in fraudulent wallet top-ups, unauthorized card usage, transaction manipulation, or suspicious account activities. Tap&amp;Go incorporates automated AI fraud monitoring and OTP verification protocols to safeguard transactions.
            </p>
          </section>

          {/* Section 6 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">6. Disclaimers &amp; Limitation of Liability</h2>
            <p>
              The platform and its services are provided on an &quot;as is&quot; and &quot;as available&quot; basis for evaluation purposes. Tap&amp;Go shall not be liable for indirect, incidental, or consequential damages resulting from platform downtime, network errors, or external hosting service restarts.
            </p>
          </section>

          {/* Section 7 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">7. Support &amp; Contact</h2>
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 space-y-1 font-medium text-sm">
              <p className="font-bold text-slate-900">Tap&amp;Go Support Team</p>
              <p>Email: <a href="mailto:tapandgosupport@gmail.com" className="text-slate-900 font-bold hover:underline">tapandgosupport@gmail.com</a></p>
              <p>General Support: 8779914564 | Lost Card Support: 9321768503</p>
              <p>Project Support Address: 7/711, Rajni Mahal, Opp. AC Market, Tardeo, Mumbai – 400034, Maharashtra, India</p>
            </div>
          </section>
        </div>
      </main>

      <Footer />
    </div>
  )
}

export default TermsConditions
