import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { API_BASE_URL, getAuthHeaders } from '../lib/apiClient'
import { formatAmount, toNumber } from './amount'
import { buildUploadUrl } from './uploads'
import { getTenantRequestHint } from './tenant'
import { getStatusMeta } from './statusMapper'

// ============================================================================
//  RAPPORTS DE LISTE (famille visuelle du rapport budgétaire generateBudgetPDF)
//  A4 · en-tête identité ONEC + logo · palette vert ONEC · table jspdf-autotable
//  (en-tête vert, lignes zébrées, montants alignés) · bloc de synthèse · pied de
//  page avec numéro de page + date de génération.
// ============================================================================

const ONEC_GREEN = '#065f46'
const ONEC_LIGHT_GREEN = '#ecfdf5'
const ONEC_GREEN_RGB: [number, number, number] = [6, 95, 70]
const DEFAULT_ORG_NAME = 'ORDRE NATIONAL DES EXPERTS-COMPTABLES'
const DEFAULT_TENANT_NAME = 'Antenne Provinciale'
const DEFAULT_SUBTITLE = "Plateforme intelligente de gestion intégrée de l'ONEC-RDC"

// --- Cache des réglages d'impression / logo (identique au système de rapports) ---
let cachedSettings: any | null = null
let cachedLogoDataUrl: string | null = null
let cachedLogoUrl: string | null = null
let cachedTenantHint: string | null = null

const resetPrintAssetCache = () => {
  cachedSettings = null
  cachedLogoDataUrl = null
  cachedLogoUrl = null
}

const ensureTenantScopedPrintCache = () => {
  const tenantHint = getTenantRequestHint()
  if (tenantHint !== cachedTenantHint) {
    cachedTenantHint = tenantHint
    resetPrintAssetCache()
  }
}

const getPrintSettingsData = async () => {
  ensureTenantScopedPrintCache()
  if (cachedSettings) return cachedSettings
  try {
    const settingsRes = await fetch(`${API_BASE_URL}/print-settings`, {
      headers: getAuthHeaders(),
      credentials: 'include',
    })
    if (!settingsRes.ok) return null
    cachedSettings = await settingsRes.json()
    return cachedSettings
  } catch {
    return null
  }
}

const getLogoDataUrl = async () => {
  ensureTenantScopedPrintCache()
  if (cachedLogoDataUrl) return cachedLogoDataUrl
  try {
    const settings = await getPrintSettingsData()
    cachedLogoUrl = settings?.logo_url || null
    const logoPath = cachedLogoUrl ? buildUploadUrl(cachedLogoUrl) : '/imge_onec.png'
    const res = await fetch(logoPath, {
      headers: getAuthHeaders(),
      credentials: 'include',
    })
    if (!res.ok) return null
    const blob = await res.blob()
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onloadend = () => resolve(String(reader.result || ''))
      reader.onerror = reject
      reader.readAsDataURL(blob)
    })
    cachedLogoDataUrl = dataUrl
    return cachedLogoDataUrl
  } catch {
    return null
  }
}

const getReportLabel = (label: string, tenantName?: string | null) =>
  tenantName ? `${label} - ${tenantName}` : label

const formatReportDate = (value: any): string => {
  if (!value) return '—'
  const raw = String(value)
  const parsed = raw.length <= 10 ? new Date(`${raw}T00:00:00`) : new Date(raw)
  if (Number.isNaN(parsed.getTime())) return '—'
  return format(parsed, 'dd/MM/yyyy')
}

// ============================================================================
//  TYPES PUBLICS
// ============================================================================

export type ReportOutput = 'download' | 'blob'

export interface ReportFilter {
  label: string
  value: string
}

export interface ReportOptions {
  dateDebut?: string | null
  dateFin?: string | null
  filters?: (ReportFilter | null | undefined | false)[]
  output?: ReportOutput
  fileName?: string
}

export interface ReportColumn {
  header: string
  width?: number
  halign?: 'left' | 'right' | 'center'
}

export interface SummaryCard {
  label: string
  value: string
}

export interface BuildListReportParams {
  title: string
  footerLabel: string
  columns: ReportColumn[]
  rows: (string | number)[][]
  footRow?: string[]
  summary: SummaryCard[]
  options: ReportOptions
  fileNameBase: string
}

// ============================================================================
//  MOTEUR DE RENDU PARTAGÉ
// ============================================================================

