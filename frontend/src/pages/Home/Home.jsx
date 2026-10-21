import { Link } from '../../routes/navigation.jsx'
import Footer from '../../components/Common/Footer.jsx'
import Navbar from '../../components/Common/Navbar.jsx'
import logo from '../../assets/images/tapgo-logo.png'
import './Home.css'

const features = [
  {
    icon: 'contactless',
    title: 'Instant Cashless Payments',
    description:
      'Complete payments instantly using NFC or QR codes, eliminating the need for cash while ensuring a smooth travel experience.',
  },
  {
    icon: 'security',
    title: 'AI Fraud Detection',
    description:
      'Advanced AI continuously analyzes transactions to detect suspicious activity and help protect both passengers and drivers.',
  },
  {
    icon: 'account_balance_wallet',
    title: 'Digital Wallet',
    description:
      'Securely manage your wallet, view transaction history, track balances, and access digital receipts-all in one place.',
  },
]

const steps = [
  { number: '1', title: 'Register', description: 'Create your passenger or driver account.' },
  { number: '2', title: 'Login', description: 'Securely access your dashboard.' },
  { number: '3', title: 'Scan QR / Tap NFC', description: 'Choose your preferred payment method.' },
  { number: '4', title: 'Pay Securely', description: 'AI verifies every transaction.' },
  { number: '5', title: 'Done!', description: 'Receive instant confirmation and receipt.' },
]

const benefits = [
  { icon: 'shield_lock', title: 'AI Security', description: 'Fraud detection helps protect every transaction.' },
  { icon: 'bolt', title: 'Instant Payments', description: 'Fast QR and NFC transactions in seconds.' },
  { icon: 'account_balance_wallet', title: 'Digital Wallet', description: 'Track balances and payment history easily.' },
  { icon: 'local_taxi', title: 'Built for Mobility', description: 'Designed specifically for taxis and auto-rickshaws.' },
]

/* The three speed lines that trail "Go" in the logo. */
function SpeedLines({ className = '' }) {
  return (
    <svg aria-hidden="true" className={className} viewBox="0 0 64 28" fill="none">
      <rect x="14" y="0" width="50" height="6" rx="3" fill="currentColor" />
      <rect x="4" y="11" width="50" height="6" rx="3" fill="currentColor" />
      <rect x="0" y="22" width="34" height="6" rx="3" fill="currentColor" />
    </svg>
  )
}

