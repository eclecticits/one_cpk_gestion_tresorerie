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

export type BudgetDecisionRow = BudgetDecisionSummary & {
  key: string
  label: string
}

export type BudgetDecisionBreakdown = {
  rows: BudgetDecisionRow[]
  totals: BudgetDecisionSummary
}

function lineKey(line: BudgetDecisionLine): string {
  return line.budget_poste_id != null
    ? `id:${line.budget_poste_id}`
    : `snap:${line.budget_poste_code_snapshot || line.budget_poste_libelle_snapshot || line.rubrique || ''}`
}

function lineLabel(line: BudgetDecisionLine): string {
  const code = String(line.budget_poste_code_snapshot || '').trim()
  const libelle = String(line.budget_poste_libelle_snapshot || '').trim()
  if (code && libelle) return `${code} - ${libelle}`
  return code || libelle || String(line.rubrique || '').trim() || 'Poste non renseigné'
}

/**
 * Le même snapshot, poste par poste. Un total agrégé additionne des
 * enveloppes qui n'ont rien à voir entre elles : celui qui décide veut
 * savoir quelle ligne budgétaire porte la demande, et laquelle passe en
 * négatif. Les totaux restent en pied de tableau, identiques à
 * `buildBudgetDecisionSummary`.
 */
export function buildBudgetDecisionBreakdown(
  lines: BudgetDecisionLine[] = [],
  requestedAmount?: Money
): BudgetDecisionBreakdown {
  const grouped = new Map<string, BudgetDecisionLine[]>()

  lines.forEach((line) => {
    const key = lineKey(line)
    const bucket = grouped.get(key)
    if (bucket) bucket.push(line)
    else grouped.set(key, [line])
  })

  const rows: BudgetDecisionRow[] = []
  grouped.forEach((posteLines, key) => {
    // Pas de montant imposé ici : la demande d'un poste, c'est la somme de
    // ses propres lignes.
    rows.push({
      key,
      label: lineLabel(posteLines[0]),
      ...buildBudgetDecisionSummary(posteLines),
    })
  })

  return { rows, totals: buildBudgetDecisionSummary(lines, requestedAmount) }
}

export function formatBudgetDecisionAmount(amount?: number | null): string {
  if (amount === null || amount === undefined) return 'Snapshot indisponible'
  return amount.toLocaleString('fr-FR', { style: 'currency', currency: 'USD' })
}
