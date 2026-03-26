export const getContrastColor = (hexColor: string): string => {
  const normalized = hexColor.startsWith('#') ? hexColor : `#${hexColor}`
  if (normalized.length !== 7) {
    return '#ffffff'
  }
  const r = parseInt(normalized.substring(1, 3), 16)
  const g = parseInt(normalized.substring(3, 5), 16)
  const b = parseInt(normalized.substring(5, 7), 16)
  const yiq = (r * 299 + g * 587 + b * 114) / 1000
  return yiq >= 128 ? '#000000' : '#ffffff'
}
