// Pure helpers for the order form and order pages (no API or router imports,
// so they're unit-testable).
import { intlLocale } from '@/i18n'

export function formatMoney(value: string | number): string {
  const amount = typeof value === 'string' ? Number(value) : value
  return amount.toLocaleString(intlLocale(), {
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

// Delivery days use the backend's numbering: Monday = 0 ... Sunday = 6.
export function isDeliveryDay(iso: string, weekdays: number[]): boolean {
  const [y, m, d] = iso.split('-').map(Number)
  const jsDay = new Date(y, m - 1, d).getDay()
  return weekdays.includes((jsDay + 6) % 7)
}

// The first delivery day at least `days` from today, as YYYY-MM-DD.
export function nextDeliveryDate(days: number, weekdays: number[]): string {
  for (let offset = days; offset < days + 7; offset++) {
    const iso = isoDateFromToday(offset)
    if (isDeliveryDay(iso, weekdays)) return iso
  }
  return isoDateFromToday(days)
}

// A date-only value ("2026-10-16") as a local calendar date, no UTC shift.
export function formatDate(value: string | null | undefined): string {
  if (!value) return ''
  const [y, m, d] = value.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(intlLocale(), {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    year: 'numeric'
  })
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return ''
  return new Date(value).toLocaleString(intlLocale(), {
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

// --- Order status --------------------------------------------------------------

export const STATUS_OPTIONS = [
  { value: 'new', label: 'New', classes: 'bg-sky-100 text-sky-800 ring-sky-200' },
  { value: 'contacted', label: 'Contacted', classes: 'bg-violet-100 text-violet-800 ring-violet-200' },
  { value: 'scheduled', label: 'Scheduled', classes: 'bg-amber-100 text-amber-900 ring-amber-200' },
  { value: 'delivered', label: 'Delivered', classes: 'bg-emerald-100 text-emerald-800 ring-emerald-200' },
  { value: 'declined', label: 'Declined', classes: 'bg-stone-100 text-stone-600 ring-stone-200' }
] as const

export function statusOption(status: string) {
  return STATUS_OPTIONS.find((option) => option.value === status) ?? STATUS_OPTIONS[0]
}

// "Screened topsoil 10 yd, Compost 3 yd"
export function itemsLabel(items: { name: string; quantity: number }[], unit = 'yd'): string {
  return items.map((item) => `${item.name} ${item.quantity} ${unit}`).join(', ')
}

// --- Yardage ---------------------------------------------------------------------

// Cubic yards to cover length x width (feet) at a depth in inches, rounded up
// to a whole yard. 27 cubic feet = 1 cubic yard.
export function cubicYards(lengthFt: number, widthFt: number, depthIn: number): number {
  if (!(lengthFt > 0 && widthFt > 0 && depthIn > 0)) return 0
  return Math.ceil((lengthFt * widthFt * (depthIn / 12)) / 27)
}
