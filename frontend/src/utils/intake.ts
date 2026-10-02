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

// --- Dates -------------------------------------------------------------------

// A date-only value ("2026-10-16") as a local calendar date, no UTC shift.
export function formatDate(value: string | null | undefined): string {
  if (!value) return ''
  const [y, m, d] = value.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric'
  })
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return ''
  return new Date(value).toLocaleString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit'
  })
}

// ISO timestamp -> value for <input type="datetime-local"> in the browser's zone.
export function toDateTimeLocal(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

// <input type="datetime-local"> value -> ISO timestamp with zone.
export function fromDateTimeLocal(value: string): string | null {
  return value ? new Date(value).toISOString() : null
}

// --- Request status ------------------------------------------------------------

export const STATUS_OPTIONS = [
  { value: 'new', label: 'New', classes: 'bg-sky-100 text-sky-800 ring-sky-200' },
  { value: 'contacted', label: 'Contacted', classes: 'bg-violet-100 text-violet-800 ring-violet-200' },
  { value: 'scheduled', label: 'Scheduled', classes: 'bg-amber-100 text-amber-900 ring-amber-200' },
  { value: 'completed', label: 'Completed', classes: 'bg-emerald-100 text-emerald-800 ring-emerald-200' },
  { value: 'declined', label: 'Declined', classes: 'bg-slate-100 text-slate-600 ring-slate-200' }
] as const

export function statusOption(status: string) {
  return STATUS_OPTIONS.find((option) => option.value === status) ?? STATUS_OPTIONS[0]
}

export function servicesLabel(services: { name: string; quantity: number }[]): string {
  return services
    .map((s) => (s.quantity > 1 ? `${s.name} ×${s.quantity}` : s.name))
    .join(', ')
}
