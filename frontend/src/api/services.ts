import { apiRequest } from '../lib/apiClient'
import type { CommissionMember, Service, ServiceConsumption, ServiceMemberFunction } from '../types'

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

export function updateServiceRubriques(serviceId: number, rubriqueIds: number[], force = false) {
  return apiRequest<{ ok: boolean; rubrique_ids: number[] }>('POST', `/services/${serviceId}/rubriques`, {
    rubrique_ids: rubriqueIds,
    force,
  })
}

export function getServiceRubriquesUsage(serviceId: number) {
  return apiRequest<{ used: number[]; en_cours: number[] }>(
    'GET',
    `/services/${serviceId}/rubriques/usage`,
  )
}

export function assignServiceResponsable(serviceId: number, userId: string | null) {
  return apiRequest<Service>('PUT', `/services/${serviceId}/responsable`, {
    user_id: userId,
  })
}

export function getServiceMembers(serviceId: number) {
  return apiRequest<CommissionMember[]>('GET', `/services/${serviceId}/members`)
}

export function getServiceMemberFunctions(serviceId: number, params?: { active?: boolean | null }) {
  return apiRequest<ServiceMemberFunction[]>('GET', `/services/${serviceId}/member-functions`, { params })
}

export function createServiceMemberFunction(serviceId: number, input: {
  label: string
  sort_order?: number | null
  is_active?: boolean | null
}) {
  return apiRequest<ServiceMemberFunction>('POST', `/services/${serviceId}/member-functions`, input)
}

export function updateServiceMemberFunction(
  serviceId: number,
  functionId: number,
  input: {
    label?: string | null
    sort_order?: number | null
    is_active?: boolean | null
  }
) {
  return apiRequest<ServiceMemberFunction>('PATCH', `/services/${serviceId}/member-functions/${functionId}`, input)
}

export function deleteServiceMemberFunction(serviceId: number, functionId: number) {
  return apiRequest<void>('DELETE', `/services/${serviceId}/member-functions/${functionId}`)
}

export function createServiceMember(
  serviceId: number,
  input: {
    user_id?: string | null
    full_name?: string | null
    email?: string | null
    matricule?: string | null
    function_id?: number | null
    function_label?: string | null
    role_type?: 'PRESIDENT' | 'DELEGUE' | 'MEMBRE' | 'ASSISTANT'
    custom_title?: string | null
    is_signer?: boolean | null
  }
) {
  return apiRequest<CommissionMember>('POST', `/services/${serviceId}/members`, input)
}

export function updateServiceMember(
  serviceId: number,
  memberId: number,
  input: {
    user_id?: string | null
    full_name?: string | null
    email?: string | null
    matricule?: string | null
    function_id?: number | null
    function_label?: string | null
    role_type?: 'PRESIDENT' | 'DELEGUE' | 'MEMBRE' | 'ASSISTANT'
    custom_title?: string | null
    is_signer?: boolean | null
  }
) {
  return apiRequest<CommissionMember>('PATCH', `/services/${serviceId}/members/${memberId}`, input)
}

export function deleteServiceMember(serviceId: number, memberId: number) {
  return apiRequest<void>('DELETE', `/services/${serviceId}/members/${memberId}`)
}

export function lookupCommissionMembers(query: string) {
  return apiRequest<{ full_name: string; email?: string | null; matricule?: string | null }[]>(
    'GET',
    '/services/members/lookup',
    { params: { q: query } }
  )
}

export function multiAssignCommissionMember(input: {
  service_ids: number[]
  user_id?: string | null
  full_name?: string | null
  email?: string | null
  matricule?: string | null
  function_id?: number | null
  function_label?: string | null
  role_type?: 'PRESIDENT' | 'DELEGUE' | 'MEMBRE' | 'ASSISTANT'
  custom_title?: string | null
  is_signer?: boolean | null
}) {
  return apiRequest<CommissionMember[]>('POST', '/services/members/assign', input)
}
