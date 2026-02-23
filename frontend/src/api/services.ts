import { apiRequest } from '../lib/apiClient'
import type { Service, ServiceConsumption } from '../types'

export function getServices(params?: { active?: boolean | null }) {
  return apiRequest<Service[]>('GET', '/services', { params })
}

export function getService(serviceId: number) {
  return apiRequest<Service>('GET', `/services/${serviceId}`)
}

export function getServiceConsumption(serviceId: number) {
  return apiRequest<ServiceConsumption>('GET', `/services/${serviceId}/consommation`)
}

export function createService(input: { code: string; libelle: string; is_active?: boolean }) {
  return apiRequest<Service>('POST', '/services', input)
}

export function updateService(serviceId: number, input: { code?: string; libelle?: string; is_active?: boolean }) {
  return apiRequest<Service>('PATCH', `/services/${serviceId}`, input)
}

export function getServiceRubriques(serviceId: number) {
  return apiRequest<{
    id: number
    code: string
    libelle: string
  }[]>('GET', `/services/${serviceId}/rubriques`)
}

export function updateServiceRubriques(serviceId: number, rubriqueIds: number[]) {
  return apiRequest<{ ok: boolean; rubrique_ids: number[] }>('POST', `/services/${serviceId}/rubriques`, {
    rubrique_ids: rubriqueIds,
  })
}

export function assignServiceResponsable(serviceId: number, userId: string | null) {
  return apiRequest<Service>('PUT', `/services/${serviceId}/responsable`, {
    user_id: userId,
  })
}
