import { useState, useMemo } from 'react'
import { useAuth, hasValidBankDetails } from '../../context/AuthContext.jsx'
import { useDriverData } from '../../context/DriverContext.jsx'
import { formatRelativeTime } from '../Passenger/format.js'
import { inr, tripStatusLabel } from './format.js'
import Pager from '../../components/Common/Pager.jsx'
import { usePaged } from '../../utils/usePaged.js'

const Icon = ({ children, className = '' }) => (
  <span className={`material-symbols-outlined ${className}`} aria-hidden="true">
    {children}
  </span>
)

function KpiModal({ title, subtitle, onClose, children }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" style={{ maxWidth: 540 }} onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div>
            <h3 style={{ margin: 0 }}>{title}</h3>
            {subtitle && <p className="muted" style={{ margin: '4px 0 0', fontSize: 13 }}>{subtitle}</p>}
          </div>
          <button
            onClick={onClose}
            style={{
              border: 0,
              background: 'var(--bg)',
              color: 'var(--text)',
              borderRadius: '50%',
              width: 32,
              height: 32,
              display: 'grid',
              placeItems: 'center',
              cursor: 'pointer',
            }}
          >
            <Icon style={{ fontSize: 18 }}>close</Icon>
          </button>
        </div>
        <div style={{ maxHeight: '60vh', overflowY: 'auto', padding: '2px 4px 8px', margin: '0 -4px' }}>
          {children}
        </div>
        <div className="modal-actions" style={{ marginTop: 20 }}>
          <button className="primary" style={{ width: '100%' }} onClick={onClose}>
            Close History
          </button>
        </div>
      </div>
    </div>
  )
}

