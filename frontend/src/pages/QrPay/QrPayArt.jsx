// Original, logo-free artwork for the confirm-payment page. Nothing here is sourced from the web.
// DriverAvatar: a cartoon driver with a blink and a slight head bob (switched off by prefers-reduced-motion in QrPay.css).
// VehicleArt: a flat illustration picked by vehicle type, used when no vehicle photo is set.

export function DriverAvatar({ label = 'Driver avatar' }) {
  return (
    <svg className="qp-avatar" viewBox="0 0 120 120" role="img" aria-label={label}>
      <circle cx="60" cy="60" r="58" fill="#fff3c4" />
      <g className="qp-avatar-body">
        <path d="M14 112c3-22 21-32 46-32s43 10 46 32a58 58 0 0 1-92 0z" fill="#fdd34d" />
        <path d="M46 82l14 14 14-14" fill="none" stroke="#f5be24" strokeWidth="4" strokeLinejoin="round" />
        <rect x="52" y="68" width="16" height="16" rx="6" fill="#d9a27a" />
      </g>
      <g className="qp-avatar-head">
        <ellipse cx="60" cy="50" rx="25" ry="27" fill="#f0b98f" />
        <ellipse cx="35.5" cy="52" rx="4" ry="6" fill="#e5a67a" />
        <ellipse cx="84.5" cy="52" rx="4" ry="6" fill="#e5a67a" />
        <path d="M34 40c0-16 12-26 26-26s26 10 26 26z" fill="#1e1b16" />
        <path d="M30 41c10-4 50-4 60 0 2 2 0 5-3 5H33c-3 0-5-3-3-5z" fill="#2b2620" />
        <circle cx="60" cy="27" r="5" fill="#fdd34d" />
        <g className="qp-avatar-eyes">
          <ellipse cx="50" cy="54" rx="3.4" ry="4.2" fill="#1e1b16" />
          <ellipse cx="70" cy="54" rx="3.4" ry="4.2" fill="#1e1b16" />
          <circle cx="51.2" cy="52.6" r="1.1" fill="#fff" />
          <circle cx="71.2" cy="52.6" r="1.1" fill="#fff" />
        </g>
        <path d="M44 47c3-2 7-2 10 0M66 47c3-2 7-2 10 0" fill="none" stroke="#1e1b16" strokeWidth="2" strokeLinecap="round" />
        <path d="M52 66c2-4 14-4 16 0-5-1.5-11-1.5-16 0z" fill="#2b2620" />
        <path d="M52 70c4 4 12 4 16 0" fill="none" stroke="#9a4a3a" strokeWidth="2.4" strokeLinecap="round" />
        <circle cx="42" cy="62" r="3.5" fill="#f08c7a" opacity="0.35" />
        <circle cx="78" cy="62" r="3.5" fill="#f08c7a" opacity="0.35" />
      </g>
    </svg>
  )
}

const Wheel = ({ cx, cy, r = 14 }) => (
  <g>
    <circle cx={cx} cy={cy} r={r} fill="#1e1b16" />
    <circle cx={cx} cy={cy} r={r * 0.5} fill="#cfc8bb" />
    <circle cx={cx} cy={cy} r={r * 0.18} fill="#6b6458" />
  </g>
)

function vehicleKind(type) {
  const t = String(type || '').toLowerCase()
  if (t.includes('auto') || t.includes('rickshaw')) return 'auto'
  if (/(suv|creta|jeep|crossover|innova|xuv|scorpio|ertiga)/.test(t)) return 'suv'
  return 'sedan'
}

export function VehicleArt({ type, label }) {
  const kind = vehicleKind(type)
  const names = { auto: 'Auto-rickshaw', suv: 'SUV', sedan: 'Car' }
  return (
    <svg className="qp-vehicle-art" viewBox="0 0 240 130" role="img" aria-label={label || `${names[kind]} illustration`}>
      <ellipse cx="120" cy="116" rx="96" ry="7" fill="#1e1b16" opacity="0.1" />
      {kind === 'auto' && (
        <g>
          <rect x="46" y="22" width="132" height="10" rx="5" fill="#177a47" />
          <path d="M56 32h114l14 40H50z" fill="#fdd34d" />
          <rect x="64" y="40" width="46" height="22" rx="4" fill="#cfe7f2" />
          <path d="M118 40h38c4 0 7 2 8 6l6 16h-52z" fill="#cfe7f2" />
          <rect x="44" y="72" width="148" height="22" rx="8" fill="#177a47" />
          <path d="M184 72h8c8 0 14 6 14 14v8h-22z" fill="#fdd34d" />
          <circle cx="198" cy="82" r="4" fill="#fff3c4" />
          <Wheel cx="76" cy="100" r="15" />
          <Wheel cx="196" cy="100" r="13" />
        </g>
      )}
      {kind === 'sedan' && (
        <g>
          <path d="M22 88c0-10 6-16 16-18l26-6 22-26c4-5 10-8 16-8h40c8 0 14 3 19 9l20 24 26 6c8 2 12 8 12 17v8c0 4-3 7-7 7H29c-4 0-7-3-7-7z" fill="#fdd34d" />
          <path d="M88 40l-16 24h56V36h-34c-3 0-5 1-6 4zM136 36v28h50l-18-22c-3-4-6-6-11-6z" fill="#cfe7f2" />
          <rect x="108" y="22" width="26" height="10" rx="3" fill="#1e1b16" />
          <rect x="22" y="94" width="196" height="9" rx="4" fill="#1e1b16" opacity="0.18" />
          <rect x="204" y="76" width="14" height="8" rx="3" fill="#fff3c4" />
          <rect x="22" y="76" width="12" height="8" rx="3" fill="#e0412f" />
          <Wheel cx="66" cy="102" />
          <Wheel cx="178" cy="102" />
        </g>
      )}
      {kind === 'suv' && (
        <g>
          <path d="M20 90c0-12 6-18 16-20l14-28c3-6 9-10 16-10h104c8 0 15 4 19 11l16 26c14 2 20 8 20 20v8c0 4-3 7-7 7H27c-4 0-7-3-7-7z" fill="#3f5a73" />
          <path d="M68 46l-10 22h60V42H72c-2 0-3 1-4 4zM126 42v26h56l-12-22c-2-3-5-4-9-4z" fill="#cfe7f2" />
          <rect x="52" y="30" width="136" height="6" rx="3" fill="#1e1b16" opacity="0.35" />
          <rect x="20" y="94" width="200" height="9" rx="4" fill="#1e1b16" opacity="0.25" />
          <rect x="206" y="76" width="14" height="8" rx="3" fill="#fff3c4" />
          <rect x="20" y="76" width="12" height="8" rx="3" fill="#e0412f" />
          <Wheel cx="64" cy="102" r="15" />
          <Wheel cx="180" cy="102" r="15" />
        </g>
      )}
    </svg>
  )
}
