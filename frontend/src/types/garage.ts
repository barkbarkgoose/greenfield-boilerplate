import type { Estimate, PartsEstimate } from '@/types/intake'

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
  messages: RequestMessage[]
}

export interface StaffRequestDetail extends RequestDetail {
  customer: { id: number; name: string; email: string } | null
  customer_request_count: number
  internal_notes: string
  updated_at: string
}

export interface StaffRequestUpdate {
  status?: RequestStatus
  scheduled_for?: string | null
  completed_on?: string | null
  odometer?: number | null
  final_total?: string | null
  internal_notes?: string
  notify_customer?: boolean
}

export interface StaffSummary {
  status_counts: Record<RequestStatus, number>
  unread_messages: number
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
