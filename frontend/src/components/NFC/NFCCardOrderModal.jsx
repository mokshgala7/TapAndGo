import React, { useState, useEffect } from 'react'
import { Link } from '../../routes/navigation.jsx'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'https://api.thetapandgo.in'

// Session token for authenticated API calls (stored by AuthContext at login).
const authHeaders = (extra = {}) => {
  let token = ''
  try { token = sessionStorage.getItem('tapgo_token') || '' } catch { /* storage unavailable */ }
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra
}
const IS_DEMO = import.meta.env.VITE_DEMO_MODE !== 'false'

export function NFCCardOrderModal({ user, onClose, onOrderSuccess }) {
  const [step, setStep] = useState(1) // 1: Address Form, 2: Order Review, 3: Confirmation
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Form State
  const [form, setForm] = useState({
    recipient_name: '',
    phone: '',
    address_line1: '',
    address_line2: '',
    area: '',
    city: '',
    state: 'Maharashtra',
    pincode: '',
  })

  const handleUseExistingDetails = () => {
    if (user) {
      setForm({
        recipient_name: user?.name || '',
        phone: user?.phone || '',
        address_line1: user?.address || '',
        address_line2: '',
        area: user?.area || '',
        city: user?.city || '',
        state: user?.state || 'Maharashtra',
        pincode: user?.pincode || '',
      })
    }
  }

  // Calculation State
  const [calc, setCalc] = useState({
    card_price: 50.0,
    delivery_charge: 0.0,
    total_amount: 50.0,
    delivery_tier: '',
    tier_name: '',
    calculated: false,
  })

  // Created Order Details (Step 3)
  const [createdOrder, setCreatedOrder] = useState(null)

  // Auto-calculate delivery when city/state/pincode are complete
  const handleCalculateDelivery = async () => {
    if (!form.pincode || form.pincode.trim().length !== 6 || !/^\d{6}$/.test(form.pincode.trim())) {
      return
    }
    if (!form.city.trim() || !form.state.trim()) {
      return
    }

    try {
      const res = await fetch(`${API_BASE}/api/card-order/calculate-delivery`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          city: form.city.trim(),
          state: form.state.trim(),
          pincode: form.pincode.trim(),
        }),
      })

      const data = await res.json()
      if (res.ok && data.success) {
        setCalc({
          card_price: data.card_price,
          delivery_charge: data.delivery_charge,
          total_amount: data.total_amount,
          delivery_tier: data.delivery_tier,
          tier_name: data.tier_name,
          calculated: true,
        })
        setError('')
      }
    } catch {
      // Quiet fail on auto-calculate
    }
  }

  useEffect(() => {
    if (form.pincode.length === 6 && form.city && form.state) {
      handleCalculateDelivery()
    }
  }, [form.pincode, form.city, form.state])

  const handleProceedToReview = async (e) => {
    e.preventDefault()
    setError('')

    // Client Validations
    if (!form.recipient_name.trim()) {
      setError('Please enter the recipient full name.')
      return
    }
    const cleanPhone = form.phone.trim().replace(/\s+/g, '').replace(/-/g, '')
    if (!cleanPhone || cleanPhone.length < 10 || !/^\d+$/.test(cleanPhone)) {
      setError('Please enter a valid 10-digit mobile number.')
      return
    }
    if (!form.address_line1.trim()) {
      setError('Please enter Address Line 1.')
      return
    }
    if (!form.area.trim()) {
      setError('Please enter Area / Locality.')
      return
    }
    if (!form.city.trim()) {
      setError('Please enter City.')
      return
    }
    if (!form.state.trim()) {
      setError('Please enter State.')
      return
    }
    const cleanPin = form.pincode.trim()
    if (!cleanPin || cleanPin.length !== 6 || !/^\d{6}$/.test(cleanPin)) {
      setError('Please enter a valid 6-digit Indian PIN code.')
      return
    }

    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/card-order/calculate-delivery`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          city: form.city.trim(),
          state: form.state.trim(),
          pincode: cleanPin,
        }),
      })

      const data = await res.json()
      if (!res.ok || !data.success) {
        throw new Error(data.detail || 'Could not calculate delivery charges.')
      }

      setCalc({
        card_price: data.card_price,
        delivery_charge: data.delivery_charge,
        total_amount: data.total_amount,
        delivery_tier: data.delivery_tier,
        tier_name: data.tier_name,
        calculated: true,
      })

      setStep(2) // Move to review step
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmOrder = async () => {
    setError('')
    setLoading(true)

    try {
      const res = await fetch(`${API_BASE}/api/card-order/create`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          user_id: user.id,
          recipient_name: form.recipient_name.trim(),
          phone: form.phone.trim(),
          address_line1: form.address_line1.trim(),
          address_line2: form.address_line2.trim() || null,
          area: form.area.trim(),
          city: form.city.trim(),
          state: form.state.trim(),
          pincode: form.pincode.trim(),
        }),
      })

      const data = await res.json()

      if (!res.ok && !data.order) {
        throw new Error(data.detail || data.message || 'Order creation failed.')
      }

      if (data.is_demo || data.success) {
        setCreatedOrder(data.order)
        setStep(3)
        onOrderSuccess?.(data.order)
      } else {
        // Production Mode: Gateway not configured
        setError(data.message || 'NFC card payment is currently unavailable because the payment gateway is not configured.')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={() => !loading && step !== 3 && onClose()}>
      <div
        className="modal-card"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 540, width: '100%', maxHeight: '90vh', overflowY: 'auto' }}
      >
        {/* Step Indicator Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div>
            <span style={{ fontSize: 11, fontWeight: 800, color: 'var(--amber, #8a6400)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Tap&amp;Go NFC Hardware Card
            </span>
            <h3 style={{ margin: '2px 0 0', fontSize: 20, fontWeight: 900 }}>
              {step === 1 && 'Get Your Tap&Go NFC Card'}
              {step === 2 && 'Review Your Order'}
              {step === 3 && 'NFC Card Order Created'}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              border: 0,
              background: 'var(--bg, #fbf9f5)',
              color: 'var(--text, #1e1b16)',
              borderRadius: '50%',
              width: 32,
              height: 32,
              display: 'grid',
              placeItems: 'center',
              cursor: 'pointer',
              fontWeight: 800,
            }}
          >
            ✕
          </button>
        </div>

        {error && (
          <div style={{ background: '#fce8e5', border: '1px solid #f1a79d', color: '#a52b23', padding: '10px 14px', borderRadius: 10, marginBottom: 16, fontSize: 13, fontWeight: 700 }}>
            ⚠️ {error}
          </div>
        )}

        {/* STEP 1: Address Collection Form */}
        {step === 1 && (
          <form onSubmit={handleProceedToReview}>
            {/* Card Product Info Box */}
            <div style={{ background: '#fdd34d', color: '#1e1b16', padding: '16px 18px', borderRadius: 14, marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <b style={{ fontSize: 16, display: 'block', color: '#1e1b16' }}>Physical NFC Smart Card</b>
                <span style={{ fontSize: 12, opacity: 0.9 }}>Cashless transit card linked to your Tap&amp;Go account</span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <strong style={{ fontSize: 24, color: '#1e1b16', fontFamily: 'var(--tg-font-display)', letterSpacing: '-0.03em' }}>₹50</strong>
                <small style={{ display: 'block', fontSize: 10, opacity: 0.8 }}>+ delivery charge</small>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h4 style={{ margin: 0, fontSize: 14, fontWeight: 800, color: 'var(--text)' }}>
                Shipping &amp; Delivery Address
              </h4>
              {user && (
                <button
                  type="button"
                  style={{ fontSize: 11, fontWeight: 700, padding: '4px 8px', borderRadius: 6, background: 'var(--bg, #fbf9f5)', border: '1px solid var(--line, #eae4da)', cursor: 'pointer', color: 'var(--text)' }}
                  onClick={handleUseExistingDetails}
                >
                  Use existing details
                </button>
              )}
            </div>

            <div style={{ display: 'grid', gap: 12 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label htmlFor="nfc-recipient-name" style={{ fontSize: 12, fontWeight: 700, display: 'block', marginBottom: 4 }}>Full Name *</label>
                  <input
                    id="nfc-recipient-name"
                    type="text"
                    required
                    placeholder="Recipient Name"
                    value={form.recipient_name}
                    onChange={(e) => setForm({ ...form, recipient_name: e.target.value })}
                    style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--line)', fontSize: 14 }}
                  />
                </div>
                <div>
                  <label htmlFor="nfc-phone" style={{ fontSize: 12, fontWeight: 700, display: 'block', marginBottom: 4 }}>Mobile Number *</label>
                  <input
                    id="nfc-phone"
                    type="tel"
                    required
                    placeholder="10-digit mobile"
                    value={form.phone}
                    onChange={(e) => setForm({ ...form, phone: e.target.value })}
                    style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--line)', fontSize: 14 }}
                  />
                </div>
              </div>

              <div>
                <label htmlFor="nfc-addr1" style={{ fontSize: 12, fontWeight: 700, display: 'block', marginBottom: 4 }}>Address Line 1 *</label>
                <input
                  id="nfc-addr1"
                  type="text"
                  required
                  placeholder="House / Flat No., Building, Street"
                  value={form.address_line1}
                  onChange={(e) => setForm({ ...form, address_line1: e.target.value })}
                  style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--line)', fontSize: 14 }}
                />
              </div>

              <div>
                <label htmlFor="nfc-addr2" style={{ fontSize: 12, fontWeight: 700, display: 'block', marginBottom: 4 }}>Address Line 2 (Optional)</label>
                <input
                  id="nfc-addr2"
                  type="text"
                  placeholder="Landmark, Apartment, Colony"
                  value={form.address_line2}
                  onChange={(e) => setForm({ ...form, address_line2: e.target.value })}
                  style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--line)', fontSize: 14 }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                <div>
                  <label htmlFor="nfc-area" style={{ fontSize: 12, fontWeight: 700, display: 'block', marginBottom: 4 }}>Area / Locality *</label>
                  <input
                    id="nfc-area"
                    type="text"
                    required
                    placeholder="e.g. Tardeo"
                    value={form.area}
                    onChange={(e) => setForm({ ...form, area: e.target.value })}
                    style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--line)', fontSize: 13 }}
                  />
                </div>
                <div>
                  <label htmlFor="nfc-city" style={{ fontSize: 12, fontWeight: 700, display: 'block', marginBottom: 4 }}>City *</label>
                  <input
                    id="nfc-city"
                    type="text"
                    required
                    placeholder="e.g. Mumbai"
                    value={form.city}
                    onChange={(e) => setForm({ ...form, city: e.target.value })}
                    style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--line)', fontSize: 13 }}
                  />
                </div>
                <div>
                  <label htmlFor="nfc-pincode" style={{ fontSize: 12, fontWeight: 700, display: 'block', marginBottom: 4 }}>PIN Code *</label>
                  <input
                    id="nfc-pincode"
                    type="text"
                    required
                    maxLength={6}
                    placeholder="6-digit PIN"
                    value={form.pincode}
                    onChange={(e) => setForm({ ...form, pincode: e.target.value })}
                    style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--line)', fontSize: 13 }}
                  />
                </div>
              </div>

              <div>
                <label htmlFor="nfc-state" style={{ fontSize: 12, fontWeight: 700, display: 'block', marginBottom: 4 }}>State *</label>
                <input
                  id="nfc-state"
                  type="text"
                  required
                  placeholder="e.g. Maharashtra"
                  value={form.state}
                  onChange={(e) => setForm({ ...form, state: e.target.value })}
                  style={{ width: '100%', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--line)', fontSize: 14 }}
                />
              </div>
            </div>

            <div className="modal-actions" style={{ marginTop: 20, display: 'flex', gap: 10 }}>
              <button
                type="button"
                className="secondary-btn"
                onClick={onClose}
                disabled={loading}
                style={{ flex: 1, padding: '12px', borderRadius: 10 }}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="primary"
                disabled={loading}
                style={{ flex: 1, padding: '12px', borderRadius: 10, fontWeight: 800 }}
              >
                {loading ? 'Calculating Delivery...' : 'Continue to Review →'}
              </button>
            </div>
          </form>
        )}

        {/* STEP 2: Checkout Review & Breakdown */}
        {step === 2 && (
          <div>
            {/* DEMO MODE Alert Badge */}
            {IS_DEMO && (
              <div style={{ background: '#FFF3C4', border: '1px solid #FFE082', borderRadius: 12, padding: '12px 14px', marginBottom: 16, fontSize: 12, color: '#6b4d05', fontWeight: 600, leadingHeight: 1.4 }}>
                <strong>DEMO MODE:</strong> This NFC card order is simulated for academic demonstration. No real payment will be processed and no physical card will be dispatched from this demonstration environment.
              </div>
            )}

            {/* Price Breakdown Card */}
            <div style={{ background: 'var(--card, #fff)', border: '1px solid var(--line, #eae4da)', borderRadius: 14, padding: 18, marginBottom: 16 }}>
              <h4 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 800, color: 'var(--text)' }}>
                Order Pricing Breakdown
              </h4>

              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--line)', fontSize: 14 }}>
                <span>Tap&amp;Go Physical NFC Card</span>
                <strong>₹{calc.card_price.toFixed(2)}</strong>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--line)', fontSize: 14 }}>
                <div>
                  <span>Delivery Charge</span>
                  <small style={{ display: 'block', color: 'var(--muted)', fontSize: 11 }}>{calc.tier_name || 'Location-Based Shipping'}</small>
                </div>
                <strong>₹{calc.delivery_charge.toFixed(2)}</strong>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', padding: '12px 0 4px', fontSize: 18, fontWeight: 900, color: 'var(--text)' }}>
                <span>Total Amount</span>
                <span style={{ color: '#177a47' }}>₹{calc.total_amount.toFixed(2)}</span>
              </div>
            </div>

            {/* Delivery Address Summary */}
            <div style={{ background: 'var(--bg, #fbf9f5)', border: '1px solid var(--line, #ddd5c8)', borderRadius: 14, padding: 16, marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <strong style={{ fontSize: 13, color: 'var(--text)' }}>Shipping Address</strong>
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  style={{ border: 0, background: 'transparent', color: '#8a6400', fontWeight: 700, fontSize: 12, cursor: 'pointer' }}
                >
                  Edit Address
                </button>
              </div>
              <p style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{form.recipient_name} ({form.phone})</p>
              <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--muted)', lineHeight: 1.4 }}>
                {form.address_line1}{form.address_line2 ? `, ${form.address_line2}` : ''}, {form.area}, {form.city}, {form.state} – {form.pincode}
              </p>
            </div>

            {/* Mandatory Compliance Policy Links */}
            <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 20, textAlign: 'center', lineHeight: 1.6 }}>
              By confirming, you agree to Tap&amp;Go&apos;s{' '}
              <Link to="/terms" style={{ color: '#8a6400', fontWeight: 700 }}>Terms &amp; Conditions</Link>,{' '}
              <Link to="/shipping-policy" style={{ color: '#8a6400', fontWeight: 700 }}>Shipping &amp; Delivery Policy</Link>,{' '}
              <Link to="/refund-policy" style={{ color: '#8a6400', fontWeight: 700 }}>Refund &amp; Cancellation Policy</Link>, and{' '}
              <Link to="/privacy" style={{ color: '#8a6400', fontWeight: 700 }}>Privacy Policy</Link>.
            </div>

            <div className="modal-actions" style={{ display: 'flex', gap: 10 }}>
              <button
                type="button"
                className="secondary-btn"
                onClick={() => setStep(1)}
                disabled={loading}
                style={{ flex: 1, padding: '12px', borderRadius: 10 }}
              >
                ← Back
              </button>
              <button
                type="button"
                className="primary"
                onClick={handleConfirmOrder}
                disabled={loading}
                style={{ flex: 1, padding: '12px', borderRadius: 10, fontWeight: 800 }}
              >
                {loading ? 'Processing Order...' : IS_DEMO ? 'Place Demo Order' : 'Continue to Payment'}
              </button>
            </div>
          </div>
        )}

        {/* STEP 3: Order Confirmation Screen */}
        {step === 3 && createdOrder && (
          <div>
            <div style={{ textAlign: 'center', padding: '16px 0' }}>
              <div style={{ width: 56, height: 56, borderRadius: '50%', background: '#e2f3e8', color: '#177a47', display: 'grid', placeItems: 'center', margin: '0 auto 12px', fontSize: 28, fontWeight: 900 }}>
                ✓
              </div>
              <h3 style={{ margin: '0 0 6px', fontSize: 22, fontWeight: 900, color: 'var(--text)' }}>
                Demo Order Created
              </h3>
              <p style={{ margin: 0, fontSize: 13, color: 'var(--muted)' }}>
                Order Ref: <strong style={{ color: 'var(--text)' }}>{createdOrder.order_reference}</strong>
              </p>
            </div>

            {/* Academic Disclosure */}
            <div style={{ background: '#fffbeb', border: '1px solid #ffe89a', color: '#8a6400', padding: '12px 14px', borderRadius: 12, marginBottom: 16, fontSize: 12, fontWeight: 600, lineHeight: 1.4 }}>
              <strong>Academic Demonstration Notice:</strong> This is an academic demonstration order. No real payment has been processed and no physical shipment will be initiated from Demo Mode.
            </div>

            {/* Summary Details */}
            <div style={{ background: 'var(--bg, #fbf9f5)', border: '1px solid var(--line, #eae4da)', borderRadius: 14, padding: 16, marginBottom: 20, fontSize: 13 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span className="muted">NFC Card Price:</span>
                <strong>₹{createdOrder.card_price.toFixed(2)}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span className="muted">Delivery Fee ({createdOrder.delivery_tier.toUpperCase()}):</span>
                <strong>₹{createdOrder.delivery_charge.toFixed(2)}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span className="muted">Payment Status:</span>
                <span style={{ fontWeight: 800, color: '#8a6400', background: '#fff2c5', padding: '2px 8px', borderRadius: 99, fontSize: 11, textTransform: 'uppercase' }}>
                  Simulated
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', paddingBefore: 6, borderTop: '1px dashed var(--line)', paddingTop: 6, fontSize: 15 }}>
                <span>Total Amount:</span>
                <strong style={{ color: '#177a47' }}>₹{createdOrder.total_amount.toFixed(2)}</strong>
              </div>
              <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--line)' }}>
                <span className="muted" style={{ display: 'block', fontSize: 11, textTransform: 'uppercase', fontWeight: 800 }}>Delivery Recipient &amp; Address</span>
                <strong style={{ display: 'block', marginTop: 2 }}>{createdOrder.recipient_name} ({createdOrder.phone})</strong>
                <p style={{ margin: '2px 0 0', color: 'var(--muted)', fontSize: 12 }}>
                  {createdOrder.address_line1}{createdOrder.address_line2 ? `, ${createdOrder.address_line2}` : ''}, {createdOrder.area}, {createdOrder.city}, {createdOrder.state} – {createdOrder.pincode}
                </p>
              </div>
            </div>

            <div className="modal-actions">
              <button
                type="button"
                className="primary"
                onClick={onClose}
                style={{ width: '100%', padding: '14px', borderRadius: 10, fontWeight: 800 }}
              >
                Done
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default NFCCardOrderModal
