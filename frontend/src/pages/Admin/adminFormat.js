// Number / money / date formatters shared by the newer admin pages (same output as the ones inside Admin.jsx).
export const number = (value) => new Intl.NumberFormat('en-IN').format(value || 0)
export const money = (value) => `₹${new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value || 0)}`
export const date = (value) => value ? new Date(value).toLocaleString() : '—'
