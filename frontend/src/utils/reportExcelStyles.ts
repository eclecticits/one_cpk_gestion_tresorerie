import type { CellObject, CellStyle, WorkSheet } from 'xlsx'

type XlsxModule = typeof import('xlsx')
type SheetValue = string | number | boolean | Date | null | undefined

export type SummaryTone = 'default' | 'positive' | 'negative' | 'accent' | 'warning'

export type ReportSummaryItem = {
  label: string
  value: SheetValue
  tone?: SummaryTone
  format?: 'text' | 'money' | 'integer'
}

const GREEN = '065F46'
const GREEN_DARK = '064E3B'
const GREEN_LIGHT = 'D1FAE5'
const TEAL_SOFT = 'CCFBF1'
const AMBER_SOFT = 'FEF3C7'
const RED_SOFT = 'FEE2E2'
const SLATE = '334155'
const SLATE_LIGHT = 'F8FAFC'
const RED = 'DC2626'
const AMBER = 'B45309'
const TEAL = '0F766E'
const BORDER = 'D1D5DB'
const WHITE = 'FFFFFF'
const MONEY_FORMAT = '#,##0.00;[Red]-#,##0.00'

const toneFills: Record<SummaryTone, string> = {
  default: SLATE_LIGHT,
  positive: GREEN_LIGHT,
  negative: RED_SOFT,
  accent: TEAL_SOFT,
  warning: AMBER_SOFT,
}

const toneValueColors: Record<SummaryTone, string> = {
  default: SLATE,
  positive: GREEN_DARK,
  negative: RED,
  accent: TEAL,
  warning: AMBER,
}

const thinBorder: NonNullable<CellStyle['border']> = {
  top: { style: 'thin', color: { rgb: BORDER } },
  bottom: { style: 'thin', color: { rgb: BORDER } },
  left: { style: 'thin', color: { rgb: BORDER } },
  right: { style: 'thin', color: { rgb: BORDER } },
}

const headerStyle: CellStyle = {
  font: { bold: true, color: { rgb: WHITE }, sz: 10 },
  fill: { patternType: 'solid', fgColor: { rgb: GREEN } },
  alignment: { horizontal: 'center', vertical: 'center', wrapText: true },
  border: thinBorder,
}

const bodyStyle: CellStyle = {
  font: { color: { rgb: SLATE }, sz: 10 },
  alignment: { vertical: 'center' },
  border: thinBorder,
}

const alternateBodyStyle: CellStyle = {
  ...bodyStyle,
  fill: { patternType: 'solid', fgColor: { rgb: SLATE_LIGHT } },
}

const totalStyle: CellStyle = {
  ...bodyStyle,
  font: { bold: true, color: { rgb: GREEN_DARK }, sz: 10 },
  fill: { patternType: 'solid', fgColor: { rgb: GREEN_LIGHT } },
}

const footerTotalStyle: CellStyle = {
  font: { bold: true, color: { rgb: WHITE }, sz: 10 },
  fill: { patternType: 'solid', fgColor: { rgb: GREEN_DARK } },
  alignment: { vertical: 'center', wrapText: true },
  border: thinBorder,
}

type RowStyleVariants = {
  text: CellStyle
  wrapped: CellStyle
  centered: CellStyle
  number: CellStyle
  money: CellStyle
}

function rowStyleVariants(base: CellStyle): RowStyleVariants {
  const rightAlignment: NonNullable<CellStyle['alignment']> = {
    ...base.alignment,
    horizontal: 'right',
  }
  return {
    text: base,
    wrapped: { ...base, alignment: { ...base.alignment, wrapText: true } },
    centered: { ...base, alignment: { ...base.alignment, horizontal: 'center' } },
    number: { ...base, alignment: rightAlignment },
    money: { ...base, alignment: rightAlignment, numFmt: MONEY_FORMAT },
  }
}

