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

// Ordre protocolaire : Président, bureau (VP, Rapporteur, Rapporteur adjoint,
// Trésorier, Trésorier adjoint), autres membres, assistants. Classé sur le
// libellé et non sur le rang réglé dans l'unité : au Conseil, « Membre du
// conseil » portait le rang du Président et l'alphabet faisait passer les
// membres devant. Même règle côté API : app/utils/hierarchie_fonctions.py.
const cleLibelle = (libelle?: string | null) =>
  String(libelle || '')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '')

export function rangFonction(libelle?: string | null): number {
  const cle = cleLibelle(libelle)
  if (cle.includes('assistant')) return 9
  const adjoint = cle.includes('adjoint')
  if (cle.includes('vicepresident')) return 2
  if (cle.includes('president')) return 1
  if (cle.includes('rapporteu')) return adjoint ? 4 : 3
  if (cle.includes('tresori')) return adjoint ? 6 : 5
  return 7
}

// Un ordre fixé à la saisie (`ordre`) prime : le classement par libellé ne
// reconnaît pas toutes les fonctions (« Membre du bureau »…).
export function trierParHierarchie<T extends { nom?: string | null; titre_fonction?: string | null; type_participant?: string | null; ordre?: number | null }>(
  participants: T[],
): T[] {
  const sansOrdre = (p: T) => Number(p.ordre == null)
  return [...participants].sort(
    (a, b) =>
      Number(a.type_participant === 'assistant') - Number(b.type_participant === 'assistant') ||
      sansOrdre(a) - sansOrdre(b) ||
      (a.ordre ?? 0) - (b.ordre ?? 0) ||
      rangFonction(a.titre_fonction) - rangFonction(b.titre_fonction) ||
      cleLibelle(a.nom).localeCompare(cleLibelle(b.nom)),
  )
}

export function sortMemberFunctions(functions: ServiceMemberFunction[]): ServiceMemberFunction[] {
  return [...functions].sort((a, b) => {
    if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order
    return a.label.localeCompare(b.label, 'fr', { sensitivity: 'base' })
  })
}
