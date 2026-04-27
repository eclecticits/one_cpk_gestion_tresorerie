import { toNumber, type Money } from './amount'

export type BudgetDecisionLine = {
  budget_poste_id?: number | null
  budget_poste_code_snapshot?: string | null
  budget_poste_libelle_snapshot?: string | null
  rubrique?: string | null
  montant_total?: Money
  montant_alloue_snapshot?: Money | null
  montant_disponible_snapshot?: Money | null
}

export type BudgetDecisionSummary = {
  budget: number | null
  engaged: number | null
  available: number | null
  remainingAfterRequest: number | null
  requested: number
}

export function buildBudgetDecisionSummary(
  lines: BudgetDecisionLine[] = [],
  requestedAmount?: Money
): BudgetDecisionSummary {
  const uniqueSnapshots = new Map<
    string,
    { allocated?: Money | null; balance?: Money | null }
  >()

  lines.forEach((line) => {
    const key =
      line.budget_poste_id != null
        ? `id:${line.budget_poste_id}`
        : `snap:${line.budget_poste_code_snapshot || line.budget_poste_libelle_snapshot || line.rubrique || ''}`
    if (!uniqueSnapshots.has(key)) {
      uniqueSnapshots.set(key, {
        allocated: line.montant_alloue_snapshot,
        balance: line.montant_disponible_snapshot,
      })
    }
  })

  let budget = 0
  let available = 0
  let hasBudget = false
  let hasAvailable = false

  uniqueSnapshots.forEach((snapshot) => {
    if (snapshot.allocated !== null && snapshot.allocated !== undefined && String(snapshot.allocated).trim() !== '') {
      budget += toNumber(snapshot.allocated)
      hasBudget = true
    }
    if (snapshot.balance !== null && snapshot.balance !== undefined && String(snapshot.balance).trim() !== '') {
      available += toNumber(snapshot.balance)
      hasAvailable = true
    }
  })

  const requested =
    requestedAmount !== undefined
      ? toNumber(requestedAmount)
      : lines.reduce((sum, line) => sum + toNumber(line.montant_total), 0)

  const resolvedBudget = hasBudget ? budget : null
  const resolvedAvailable = hasAvailable ? available : null
  const engaged =
    resolvedBudget !== null && resolvedAvailable !== null
      ? Math.max(resolvedBudget - resolvedAvailable, 0)
      : null
  const remainingAfterRequest =
    resolvedAvailable !== null ? resolvedAvailable - requested : null

  return {
    budget: resolvedBudget,
    engaged,
    available: resolvedAvailable,
    remainingAfterRequest,
    requested,
  }
}

export function formatBudgetDecisionAmount(amount?: number | null): string {
  if (amount === null || amount === undefined) return 'Snapshot indisponible'
  return amount.toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })
}
