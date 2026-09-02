export type Money = string | number | null | undefined

export function toNumber(value: Money): number {
  if (value === null || value === undefined || value === '') return 0
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  const normalized = String(value)
    .replace(/[\s\u00a0\u202f]/g, '')
    .replace(',', '.')
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : 0
}

/**
 * Remplace par une espace ordinaire les espaces insécables que produit
 * `Intl.NumberFormat('fr-FR')` comme séparateur de milliers : l'espace fine
 * insécable (U+202F, depuis ICU 72) est absente de l'encodage WinAnsi des
 * polices standard de jsPDF, et sort en caractère parasite dans les PDF.
 *
 * Tout montant destiné à un PDF doit passer par ici. Les échappements sont
 * écrits en `\u….` : ces caractères sont invisibles dans le source, et un
 * formateur ou un copier-coller qui les normaliserait casserait le correctif
 * sans que rien ne le signale.
 */
export function stripNarrowSpaces(text: string): string {
  return text.replace(/[\u00a0\u202f]/g, ' ')
}

/** Format utilisé par les documents PDF et les écrans qui affichent les montants. */
export function formatPdfAmount(value: Money, fractionDigits = 2): string {
  return stripNarrowSpaces(
    new Intl.NumberFormat('fr-FR', {
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(toNumber(value)),
  )
}

export const formatAmount = formatPdfAmount
