import api from '@/services/api'
import type {
  DispatchBoard,
  Invoice,
  InvoiceInput,
  OrderDetail,
  OrderMessage,
  OrderSummary,
  OrderUpdates,
  Paginated,
  StaffOrderDetail,
  StaffOrderSummary,
  StaffOrderUpdate,
  StaffSummary
} from '@/types/account'

// --- Customer ("my orders") ---------------------------------------------------

export async function fetchMyOrders(): Promise<OrderSummary[]> {
  return (await api.get<OrderSummary[]>('/api/v1/account/orders/')).data
}

export async function fetchMyOrder(id: number | string): Promise<OrderDetail> {
  return (await api.get<OrderDetail>(`/api/v1/account/orders/${id}/`)).data
}

export async function sendCustomerMessage(id: number, body: string): Promise<OrderMessage> {
  return (await api.post<OrderMessage>(`/api/v1/account/orders/${id}/messages/`, { body })).data
}

export async function claimOrder(token: string): Promise<{ id: number }> {
  return (await api.post<{ id: number }>('/api/v1/account/claim/', { token })).data
}

// --- Staff ---------------------------------------------------------------------

export interface StaffOrderFilters {
  status?: string
  q?: string
  unread?: boolean
  rush?: boolean
  needsDispatch?: boolean
  ordering?: string
  page?: number
}

export async function fetchStaffSummary(): Promise<StaffSummary> {
  return (await api.get<StaffSummary>('/api/v1/manage/summary/')).data
}

export async function fetchStaffOrders(filters: StaffOrderFilters): Promise<Paginated<StaffOrderSummary>> {
  const params: Record<string, string | number> = {}
  if (filters.status) params.status = filters.status
  if (filters.q) params.q = filters.q
  if (filters.unread) params.unread = 1
  if (filters.rush) params.rush = 1
  if (filters.needsDispatch) params.needs_dispatch = 1
  if (filters.ordering) params.ordering = filters.ordering
  if (filters.page && filters.page > 1) params.page = filters.page
  return (await api.get('/api/v1/manage/orders/', { params })).data
}

export async function fetchStaffOrder(id: number | string): Promise<StaffOrderDetail> {
  return (await api.get<StaffOrderDetail>(`/api/v1/manage/orders/${id}/`)).data
}

export async function updateStaffOrder(id: number, changes: StaffOrderUpdate): Promise<StaffOrderDetail> {
  return (await api.patch<StaffOrderDetail>(`/api/v1/manage/orders/${id}/`, changes)).data
}

export async function replanOrder(id: number): Promise<StaffOrderDetail> {
  return (await api.post<StaffOrderDetail>(`/api/v1/manage/orders/${id}/replan/`)).data
}

export async function assignLoad(orderId: number, loadId: number, truck: number | null): Promise<StaffOrderDetail> {
  return (await api.patch<StaffOrderDetail>(`/api/v1/manage/orders/${orderId}/loads/${loadId}/`, { truck })).data
}

export async function sendStaffMessage(id: number, body: string): Promise<OrderMessage> {
  return (await api.post<OrderMessage>(`/api/v1/manage/orders/${id}/messages/`, { body })).data
}

// --- Dispatch board -----------------------------------------------------------------

export async function fetchDispatchBoard(date: string): Promise<DispatchBoard> {
  return (await api.get<DispatchBoard>('/api/v1/manage/dispatch/', { params: { date } })).data
}

export async function setStock(id: number, inStock: boolean): Promise<void> {
  await api.patch(`/api/v1/manage/stock/${id}/`, { in_stock: inStock })
}

export async function setTruckActive(id: number, active: boolean): Promise<void> {
  await api.patch(`/api/v1/manage/trucks/${id}/`, { active })
}

export async function setTruckDayOff(id: number, date: string, off: boolean): Promise<void> {
  if (off) await api.post(`/api/v1/manage/trucks/${id}/days-off/`, { date })
  else await api.delete(`/api/v1/manage/trucks/${id}/days-off/`, { params: { date } })
}

// --- Live updates (polling) -------------------------------------------------------

export async function pollMyOrder(id: number, afterId: number): Promise<OrderUpdates> {
  return (await api.get<OrderUpdates>(`/api/v1/account/orders/${id}/updates/`, { params: { after: afterId } })).data
}

export async function pollStaffOrder(id: number, afterId: number): Promise<OrderUpdates> {
  return (await api.get<OrderUpdates>(`/api/v1/manage/orders/${id}/updates/`, { params: { after: afterId } })).data
}

// --- Invoices (staff) -------------------------------------------------------------

export async function fetchInvoice(id: number): Promise<Invoice> {
  return (await api.get<Invoice>(`/api/v1/manage/orders/${id}/invoice/`)).data
}

export async function previewInvoice(id: number, input: InvoiceInput): Promise<Invoice> {
  return (await api.post<Invoice>(`/api/v1/manage/orders/${id}/invoice/preview/`, input)).data
}

export async function saveInvoice(id: number, input: InvoiceInput): Promise<Invoice> {
  return (await api.put<Invoice>(`/api/v1/manage/orders/${id}/invoice/`, input)).data
}

export async function deleteInvoice(id: number): Promise<void> {
  await api.delete(`/api/v1/manage/orders/${id}/invoice/`)
}
