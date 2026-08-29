/** Normalisation d'un code de poste budgétaire.
 *
 *  Partagée entre l'écran Budget et les générateurs de documents : c'est cette
 *  clé qui relie un commentaire à sa ligne. Deux normalisations légèrement
 *  différentes de part et d'autre (une casse, un point de trop) ne provoquent
 *  aucune erreur — elles font simplement disparaître tous les commentaires du
 *  document exporté, en silence. D'où l'unique implémentation.
 *
 *  Mêmes règles que `_normalize_budget_code` côté API, plus la casse repliée :
 *  « I.7.1 » et « i.7.1 » désignent le même poste.
 */
export const normalizeBudgetCode = (value?: string | null): string => {
  if (!value) return ''
  return value
    .trim()
    .replace(/\s+/g, '')
    .replace(/\.+/g, '.')
    .replace(/^\.+|\.+$/g, '')
    .toLowerCase()
}

const romanValues: Record<string, number> = {
  I: 1,
  V: 5,
  X: 10,
  L: 50,
  C: 100,
  D: 500,
  M: 1000,
}

const romanToNumber = (value: string): number | null => {
  if (!value) return null
  let total = 0
  let previous = 0
  for (const char of value.toUpperCase().split('').reverse()) {
    const current = romanValues[char]
    if (!current) return null
    if (current < previous) total -= current
    else {
      total += current
      previous = current
    }
  }
  return total
}

type BudgetCodePart = [number, number | string]

export const budgetCodeSortKey = (value?: string | null): BudgetCodePart[] => {
  const code = normalizeBudgetCode(value)
  if (!code) return []
  return code.split('.').map((part) => {
    if (/^\d+$/.test(part)) return [0, Number(part)]
    const roman = romanToNumber(part)
    if (roman !== null) return [1, roman]
    return [2, part]
  })
}

export const compareBudgetCodes = (a?: string | null, b?: string | null): number => {
  const left = budgetCodeSortKey(a)
  const right = budgetCodeSortKey(b)
  const max = Math.max(left.length, right.length)
  for (let i = 0; i < max; i += 1) {
    const l = left[i]
    const r = right[i]
    if (!l) return -1
    if (!r) return 1
    if (l[0] !== r[0]) return l[0] - r[0]
    if (l[1] < r[1]) return -1
    if (l[1] > r[1]) return 1
  }
  return 0
}
