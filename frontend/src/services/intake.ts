import api from '@/services/api'
import type { Catalog, Estimate, ItemSelection, OrderCreated, OrderPayload } from '@/types/intake'

export async function fetchCatalog(): Promise<Catalog> {
  const { data } = await api.get<Catalog>('/api/v1/intake/catalog/')
  return data
}

// Coverage for the zip, routing and a price. Works with no items (just a
// coverage check) and with no date (priced without checking trucks).
export async function fetchEstimate(
  items: ItemSelection[],
  zipCode: string,
  preferredDate: string | null
): Promise<Estimate> {
  const { data } = await api.post<Estimate>('/api/v1/intake/estimate/', {
    items,
    zip_code: zipCode,
    preferred_date: preferredDate || null
  })
  return data
}

export async function submitOrder(payload: OrderPayload): Promise<OrderCreated> {
  const { data } = await api.post<OrderCreated>('/api/v1/intake/orders/', payload)
  return data
}