// Ces objets sont volontairement mutualisés. xlsx-js-style sérialise chaque
// nouvel objet de style ; en recréer un par cellule ferait exploser styles.xml
// sur un rapport de plusieurs milliers de lignes.
const bodyVariants = rowStyleVariants(bodyStyle)
const alternateBodyVariants = rowStyleVariants(alternateBodyStyle)
const totalVariants = rowStyleVariants(totalStyle)
const footerTotalVariants = rowStyleVariants(footerTotalStyle)
const highlightedBodyVariants = Object.fromEntries(
  Object.entries({
    positive: GREEN_LIGHT,
    negative: RED_SOFT,
    accent: TEAL_SOFT,
    warning: AMBER_SOFT,
  }).map(([tone, fill]) => [
    tone,
    rowStyleVariants({
      ...bodyStyle,
      font: { color: { rgb: toneValueColors[tone as Exclude<SummaryTone, 'default'>] }, sz: 10 },
      fill: { patternType: 'solid', fgColor: { rgb: fill } },
    }),
  ]),
) as Record<Exclude<SummaryTone, 'default'>, RowStyleVariants>

function ensureCell(sheet: WorkSheet, xlsx: XlsxModule, row: number, col: number): CellObject {
  const address = xlsx.utils.encode_cell({ r: row - 1, c: col - 1 })
  if (!sheet[address]) {
    sheet[address] = { t: 's', v: '' } as CellObject
  }
  return sheet[address] as CellObject
}

function applyRowStyle(
  sheet: WorkSheet,
  xlsx: XlsxModule,
  row: number,
  firstCol: number,
  lastCol: number,
  style: CellStyle,
) {
  for (let col = firstCol; col <= lastCol; col += 1) {
    ensureCell(sheet, xlsx, row, col).s = style
  }
}

function addMerge(sheet: WorkSheet, startRow: number, startCol: number, endRow: number, endCol: number) {
  sheet['!merges'] = [
    ...(sheet['!merges'] || []),
    { s: { r: startRow - 1, c: startCol - 1 }, e: { r: endRow - 1, c: endCol - 1 } },
  ]
}

function applyBanner(
  sheet: WorkSheet,
  xlsx: XlsxModule,
  lastCol: number,
) {
  const titleStyle: CellStyle = {
    font: { bold: true, color: { rgb: WHITE }, sz: 16 },
    fill: { patternType: 'solid', fgColor: { rgb: GREEN_DARK } },
    alignment: { horizontal: 'center', vertical: 'center' },
  }
  const organisationStyle: CellStyle = {
    font: { bold: true, color: { rgb: GREEN_DARK }, sz: 11 },
    alignment: { horizontal: 'center', vertical: 'center' },
  }
  const subtitleStyle: CellStyle = {
    font: { italic: true, color: { rgb: SLATE }, sz: 10 },
    alignment: { horizontal: 'center', vertical: 'center', wrapText: true },
  }

  applyRowStyle(sheet, xlsx, 1, 1, lastCol, titleStyle)
  applyRowStyle(sheet, xlsx, 2, 1, lastCol, organisationStyle)
  applyRowStyle(sheet, xlsx, 3, 1, lastCol, subtitleStyle)
  addMerge(sheet, 1, 1, 1, lastCol)
  addMerge(sheet, 2, 1, 2, lastCol)
  addMerge(sheet, 3, 1, 3, lastCol)
  sheet['!rows'] = [{ hpt: 28 }, { hpt: 20 }, { hpt: 24 }]
}

export type ReportListSheetOptions = {
  title: string
  organisation: string
  subtitle: string
  headers: string[]
  rows: SheetValue[][]
  widths: number[]
  moneyColumns?: number[]
  totalRowIndexes?: number[]
  summaryCards?: ReportSummaryItem[]
  footerRow?: SheetValue[]
  wrapColumns?: number[]
  centerColumns?: number[]
  rowTone?: (row: SheetValue[], rowIndex: number) => SummaryTone | undefined
  cellTone?: (value: SheetValue, rowIndex: number, columnIndex: number) => SummaryTone | undefined
}

