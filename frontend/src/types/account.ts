import type { DeliveryWindow, Quote, RequestType } from '@/types/intake'

export type OrderStatus = 'new' | 'contacted' | 'scheduled' | 'delivered' | 'declined'

export interface OrderItem {
  key: string
  name: string
  quantity: number
}

export interface OrderSummary {
  id: number
  request_type: RequestType
  status: OrderStatus
  zip_code: string
  city: string
  delivery_address: string
  items: OrderItem[]
  preferred_date: string | null
  scheduled_date: string | null
  delivery_window: DeliveryWindow
  delivered_on: string | null
  estimated_total: string | null
  final_total: string | null
  is_rush: boolean
  unread_count: number
  created_at: string
}

export type PlanStatusValue = '' | 'ok' | 'no_capacity' | 'out_of_stock'

export interface StaffOrderSummary extends OrderSummary {
  name: string
  phone: string
  plan_status: PlanStatusValue
  coverage: '' | 'serve' | 'contact' | 'outside'
}

export interface OrderMessage {
  id: number
  body: string
  from_staff: boolean
  author_name: string
  created_at: string
}

export interface OrderDetail extends OrderSummary {
  name: string
  phone: string
  email: string
  placement_notes: string
  notes: string
  quote: Quote | Record<string, never>
  invoice: Invoice | null
  messages: OrderMessage[]
  // Message threads can be switched off on the server (INTAKE_MESSAGING_ENABLED).
  messaging_enabled: boolean
  updated_at: string
}

export interface OrderUpdates {
  messages: OrderMessage[]
  updated_at: string
}

// --- Invoices ------------------------------------------------------------------

export type InvoiceLineKind = 'service' | 'fee' | 'adjustment'

export const INVOICE_LINE_KINDS: InvoiceLineKind[] = ['service', 'fee', 'adjustment']

export interface InvoiceLine {
  kind: InvoiceLineKind
  description: string
  quantity: string
  unit_price: string
  amount: string
}

export interface InvoiceLoad {
  product: string
  quantity: number
  miles: string
}

export interface InvoiceTotals {
  delivered: string
  services: string
  fees: string
  adjustments: string
  total: string
}

export interface Invoice {
  exists: boolean
  items: OrderItem[]
  loads: InvoiceLoad[]
  charge_rush_fee: boolean
  // Material + per-load delivery, priced like an order quote.
  priced: Quote
  lines: InvoiceLine[]
  note: string
  totals: InvoiceTotals
  published_at: string | null
  updated_at: string | null
}

export interface InvoiceInput {
  items: { key: string; quantity: number }[]
  loads: InvoiceLoad[]
  charge_rush_fee: boolean
  lines: Omit<InvoiceLine, 'amount'>[]
  note: string
  published: boolean
  notify_customer: boolean
}

// --- Staff ---------------------------------------------------------------------

export interface OrderLoad {
  id: number
  product: string
  product_name: string
  quantity: number
  yard: number | null
  yard_name: string
  truck: number | null
  truck_name: string
  date: string | null
  miles: string
  minutes: number
}

export interface StaffOrderDetail extends OrderDetail {
  customer: { id: number; name: string; email: string } | null
  customer_order_count: number
  internal_notes: string
  language: string
  coverage: StaffOrderSummary['coverage']
  plan_status: PlanStatusValue
  loads: OrderLoad[]
  area: {
    status: 'serve' | 'contact' | 'outside'
    city: string
    note: string
    yards: { code: string; miles: string; minutes: number }[]
  }
  contact_consent: boolean
  marketing_consent: boolean
  consent_at: string | null
  // Django admin base path (ADMIN_URL), e.g. "/back-office-7f3k2q/".
  admin_url: string
}

export interface StaffOrderUpdate {
  status?: OrderStatus
  scheduled_date?: string | null
  delivery_window?: DeliveryWindow
  delivered_on?: string | null
  final_total?: string | null
  internal_notes?: string
  notify_customer?: boolean
}

export interface StaffSummary {
  status_counts: Record<OrderStatus, number>
  unread_messages: number
  messaging_enabled: boolean
  new_this_week: number
  rush_open: number
  needs_dispatch: number
  loads_today: number
  upcoming: StaffOrderSummary[]
}

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

// --- Dispatch board -------------------------------------------------------------

export interface BoardLoad {
  id: number
  order_id: number
  order_name: string
  order_status: OrderStatus
  zip_code: string
  city: string
  window: DeliveryWindow
  product: string
  product_name: string
  quantity: number
  yard: string | null
  miles: string
  minutes: number
}

export interface BoardTruck {
  id: number
  name: string
  capacity_yards: number
  workday_minutes: number
  active: boolean
  day_off: boolean
  used_minutes: number
  loads: BoardLoad[]
}

export interface BoardStock {
  id: number | null
  product: string
  product_name: string
  carried: boolean
  in_stock: boolean
  note: string
}

export interface BoardYard {
  code: string
  name: string
  active: boolean
  stock: BoardStock[]
  trucks: BoardTruck[]
}

export interface DispatchBoard {
  date: string
  delivery_day: boolean
  yards: BoardYard[]
  unassigned: BoardLoad[]
}
