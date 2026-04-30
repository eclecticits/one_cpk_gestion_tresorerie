import type { CommissionMember, CommissionRole, ServiceMemberFunction } from '../types'

export const DEFAULT_MEMBER_FUNCTION_LABELS = [
  'Président(e)',
  'Vice-président(e)',
  'Rapporteur',
  'Rapporteur adjoint',
  'Trésorier',
  'Trésorier(e) adjoint',
  'Secrétaire exécutif',
  'Assistant(e)',
  'Autre',
]

const leadershipSet = new Set(DEFAULT_MEMBER_FUNCTION_LABELS.slice(0, 7).map((label) => label.toLowerCase()))

export function resolveMemberFunctionLabel(member: Pick<CommissionMember, 'function_label' | 'function' | 'role_type'>): string {
  const directLabel = String(member.function_label || member.function?.label || '').trim()
  if (directLabel) return directLabel
  return roleLabel(member.role_type)
}

export function roleLabel(role?: CommissionRole | null): string {
  if (role === 'PRESIDENT') return 'Président(e)'
  if (role === 'DELEGUE') return 'Vice-président(e)'
  if (role === 'ASSISTANT') return 'Assistant(e)'
  return 'Autre'
}

export function isAssistantMember(member: Pick<CommissionMember, 'function_label' | 'function' | 'role_type'>): boolean {
  const label = resolveMemberFunctionLabel(member).toLowerCase()
  return label.includes('assistant') || member.role_type === 'ASSISTANT'
}

export function isLeadershipMember(member: Pick<CommissionMember, 'function_label' | 'function' | 'role_type'>): boolean {
  const label = resolveMemberFunctionLabel(member).toLowerCase()
  return leadershipSet.has(label) || member.role_type === 'PRESIDENT' || member.role_type === 'DELEGUE'
}

export function sortMemberFunctions(functions: ServiceMemberFunction[]): ServiceMemberFunction[] {
  return [...functions].sort((a, b) => {
    if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order
    return a.label.localeCompare(b.label, 'fr', { sensitivity: 'base' })
  })
}
