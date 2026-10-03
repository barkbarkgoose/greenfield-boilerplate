import api from '@/services/api'
import type { PartsEstimate } from '@/types/intake'
import type {
  Invoice,
  InvoiceInput,
  Paginated,
  RequestDetail,
  RequestMessage,
  RequestSummary,
  RequestUpdates,
  StaffRequestDetail,
  StaffRequestUpdate,
  StaffSummary,
  Vehicle
} from '@/types/garage'

// --- Customer ("my garage") ---------------------------------------------------

export async function fetchMyVehicles(): Promise<Vehicle[]> {
  return (await api.get<Vehicle[]>('/api/v1/garage/vehicles/')).data
}

export async function renameVehicle(id: number, nickname: string): Promise<Vehicle> {
  return (await api.patch<Vehicle>(`/api/v1/garage/vehicles/${id}/`, { nickname })).data
}

export async function fetchMyRequests(): Promise<RequestSummary[]> {
  return (await api.get<RequestSummary[]>('/api/v1/garage/requests/')).data
}

export async function fetchMyRequest(id: number | string): Promise<RequestDetail> {
  return (await api.get<RequestDetail>(`/api/v1/garage/requests/${id}/`)).data
}

export async function sendCustomerMessage(id: number, body: string): Promise<RequestMessage> {
  return (await api.post<RequestMessage>(`/api/v1/garage/requests/${id}/messages/`, { body })).data
}

export async function claimRequest(token: string): Promise<{ id: number }> {
  return (await api.post<{ id: number }>('/api/v1/garage/claim/', { token })).data
}

// --- Staff ---------------------------------------------------------------------

export interface StaffRequestFilters {
  status?: string
  q?: string
  unread?: boolean
  emergency?: boolean
  ordering?: string
  page?: number
}

export async function fetchStaffSummary(): Promise<StaffSummary> {
  return (await api.get<StaffSummary>('/api/v1/manage/summary/')).data
}

export async function fetchStaffRequests(
  filters: StaffRequestFilters
): Promise<Paginated<RequestSummary & { name: string }>> {
  const params: Record<string, string | number> = {}
  if (filters.status) params.status = filters.status
  if (filters.q) params.q = filters.q
  if (filters.unread) params.unread = 1
  if (filters.emergency) params.emergency = 1
  if (filters.ordering) params.ordering = filters.ordering
  if (filters.page && filters.page > 1) params.page = filters.page
  return (await api.get('/api/v1/manage/requests/', { params })).data
}

export async function fetchStaffRequest(id: number | string): Promise<StaffRequestDetail> {
  return (await api.get<StaffRequestDetail>(`/api/v1/manage/requests/${id}/`)).data
}

export async function updateStaffRequest(
  id: number,
  changes: StaffRequestUpdate
): Promise<StaffRequestDetail> {
  return (await api.patch<StaffRequestDetail>(`/api/v1/manage/requests/${id}/`, changes)).data
}

export async function sendStaffMessage(id: number, body: string): Promise<RequestMessage> {
  return (await api.post<RequestMessage>(`/api/v1/manage/requests/${id}/messages/`, { body })).data
}

export async function retryPartsEstimate(id: number): Promise<PartsEstimate | null> {
  return (
    await api.post<{ parts_estimate: PartsEstimate | null }>(`/api/v1/manage/requests/${id}/parts-estimate/`)
  ).data.parts_estimate
}

// --- Live updates (polling) -------------------------------------------------------

export async function pollMyRequest(id: number, afterId: number): Promise<RequestUpdates> {
  return (await api.get<RequestUpdates>(`/api/v1/garage/requests/${id}/updates/`, { params: { after: afterId } })).data
}

export async function pollStaffRequest(id: number, afterId: number): Promise<RequestUpdates> {
  return (await api.get<RequestUpdates>(`/api/v1/manage/requests/${id}/updates/`, { params: { after: afterId } })).data
}

// --- Invoices (staff) -------------------------------------------------------------

export async function fetchInvoice(id: number): Promise<Invoice> {
  return (await api.get<Invoice>(`/api/v1/manage/requests/${id}/invoice/`)).data
}

export async function previewInvoice(id: number, input: InvoiceInput): Promise<Invoice> {
  return (await api.post<Invoice>(`/api/v1/manage/requests/${id}/invoice/preview/`, input)).data
}

export async function saveInvoice(id: number, input: InvoiceInput): Promise<Invoice> {
  return (await api.put<Invoice>(`/api/v1/manage/requests/${id}/invoice/`, input)).data
}

export async function deleteInvoice(id: number): Promise<void> {
  await api.delete(`/api/v1/manage/requests/${id}/invoice/`)
}
