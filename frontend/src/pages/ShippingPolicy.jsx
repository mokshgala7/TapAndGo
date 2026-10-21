import React from 'react'
import Navbar from '../components/Common/Navbar.jsx'
import Footer from '../components/Common/Footer.jsx'

export function ShippingPolicy() {
  return (
    <div className="bg-surface min-h-screen text-slate-900 flex flex-col font-sans antialiased">
      <Navbar />

      <main className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 space-y-8">
        {/* Header */}
        <section className="relative border-b-2 border-slate-900 pb-10 pt-2 sm:pb-14 space-y-3">
          <div className="tg-kicker">
            <span className="material-symbols-outlined text-sm">local_shipping</span>
            Shipping &amp; Delivery Policy
          </div>
          <h1 className="max-w-4xl font-display text-[40px] font-extrabold leading-[1.02] tracking-[-0.04em] text-slate-900 sm:text-[60px]">
            NFC Card Shipping &amp; Delivery Policy
          </h1>
          <p className="text-slate-500 text-xs sm:text-sm">
            Last Updated: August 2026
          </p>
        </section>

        {/* Content Body */}
        <div className="bg-white rounded-[22px] p-6 sm:p-10 border border-[#dcd4c6] space-y-8 text-slate-700 leading-relaxed text-sm sm:text-base">
          {/* Main Platform Statement */}
          <div className="p-5 rounded-2xl bg-blue-50/80 border border-blue-200 text-blue-950 font-medium space-y-2">
            <h2 className="text-lg font-bold text-blue-900">Digital Mobility &amp; Card Delivery Overview</h2>
            <p className="text-sm leading-relaxed">
              Tap&amp;Go is a digital transportation payment platform. As part of our cashless mobility ecosystem, physical Tap&amp;Go NFC smart cards may be issued and shipped to users for travel convenience.
            </p>
          </div>

          {/* Section 1: NFC Card Delivery */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">1. NFC Card Delivery</h2>
            <p>
              Tap&amp;Go may provide physical NFC smart cards to eligible passengers and drivers as part of the Tap&amp;Go cashless payment ecosystem. Because NFC cards are physical items, they require physical shipping and delivery to the destination address supplied by the user during the card request process.
            </p>
          </section>

          {/* Section 2: Delivery Charges */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">2. Delivery Charges</h2>
            <p>
              An applicable shipping and delivery fee may apply for physical NFC card orders. The exact delivery charge will be clearly displayed on the order summary screen prior to user payment confirmation.
            </p>
          </section>

          {/* Section 3: Delivery Address Responsibility */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">3. Delivery Address Responsibility</h2>
            <p>
              Users are responsible for ensuring that a complete, accurate, and accessible shipping address is provided during card ordering. Tap&amp;Go is not responsible for shipment delays, misdelivery, or failed delivery resulting from incomplete, inaccurate, or unreachable address details provided by the user.
            </p>
          </section>

          {/* Section 4: Delivery Timelines */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">4. Delivery Timelines</h2>
            <p>
              Delivery timelines may vary depending on the destination address and applicable courier or logistics service. The applicable delivery status and tracking information will be communicated to the user where required upon dispatch.
            </p>
          </section>

          {/* Section 5: Hardware Concept Distinction */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">5. Hardware &amp; Prototype Distinction</h2>
            <p>
              Please note that while the Tap&amp;Go physical NFC user card may be issued and delivered to users, the ESP32-S3 smart POS terminal is a hardware prototype developed as part of the academic project and is not offered or sold as an e-commerce retail product.
            </p>
          </section>

          {/* Section 6: Delivery Support */}
          <section className="space-y-3">
            <h2 className="text-xl font-bold text-slate-900 border-b border-slate-100 pb-2">6. Card Delivery Support</h2>
            <p>For questions regarding NFC card orders, shipment status, or address updates, please reach out to our team:</p>
            <div className="p-5 rounded-2xl bg-slate-50 border border-slate-200 text-slate-800 space-y-3 font-medium text-sm">
              <p className="font-bold text-slate-900">Tap&amp;Go NFC Card Delivery Support</p>
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
                Project Support Address: 7/711, Rajni Mahal, Opp. AC Market, Tardeo, Mumbai – 400034, Maharashtra, India
              </p>
            </div>
          </section>
        </div>
      </main>

      <Footer />
    </div>
  )
}

export default ShippingPolicy