function Home() {
  return (
    <div className="tapgo-home tapgo-shell bg-surface text-on-surface font-body-lg antialiased">
      <Navbar />

      <main className="flex min-h-screen flex-col pb-section-gap">
        {/* ── Masthead: the logo, then the promise ───────────── */}
        <section className="mx-auto w-full max-w-7xl px-container-padding pt-8 sm:pt-12">
          <h1 className="sr-only">Smart Payments. Every Ride.</h1>
          <img
            alt="Tap&Go Mobility logo"
            className="tapgo-masthead mx-auto w-full max-w-[880px] object-contain"
            src={logo}
          />

          <div className="tapgo-rule mt-10 sm:mt-14" />

          <div className="grid gap-8 py-10 sm:py-14 lg:grid-cols-12 lg:gap-12">
            <p className="font-display text-[42px] font-extrabold leading-[0.98] tracking-[-0.04em] text-slate-900 sm:text-[64px] lg:col-span-7 lg:text-[76px]">
              <strong className="font-extrabold">
                Fast. Secure. <br className="hidden sm:block" />
                Cashless Travel Payments.
              </strong>
              <SpeedLines className="ml-3 inline-block h-[0.36em] w-auto -translate-y-[0.12em] align-middle text-yellow-400" />
            </p>

            <div className="flex flex-col justify-end lg:col-span-5">
              <p className="text-[17px] leading-[1.65] text-slate-600 sm:text-lg">
                Experience the future of transportation payments with <strong className="text-slate-900">Tap&Go</strong>.
                Our platform enables passengers to pay taxi and auto-rickshaw fares instantly
                using <strong className="text-slate-900">NFC</strong> or <strong className="text-slate-900">QR codes</strong>, while providing drivers
                with secure digital payments, real-time transaction tracking, and AI-powered
                fraud detection.
              </p>

              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Link className="tapgo-button tapgo-button--ghost" to="/login">
                  Log in
                  <span className="material-symbols-outlined text-[20px]" aria-hidden="true">
                    arrow_forward
                  </span>
                </Link>
                <Link className="tapgo-button tapgo-button--yellow" to="/register">
                  Register
                </Link>
              </div>
            </div>
          </div>
        </section>

        {/* ── Features: an editorial list ────────────────────── */}
        <section id="features" className="border-y border-slate-300/70 bg-white">
          <div className="mx-auto grid w-full max-w-7xl gap-10 px-container-padding py-16 sm:py-24 lg:grid-cols-12 lg:gap-12">
            <div className="lg:col-span-5">
              <div className="lg:sticky lg:top-28">
                <h3 className="tapgo-kicker">Features</h3>
                <h2 className="mt-4 font-display text-[34px] font-extrabold leading-[1.04] tracking-[-0.03em] text-slate-900 sm:text-[48px]">
                  Designed for Safe and Seamless Payments
                </h2>
                <p className="mt-5 max-w-md text-[17px] leading-relaxed text-slate-600">
                  Built specifically for taxis and auto-rickshaws, Tap&Go delivers fast
                  transactions, secure authentication, and an effortless payment experience for every
                  ride.
                </p>
              </div>
            </div>

            <ol className="divide-y divide-slate-300/70 border-y border-slate-300/70 lg:col-span-7 lg:border-t-0">
              {features.map((feature) => (
                <li key={feature.title} className="tapgo-feature grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 py-8 sm:py-10">
                  <span className="tapgo-feature-icon row-span-2" aria-hidden="true">
                    <span className="material-symbols-outlined">{feature.icon}</span>
                  </span>
                  <h3 className="font-display text-[24px] font-bold tracking-[-0.02em] text-slate-900 sm:text-[28px]">{feature.title}</h3>
                  <p className="max-w-xl text-[16px] leading-relaxed text-slate-600">{feature.description}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ── How it works: a road with five stops ───────────── */}
        <section id="how" className="mx-auto w-full max-w-7xl px-container-padding py-16 sm:py-24">
          <div className="max-w-2xl">
            <h2 className="font-display text-[34px] font-extrabold leading-[1.04] tracking-[-0.03em] text-slate-900 sm:text-[48px]">How Tap&Go Works</h2>
            <p className="mt-4 text-[17px] text-slate-600">Getting started is simple and takes only a few seconds.</p>
          </div>

          <ol className="tapgo-road mt-12 sm:mt-16">
            {steps.map((step) => (
              <li key={step.title} className="tapgo-stop">
                <span className="tapgo-stop-sign">{step.number}</span>
                <div className="tapgo-stop-text">
                  <h3 className="font-display text-[19px] font-bold tracking-[-0.01em] text-slate-900">{step.title}</h3>
                  <p className="mt-1 text-[15px] leading-relaxed text-slate-600">{step.description}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        {/* ── Why choose: a spec sheet ───────────────────────── */}
        <section id="why" className="mx-auto w-full max-w-7xl px-container-padding pb-16 sm:pb-24">
          <h2 className="font-display text-[34px] font-extrabold leading-[1.04] tracking-[-0.03em] text-slate-900 sm:text-[48px]">Why Choose Tap&Go?</h2>

          <div className="tapgo-spec mt-10 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
            {benefits.map((benefit) => (
              <article key={benefit.title} className="tapgo-spec-cell">
                <span className="material-symbols-outlined text-[30px] text-slate-900" aria-hidden="true">{benefit.icon}</span>
                <h3 className="mt-6 font-display text-[21px] font-bold tracking-[-0.015em] text-slate-900">{benefit.title}</h3>
                <p className="mt-2 text-[15px] leading-relaxed text-slate-600">{benefit.description}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ── Call to action: a taxi-yellow band ─────────────── */}
        <section className="bg-yellow-400">
          <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-container-padding py-14 sm:py-20 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <h3 className="font-display text-[34px] font-extrabold leading-[1.02] tracking-[-0.035em] text-slate-900 sm:text-[52px]">Ready to Experience Smarter Travel?</h3>
              <p className="mt-4 text-[17px] text-[#5e4a10] sm:text-lg">
                Join Tap&amp;Go today and enjoy fast, secure and cashless transportation payments.
              </p>
            </div>
            <div className="flex items-center gap-6">
              <SpeedLines className="hidden h-7 w-auto text-slate-900 sm:block" />
              <Link className="tapgo-button tapgo-button--ink" to="/register">
                Register Now
              </Link>
            </div>
          </div>
        </section>

        {/* Need Help Support CTA Section */}
        <section className="mx-auto w-full max-w-7xl px-container-padding py-12 sm:py-16">
          <div className="flex flex-col justify-between gap-6 border-b border-slate-300/70 pb-12 md:flex-row md:items-end">
            <div className="max-w-2xl space-y-3">
              <h3 className="font-display text-[28px] font-extrabold tracking-[-0.025em] text-slate-900 sm:text-[34px]">Need Help?</h3>
              <p className="text-[16px] leading-relaxed text-slate-600">
                Tap&amp;Go Project Support is available for questions regarding wallets, transactions, account security, and the academic demonstration platform.
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <Link to="/contact" className="tapgo-button tapgo-button--ink">
                Contact Support
              </Link>
              <Link to="/lost-card" className="tapgo-button tapgo-button--alert">
                <span className="material-symbols-outlined text-[20px]" aria-hidden="true">credit_card_off</span>
                Lost Card Support
              </Link>
            </div>
          </div>

          {/* Compliance Footer Banner Disclosure */}
          <p className="mx-auto mt-8 max-w-4xl text-center text-xs leading-relaxed text-slate-500">
            <strong className="text-slate-800">Academic Project Disclosure:</strong> Tap&amp;Go is a student / final-year academic project developed by Moksh Gala,Arham Fofriya and Vansh Gala at SVKM’s Shri Bhagubai Mafatlal Polytechnic. The platform is presented for technological demonstration and evaluation and is not a registered commercial payment institution.
          </p>
        </section>
      </main>

      <Footer />
    </div>
  )
}

export default Home