const summaryLabelStyles = Object.fromEntries(
  Object.entries(toneFills).map(([tone, fill]) => [
    tone,
    {
      font: { bold: true, color: { rgb: SLATE }, sz: 9 },
      fill: { patternType: 'solid', fgColor: { rgb: fill } },
      alignment: { horizontal: 'center', vertical: 'center', wrapText: true },
      border: thinBorder,
    } satisfies CellStyle,
  ]),
) as Record<SummaryTone, CellStyle>

const summaryValueStyles = Object.fromEntries(
  Object.entries(toneFills).map(([tone, fill]) => {
    const base: CellStyle = {
      font: { bold: true, color: { rgb: toneValueColors[tone as SummaryTone] }, sz: 12 },
      fill: { patternType: 'solid', fgColor: { rgb: fill } },
      alignment: { horizontal: 'center', vertical: 'center', wrapText: true },
      border: thinBorder,
    }
    return [
      tone,
      {
        text: base,
        integer: { ...base, numFmt: '#,##0' },
        money: { ...base, numFmt: MONEY_FORMAT },
      },
    ]
  }),
) as Record<SummaryTone, Record<'text' | 'integer' | 'money', CellStyle>>

function cardBounds(index: number, count: number, lastCol: number) {
  return {
    start: Math.floor((index * lastCol) / count) + 1,
    end: Math.floor(((index + 1) * lastCol) / count),
  }
}

function cardRows(items: ReportSummaryItem[], lastCol: number): SheetValue[][] {
  const labels: SheetValue[] = Array(lastCol).fill('')
  const values: SheetValue[] = Array(lastCol).fill('')
  items.forEach((item, index) => {
    const { start } = cardBounds(index, items.length, lastCol)
    labels[start - 1] = item.label
    values[start - 1] = item.value
  })
  return [labels, values]
}

function styleCards(
  sheet: WorkSheet,
  xlsx: XlsxModule,
  items: ReportSummaryItem[],
  labelRow: number,
  lastCol: number,
) {
  items.forEach((item, index) => {
    const { start, end } = cardBounds(index, items.length, lastCol)
    const tone = item.tone || 'default'
    const format = item.format || 'text'
    applyRowStyle(sheet, xlsx, labelRow, start, end, summaryLabelStyles[tone])
    applyRowStyle(sheet, xlsx, labelRow + 1, start, end, summaryValueStyles[tone][format])
    addMerge(sheet, labelRow, start, labelRow, end)
    addMerge(sheet, labelRow + 1, start, labelRow + 1, end)
  })
  sheet['!rows']![labelRow - 1] = { hpt: 20 }
  sheet['!rows']![labelRow] = { hpt: 27 }
}

function applySheetLayout(sheet: WorkSheet) {
  sheet['!margins'] = {
    left: 0.35,
    right: 0.35,
    top: 0.5,
    bottom: 0.5,
    header: 0.2,
    footer: 0.2,
  }
}

