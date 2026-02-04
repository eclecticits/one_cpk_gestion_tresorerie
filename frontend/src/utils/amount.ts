export type Money = string | number | null | undefined

export function toNumber(value: Money): number {
  if (value === null || value === undefined || value === '') return 0
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0
  const normalized = String(value).replace(',', '.')
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : 0
}

export function formatAmount(value: Money, fractionDigits = 2): string {
  return toNumber(value).toFixed(fractionDigits)
}
