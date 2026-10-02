// Pure helpers for the intake form (no API or router imports, so they're unit-testable).

export const VIN_PATTERN = /^[A-HJ-NPR-Z0-9]{17}$/

export function normalizeVin(value: string): string {
  return value.replace(/[\s-]/g, '').toUpperCase()
}

export function formatMoney(value: string | number): string {
  const amount = typeof value === 'string' ? Number(value) : value
  return amount.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: amount % 1 === 0 ? 0 : 2
  })
}

// YYYY-MM-DD in the browser's local time zone (what <input type="date"> uses).
export function isoDateFromToday(days: number): string {
  const date = new Date()
  date.setDate(date.getDate() + days)
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}