/** Construit une feuille de liste conforme à la charte des exports backend. */
export function createReportListSheet(
  xlsx: XlsxModule,
  options: ReportListSheetOptions,
): WorkSheet {
  const { title, organisation, subtitle, headers, rows, widths } = options
  const lastCol = Math.max(headers.length, 1)
  const cards = (options.summaryCards || []).slice(0, Math.min(5, lastCol))
  const hasCards = cards.length > 0
  const headerRow = hasCards ? 7 : 4
  const content: SheetValue[][] = [
    [title],
    [organisation],
    [subtitle],
  ]
  if (hasCards) content.push(...cardRows(cards, lastCol), [])
  content.push(headers, ...rows)
  if (options.footerRow) content.push(options.footerRow)

  const sheet = xlsx.utils.aoa_to_sheet(content)
  const firstDataRow = headerRow + 1
  const lastDataRow = rows.length ? firstDataRow + rows.length - 1 : headerRow
  const footerRow = options.footerRow ? lastDataRow + 1 : null
  const moneyColumns = new Set(options.moneyColumns || [])
  const totalRows = new Set(options.totalRowIndexes || [])
  const wrapColumns = new Set(options.wrapColumns || [])
  const centerColumns = new Set(options.centerColumns || [])

  applyBanner(sheet, xlsx, lastCol)
  if (hasCards) styleCards(sheet, xlsx, cards, 4, lastCol)
  applyRowStyle(sheet, xlsx, headerRow, 1, lastCol, headerStyle)
  sheet['!rows']![headerRow - 1] = { hpt: 25 }

  rows.forEach((rowValues, rowIndex) => {
    const excelRow = firstDataRow + rowIndex
    const rowTone = options.rowTone?.(rowValues, rowIndex)
    const rowVariants = rowTone && rowTone !== 'default'
      ? highlightedBodyVariants[rowTone]
      : totalRows.has(rowIndex)
      ? totalVariants
      : rowIndex % 2 === 1
        ? alternateBodyVariants
        : bodyVariants

    for (let col = 1; col <= lastCol; col += 1) {
      const cell = ensureCell(sheet, xlsx, excelRow, col)
      const columnIndex = col - 1
      const cellTone = options.cellTone?.(rowValues[columnIndex], rowIndex, columnIndex)
      const variants = cellTone && cellTone !== 'default'
        ? highlightedBodyVariants[cellTone]
        : rowVariants
      cell.s = moneyColumns.has(columnIndex)
        ? variants.money
        : cell.t === 'n'
          ? variants.number
          : centerColumns.has(columnIndex)
            ? variants.centered
            : wrapColumns.has(columnIndex)
              ? variants.wrapped
              : variants.text
    }
  })

  if (footerRow) {
    for (let col = 1; col <= lastCol; col += 1) {
      const cell = ensureCell(sheet, xlsx, footerRow, col)
      const isMoney = moneyColumns.has(col - 1)
      cell.s = isMoney
        ? footerTotalVariants.money
        : cell.t === 'n'
          ? footerTotalVariants.number
          : footerTotalVariants.text
    }
    sheet['!rows']![footerRow - 1] = { hpt: 24 }
  }

  sheet['!cols'] = headers.map((_, index) => ({ wch: widths[index] || 18 }))
  sheet['!autofilter'] = {
    ref: `${xlsx.utils.encode_cell({ r: headerRow - 1, c: 0 })}:${xlsx.utils.encode_cell({ r: lastDataRow - 1, c: lastCol - 1 })}`,
  }
  applySheetLayout(sheet)
  return sheet
}

export type ReportSummarySheetOptions = {
  title: string
  organisation: string
  subtitle: string
  items: ReportSummaryItem[]
  detailTitle?: string
  detailHeaders?: string[]
  detailRows?: SheetValue[][]
  detailMoneyColumns?: number[]
  detailWidths?: number[]
  detailCenterColumns?: number[]
  detailCellTone?: (value: SheetValue, rowIndex: number, columnIndex: number) => SummaryTone | undefined
  notice?: string
}