function DriverDashboard({ flash, openModal, goToEarnings }) {
  const { user } = useAuth()
  const { trips, transactions, completedTrips, reviews, rating, earnings, walletBalance } = useDriverData()
  const [kpiModal, setKpiModal] = useState(null)
  const txPages = usePaged(transactions)

  const now = Date.now()
  const todayTrips = useMemo(() => completedTrips.filter((t) => now - t.timestamp <= 86400000), [completedTrips, now])
  const weekTrips = useMemo(() => completedTrips.filter((t) => now - t.timestamp <= 7 * 86400000), [completedTrips, now])
  const monthTrips = useMemo(() => completedTrips.filter((t) => now - t.timestamp <= 30 * 86400000), [completedTrips, now])

  const recentTrips = useMemo(() => trips.slice(0, 4), [trips])

  const recentActivity = useMemo(() => {
    const tripEvents = completedTrips.map((t) => ({
      id: t.id,
      title: t.passenger,
      subtitle: t.route,
      amount: t.fare,
      credit: true,
      timestamp: t.timestamp,
    }))
    return tripEvents.sort((a, b) => b.timestamp - a.timestamp).slice(0, 4)
  }, [completedTrips])

  const firstName = (user?.name || 'Driver').split(' ')[0]
  const today = new Date().toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' })
  const registeredDate = user?.created_at
    ? new Date(user.created_at).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
    : 'Jul 2026'

  return (
    <>
      <div className="section-head">
        <div>
          <p className="eyebrow">Welcome back</p>
          <h1>Hello, {firstName}</h1>
          <p className="muted">Here&apos;s what&apos;s happening with your trips today.</p>
        </div>
        <span className="muted" style={{ fontWeight: 700 }}>
          {today}
        </span>
      </div>

      <div className="kpi-grid">
        {/* Today's Earnings */}
        <div
          className="kpi-card"
          onClick={() => setKpiModal('today')}
          style={{ cursor: 'pointer', transition: 'transform 0.15s ease' }}
          title="Click to view Today's Earnings history"
        >
          <div className="kpi-top">
            <span className="kpi-label">Today&apos;s Earnings</span>
            <span className="kpi-icon">
              <Icon>trending_up</Icon>
            </span>
          </div>
          <span className="kpi-value">{inr(earnings.today)}</span>
          <span className="kpi-sub" style={{ color: 'var(--accent)', fontWeight: 700 }}>
            {todayTrips.length} trips today &rarr;
          </span>
        </div>

        {/* Weekly Earnings */}
        <div
          className="kpi-card"
          onClick={() => setKpiModal('weekly')}
          style={{ cursor: 'pointer' }}
          title="Click to view Weekly Earnings history"
        >
          <div className="kpi-top">
            <span className="kpi-label">Weekly Earnings</span>
            <span className="kpi-icon">
              <Icon>calendar_view_week</Icon>
            </span>
          </div>
          <span className="kpi-value">{inr(earnings.week)}</span>
          <span className="kpi-sub" style={{ color: 'var(--accent)', fontWeight: 700 }}>
            Last 7 days ({weekTrips.length} trips) &rarr;
          </span>
        </div>

        {/* Monthly Earnings */}
        <div
          className="kpi-card"
          onClick={() => setKpiModal('monthly')}
          style={{ cursor: 'pointer' }}
          title="Click to view Monthly Earnings history"
        >
          <div className="kpi-top">
            <span className="kpi-label">Monthly Earnings</span>
            <span className="kpi-icon">
              <Icon>calendar_month</Icon>
            </span>
          </div>
          <span className="kpi-value">{inr(earnings.month)}</span>
          <span className="kpi-sub" style={{ color: 'var(--accent)', fontWeight: 700 }}>
            Last 30 days ({monthTrips.length} trips) &rarr;
          </span>
        </div>

        {/* Lifetime Earnings */}
        <div
          className="kpi-card"
          onClick={() => setKpiModal('lifetime')}
          style={{ cursor: 'pointer' }}
          title="Click to view Lifetime Earnings summary"
        >
          <div className="kpi-top">
            <span className="kpi-label">Lifetime Earnings</span>
            <span className="kpi-icon">
              <Icon>military_tech</Icon>
            </span>
          </div>
          <span className="kpi-value">{inr(earnings.lifetime)}</span>
          <span className="kpi-sub">Since {registeredDate} &rarr;</span>
        </div>

        {/* Wallet Balance */}
        <div className="kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">Wallet Balance</span>
            <span className="kpi-icon">
              <Icon>account_balance_wallet</Icon>
            </span>
          </div>
          <span className="kpi-value">{inr(walletBalance)}</span>
          <button className="primary kpi-action" onClick={() => openModal('withdraw')}>
            Withdraw
          </button>
        </div>

        {/* Total Trips */}
        <div
          className="kpi-card"
          onClick={() => setKpiModal('trips')}
          style={{ cursor: 'pointer' }}
          title="Click to view completed trips history"
        >
          <div className="kpi-top">
            <span className="kpi-label">Total Trips</span>
            <span className="kpi-icon">
              <Icon>directions_car</Icon>
            </span>
          </div>
          <span className="kpi-value">{completedTrips.length}</span>
          <span className="kpi-sub" style={{ fontWeight: 600 }}>
            {completedTrips.length} completed trips &middot; Instant payment
          </span>
        </div>

        {/* Passenger Rating */}
        <div
          className="kpi-card"
          onClick={() => setKpiModal('ratings')}
          style={{ cursor: 'pointer' }}
          title="Click to view passenger ratings and reviews"
        >
          <div className="kpi-top">
            <span className="kpi-label">Passenger Rating</span>
            <span className="kpi-icon">
              <Icon>star</Icon>
            </span>
          </div>
          <span className="kpi-value">{rating || '4.8'}</span>
          <span className="kpi-sub" style={{ color: 'var(--accent)', fontWeight: 700 }}>
            {reviews.length} passenger reviews &rarr;
          </span>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 12 }}>
        <button className="primary" onClick={() => openModal('withdraw')}>
          Withdraw Balance
        </button>
        {!hasValidBankDetails(user) && (
          <button
            className="secondary-btn"
            style={{ color: 'var(--text)', background: 'var(--card)', border: '1px solid var(--line)' }}
            onClick={() => openModal('bank')}
          >
            Add Bank Details
          </button>
        )}
        <button
          className="secondary-btn"
          style={{ color: 'var(--text)', background: 'var(--card)', border: '1px solid var(--line)' }}
          onClick={() => {
            goToEarnings()
            flash('Showing your statements in Earnings.')
          }}
        >
          View Statements
        </button>
      </div>

      {!hasValidBankDetails(user) && (
        <div
          className="bank-alert-card"
          style={{
            background: 'var(--card)',
            border: '1px solid var(--line)',
            borderLeft: '6px solid var(--yellow)',
            borderRadius: 16,
            padding: '16px 20px',
            marginTop: 16,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 14,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 18 }}>🏦</span>
              <span style={{ fontSize: 11, fontWeight: 800, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: '0.12em' }}>Payout Account Setup</span>
            </div>
            <h3 style={{ margin: '2px 0 4px', fontSize: 16, fontWeight: 800, color: 'var(--text, #1e1b16)' }}>Add Your Bank Details</h3>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--muted, #6b6458)' }}>
              Link your bank account and UPI ID to withdraw your fare earnings.
            </p>
          </div>
          <button
            type="button"
            className="primary"
            onClick={() => openModal('bank')}
            style={{
              background: '#FDD34D',
              color: '#1e1b16',
              fontWeight: 800,
              fontSize: 13,
              padding: '12px 22px',
              borderRadius: 12,
              border: 'none',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            <span>Add Bank Details</span>
            <span>&rarr;</span>
          </button>
        </div>
      )}

      <div className="section-head" style={{ marginTop: 34 }}>
        <h2 style={{ margin: 0 }}>Transaction History</h2>
      </div>
      <div id={txPages.anchorId} className="paged-anchor" />
      {transactions.length === 0 ? (
        <p className="driver-empty">No transactions yet.</p>
      ) : (
        txPages.pageItems.map((t) => (
          <article className="ride" key={t.id || t.reference} style={{ flexDirection: 'column', alignItems: 'stretch', gap: 6, padding: '14px 16px', marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <b style={{ fontSize: 15, color: 'var(--text)' }}>{t.type}</b>
                <span style={{ fontSize: 11, fontWeight: 700, marginLeft: 8, padding: '2px 8px', borderRadius: 99, background: t.is_credit ? '#e2f3e8' : '#fce8e5', color: t.is_credit ? '#177a47' : '#a52b23' }}>
                  {t.is_credit ? 'CREDIT' : 'DEBIT'}
                </span>
              </div>
              <strong className={t.is_credit ? 'credit' : ''} style={{ fontSize: 16, color: t.is_credit ? '#177a47' : 'var(--text)' }}>
                {t.is_credit ? '+' : '-'}₹{t.amount.toFixed(2)}
              </strong>
            </div>

            <div style={{ fontSize: 13, color: 'var(--muted)', fontWeight: 600 }}>
              {t.description}
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 4, pt: 6, borderTop: '1px dashed var(--line)', fontSize: 12 }}>
              <span style={{ fontWeight: 700, color: 'var(--text)' }}>
                Available balance: ₹{t.balance_after !== undefined ? Number(t.balance_after).toFixed(2) : walletBalance.toFixed(2)}
              </span>
              <span className="muted" style={{ fontSize: 11 }}>
                {t.reference} &middot; {t.payment_method} &middot; {t.created_at ? new Date(t.created_at).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''}
              </span>
            </div>
          </article>
        ))
      )}
      <Pager paged={txPages} />

      <h2>What Passengers Say</h2>
      {reviews.length === 0 && <p className="driver-empty">No reviews yet.</p>}
      {reviews.slice(0, 3).map((review) => (
        <div className="review-card" key={review.id}>
          <div className="review-top">
            <b>{review.passenger}</b>
            <span className="review-stars">{'★'.repeat(review.rating)}{'☆'.repeat(5 - review.rating)}</span>
          </div>
          <p>{review.comment}</p>
        </div>
      ))}

      {/* KPI MODALS */}
      {kpiModal === 'today' && (
        <KpiModal title="Today's Earnings History" subtitle={`Total Earned Today: ${inr(earnings.today)} (${todayTrips.length} ${todayTrips.length === 1 ? 'trip' : 'trips'})`} onClose={() => setKpiModal(null)}>
          {todayTrips.length === 0 ? (
            <p className="driver-empty">No trips completed today yet.</p>
          ) : (
            todayTrips.map((t) => (
              <article className="ride" key={t.id}>
                <div>
                  <b>{t.passenger}</b>
                  <small>{t.route}</small>
                  <small>{new Date(t.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}</small>
                </div>
                <strong className="credit">{inr(t.fare)}</strong>
              </article>
            ))
          )}
        </KpiModal>
      )}

      {kpiModal === 'weekly' && (
        <KpiModal title="Weekly Earnings Breakdown" subtitle={`Last 7 Days Earnings: ${inr(earnings.week)}`} onClose={() => setKpiModal(null)}>
          <div style={{ background: 'var(--bg)', padding: 14, borderRadius: 12, marginBottom: 14 }}>
            <b>Daily Earnings Overview</b>
            <p className="muted" style={{ margin: '4px 0 0', fontSize: 13 }}>Average per day: {inr(Math.round(earnings.week / 7))}</p>
          </div>
          {weekTrips.map((t) => (
            <article className="ride" key={t.id}>
              <div>
                <b>{t.passenger}</b>
                <small>{t.route}</small>
                <small>{formatRelativeTime(t.timestamp)}</small>
              </div>
              <strong className="credit">{inr(t.fare)}</strong>
            </article>
          ))}
        </KpiModal>
      )}

      {kpiModal === 'monthly' && (
        <KpiModal title="Monthly Earnings Breakdown" subtitle={`Last 30 Days Earnings: ${inr(earnings.month)}`} onClose={() => setKpiModal(null)}>
          <div style={{ background: 'var(--bg)', padding: 14, borderRadius: 12, marginBottom: 14 }}>
            <b>Monthly Performance</b>
            <p className="muted" style={{ margin: '4px 0 0', fontSize: 13 }}>Total Completed Trips: {monthTrips.length}</p>
          </div>
          {monthTrips.map((t) => (
            <article className="ride" key={t.id}>
              <div>
                <b>{t.passenger}</b>
                <small>{t.route}</small>
                <small>{formatRelativeTime(t.timestamp)}</small>
              </div>
              <strong className="credit">{inr(t.fare)}</strong>
            </article>
          ))}
        </KpiModal>
      )}

      {kpiModal === 'lifetime' && (
        <KpiModal title="Lifetime Earnings Summary" subtitle={`Total Earnings Since ${registeredDate}`} onClose={() => setKpiModal(null)}>
          <div style={{ background: 'var(--bg)', padding: 16, borderRadius: 12, marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <span>Total Earned:</span>
              <b style={{ color: 'var(--accent)', fontSize: 18 }}>{inr(earnings.lifetime)}</b>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <span>Completed Trips:</span>
              <b>{completedTrips.length}</b>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Current Wallet Balance:</span>
              <b>{inr(walletBalance)}</b>
            </div>
          </div>
        </KpiModal>
      )}

      {kpiModal === 'trips' && (
        <KpiModal title="Completed Trips History" subtitle={`Total Completed: ${completedTrips.length} trips`} onClose={() => setKpiModal(null)}>
          {completedTrips.map((t) => (
            <article className="ride" key={t.id}>
              <div>
                <b>{t.passenger}</b>
                <small>{t.route}</small>
                <small>{formatRelativeTime(t.timestamp)}</small>
              </div>
              <div style={{ textAlign: 'right' }}>
                <strong className="credit">{inr(t.fare)}</strong>
                <small className="muted" style={{ display: 'block' }}>Paid Cashless</small>
              </div>
            </article>
          ))}
        </KpiModal>
      )}

      {kpiModal === 'ratings' && (
        <KpiModal title="Passenger Reviews & Ratings" subtitle={`Overall Rating: ★ ${rating || '4.8'} (${reviews.length} reviews)`} onClose={() => setKpiModal(null)}>
          {reviews.length === 0 ? (
            <p className="driver-empty">No reviews submitted yet.</p>
          ) : (
            reviews.map((review) => (
              <div className="review-card" key={review.id} style={{ marginBottom: 12 }}>
                <div className="review-top">
                  <b>{review.passenger}</b>
                  <span className="review-stars">{'★'.repeat(review.rating)}{'☆'.repeat(5 - review.rating)}</span>
                </div>
                <p style={{ margin: '6px 0 0', fontSize: 14 }}>{review.comment}</p>
              </div>
            ))
          )}
        </KpiModal>
      )}
    </>
  )
}

export default DriverDashboard
