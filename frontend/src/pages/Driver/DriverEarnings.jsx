import { useEffect, useMemo, useRef, useState } from 'react'
import Chart from 'chart.js/auto'
import { useDriverData } from '../../context/DriverContext.jsx'
import { useAuth } from '../../context/AuthContext.jsx'
import Pager from '../../components/Common/Pager.jsx'
import StatementButton from '../../components/Common/StatementButton.jsx'
import { usePaged } from '../../utils/usePaged.js'
import { inr, CHART_VIEWS, tripStatusLabel } from './format.js'

const Icon = ({ children, className = '' }) => (
  <span className={`material-symbols-outlined ${className}`} aria-hidden="true">
    {children}
  </span>
)

const DAY = 1000 * 60 * 60 * 24

const startOfDay = (ts) => {
  const d = new Date(ts)
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

function sumFaresBetween(trips, start, end) {
  return Math.round(
    trips.filter((t) => t.timestamp >= start && t.timestamp < end).reduce((sum, t) => sum + t.fare, 0),
  )
}

function buildWeekView(trips) {
  const labels = []
  const data = []
  for (let i = 6; i >= 0; i -= 1) {
    const start = startOfDay(Date.now() - i * DAY)
    const end = start + DAY
    labels.push(new Date(start).toLocaleDateString('en-US', { weekday: 'short' }))
    data.push(sumFaresBetween(trips, start, end))
  }
  return { labels, data }
}

function buildMonthView(trips) {
  const labels = []
  const data = []
  for (let i = 3; i >= 0; i -= 1) {
    const end = Date.now() - i * 7 * DAY
    const start = end - 7 * DAY
    labels.push(`Week ${4 - i}`)
    data.push(sumFaresBetween(trips, start, end))
  }
  return { labels, data }
}

function buildYearView(trips) {
  const labels = []
  const data = []
  const now = new Date()
  for (let i = 11; i >= 0; i -= 1) {
    const monthDate = new Date(now.getFullYear(), now.getMonth() - i, 1)
    const start = monthDate.getTime()
    const end = new Date(now.getFullYear(), now.getMonth() - i + 1, 1).getTime()
    labels.push(monthDate.toLocaleDateString('en-US', { month: 'short' }))
    data.push(sumFaresBetween(trips, start, end))
  }
  return { labels, data }
}

function DriverEarnings({ flash }) {
  const { user } = useAuth()
  const { trips, transactions, completedTrips, earnings, walletBalance, withdrawals, pendingWithdrawals, successfulWithdrawals } =
    useDriverData()
  const [view, setView] = useState('week')
  const canvasRef = useRef(null)
  const chartRef = useRef(null)

  const chartData = useMemo(() => {
    if (view === 'month') return buildMonthView(completedTrips)
    if (view === 'year') return buildYearView(completedTrips)
    return buildWeekView(completedTrips)
  }, [view, completedTrips])

  useEffect(() => {
    if (!canvasRef.current) return undefined
    chartRef.current?.destroy()

    chartRef.current = new Chart(canvasRef.current, {
      type: 'bar',
      data: {
        labels: chartData.labels,
        datasets: [
          {
            label: 'Earnings (\u20b9)',
            data: chartData.data,
            backgroundColor: '#fdd34d',
            borderRadius: 6,
            maxBarThickness: 42,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => inr(ctx.parsed.y) } },
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { callback: (value) => `\u20b9${value}` },
            grid: { color: 'rgba(150,160,170,0.15)' },
          },
          x: { grid: { display: false } },
        },
      },
    })

    return () => chartRef.current?.destroy()
  }, [chartData])

  const sortedTrips = useMemo(() => [...trips].sort((a, b) => b.timestamp - a.timestamp), [trips])
  // Ten rows per page for trips and for withdrawals.
  const tripPages = usePaged(sortedTrips)
  const withdrawalPages = usePaged(withdrawals)

  return (
    <>
      <h1>Earnings</h1>
      <p className="muted">All amounts are in Indian Rupees (₹).</p>

      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">Today&apos;s Earnings</span>
            <span className="kpi-icon">
              <Icon>today</Icon>
            </span>
          </div>
          <span className="kpi-value">{inr(earnings.today)}</span>
        </div>
        <div className="kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">Weekly Earnings</span>
            <span className="kpi-icon">
              <Icon>date_range</Icon>
            </span>
          </div>
          <span className="kpi-value">{inr(earnings.week)}</span>
        </div>
        <div className="kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">Monthly Earnings</span>
            <span className="kpi-icon">
              <Icon>calendar_month</Icon>
            </span>
          </div>
          <span className="kpi-value">{inr(earnings.month)}</span>
        </div>
        <div className="kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">Lifetime Earnings</span>
            <span className="kpi-icon">
              <Icon>military_tech</Icon>
            </span>
          </div>
          <span className="kpi-value">{inr(earnings.lifetime)}</span>
        </div>
        <div className="kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">Wallet Balance</span>
            <span className="kpi-icon">
              <Icon>account_balance_wallet</Icon>
            </span>
          </div>
          <span className="kpi-value">{inr(walletBalance)}</span>
        </div>
        <div className="kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">Pending Withdrawals</span>
            <span className="kpi-icon">
              <Icon>hourglass_top</Icon>
            </span>
          </div>
          <span className="kpi-value">{inr(pendingWithdrawals.reduce((s, w) => s + w.amount, 0))}</span>
          <span className="kpi-sub">{pendingWithdrawals.length} request(s)</span>
        </div>
        <div className="kpi-card">
          <div className="kpi-top">
            <span className="kpi-label">Successful Withdrawals</span>
            <span className="kpi-icon">
              <Icon>check_circle</Icon>
            </span>
          </div>
          <span className="kpi-value">{inr(successfulWithdrawals.reduce((s, w) => s + w.amount, 0))}</span>
          <span className="kpi-sub">{successfulWithdrawals.length} completed</span>
        </div>
      </div>

      <div className="chart-card">
        <div className="chart-head">
          <b>Earnings Trend</b>
          <div className="ranges">
            {CHART_VIEWS.map((option) => (
              <button
                key={option.key}
                className={view === option.key ? 'active' : ''}
                onClick={() => setView(option.key)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <div style={{ position: 'relative', height: 260 }}>
          <canvas ref={canvasRef} />
        </div>
      </div>

      <h2 id={tripPages.anchorId} className="paged-anchor">Trips History</h2>
      <div className="chart-card" style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 560 }}>
          <thead>
            <tr style={{ textAlign: 'left', borderBottom: '1px solid var(--line)' }}>
              <th style={{ padding: '10px 8px', fontSize: 12, color: 'var(--muted)', textTransform: 'uppercase' }}>Trip ID</th>
              <th style={{ padding: '10px 8px', fontSize: 12, color: 'var(--muted)', textTransform: 'uppercase' }}>Passenger</th>
              <th style={{ padding: '10px 8px', fontSize: 12, color: 'var(--muted)', textTransform: 'uppercase' }}>Date</th>
              <th style={{ padding: '10px 8px', fontSize: 12, color: 'var(--muted)', textTransform: 'uppercase' }}>Status</th>
              <th style={{ padding: '10px 8px', fontSize: 12, color: 'var(--muted)', textTransform: 'uppercase', textAlign: 'right' }}>Earnings</th>
            </tr>
          </thead>
          <tbody>
            {tripPages.pageItems.map((trip) => (
              <tr key={trip.id} style={{ borderBottom: '1px solid var(--line)' }}>
                <td style={{ padding: '10px 8px', fontWeight: 700 }}>{trip.id}</td>
                <td style={{ padding: '10px 8px' }}>{trip.passenger}</td>
                <td style={{ padding: '10px 8px', color: 'var(--muted)' }}>
                  {new Date(trip.timestamp).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}
                </td>
                <td style={{ padding: '10px 8px' }}>{tripStatusLabel[trip.status]}</td>
                <td style={{ padding: '10px 8px', textAlign: 'right', fontWeight: 700 }}>{inr(trip.fare)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pager paged={tripPages} />

      <h2 id={withdrawalPages.anchorId} className="paged-anchor">Withdrawal History</h2>
      {withdrawals.length === 0 && <p className="driver-empty">No withdrawals yet.</p>}
      {withdrawalPages.pageItems.map((w) => (
        <article className="ride" key={w.id}>
          <div>
            <b>Withdrawal to bank</b>
            <small>{w.id}</small>
            <small>{new Date(w.timestamp).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</small>
          </div>
          <div style={{ textAlign: 'right', display: 'grid', gap: 4 }}>
            <strong>{inr(w.amount)}</strong>
            <small className="muted">{w.status === 'success' ? 'Successful' : 'Pending'}</small>
          </div>
        </article>
      ))}
      <Pager paged={withdrawalPages} />

      <StatementButton
        className="tg-statement-btn--block"
        label="Download Statement (PDF)"
        onError={flash}
        getData={() => ({
          holderName: user?.name,
          email: user?.email,
          role: 'driver',
          balance: walletBalance,
          transactions,
        })}
      />
    </>
  )
}

export default DriverEarnings