/** Feuille de synthèse : cartes de chiffres clés, puis tableau par devise. */
export function createReportSummarySheet(
  xlsx: XlsxModule,
  options: ReportSummarySheetOptions,
): WorkSheet {
  const detailHeaders = options.detailHeaders || []
  const detailRows = options.detailRows || []
  const hasDetails = detailHeaders.length > 0
  const tableCols = Math.max(detailHeaders.length, 1)
  const lastCol = Math.max(tableCols, 14)
  const cardGroups: ReportSummaryItem[][] = []
  for (let index = 0; index < options.items.length; index += 7) {
    cardGroups.push(options.items.slice(index, index + 7))
  }
  const data: SheetValue[][] = [
    [options.title],
    [options.organisation],
    [options.subtitle],
  ]
  cardGroups.forEach((group) => data.push(...cardRows(group, lastCol), []))

  let noticeRow: number | null = null
  if (options.notice) {
    noticeRow = data.length + 1
    data.push([options.notice], [])
  }

  let detailTitleRow: number | null = null
  if (hasDetails) {
    detailTitleRow = data.length + 1
    data.push([options.detailTitle || 'DÉTAIL'], detailHeaders, ...detailRows)
  }

  const sheet = xlsx.utils.aoa_to_sheet(data)
  applyBanner(sheet, xlsx, lastCol)
  cardGroups.forEach((group, index) => styleCards(sheet, xlsx, group, 4 + index * 3, lastCol))

  const sectionStyle: CellStyle = {
    font: { bold: true, color: { rgb: WHITE }, sz: 11 },
    fill: { patternType: 'solid', fgColor: { rgb: GREEN } },
    alignment: { horizontal: 'left', vertical: 'center' },
    border: thinBorder,
  }

  if (noticeRow) {
    const noticeStyle: CellStyle = {
      font: { bold: true, italic: true, color: { rgb: AMBER }, sz: 10 },
      fill: { patternType: 'solid', fgColor: { rgb: AMBER_SOFT } },
      alignment: { horizontal: 'center', vertical: 'center', wrapText: true },
      border: thinBorder,
    }
    applyRowStyle(sheet, xlsx, noticeRow, 1, lastCol, noticeStyle)
    addMerge(sheet, noticeRow, 1, noticeRow, lastCol)
    sheet['!rows']![noticeRow - 1] = { hpt: 25 }
  }

  if (detailTitleRow) {
    const detailHeaderRow = detailTitleRow + 1
    const firstDetailRow = detailHeaderRow + 1
    const moneyColumns = new Set(options.detailMoneyColumns || [])
    const centerColumns = new Set(options.detailCenterColumns || [])

    applyRowStyle(sheet, xlsx, detailTitleRow, 1, lastCol, sectionStyle)
    addMerge(sheet, detailTitleRow, 1, detailTitleRow, lastCol)
    applyRowStyle(sheet, xlsx, detailHeaderRow, 1, tableCols, headerStyle)
    sheet['!rows']![detailTitleRow - 1] = { hpt: 21 }
    sheet['!rows']![detailHeaderRow - 1] = { hpt: 25 }

    detailRows.forEach((_, rowIndex) => {
      const row = firstDetailRow + rowIndex
      const rowVariants = rowIndex % 2 === 1 ? alternateBodyVariants : bodyVariants
      for (let col = 1; col <= tableCols; col += 1) {
        const cell = ensureCell(sheet, xlsx, row, col)
        const columnIndex = col - 1
        const cellTone = options.detailCellTone?.(detailRows[rowIndex]?.[columnIndex], rowIndex, columnIndex)
        const variants = cellTone && cellTone !== 'default'
          ? highlightedBodyVariants[cellTone]
          : rowVariants
        cell.s = moneyColumns.has(columnIndex)
          ? variants.money
          : centerColumns.has(columnIndex)
            ? variants.centered
            : cell.t === 'n'
              ? variants.number
              : variants.text
      }
    })
    sheet['!autofilter'] = {
      ref: `${xlsx.utils.encode_cell({ r: detailHeaderRow - 1, c: 0 })}:${xlsx.utils.encode_cell({
        r: Math.max(detailHeaderRow, firstDetailRow + detailRows.length - 1) - 1,
        c: tableCols - 1,
      })}`,
    }
  }

  const defaultWidths = [14, 18, 20, 24, 22, 18, 22, 18, 18, 20, 18]
  sheet['!cols'] = Array.from({ length: lastCol }, (_, index) => ({
    wch: index < tableCols ? options.detailWidths?.[index] || defaultWidths[index] || 18 : 3,
  }))
  applySheetLayout(sheet)
  return sheet
}
