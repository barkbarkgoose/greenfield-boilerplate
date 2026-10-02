import api from '@/services/api'
import type {
  Catalog,
  DecodedVehicle,
  Estimate,
  ServiceRequestCreated,
  ServiceRequestPayload,
  ServiceSelection
} from '@/types/intake'

export async function fetchCatalog(): Promise<Catalog> {
  const { data } = await api.get<Catalog>('/api/v1/intake/catalog/')
  return data
}

export async function fetchEstimate(
  services: ServiceSelection[],
  preferredDate: string | null
): Promise<Estimate> {
  const { data } = await api.post<Estimate>('/api/v1/intake/estimate/', {
    services,
    preferred_date: preferredDate || null
  })
  return data
}

export async function submitServiceRequest(
  payload: ServiceRequestPayload
): Promise<ServiceRequestCreated> {
  const { data } = await api.post<ServiceRequestCreated>('/api/v1/intake/requests/', payload)
  return data
}

// NHTSA's free vPIC decoder. Best-effort: the form never depends on it.
export async function decodeVin(vin: string): Promise<DecodedVehicle | null> {
  try {
    const response = await fetch(
      `https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/${encodeURIComponent(vin)}?format=json`
    )
    if (!response.ok) return null
    const body = await response.json()
    const result = body?.Results?.[0]
    if (!result?.Make) return null
    return {
      year: result.ModelYear || '',
      make: result.Make || '',
      model: result.Model || ''
    }
  } catch {
    return null
  }
}
