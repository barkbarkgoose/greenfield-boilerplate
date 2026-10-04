// Public catalog, live quotes and the order form.

export interface CatalogProduct {
  key: string
  name: string
  description: string
  price_per_yard: string
  min_yards: number
  max_yards: number
}

export interface Catalog {
  products: CatalogProduct[]
  delivery_base_fee: string
  included_miles: string
  per_mile_fee: string
  rush_fee: string
  rush_window_days: number
  // Days trucks run, Monday = 0 (Python's weekday()).
  delivery_weekdays: number[]
  max_days_ahead: number
  sales_tax_rate: string
}

export interface ItemSelection {
  key: string
  quantity: number
}

export interface QuoteLineItem {
  key: string
  name: string
  quantity: number
  unit_price: string
  amount: string
}

export interface QuoteDelivery {
  product: string
  product_name?: string
  quantity: number
  miles: string
  fee: string
}

export interface Quote {
  line_items: QuoteLineItem[]
  deliveries: QuoteDelivery[]
  material_total: string
  tax: string
  delivery_total: string
  rush_fee: string
  total: string
  load_count: number
  scheduling: { days_out: number | null; is_rush: boolean }
}

// What routing said about the zip and the order (see backend dispatch.py).
export type PlanStatus = 'ok' | 'no_capacity' | 'out_of_stock' | 'special_request' | 'outside_area' | 'empty'
export type Coverage = 'serve' | 'contact' | 'outside'

export interface PlanProblem {
  code: 'out_of_stock' | 'no_capacity'
  product: string
  product_name: string
  quantity?: number
}

export interface Plan {
  status: PlanStatus
  zip_code: string
  coverage: Coverage
  city: string
  date: string | null
  loads: {
    product: string
    product_name: string
    quantity: number
    yard: string | null
    yard_name: string
    miles: string
    minutes: number
    assigned: boolean
  }[]
  problems: PlanProblem[]
  next_available_date: string | null
}

export interface Estimate {
  quote: Quote | null
  plan: Plan
}

export type RequestType = 'delivery' | 'callback'
export type DeliveryWindow = 'any' | 'morning' | 'afternoon'
export const DELIVERY_WINDOWS: DeliveryWindow[] = ['any', 'morning', 'afternoon']

export interface OrderPayload {
  request_type: RequestType
  name: string
  phone: string
  email: string
  delivery_address: string
  zip_code: string
  items: ItemSelection[]
  preferred_date: string | null
  delivery_window: DeliveryWindow
  placement_notes: string
  notes: string
  contact_consent: boolean
  marketing_consent: boolean
  website?: string
  captcha_token?: string
}

export interface OrderCreated {
  id: number
  request_type: RequestType
  quote: Quote | Record<string, never>
  preferred_date: string | null
  plan_status: PlanStatus | null
  claim_token: string | null
}