export const buildListReport = async ({
  title,
  footerLabel,
  columns,
  rows,
  footRow,
  summary,
  options,
  fileNameBase,
}: BuildListReportParams): Promise<Blob | null> => {
  const settings = await getPrintSettingsData()
  const logoDataUrl = settings?.show_header_logo === false ? null : await getLogoDataUrl()

  const doc = new jsPDF({ orientation: 'l', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const marginX = 10
  const contentW = pageWidth - marginX * 2
  const orgName = settings?.organization_name || DEFAULT_TENANT_NAME
  const subtitle = settings?.organization_subtitle || DEFAULT_SUBTITLE

  const addHeader = () => {
    if (logoDataUrl) {
      doc.addImage(logoDataUrl, 'PNG', marginX, 8, 22, 22)
    }

    doc.setFontSize(16)
    doc.setTextColor(ONEC_GREEN)
    doc.setFont('helvetica', 'bold')
    doc.text(DEFAULT_ORG_NAME, pageWidth / 2, 14, { align: 'center' })

    doc.setFontSize(13)
    doc.setTextColor(0, 0, 0)
    doc.setFont('times', 'bolditalic')
    doc.text(String(orgName), pageWidth / 2, 21, { align: 'center' })

    doc.setFontSize(10)
    doc.setTextColor(0, 0, 0)
    doc.setFont('helvetica', 'normal')
    doc.text(String(subtitle), pageWidth / 2, 27, { align: 'center' })

    // Date de génération (discrète, au-dessus du filet)
    doc.setFontSize(8)
    doc.setTextColor(120)
    doc.setFont('helvetica', 'normal')
    doc.text(`Généré le ${format(new Date(), 'dd/MM/yyyy HH:mm')}`, pageWidth - marginX, 31.5, {
      align: 'right',
    })

    doc.setDrawColor(ONEC_GREEN)
    doc.setLineWidth(2.5)
    doc.line(marginX, 33, pageWidth - marginX, 33)
  }

  const addFooter = (pageNumber: number) => {
    doc.setFontSize(8)
    doc.setTextColor(100)
    doc.setFont('helvetica', 'normal')
    doc.text(`${format(new Date(), 'dd/MM/yyyy HH:mm')}`, marginX, pageHeight - 8)
    doc.text(getReportLabel(footerLabel, settings?.organization_name), pageWidth / 2, pageHeight - 8, {
      align: 'center',
    })
    doc.text(`Page ${pageNumber}`, pageWidth - 20, pageHeight - 8)
  }

  addHeader()

  // --- Titre du rapport ---
  doc.setFontSize(15)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text(title, pageWidth / 2, 41, { align: 'center' })

  // --- Période ---
  let subY = 47
  doc.setFontSize(9.5)
  doc.setTextColor(0)
  doc.setFont('helvetica', 'normal')
  if (options.dateDebut || options.dateFin) {
    doc.text(
      `Période du ${formatReportDate(options.dateDebut)} au ${formatReportDate(options.dateFin)}`,
      pageWidth / 2,
      subY,
      { align: 'center' }
    )
    subY += 5
  }

  // --- Filtres actifs ---
  const activeFilters = (options.filters || []).filter(
    (f): f is ReportFilter => Boolean(f) && Boolean((f as ReportFilter).value)
  )
  if (activeFilters.length > 0) {
    const filtersText = activeFilters.map((f) => `${f.label} : ${f.value}`).join('   ·   ')
    doc.setFontSize(8.5)
    doc.setTextColor(90)
    const filterLines = doc.splitTextToSize(filtersText, contentW)
    doc.text(filterLines, pageWidth / 2, subY, { align: 'center' })
    subY += filterLines.length * 4 + 1
  }

  const startY = subY + 2

  // --- Table principale ---
  // Colonne « N° » séquentielle en tête (référencer chaque ligne du rapport) ;
  // les numéros métiers (réquisition, note de débit, ordre EC…) restent dans leurs colonnes.
  const numberedColumns: ReportColumn[] = [{ header: 'N°', width: 12, halign: 'center' }, ...columns]
  const numberedRows: (string | number)[][] = rows.map((r, i) => [i + 1, ...r])
  const numberedFoot: string[] | undefined = footRow ? ['', ...footRow] : undefined

  const columnStyles: Record<number, any> = {}
  numberedColumns.forEach((col, index) => {
    columnStyles[index] = {}
    if (col.width) columnStyles[index].cellWidth = col.width
    if (col.halign) columnStyles[index].halign = col.halign
  })

  const statutColIndex = numberedColumns.findIndex((c) => c.header.toLowerCase().includes('statut'))
  const bodyRows = numberedRows.length > 0 ? numberedRows : [numberedColumns.map(() => '—')]

  autoTable(doc, {
    head: [numberedColumns.map((c) => c.header)],
    body: bodyRows,
    foot: numberedFoot ? [numberedFoot] : undefined,
    startY,
    theme: 'grid',
    margin: { left: marginX, right: marginX, bottom: 16 },
    styles: {
      overflow: 'linebreak',
      cellPadding: 2.5,
      lineColor: [222, 226, 230],
      lineWidth: 0.2,
    },
    headStyles: {
      fillColor: ONEC_GREEN,
      textColor: 255,
      fontStyle: 'bold',
      fontSize: 8.5,
      halign: 'left',
    },
    bodyStyles: {
      fontSize: 8,
      textColor: [40, 40, 40],
    },
    footStyles: {
      fillColor: ONEC_LIGHT_GREEN,
      textColor: ONEC_GREEN_RGB,
      fontStyle: 'bold',
      fontSize: 8.5,
    },
    alternateRowStyles: {
      fillColor: [245, 245, 245],
    },
    columnStyles,
    didParseCell: (data: any) => {
      if (data.section !== 'body' || statutColIndex < 0 || data.column.index !== statutColIndex) return
      const value = String(data.cell.raw || '').toLowerCase()
      if (value.includes('annul') || value.includes('rejet') || value.includes('non pay')) {
        data.cell.styles.fillColor = [254, 226, 226]
        data.cell.styles.textColor = [153, 27, 27]
      } else if (
        value.includes('pay') ||
        value.includes('valid') ||
        value.includes('complet')
      ) {
        data.cell.styles.fillColor = [220, 252, 231]
        data.cell.styles.textColor = [22, 101, 52]
      } else if (value.includes('partiel') || value.includes('avance') || value.includes('attente')) {
        data.cell.styles.fillColor = [255, 247, 237]
        data.cell.styles.textColor = [154, 52, 18]
      }
    },
    didDrawPage: () => {
      addFooter(doc.getNumberOfPages())
    },
  })

  // --- Bloc de synthèse (cartes KPI dans la palette ONEC) ---
  const summaryHeight = 18
  const bandHeight = 8
  let y = ((doc as any).lastAutoTable?.finalY ?? startY) + 8
  if (y + bandHeight + summaryHeight + 6 > pageHeight - 14) {
    doc.addPage()
    addFooter(doc.getNumberOfPages())
    y = 18
  }

  doc.setFillColor(ONEC_GREEN)
  doc.rect(marginX, y, contentW, bandHeight, 'F')
  doc.setFontSize(10.5)
  doc.setTextColor(255)
  doc.setFont('helvetica', 'bold')
  doc.text('SYNTHÈSE', marginX + 4, y + 5.6)
  y += bandHeight + 5

  const cards = summary.slice(0, 4)
  if (cards.length > 0) {
    const gap = 4
    const cardW = (contentW - gap * (cards.length - 1)) / cards.length
    cards.forEach((card, i) => {
      const cx = marginX + i * (cardW + gap)
      doc.setDrawColor(ONEC_GREEN)
      doc.setFillColor(ONEC_LIGHT_GREEN)
      doc.roundedRect(cx, y, cardW, summaryHeight, 2, 2, 'FD')
      doc.setFontSize(7.5)
      doc.setTextColor(90)
      doc.setFont('helvetica', 'normal')
      doc.text(card.label.toUpperCase(), cx + 3, y + 6)
      doc.setFontSize(12)
      doc.setTextColor(ONEC_GREEN)
      doc.setFont('helvetica', 'bold')
      doc.text(card.value, cx + 3, y + 14)
    })
  }

  const fileName = options.fileName || `${fileNameBase}.pdf`
  if (options.output === 'blob') {
    return doc.output('blob')
  }
  doc.save(fileName)
  return null
}

// ============================================================================
//  HELPERS DE FORMATAGE COMMUNS
// ============================================================================

const usd = (value: any) => `${formatAmount(value)} $`

const buildFileSuffix = (options: ReportOptions) => {
  const debut = options.dateDebut ? String(options.dateDebut).slice(0, 10) : 'debut'
  const fin = options.dateFin ? String(options.dateFin).slice(0, 10) : 'fin'
  return `${debut}_${fin}`
}

const sortieTypeLabel = (value: string): string => {
  switch (value) {
    case 'requisition':
      return 'Réquisition'
    case 'remboursement':
      return 'Remboursement'
    case 'versement_banque':
      return 'Versement banque'
    case 'approvisionnement_caisse':
      return 'Approvisionnement'
    case 'sortie_directe':
      return 'Sortie directe'
    default:
      return value || '—'
  }
}

const modePaiementLabel = (value: string): string => {
  if (value === 'cash') return 'Cash'
  if (value === 'mobile_money') return 'Mobile Money'
  if (value === 'card') return 'Carte (Visa)'
  if (value === 'virement' || value === 'bank_transfer') return 'Opération bancaire'
  return value || '—'
}

const sortieStatutLabel = (value: string): string => {
  const statut = String(value || 'VALIDE').toUpperCase()
  if (statut === 'ANNULEE') return 'Annulée'
  if (statut === 'REMBOURSEE') return 'Remboursée'
  return 'Validée'
}

const resolvePosteLabel = (row: any): string => {
  if (row?.budget_poste_code && row?.budget_poste_libelle) {
    return `${row.budget_poste_code} - ${row.budget_poste_libelle}`
  }
  if (row?.budget_poste_libelle) return String(row.budget_poste_libelle)
  if (row?.rubrique) return String(row.rubrique)
  if (row?.rubrique_code) return String(row.rubrique_code)
  return '—'
}

// ============================================================================
//  1) RAPPORT DES SORTIES DE FONDS
// ============================================================================

export const generateSortiesReportPDF = async (
  rows: any[],
  options: ReportOptions & { retours?: any[] } = {}
): Promise<Blob | null> => {
  const list = Array.isArray(rows) ? rows : []
  const retours: any[] = Array.isArray((options as any).retours) ? (options as any).retours : []
  const columns: ReportColumn[] = [
    { header: 'Date', width: 20 },
    { header: 'Type', width: 24 },
    { header: 'Référence', width: 30 },
    { header: 'Bénéficiaire', width: 40 },
    { header: 'Motif / Objet', width: 45 },
    { header: 'Poste budgétaire', width: 40 },
    { header: 'Mode', width: 26 },
    { header: 'Montant payé', width: 26, halign: 'right' },
    { header: 'Statut', width: 26, halign: 'center' },
  ]

  const sortieEntries = list.map((s) => {
    const typeSortie = s?.type_sortie || 'requisition'
    const isReq = typeSortie === 'requisition'
    const reference = isReq
      ? s?.requisition?.numero_requisition || s?.reference_numero || s?.reference || '—'
      : s?.reference_numero || s?.reference || '—'
    const beneficiaire = s?.beneficiaire || (isReq ? s?.requisition?.objet : '') || '—'
    const motif = isReq ? s?.requisition?.objet || s?.motif || '—' : s?.motif || '—'
    return {
      key: new Date(s?.date_paiement || s?.created_at || 0).getTime(),
      montant: toNumber(s?.montant_paye || 0),
      row: [
        formatReportDate(s?.date_paiement),
        sortieTypeLabel(typeSortie),
        String(reference),
        String(beneficiaire),
        String(motif),
        resolvePosteLabel(s),
        modePaiementLabel(s?.mode_paiement),
        usd(s?.montant_paye),
        sortieStatutLabel(s?.statut),
      ] as (string | number)[],
    }
  })

  // Retours en caisse : lignes à montant NÉGATIF, mêlées aux sorties et triées
  // par date. Le total de la colonne devient net (sorties − retours).
  const retourEntries = retours.map((r) => {
    const montant = -toNumber(r?.montant || 0)
    return {
      key: new Date(r?.date_retour || r?.created_at || 0).getTime(),
      montant,
      row: [
        formatReportDate(r?.date_retour),
        '↩ Retour caisse',
        String(r?.reference_numero || '—'),
        '—',
        String(r?.motif || 'Reliquat rendu'),
        String(r?.budget_poste_libelle || '—'),
        modePaiementLabel(r?.mode),
        usd(montant),
        sortieStatutLabel(r?.statut),
      ] as (string | number)[],
    }
  })

  const allEntries = [...sortieEntries, ...retourEntries].sort((a, b) => b.key - a.key)
  const body = allEntries.map((e) => e.row)
  const total = allEntries.reduce((sum, e) => sum + e.montant, 0)
  const footRow = ['', '', '', '', '', '', 'TOTAL NET', usd(total), '']

  return buildListReport({
    title: 'RAPPORT DES SORTIES DE FONDS',
    footerLabel: 'Rapport des sorties de fonds',
    columns,
    rows: body,
    footRow,
    summary: [
      { label: 'Nombre de sorties', value: String(list.length) },
      { label: 'Retours en caisse', value: String(retours.length) },
      { label: 'Montant net', value: usd(total) },
    ],
    options,
    fileNameBase: `sorties_fonds_${buildFileSuffix(options)}`,
  })
}

// ============================================================================
//  2) RAPPORT DES RÉQUISITIONS
// ============================================================================

const formatPersonName = (person: any): string => {
  if (!person) return '—'
  const full = `${person.prenom || ''} ${person.nom || ''}`.trim()
  return full || '—'
}

export const generateRequisitionsReportPDF = async (
  rows: any[],
  options: ReportOptions = {}
): Promise<Blob | null> => {
  const list = Array.isArray(rows) ? rows : []
  const columns: ReportColumn[] = [
    { header: 'N° Réquisition', width: 30 },
    { header: 'Date', width: 20 },
    { header: 'Objet', width: 50 },
    { header: 'Service / Commission', width: 32 },
    { header: 'Poste budgétaire', width: 35 },
    { header: 'Montant', width: 26, halign: 'right' },
    { header: 'Statut', width: 24, halign: 'center' },
    { header: 'Validation 1/2', width: 30 },
    { header: 'Validation 2/2', width: 30 },
  ]

  const body = list.map((r) => {
    const statutValue = r?.statut ?? r?.status
    const serviceLabel =
      r?.service?.libelle ||
      (r?.service?.code ? `${r.service.code} - ${r.service.libelle || ''}`.trim() : '') ||
      r?.service_libelle ||
      '—'
    return [
      r?.numero_requisition || '—',
      formatReportDate(r?.created_at),
      String(r?.objet || '—'),
      String(serviceLabel || '—'),
      String(r?.poste_budgetaire || '—'),
      usd(r?.montant_total),
      getStatusMeta(String(statutValue || '')).label,
      formatPersonName(r?.validateur),
      formatPersonName(r?.approbateur),
    ]
  })

  const total = list.reduce((sum, r) => sum + toNumber(r?.montant_total || 0), 0)
  const footRow = ['', '', '', '', 'TOTAL', usd(total), '', '', '']

  return buildListReport({
    title: 'RAPPORT DES RÉQUISITIONS DE FONDS',
    footerLabel: 'Rapport des réquisitions',
    columns,
    rows: body,
    footRow,
    summary: [
      { label: 'Nombre de réquisitions', value: String(list.length) },
      { label: 'Montant total', value: usd(total) },
    ],
    options,
    fileNameBase: `requisitions_${buildFileSuffix(options)}`,
  })
}

// ============================================================================
//  3) RAPPORT DES ENCAISSEMENTS
// ============================================================================

const encaissementStatutLabel = (value: string): string => {
  if (value === 'complet') return 'Payé'
  if (value === 'partiel') return 'Partiel'
  if (value === 'avance') return 'Avance'
  return 'Non payé'
}

const encaissementMontantAffiche = (enc: any): string => {
  const devise = String(enc?.devise_perception || 'USD').toUpperCase()
  if (devise === 'CDF') return `${formatAmount(enc?.montant_percu, 0)} CDF`
  return `${formatAmount(enc?.montant_total)} USD`
}

export const generateEncaissementsReportPDF = async (
  rows: any[],
  options: ReportOptions = {}
): Promise<Blob | null> => {
  const list = Array.isArray(rows) ? rows : []
  const columns: ReportColumn[] = [
    { header: 'Date', width: 20 },
    { header: 'N° Note de débit', width: 30 },
    { header: 'Matricule', width: 24, halign: 'center' },
    { header: 'Client / Membre', width: 55 },
    { header: 'Poste budgétaire', width: 40 },
    { header: 'Libellé', width: 42 },
    { header: 'Montant', width: 30, halign: 'right' },
    { header: 'Statut', width: 36, halign: 'center' },
  ]

  const body = list.map((enc) => [
    formatReportDate(enc?.date_encaissement),
    enc?.numero_recu || '—',
    String(enc?.matricule || '—').toUpperCase(),
    String(enc?.client || enc?.client_nom || '—'),
    resolvePosteLabel(enc),
    String(enc?.libelle || '—'),
    encaissementMontantAffiche(enc),
    encaissementStatutLabel(enc?.statut_paiement),
  ])

  const total = list.reduce((sum, enc) => sum + toNumber(enc?.montant_total || 0), 0)
  const footRow = ['', '', '', '', '', 'TOTAL', `${formatAmount(total)} USD`, '']

  return buildListReport({
    title: 'RAPPORT DES ENCAISSEMENTS',
    footerLabel: 'Rapport des encaissements',
    columns,
    rows: body,
    footRow,
    summary: [
      { label: "Nombre d'encaissements", value: String(list.length) },
      { label: 'Montant total (USD)', value: `${formatAmount(total)} USD` },
    ],
    options,
    fileNameBase: `encaissements_${buildFileSuffix(options)}`,
  })
}
