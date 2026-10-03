import type { Estimate, PartsEstimate, VehicleType } from '@/types/intake'

export type RequestStatus = 'new' | 'contacted' | 'scheduled' | 'completed' | 'declined'

export interface RequestService {
  key: string
  name: string
  quantity: number
}

export interface RequestSummary {
  id: number
  request_type: 'booking' | 'callback'
  status: RequestStatus
  vehicle_id: number | null
  vehicle_label: string
  vin: string
  services: RequestService[]
  preferred_date: string | null
  scheduled_for: string | null
  completed_on: string | null
  odometer: number | null
  estimated_total: string | null
  final_total: string | null
  is_emergency: boolean
  unread_count: number
  created_at: string
}

export interface StaffRequestSummary extends RequestSummary {
  name?: string
}

export interface RequestMessage {
  id: number
  body: string
  from_staff: boolean
  author_name: string
  created_at: string
}

export interface VehicleSummary {
  id: number
  vin: string
  year: string
  make: string
  model: string
  nickname: string
  label: string
}

export interface Vehicle extends VehicleSummary {
  history: RequestSummary[]
  created_at: string
}

export interface RequestDetail extends RequestSummary {
  vehicle: VehicleSummary | null
  name: string
  phone: string
  email: string
  service_address: string
  vehicle_year: string
  vehicle_make: string
  vehicle_model: string
  other_description: string
  notes: string
  estimate: Estimate | Record<string, never>
  parts_estimate: PartsEstimate | null
  invoice: Invoice | null
  messages: RequestMessage[]
  // Message threads can be switched off on the server (INTAKE_MESSAGING_ENABLED).
  messaging_enabled: boolean
  updated_at: string
}

export interface RequestUpdates {
  messages: RequestMessage[]
  updated_at: string
}

// --- Invoices ------------------------------------------------------------------

export type InvoiceLineKind = 'part' | 'shipping' | 'labor' | 'adjustment'

export const INVOICE_LINE_KINDS: InvoiceLineKind[] = ['part', 'shipping', 'labor', 'adjustment']

export interface InvoiceLine {
  kind: InvoiceLineKind
  description: string
  quantity: string
  unit_price: string
  amount: string
}

export interface InvoiceTotals {
  jobs: string
  parts: string
  shipping: string
  labor: string
  adjustments: string
  total: string
}

export interface Invoice {
  exists: boolean
  services: RequestService[]
  charge_rush_fee: boolean
  // Jobs priced like a booking estimate (bundles, deals, service call, rush fee).
  labor: Estimate
  lines: InvoiceLine[]
  note: string
  totals: InvoiceTotals
  published_at: string | null
  updated_at: string | null
}

export interface InvoiceInput {
  services: { key: string; quantity: number }[]
  charge_rush_fee: boolean
  lines: Omit<InvoiceLine, 'amount'>[]
  note: string
  published: boolean
  notify_customer: boolean
}

export interface StaffRequestDetail extends RequestDetail {
  customer: { id: number; name: string; email: string } | null
  customer_request_count: number
  internal_notes: string
  vehicle_type: VehicleType | ''
  contact_consent: boolean
  marketing_consent: boolean
  consent_at: string | null
}

export interface StaffRequestUpdate {
  status?: RequestStatus
  scheduled_for?: string | null
  completed_on?: string | null
  odometer?: number | null
  final_total?: string | null
  internal_notes?: string
  vehicle_type?: VehicleType | ''
  notify_customer?: boolean
}

export interface StaffSummary {
  status_counts: Record<RequestStatus, number>
  unread_messages: number
  messaging_enabled: boolean
  new_this_week: number
  emergencies_open: number
  upcoming: RequestSummary[]
}

export interface Paginated<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}
