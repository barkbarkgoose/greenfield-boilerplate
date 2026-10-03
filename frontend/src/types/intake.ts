export interface CatalogService {
  key: string
  name: string
  description: string
  labor_hours: string
  price: string
  unit: string | null
  max_quantity: number
  quote_required: boolean
}

export interface CatalogBundle {
  key: string
  name: string
  description: string
  discount_per_unit: string
}

export interface Catalog {
  services: CatalogService[]
  bundles: CatalogBundle[]
  deals: { key: string; name: string; description: string }[]
  labor_rate: string
  service_call_fee: string
  emergency_fee: string
  booking_lead_days: number
  emergency_window_days: number
}

export interface ServiceSelection {
  key: string
  quantity: number
}

export interface EstimateLineItem {
  key: string
  name: string
  quantity: number
  unit: string | null
  unit_price: string
  amount: string
  quote_required: boolean
}

export interface Estimate {
  line_items: EstimateLineItem[]
  discounts: { key: string; name: string; units: number; amount: string }[]
  subtotal: string
  discount_total: string
  service_call_fee: string
  emergency_fee: string
  total: string
  labor_hours: string
  needs_custom_quote: boolean
  scheduling: {
    days_out: number | null
    is_emergency: boolean
    short_notice: boolean
  }
}

export type RequestType = 'booking' | 'callback'

export interface ServiceRequestPayload {
  request_type: RequestType
  name: string
  phone: string
  email: string
  service_address: string
  vin: string
  vehicle_year: string
  vehicle_make: string
  vehicle_model: string
  services: ServiceSelection[]
  other_description: string
  preferred_date: string | null
  notes: string
  website?: string
  captcha_token?: string
}

export interface ServiceRequestCreated {
  id: number
  request_type: RequestType
  estimate: Estimate | Record<string, never>
  preferred_date: string | null
  claim_token: string | null
  parts_estimate_status: 'pending' | null
}

export interface DecodedVehicle {
  year: string
  make: string
  model: string
}

export type VehicleType = 'sedan' | 'crossover' | 'suv' | 'truck' | 'european'

export const VEHICLE_TYPES: { value: VehicleType; label: string }[] = [
  { value: 'sedan', label: 'Sedan / car' },
  { value: 'crossover', label: 'Crossover' },
  { value: 'suv', label: 'SUV / van' },
  { value: 'truck', label: 'Truck' },
  { value: 'european', label: 'European' }
]

export interface PartsEstimateService {
  service_key: string
  name: string
  quantity: number
  unit: string
  low: string
  typical: string
  high: string
  unit_label: string
  sample_count: number
  basis: { make: string; type: string }
  basis_label: string
  examples: { part_brand: string; description: string; source: string; price: string }[]
}

export interface PartsEstimate {
  status: 'pending' | 'ready' | 'unavailable'
  vehicle_type?: VehicleType | ''
  vehicle_type_label?: string
  vehicle_summary?: string
  services?: PartsEstimateService[]
  missing?: string[]
  low?: string
  typical?: string
  high?: string
  generated_at?: string
}
