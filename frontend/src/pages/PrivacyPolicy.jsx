import React from 'react'
import Navbar from '../components/Common/Navbar.jsx'
import Footer from '../components/Common/Footer.jsx'

export function PrivacyPolicy() {
  return (
    <div className="bg-surface min-h-screen text-slate-900 flex flex-col font-sans antialiased">
      <Navbar />

      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8">
        {/* Header */}
        <section className="relative border-b-2 border-slate-900 pb-10 pt-2 sm:pb-14 space-y-3">
          <div className="tg-kicker">
            <span className="material-symbols-outlined text-sm">shield</span>
            Privacy Policy
          </div>
          <h1 className="max-w-4xl font-display text-[40px] font-extrabold leading-[1.02] tracking-[-0.04em] text-slate-900 sm:text-[60px]">
            Tap&amp;Go Privacy Policy
          </h1>
          <p className="text-slate-500 text-xs sm:text-sm">
            Last Updated: August 2026
          </p>
        </section>

        {/* Content Body */}
        <div className="bg-white rounded-[22px] p-6 sm:p-10 border border-[#dcd4c6] space-y-8 text-slate-700 leading-relaxed text-sm sm:text-base">
          {/* Section 1 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">1. Overview</h2>
            <p>
              Tap&amp;Go (&quot;we&quot;, &quot;our&quot;, or &quot;platform&quot;) values your privacy and is committed to protecting your personal information. This Privacy Policy outlines how personal data is collected, processed, used, stored, and protected when you access or use the Tap&amp;Go platform, passenger dashboard, driver portal, or smart cashless payment services.
            </p>
          </section>

          {/* Section 2 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">2. Information We Collect</h2>
            <p>To provide and operate our smart transportation payment services, Tap&amp;Go may collect the following types of information:</p>
            <ul className="list-disc list-inside space-y-2 pl-2 text-slate-600">
              <li><strong>Account Information:</strong> Name, phone number, email address, password hash, account role (passenger or driver).</li>
              <li><strong>Profile Data:</strong> Profile photo, driver verification documents (driving license, vehicle registration, Aadhaar, PAN) where applicable for driver verification.</li>
              <li><strong>Wallet &amp; Financial Information:</strong> Wallet balances, wallet top-up requests, withdrawal requests, transaction records, and payment status receipts.</li>
              <li><strong>Ride &amp; Payment Data:</strong> Internal passenger-to-driver fare transfers, transaction timestamps, trip payment IDs, and NFC/QR payment interaction logs.</li>
              <li><strong>Technical &amp; Device Information:</strong> IP address, browser type, device identifiers, session cookies, and local storage data required for authentication.</li>
              <li><strong>Security &amp; Fraud Logs:</strong> Risk scores, failed authentication attempts, OTP verification state, and security monitoring logs.</li>
            </ul>
          </section>

          {/* Section 3 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">3. How Information Is Used</h2>
            <p>We use the collected information solely for legitimate operational purposes, including:</p>
            <ul className="list-disc list-inside space-y-2 pl-2 text-slate-600">
              <li>Creating and managing passenger and driver user accounts.</li>
              <li>Authenticating users and securing access to user dashboards.</li>
              <li>Processing wallet top-ups, wallet balance transfers, and withdrawal requests.</li>
              <li>Recording and displaying accurate ride payment transaction histories.</li>
              <li>Executing AI-assisted fraud detection algorithms to identify suspicious activities.</li>
              <li>Delivering email OTP verification codes for account security.</li>
              <li>Responding to user inquiries and providing customer support.</li>
              <li>Improving platform performance, reliability, and user interface features.</li>
            </ul>
          </section>

          {/* Section 4 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">4. Data Security</h2>
            <p>
              We implement reasonable technical and organizational measures to protect personal data against unauthorized access, loss, misuse, or alteration. Password records are hashed securely, and data communications utilize standard secure protocols.
            </p>
          </section>

          {/* Section 5 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">5. Data Sharing &amp; Third Parties</h2>
            <p>
              Tap&amp;Go does not sell, rent, or trade personal data to third-party marketers. Data may be shared only under the following limited circumstances:
            </p>
            <ul className="list-disc list-inside space-y-2 pl-2 text-slate-600">
              <li><strong>Payment Processors:</strong> Facilitating wallet top-up transactions via supported external payment gateways.</li>
              <li><strong>Infrastructure Providers:</strong> Secure hosting, cloud database, and email delivery services (e.g. Vercel, Render, Gmail SMTP).</li>
              <li><strong>Legal Compliance:</strong> When required by applicable law, regulation, or legal process to protect legal rights or prevent fraudulent activities.</li>
            </ul>
          </section>

          {/* Section 6 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">6. Cookies &amp; Local Storage</h2>
            <p>
              Tap&amp;Go uses browser local storage and session storage to maintain active session states, authentication tokens, and user display preferences. These storage mechanisms are essential for session stability and navigation security.
            </p>
          </section>

          {/* Section 7 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">7. Data Retention &amp; User Rights</h2>
            <p>
              Personal data is retained as long as user accounts remain active or as required for transaction record-keeping and platform security. Users have the right to inspect their profile details, request account updates, or seek account deletion by contacting support.
            </p>
          </section>

          {/* Section 8 */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">8. Contact Information</h2>
            <p>
              If you have any questions or concerns regarding this Privacy Policy, please contact our support team at:
            </p>
            <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 text-slate-800 space-y-1 font-medium text-sm">
              <p className="font-bold text-slate-900">Tap&amp;Go Privacy Support</p>
              <p>Email: <a href="mailto:tapandgosupport@gmail.com" className="text-slate-900 font-bold hover:underline">tapandgosupport@gmail.com</a></p>
              <p>General Support: 8779914564</p>
              <p>Address: 7/711, Rajni Mahal, Opp. AC Market, Tardeo, Mumbai – 400034, Maharashtra, India</p>
            </div>
          </section>
        </div>
      </main>

      <Footer />
    </div>
  )
}

export default PrivacyPolicy
