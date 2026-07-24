import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { fr } from 'date-fns/locale'
import type { PrintSettings } from '../api/settings'
import { numberToWords } from './numberToWords'
import { formatAmount, toNumber } from './amount'
import { API_BASE_URL, getAuthHeaders } from '../lib/apiClient'
import { getTypeClientLabel } from './encaissementHelpers'
import { getTenantRequestHint } from './tenant'
import { buildUploadUrl } from './uploads'

const ONEC_GREEN = '#065f46'
const ONEC_LIGHT_GREEN = '#ecfdf5'
const ONEC_LIGHT_BG = '#ecfdf5'
const HEADER_HEIGHT = 28
const LOGO_SIZE = 20
const HEADER_CENTER_X = (docWidth: number) => docWidth / 2

let cachedLogoDataUrl: string | null = null
let cachedLogoUrl: string | null = null
let cachedStampDataUrl: string | null = null
let cachedStampUrl: string | null = null
let cachedSettings: any | null = null
let cachedTenantHint: string | null = null

const resetPrintAssetCache = () => {
  cachedLogoDataUrl = null
  cachedLogoUrl = null
  cachedStampDataUrl = null
  cachedStampUrl = null
  cachedSettings = null
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
      credentials: 'include' 
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

const getStampDataUrl = async () => {
  ensureTenantScopedPrintCache()
  if (cachedStampDataUrl) return cachedStampDataUrl
  try {
    if (!cachedStampUrl) {
      const settings = await getPrintSettingsData()
      cachedStampUrl = settings?.stamp_url || null
    }
    if (!cachedStampUrl) return null
    const res = await fetch(buildUploadUrl(cachedStampUrl), { 
      headers: getAuthHeaders(),
      credentials: 'include' 
    })
    if (!res.ok) return null
    const blob = await res.blob()
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onloadend = () => resolve(String(reader.result || ''))
      reader.onerror = reject
      reader.readAsDataURL(blob)
    })
    cachedStampDataUrl = dataUrl
    return cachedStampDataUrl
  } catch {
    return null
  }
}

const addLogo = (doc: jsPDF, x: number, y: number, size: number, dataUrl?: string | null) => {
  if (!dataUrl) return
  doc.addImage(dataUrl, 'PNG', x, y, size, size)
}

const openPdfInNewTab = (doc: jsPDF) => {
  const blob = doc.output('blob')
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank', 'noopener,noreferrer')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

type ReceiptPdfFormat = 'a4' | 'a5'

interface ReceiptPdfOptions {
  format?: ReceiptPdfFormat
  duplicate?: boolean
  compactHeader?: boolean
  settings?: Partial<PrintSettings> | null
}

const DEFAULT_ORG_NAME = 'ORDRE NATIONAL DES EXPERTS-COMPTABLES'
const DEFAULT_TENANT_NAME = 'Antenne Provinciale'
const DEFAULT_FOOTER_TEXT = 'Document généré automatiquement © 2026 ONEC (Dev: kidikala@gmail.com)'
const DEFAULT_REQUISITION_ORG_NAME = 'Organisation'

const getTrimmedSetting = (value?: string | null) => {
  const trimmed = String(value || '').trim()
  return trimmed || ''
}

const getReportLabel = (label: string, tenantName?: string | null) =>
  tenantName ? `${label} - ${tenantName}` : label

export const generateReceiptPDF = async (encaissement: any, options: ReceiptPdfOptions = {}) => {
  const paperFormat = options.format ?? 'a5'
  const isA5 = paperFormat === 'a5'
  const compactHeader = options.compactHeader ?? false
  const settings = options.settings ?? (await getPrintSettingsData())
  const logoDataUrl = settings?.show_header_logo === false ? null : await getLogoDataUrl()
  const stampDataUrl = settings?.show_footer_signature === false ? null : await getStampDataUrl()
  let receiptQrDataUrl: string | null = null
  const isProforma = !!encaissement?.est_proforma
  const marginLeft = 0
  const marginRight = 0
  const marginTop = 0
  const marginBottom = 55

  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: paperFormat })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const titleGreen = [6, 95, 70]

  if (options.duplicate) {
    doc.setTextColor(230)
    doc.setFont('times', 'bold')
    doc.setFontSize(isA5 ? 24 : 32)
    doc.text('DUPLICATA', pageWidth / 2, pageHeight / 2, { align: 'center', angle: 35 })
  }
  if (isProforma) {
    doc.setTextColor(219, 39, 119)
    doc.setFont('times', 'bold')
    doc.setFontSize(isA5 ? 28 : 36)
    doc.text('PROFORMA', pageWidth / 2, pageHeight / 2, { align: 'center', angle: 35 })
    doc.setTextColor(0)
  }

  const headerTop = marginTop
  if (logoDataUrl) {
    const logoSize = compactHeader ? (isA5 ? 16 : 20) : isA5 ? 18 : 22
    doc.addImage(logoDataUrl, 'PNG', marginLeft, headerTop, logoSize, logoSize)
  }

  doc.setTextColor(titleGreen[0], titleGreen[1], titleGreen[2])
  doc.setFont('times', 'bold')
  doc.setFontSize(isA5 ? 11 : 14)
  const headerTextX = marginLeft + (isA5 ? 24 : 28) + 4
  const headerLineStartY = headerTop + (isA5 ? 4.5 : 6)
  const headerLineGap = compactHeader ? (isA5 ? 3.8 : 5) : isA5 ? 5 : 7
  let headerLineY = headerLineStartY
  doc.text(DEFAULT_ORG_NAME, headerTextX, headerLineY)

  doc.setFont('times', 'normal')
  doc.setFontSize(isA5 ? 8 : 10)
  headerLineY += headerLineGap
  doc.text(settings?.organization_name || DEFAULT_TENANT_NAME, headerTextX, headerLineY)
  if (settings?.organization_subtitle) {
    headerLineY += headerLineGap
    doc.text(settings.organization_subtitle, headerTextX, headerLineY)
  }
  if (settings?.header_text) {
    headerLineY += headerLineGap
    doc.text(settings.header_text, headerTextX, headerLineY)
  }
  if (settings?.address || settings?.phone || settings?.email) {
    const contactParts: string[] = []
    if (settings.address) contactParts.push(settings.address)
    if (settings.phone) contactParts.push(`Tél: ${settings.phone}`)
    if (settings.email) contactParts.push(`Email: ${settings.email}`)
    headerLineY += headerLineGap
    doc.setFontSize(isA5 ? 7 : 8)
    const contactText = contactParts.join(' | ')
    const maxWidth = pageWidth - marginRight - headerTextX
    const contactLines = doc.splitTextToSize(contactText, maxWidth)
    doc.text(contactLines, headerTextX, headerLineY)
    headerLineY += (contactLines.length - 1) * (isA5 ? 3.2 : 4)
    doc.setFontSize(isA5 ? 8 : 10)
  }

  const headerBottom = (compactHeader ? (isA5 ? 26 : 32) : isA5 ? 32 : 38) + marginTop
  doc.setDrawColor(titleGreen[0], titleGreen[1], titleGreen[2])
  doc.setLineWidth(0.6)
  doc.line(marginLeft, headerBottom, pageWidth - marginRight, headerBottom)

  doc.setFont('times', 'bold')
  doc.setFontSize(isA5 ? 13 : 16)
  doc.setTextColor(titleGreen[0], titleGreen[1], titleGreen[2])
  const headerNumero = isProforma ? encaissement.numero_proforma : encaissement.numero_recu
  const headerTitle = isProforma ? 'FACTURE PROFORMA' : 'REÇU DE PAIEMENT'
  doc.text(`${headerTitle} N° ${headerNumero || ''}`, pageWidth / 2, headerBottom + 10, {
    align: 'center',
  })
  if (isProforma) {
    doc.setFont('times', 'normal')
    doc.setFontSize(isA5 ? 8 : 9)
    doc.setTextColor(180, 83, 9)
    doc.text('Document non comptable', pageWidth / 2, headerBottom + (isA5 ? 15 : 18), { align: 'center' })
    doc.setTextColor(0)
  }
  doc.setTextColor(0)

  const clientName = encaissement.expert_comptable
    ? encaissement.expert_comptable.nom_denomination
    : encaissement.client_nom || 'N/A'

  const clientInfo = encaissement.expert_comptable
    ? `N° Ordre: ${encaissement.expert_comptable.numero_ordre}`
    : 'Autre client'
  const clientMatricule = encaissement.expert_comptable?.numero_ordre || encaissement.matricule || ''

  const modesPaiement: Record<string, string> = {
    cash: 'Espèces',
    check: 'Chèque',
    cheque: 'Chèque',
    bank_transfer: 'Opération bancaire',
    mobile_money: 'Mobile Money',
    card: 'Carte (Visa)',
    virement: 'Opération bancaire',
  }

  const totalMontant = toNumber(encaissement.montant_total || encaissement.montant || 0)
  const montantPaye = toNumber(encaissement.montant_paye || 0)
  const montantPercu = toNumber(encaissement.montant_percu || 0)
  const devisePercu = (encaissement.devise_perception || 'USD').toUpperCase()
  const soldeRestant = totalMontant - montantPaye

  if (!isProforma && settings?.afficher_qr_code !== false && encaissement.numero_recu) {
    try {
      const { default: QRCode } = await import('qrcode')
      const baseUrl = typeof window !== 'undefined' ? window.location.origin : ''
      const qrPayload = baseUrl
        ? `${baseUrl}/api/v1/encaissements/verify?numero_recu=${encodeURIComponent(encaissement.numero_recu)}&amount=${encodeURIComponent(totalMontant.toFixed(2))}`
        : `REC:${encaissement.numero_recu}|DATE:${format(new Date(encaissement.date_encaissement), 'dd/MM/yyyy')}|AMT:${formatAmount(totalMontant)}|DEV:${devisePercu}`
      receiptQrDataUrl = await QRCode.toDataURL(qrPayload, { margin: 1, width: isA5 ? 70 : 90 })
    } catch (_err) {
      receiptQrDataUrl = null
    }
  }

  if (receiptQrDataUrl) {
    const qrSize = isA5 ? 14 : 18
    const qrX = pageWidth - marginRight - qrSize - 10
    const qrY = headerBottom + (isA5 ? 2 : 3)
    doc.setFillColor(255, 255, 255)
    doc.setDrawColor(6, 95, 70)
    doc.roundedRect(qrX - 2, qrY - 2, qrSize + 6, qrSize + 6, 1.5, 1.5, 'FD')
    doc.addImage(receiptQrDataUrl, 'PNG', qrX + 1, qrY + 1, qrSize, qrSize)
    doc.setFontSize(isA5 ? 6.5 : 7.5)
    doc.setTextColor(100)
    doc.text('Scan vérification', qrX - 4, qrY + qrSize + 8)
    doc.setTextColor(0)
  }

  const dateLabel = isProforma ? "Date d'émission" : 'Date de paiement'
  const dateValue = encaissement.date_paiement || encaissement.date_encaissement
  const infoBody: Array<[string, string]> = [
    [dateLabel, format(new Date(dateValue), 'dd MMMM yyyy', { locale: fr })],
    ['Reçu de', clientName],
    ['Identification', clientInfo],
    ['Type de client', getTypeClientLabel(encaissement.type_client)],
    [
      'Poste budgétaire',
      encaissement.budget_poste_code
        ? `${encaissement.budget_poste_code} ${encaissement.budget_poste_libelle ? `- ${encaissement.budget_poste_libelle}` : ''}`.trim()
        : '—',
    ],
    ['Libellé', encaissement.libelle || '—'],
    ['Mode de paiement', modesPaiement[encaissement.mode_paiement] || encaissement.mode_paiement || 'N/A'],
  ]
  if (clientMatricule) {
    infoBody.push(['Matricule', String(clientMatricule).toUpperCase()])
  }

  if (encaissement.reference) {
    infoBody.push(['Référence', encaissement.reference])
  }
  if (encaissement.description) {
    infoBody.push(['Description', encaissement.description])
  }

  autoTable(doc, {
    startY: headerBottom + (isA5 ? 16 : 18),
    body: infoBody,
    theme: 'striped',
    tableWidth: pageWidth - marginLeft - marginRight,
    styles: {
      font: 'times',
      fontSize: isA5 ? 8.5 : 10,
      cellPadding: 3,
      valign: 'middle',
      fillColor: [255, 255, 255],
    },
    columnStyles: {
      0: { cellWidth: isA5 ? 38 : 50, fontStyle: 'bold', fillColor: [236, 253, 245], textColor: [4, 120, 87] },
    },
    margin: { left: marginLeft, right: marginRight },
  })

  const infoTableEndY = (doc as any).lastAutoTable.finalY || headerBottom + 20

  const paymentBody: any[] = [
    ['Montant dû (USD)', { content: `${formatAmount(totalMontant)} USD`, styles: { fontStyle: 'bold' } }],
    ['Somme en lettres', { content: numberToWords(totalMontant), styles: { fontStyle: 'italic' } }],
    ['Montant payé (USD)', { content: `${formatAmount(montantPaye)} USD`, styles: { fontStyle: 'bold' } }],
    ['Somme en lettres', { content: numberToWords(montantPaye), styles: { fontStyle: 'italic' } }],
  ]

  if (devisePercu === 'CDF') {
    paymentBody.push(['Montant perçu (CDF)', `${formatAmount(montantPercu, 0)} CDF`])
    paymentBody.push(['Équivalent USD', `${formatAmount(totalMontant)} USD`])
  }

  if (soldeRestant > 0) {
    paymentBody.push(['Solde restant (USD)', `${formatAmount(soldeRestant)} USD`])
    paymentBody.push(['Somme en lettres', { content: numberToWords(soldeRestant), styles: { fontStyle: 'italic' } }])
  }

  const paymentTableWidth = pageWidth - marginLeft - marginRight
  const paymentLabelWidth = Math.floor(paymentTableWidth * 0.3)
  autoTable(doc, {
    startY: infoTableEndY + (isA5 ? 6 : 8),
    body: paymentBody,
    theme: 'striped',
    tableWidth: paymentTableWidth,
    styles: {
      font: 'times',
      fontSize: isA5 ? 8 : 10,
      cellPadding: 2,
      valign: 'middle',
    },
    columnStyles: {
      0: { cellWidth: paymentLabelWidth, fontStyle: 'bold', fillColor: [236, 253, 245] },
      1: { cellWidth: paymentTableWidth - paymentLabelWidth },
    },
    margin: { left: marginLeft, right: marginRight },
  })

  const paymentEndY = (doc as any).lastAutoTable.finalY || infoTableEndY + 10
  const maxSignatureTop = pageHeight - marginBottom - (isA5 ? 24 : 28)
  const signatureTop = Math.min(paymentEndY + (isA5 ? 8 : 12), maxSignatureTop)

  if (settings?.show_footer_signature !== false) {
    doc.setFont('times', 'normal')
    doc.setFontSize(isA5 ? 8 : 10)
    doc.text(
      `Fait à Kinshasa, le ${format(new Date(encaissement.date_encaissement), 'dd/MM/yyyy')}`,
      marginLeft,
      signatureTop
    )

    const signX = pageWidth - marginRight - (isA5 ? 55 : 65)
    doc.setFont('times', 'bold')
    doc.text(settings?.recu_label_signature || 'Cachet & signature', signX, signatureTop + (isA5 ? 4 : 6))
    doc.setFont('times', 'normal')
    if (settings?.recu_nom_signataire) {
      doc.text(settings.recu_nom_signataire, signX, signatureTop + (isA5 ? 8 : 10))
    }

    if (stampDataUrl) {
      const stampSize = isA5 ? 22 : 28
      doc.addImage(stampDataUrl, 'PNG', signX, signatureTop + (isA5 ? 14 : 16), stampSize, stampSize)
    }
  }

  doc.setFont('times', 'normal')
  doc.setFontSize(isA5 ? 7 : 8.5)
  doc.setTextColor(100)
  doc.text(
    settings?.pied_de_page_legal || DEFAULT_FOOTER_TEXT,
    pageWidth / 2,
    pageHeight - marginBottom + (isA5 ? 8 : 10),
    { align: 'center' }
  )

  doc.setTextColor(0)
  openPdfInNewTab(doc)
}

export const generateRequisitionsPDF = async (
  requisitions: any[],
  dateDebut: string,
  dateFin: string,
  _userName: string
) => {
  const settings = await getPrintSettingsData()
  const logoDataUrl = await getLogoDataUrl()
  const formatUserName = (user: any) => {
    if (!user) return 'N/A'
    const fullName = `${user.prenom || ''} ${user.nom || ''}`.trim()
    return fullName || 'N/A'
  }

  const doc = new jsPDF({ orientation: 'l', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  let qrDataUrl: string | null = null

  const addHeader = () => {
    doc.setFillColor(ONEC_LIGHT_BG)
    doc.roundedRect(10, 8, pageWidth - 20, HEADER_HEIGHT, 3, 3, 'F')
    addLogo(doc, 12, 10, LOGO_SIZE, logoDataUrl)

    doc.setDrawColor(ONEC_GREEN)
    doc.setLineWidth(3)
    doc.line(10, 40, pageWidth - 10, 40)

    doc.setFontSize(14)
    doc.setTextColor(ONEC_GREEN)
    doc.setFont('helvetica', 'bold')
    doc.text('ORDRE NATIONAL DES EXPERTS-COMPTABLES', HEADER_CENTER_X(pageWidth), 18, { align: 'center' })

    doc.setFontSize(12)
    doc.setTextColor(0, 0, 0)
    doc.setFont('times', 'bolditalic')
    doc.text(settings?.organization_name || DEFAULT_TENANT_NAME, HEADER_CENTER_X(pageWidth), 25, { align: 'center' })

    doc.setFontSize(10)
    doc.setTextColor(0, 0, 0)
    doc.setFont('helvetica', 'normal')
    doc.text("Plateforme intelligente de gestion intégrée de l'ONEC-RDC", HEADER_CENTER_X(pageWidth), 32, { align: 'center' })
  }

  const addFooter = (pageNumber: number) => {
    doc.setFontSize(8)
    doc.setTextColor(100)
    doc.text(
      `${format(new Date(), 'dd/MM/yyyy HH:mm')}`,
      10,
      pageHeight - 10
    )

    doc.text(
      getReportLabel('Rapport examens des réquisitions', settings?.organization_name),
      pageWidth / 2,
      pageHeight - 10,
      { align: 'center' }
    )
    doc.text(
      "Document généré automatiquement par l’application développée par ck (kidikala@gmail.com)",
      pageWidth / 2,
      pageHeight - 6,
      { align: 'center' }
    )

    doc.text(
      `Page ${pageNumber}`,
      pageWidth - 20,
      pageHeight - 10
    )
  }

  const normalizeStatut = (value: any) => {
    const raw = String(value || '').trim()
    if (!raw) return ''
    const lower = raw.toLowerCase()
    if (lower === 'en_attente_commission' || lower === 'approuve_commission') return 'en_attente_commission'
    if (lower === 'en_attente' || lower === 'brouillon' || lower === 'a_valider') return 'en_attente'
    if (lower === 'validee' || lower === 'autorisee' || lower === 'validee_tresorerie') return 'autorisee'
    if (lower === 'approuvee') return 'approuvee'
    if (lower === 'payee') return 'payee'
    if (lower === 'rejetee' || lower === 'rejeté' || lower === 'rejette') return 'rejetee'
    if (lower === 'valide_technique') return 'autorisee'
    if (lower === 'decaisse') return 'payee'
    if (raw === 'EN_ATTENTE_COMMISSION') return 'en_attente_commission'
    if (raw === 'EN_ATTENTE') return 'en_attente'
    if (raw === 'APPROUVE_COMMISSION') return 'en_attente'
    if (raw === 'VALIDEE') return 'autorisee'
    if (raw === 'AUTORISEE') return 'autorisee'
    if (raw === 'APPROUVEE') return 'approuvee'
    if (raw === 'REJETEE') return 'rejetee'
    if (raw === 'PAYEE') return 'payee'
    return lower
  }

  const normalizeRubrique = (value: any) => {
    const raw = String(value || '').replace(/\s+/g, ' ').trim()
    if (!raw) return ''
    const cleaned = raw
      .replace(/\b([A-ZÉÈÊÀÙÂÎÔÛÇ]{4,})\s+MENT\b/g, '$1MENT')
      .replace(/\b([A-ZÉÈÊÀÙÂÎÔÛÇ]{4,})\s+TION\b/g, '$1TION')
      .replace(/\b([A-ZÉÈÊÀÙÂÎÔÛÇ]{4,})\s+TIONS\b/g, '$1TIONS')
      .replace(/\b([A-ZÉÈÊÀÙÂÎÔÛÇ]{4,})\s+TE\b/g, '$1TE')
    return cleaned
  }

  const extractRubriqueKey = (value: any) => {
    const cleaned = normalizeRubrique(value)
    if (!cleaned) return { key: 'Non classé', label: 'Non classé', code: '' }
    const match = cleaned.match(/^(\d+(?:\.\d+)*)(?:\s*[-:])?\s*(.*)$/)
    if (!match) return { key: cleaned, label: cleaned, code: '' }
    const code = match[1]
    const label = match[2] || cleaned
    return { key: `${code} ${label}`.trim(), label: label.trim(), code }
  }

  const getStatut = (r: any) => normalizeStatut(r?.statut ?? r?.status)
  const isPayee = (r: any) => {
    const statut = getStatut(r)
    return statut === 'payee' || !!r?.payee_par || !!r?.payee_le
  }

  const totalRequisitions = requisitions.length
  const totalMontant = requisitions.reduce((sum, r) => sum + Number(r.montant_total || 0), 0)
  const totalDecaisse = requisitions.filter(r => isPayee(r)).reduce((sum, r) => sum + Number(r.montant_total || 0), 0)
  const totalRejeteMontant = requisitions
    .filter(r => normalizeStatut(r?.statut ?? r?.status) === 'rejetee')
    .reduce((sum, r) => sum + Number(r.montant_total || 0), 0)
  const totalEnAttenteMontant = Math.max(0, totalMontant - totalDecaisse - totalRejeteMontant)

  const rubriqueTotals = new Map<string, { label: string; code: string; total: number }>()
  requisitions.forEach((req) => {
    const { key, label, code } = extractRubriqueKey(req.poste_budgetaire || '')
    const prev = rubriqueTotals.get(key)
    const montant = Number(req.montant_total || 0)
    if (prev) {
      prev.total += montant
    } else {
      rubriqueTotals.set(key, { label, code, total: montant })
    }
  })
  const topRubriques = Array.from(rubriqueTotals.values())
    .sort((a, b) => b.total - a.total)
    .slice(0, 4)

  try {
    const { default: QRCode } = await import('qrcode')
    const baseUrl = typeof window !== 'undefined' ? window.location.origin : ''
    const url = baseUrl
      ? `${baseUrl}/api/v1/requisitions/verify-report?date_debut=${encodeURIComponent(dateDebut)}&date_fin=${encodeURIComponent(dateFin)}&total=${encodeURIComponent(totalMontant.toFixed(2))}&count=${encodeURIComponent(String(totalRequisitions))}`
      : `REQ-RPT:${dateDebut}-${dateFin}|COUNT:${totalRequisitions}|TOTAL:${formatAmount(totalMontant)}USD`
    qrDataUrl = await QRCode.toDataURL(url, { margin: 1, width: 70 })
  } catch (_err) {
    qrDataUrl = null
  }

  addHeader()

  doc.setFontSize(16)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text("RAPPORT D’EXAMEN DES DOSSIERS DE RÉQUISITION DE FONDS", pageWidth / 2, 50, { align: 'center' })

  doc.setFontSize(10)
  doc.setTextColor(0)
  doc.setFont('helvetica', 'normal')
  doc.text(
    `Période : du ${format(new Date(dateDebut), 'dd/MM/yyyy')} au ${format(new Date(dateFin), 'dd/MM/yyyy')}`,
    pageWidth / 2,
    60,
    { align: 'center' }
  )

  const kpiTop = 66
  doc.setFillColor(255, 255, 255)
  doc.setDrawColor(ONEC_LIGHT_GREEN)
  doc.roundedRect(10, kpiTop, pageWidth - 20, 22, 3, 3, 'FD')

  doc.setFontSize(9)
  doc.setTextColor(90)
  doc.text('Total', 14, kpiTop + 7)
  doc.text('Payé', 58, kpiTop + 7)
  doc.text('En attente', 100, kpiTop + 7)
  doc.text('Rejeté', 150, kpiTop + 7)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.setTextColor(0)
  doc.text(`${formatAmount(totalMontant)} $`, 14, kpiTop + 15)
  doc.text(`${formatAmount(totalDecaisse)} $`, 58, kpiTop + 15)
  doc.text(`${formatAmount(totalEnAttenteMontant)} $`, 100, kpiTop + 15)
  doc.text(`${formatAmount(totalRejeteMontant)} $`, 150, kpiTop + 15)

  const barY = kpiTop + 26
  doc.setFillColor(230, 230, 230)
  doc.roundedRect(10, barY, pageWidth - 20, 6, 2, 2, 'F')
  const totalSafe = totalMontant || 1
  const paidW = ((totalDecaisse / totalSafe) * (pageWidth - 20))
  const pendingW = ((totalEnAttenteMontant / totalSafe) * (pageWidth - 20))
  const rejectedW = ((totalRejeteMontant / totalSafe) * (pageWidth - 20))
  doc.setFillColor(34, 197, 94)
  doc.rect(10, barY, paidW, 6, 'F')
  doc.setFillColor(249, 115, 22)
  doc.rect(10 + paidW, barY, pendingW, 6, 'F')
  doc.setFillColor(239, 68, 68)
  doc.rect(10 + paidW + pendingW, barY, rejectedW, 6, 'F')

  let rubriqueY = barY + 10
  if (topRubriques.length > 0) {
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(9)
    doc.setTextColor(ONEC_GREEN)
    doc.text('Répartition par poste budgétaire', 10, rubriqueY)
    rubriqueY += 5
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    doc.setTextColor(60)
    topRubriques.forEach((rub) => {
      const label = rub.code ? `${rub.code} - ${rub.label}` : rub.label
      doc.text(label, 12, rubriqueY)
      doc.text(`${formatAmount(rub.total)} $`, pageWidth - 20, rubriqueY, { align: 'right' })
      rubriqueY += 4.5
    })
  }

  const tableData = requisitions.map((req, index) => [
    String(index + 1),
    req.numero_requisition,
    format(new Date(req.created_at), 'dd/MM/yyyy'),
    req.objet.substring(0, 30) + (req.objet.length > 30 ? '...' : ''),
    normalizeRubrique(req.poste_budgetaire || ''),
    `${formatAmount(req.montant_total)} $`,
    (() => {
      const statut = normalizeStatut(req?.statut ?? req?.status)
      if (statut === 'en_attente_commission') return 'Attente signature commission'
      if (statut === 'en_attente') return 'En attente validation 1/2'
      if (statut === 'autorisee') return 'Validation 1/2'
      if (statut === 'approuvee') return 'Validation 2/2'
      if (statut === 'payee') return 'Payée'
      return 'Rejetée'
    })(),
    req.mode_paiement === 'cash' ? 'Caisse' :
    req.mode_paiement === 'mobile_money' ? 'Mobile Money' :
    req.mode_paiement === 'card' ? 'Carte (Visa)' : 'Virement',
    formatUserName(req.demandeur),
    formatUserName(req.examinateur),
    formatUserName(req.validateur),
    formatUserName(req.approbateur)
  ])

  autoTable(doc, {
    head: [[
      'N°',
      'N° Réquisition',
      'Date',
      'Objet',
      'Poste budgétaire',
      'Montant',
      'Statut',
      'Paiement',
      'Demandeur',
      'Examinateur',
      'Validation 1/2',
      'Validation 2/2'
    ]],
    body: tableData,
    startY: Math.max(92, rubriqueY + 2),
    margin: { left: 10, right: 10, bottom: 18 },
    theme: 'grid',
    headStyles: {
      fillColor: ONEC_GREEN,
      textColor: 255,
      fontStyle: 'bold',
      fontSize: 7
    },
    bodyStyles: {
      fontSize: 7,
      cellPadding: 3
    },
    alternateRowStyles: {
      fillColor: [245, 245, 245]
    },
    columnStyles: {
      0: { cellWidth: 12 },
      1: { cellWidth: 26 },
      2: { cellWidth: 18 },
      3: { cellWidth: 30 },
      4: { cellWidth: 22 },
      5: { cellWidth: 18, halign: 'right' },
      6: { cellWidth: 18 },
      7: { cellWidth: 18 },
      8: { cellWidth: 26 },
      9: { cellWidth: 26 },
      10: { cellWidth: 26 },
      11: { cellWidth: 26 }
    },
    didParseCell: (data) => {
      if (data.section === 'body' && data.column.index === 5) {
        const value = String(data.cell.text?.[0] || '').toLowerCase()
        if (value.includes('rejet')) {
          data.cell.styles.fillColor = [254, 226, 226]
          data.cell.styles.textColor = [153, 27, 27]
        } else if (value.includes('payé') || value.includes('payee')) {
          data.cell.styles.fillColor = [220, 252, 231]
          data.cell.styles.textColor = [22, 101, 52]
        } else if (value.includes('validation')) {
          data.cell.styles.fillColor = [255, 247, 237]
          data.cell.styles.textColor = [154, 52, 18]
        }
      }
    },
    didDrawPage: () => {
      addFooter(doc.getNumberOfPages())
    }
  })

  if (qrDataUrl) {
    const qrX = 15
    const qrY = pageHeight - 34
    const qrSize = 12
    doc.setFontSize(8)
    doc.setTextColor(90)
    doc.setFillColor(255, 255, 255)
    doc.rect(qrX, qrY - 8, 56, 6, 'F')
    doc.text("Scannez pour vérifier l'authenticité", qrX, qrY - 4)
    doc.addImage(qrDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
  }

  doc.save(`requisitions_${dateDebut}_${dateFin}.pdf`)
}

export const generateEncaissementsPDF = async (
  encaissements: any[],
  dateDebut: string,
  dateFin: string,
  _userName: string
) => {
  const settings = await getPrintSettingsData()
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  let qrDataUrl: string | null = null
  const logoDataUrl = await getLogoDataUrl()
  const accent: [number, number, number] = [0, 160, 157]
  const textMain: [number, number, number] = [76, 76, 76]
  const textMuted: [number, number, number] = [120, 120, 120]
  const lineLight: [number, number, number] = [230, 232, 236]

  const addHeader = () => {
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(textMain[0], textMain[1], textMain[2])
    doc.setFontSize(9)
    doc.text('Ordre National des Experts-Comptables', 12, 14)
    doc.text(settings?.organization_name || DEFAULT_TENANT_NAME, 12, 18)
    doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
    doc.text("Plateforme intelligente de gestion intégrée de l'ONEC-RDC", 12, 22)

    if (logoDataUrl) {
      addLogo(doc, pageWidth - 30, 10, 18, logoDataUrl)
    }

    doc.setDrawColor(lineLight[0], lineLight[1], lineLight[2])
    doc.setLineWidth(0.5)
    doc.line(10, 28, pageWidth - 10, 28)
  }

  const addFooter = (pageNumber: number) => {
    doc.setFontSize(8)
    doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
    doc.text(
      `${format(new Date(), 'dd/MM/yyyy HH:mm')}`,
      10,
      pageHeight - 10
    )

    doc.text(
      getReportLabel('Rapport des encaissements', settings?.organization_name),
      pageWidth / 2,
      pageHeight - 10,
      { align: 'center' }
    )

    doc.text(
      `Page ${pageNumber}`,
      pageWidth - 20,
      pageHeight - 10
    )
  }

  const totalMontant = encaissements.reduce((sum, e) => sum + Number(e.montant_total), 0)
  try {
    const { default: QRCode } = await import('qrcode')
    const qrPayload = `ENC-RPT:${dateDebut}-${dateFin}|COUNT:${encaissements.length}|TOTAL:${formatAmount(totalMontant)}USD`
    qrDataUrl = await QRCode.toDataURL(qrPayload, { margin: 1, width: 120 })
  } catch (_err) {
    qrDataUrl = null
  }

  addHeader()

  doc.setFontSize(16)
  doc.setTextColor(accent[0], accent[1], accent[2])
  doc.setFont('helvetica', 'bold')
  doc.text('RAPPORT DES ENCAISSEMENTS', 10, 42)

  doc.setFontSize(9)
  doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
  doc.setFont('helvetica', 'normal')
  doc.text(
    `Période du ${format(new Date(dateDebut), 'dd/MM/yyyy')} au ${format(new Date(dateFin), 'dd/MM/yyyy')}`,
    10,
    48
  )

  const tableData = encaissements.map(enc => {
    const devise = (enc.devise_perception || 'USD').toUpperCase()
    const percu = devise === 'CDF'
      ? `${formatAmount(enc.montant_percu, 0)} CDF`
      : `${formatAmount(enc.montant_total)} USD`
    return [
      format(new Date(enc.date_encaissement), 'dd/MM/yyyy'),
      enc.numero_recu,
      (enc.matricule || '—').toUpperCase(),
      enc.client || '',
      enc.rubrique || '',
      enc.libelle || '',
      percu,
      enc.statut_paiement === 'complet' ? 'Payé' :
      enc.statut_paiement === 'partiel' ? 'Partiel' :
      enc.statut_paiement === 'avance' ? 'Avance' : 'Non payé'
    ]
  })

  autoTable(doc, {
    head: [['Date', 'N° Reçu', 'Matricule', 'Client / Membre', 'Poste budgétaire', 'Libellé', 'Montant', 'Statut']],
    body: tableData,
    startY: 56,
    theme: 'plain',
    margin: { left: 8, right: 8 },
    tableWidth: 'auto',
    headStyles: {
      fillColor: [255, 255, 255],
      textColor: [102, 102, 102],
      fontStyle: 'bold',
      fontSize: 9,
      lineWidth: 0.3,
      lineColor: lineLight
    },
    bodyStyles: {
      fontSize: 8.5,
      cellPadding: 2,
      textColor: textMain,
      lineWidth: 0.2,
      lineColor: lineLight
    },
    styles: {
      overflow: 'linebreak',
      lineWidth: 0.2,
      lineColor: lineLight
    },
    columnStyles: {
      0: { cellWidth: 18 },
      1: { cellWidth: 28 },
      2: { cellWidth: 20, halign: 'center', fontStyle: 'bold', textColor: [4, 120, 87] },
      3: { cellWidth: 34 },
      4: { cellWidth: 24 },
      5: { cellWidth: 24 },
      6: { cellWidth: 20, halign: 'right', fontStyle: 'bold' },
      7: { cellWidth: 16, halign: 'center' }
    },
    didParseCell: (data) => {
      if (data.section === 'body' && data.column.index === 7) {
        const value = String(data.cell.raw || '').toLowerCase()
        data.cell.styles.halign = 'center'
        data.cell.styles.fontStyle = 'bold'
        if (value.includes('payé')) {
          data.cell.styles.fillColor = [209, 250, 229]
          data.cell.styles.textColor = [6, 95, 70]
        } else if (value.includes('partiel') || value.includes('avance')) {
          data.cell.styles.fillColor = [254, 243, 199]
          data.cell.styles.textColor = [146, 64, 14]
        } else {
          data.cell.styles.fillColor = [254, 226, 226]
          data.cell.styles.textColor = [153, 27, 27]
        }
      }
    },
    didDrawPage: () => {
      addFooter(doc.getNumberOfPages())
    }
  })

  let finalY = (doc as any).lastAutoTable.finalY + 10
  const blockHeight = 36
  if (finalY + blockHeight > pageHeight - 20) {
    doc.addPage()
    addHeader()
    finalY = 55
  }

  const securityX = 12
  const securityY = finalY + 6
  const totalBoxWidth = 62

  doc.setFontSize(9)
  doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
  doc.setFont('helvetica', 'bold')
  doc.text('Validation', securityX, securityY)

  if (qrDataUrl) {
    doc.setDrawColor(lineLight[0], lineLight[1], lineLight[2])
    doc.setFillColor(255, 255, 255)
    doc.roundedRect(securityX, securityY + 4, 24, 24, 2, 2, 'FD')
    doc.addImage(qrDataUrl, 'PNG', securityX + 3, securityY + 7, 18, 18)
    doc.setFontSize(8)
    doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
    doc.text('Scan. vérification', securityX, securityY + 32)
  }

  doc.setFontSize(8)
  doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
  doc.text('Signature Trésorier', securityX + 32, securityY + 12)
  doc.setDrawColor(lineLight[0], lineLight[1], lineLight[2])
  doc.line(securityX + 32, securityY + 20, securityX + 96, securityY + 20)

  doc.setFontSize(9)
  doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
  doc.text(`Total encaissements : ${encaissements.length}`, securityX + 32, securityY + 30)

  const totalBoxX = pageWidth - totalBoxWidth - 14
  doc.setDrawColor(accent[0], accent[1], accent[2])
  doc.setLineWidth(0.6)
  doc.line(totalBoxX, finalY + 6, totalBoxX + totalBoxWidth, finalY + 6)
  doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
  doc.setFontSize(8)
  doc.setFont('helvetica', 'bold')
  doc.text('TOTAL', totalBoxX, finalY + 12)
  doc.setFontSize(11)
  doc.setTextColor(textMain[0], textMain[1], textMain[2])
  doc.text(`${formatAmount(totalMontant)} USD`, totalBoxX + totalBoxWidth, finalY + 20, { align: 'right' })

  doc.save(`encaissements_${dateDebut}_${dateFin}.pdf`)
}

const formatPdfDate = (value: any) => {
  if (!value) return '-'
  const raw = String(value)
  const parsed = raw.length <= 10 ? new Date(`${raw}T00:00:00`) : new Date(raw)
  if (Number.isNaN(parsed.getTime())) return '-'
  return format(parsed, 'dd/MM/yyyy')
}

export const generateGlobalReportPDF = async (
  rapport: any,
  dateDebut: string,
  dateFin: string
) => {
  const settings = await getPrintSettingsData()
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const logoDataUrl = await getLogoDataUrl()

  const accent = [0, 160, 157]
  const textMain: [number, number, number] = [76, 76, 76]
  const textMuted: [number, number, number] = [120, 120, 120]
  const lineLight: [number, number, number] = [230, 232, 236]

  doc.setFillColor(accent[0], accent[1], accent[2])
  doc.rect(0, 0, pageWidth, 4, 'F')

  doc.setFont('helvetica', 'normal')
  doc.setTextColor(textMain[0], textMain[1], textMain[2])
  doc.setFontSize(10)
  doc.text('ORDRE NATIONAL DES EXPERTS-COMPTABLES', 12, 14)
  doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
  doc.text(settings?.organization_name || DEFAULT_TENANT_NAME, 12, 19)
  doc.text("Plateforme intelligente de gestion intégrée de l'ONEC-RDC", 12, 24)

  if (logoDataUrl) {
    addLogo(doc, pageWidth - 30, 10, 18, logoDataUrl)
  }

  doc.setDrawColor(lineLight[0], lineLight[1], lineLight[2])
  doc.setLineWidth(0.5)
  doc.line(10, 28, pageWidth - 10, 28)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.setTextColor(textMain[0], textMain[1], textMain[2])
  doc.text('RAPPORT DE TRÉSORERIE', 10, 38)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
  doc.text(`Période du ${formatPdfDate(dateDebut)} au ${formatPdfDate(dateFin)}`, 10, 44)

  let currentY = 52

  const addSection = (title: string, head: string[], body: any[][]) => {
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11)
    doc.setTextColor(textMain[0], textMain[1], textMain[2])
    doc.text(title, 10, currentY)
    currentY += 4

    autoTable(doc, {
      head: [head],
      body: body.length ? body : [['—', '—', '—']],
      startY: currentY + 2,
      theme: 'plain',
      margin: { left: 10, right: 10 },
      headStyles: {
        fillColor: [255, 255, 255],
        textColor: [102, 102, 102],
        fontStyle: 'bold',
        fontSize: 8,
        lineWidth: 0.3,
        lineColor: lineLight,
      },
      bodyStyles: {
        fontSize: 8.5,
        textColor: textMain,
        cellPadding: 2.5,
        lineWidth: 0.2,
        lineColor: lineLight,
      },
      styles: {
        overflow: 'linebreak',
        lineWidth: 0.2,
        lineColor: lineLight,
      },
      didDrawPage: (data) => {
        const pageNumber = (doc as any).internal.getNumberOfPages()
        doc.setFontSize(8)
        doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
        doc.text(`${format(new Date(), 'dd/MM/yyyy HH:mm')}`, 10, pageHeight - 10)
        doc.text(getReportLabel('Rapport de trésorerie', settings?.organization_name), pageWidth / 2, pageHeight - 10, { align: 'center' })
        doc.text(`Page ${pageNumber}`, pageWidth - 20, pageHeight - 10)
        if (data.pageNumber > 1 && data.pageNumber === pageNumber) {
          doc.setDrawColor(lineLight[0], lineLight[1], lineLight[2])
          doc.setLineWidth(0.5)
          doc.line(10, 14, pageWidth - 10, 14)
        }
      }
    })

    const nextY = (doc as any).lastAutoTable?.finalY ?? currentY
    currentY = nextY + 10
  }

  const encaissements = Array.isArray(rapport?.encaissements) ? rapport.encaissements : []
  const sorties = Array.isArray(rapport?.sorties) ? rapport.sorties : []

  const encRows = encaissements.map((e: any) => [
    formatPdfDate(e.date_encaissement),
    e.numero_recu || '-',
    e.expert_comptable?.nom_denomination || e.client_nom || '-',
    formatAmount(toNumber(e.montant_paye ?? e.montant_total ?? e.montant ?? 0)),
  ])
  addSection('ENCAISSEMENTS', ['Date', 'Reçu', 'Client', 'Montant (USD)'], encRows)

  const sortieRows = sorties.map((s: any) => [
    formatPdfDate(s.date_paiement),
    s.reference || '-',
    s.requisition?.numero_requisition || s.requisition_id || '-',
    formatAmount(toNumber(s.montant_paye ?? 0)),
  ])
  addSection('SORTIES DE FONDS', ['Date', 'Référence', 'Réquisition', 'Montant (USD)'], sortieRows)

  const totalEnc =
    toNumber(rapport?.totalEncaissements) ||
    encaissements.reduce((sum: number, e: any) => sum + toNumber(e.montant_paye ?? e.montant_total ?? e.montant ?? 0), 0)
  const totalSorties =
    toNumber(rapport?.totalSorties) ||
    sorties.reduce((sum: number, s: any) => sum + toNumber(s.montant_paye ?? 0), 0)
  const soldeNet = toNumber(rapport?.soldeFinal ?? rapport?.solde ?? totalEnc - totalSorties)

  if (currentY + 30 > pageHeight - 20) {
    doc.addPage()
    currentY = 20
  }

  const summaryX = pageWidth - 80
  doc.setDrawColor(accent[0], accent[1], accent[2])
  doc.setLineWidth(0.6)
  doc.line(summaryX, currentY, pageWidth - 10, currentY)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.setTextColor(textMain[0], textMain[1], textMain[2])
  doc.text('RÉSUMÉ DE TRÉSORERIE', summaryX, currentY + 8)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
  doc.text(`Total entrées : ${formatAmount(totalEnc)} USD`, summaryX, currentY + 16)
  doc.text(`Total sorties : ${formatAmount(totalSorties)} USD`, summaryX, currentY + 22)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(textMain[0], textMain[1], textMain[2])
  doc.text(`Solde net : ${formatAmount(soldeNet)} USD`, summaryX, currentY + 30)

  doc.save(`rapport_tresorerie_${formatPdfDate(dateDebut).split('/').join('-')}.pdf`)
}

export const generateBudgetPDF = async (
  lignes: Array<{
    code: string
    libelle: string
    type?: string | null
    montant_prevu: string | number
    montant_engage: string | number
    montant_paye: string | number
    montant_disponible: string | number
    pourcentage_consomme: string | number
    is_parent?: boolean
    level?: number
  }>,
  annee: number,
  vue: 'DEPENSE' | 'RECETTE'
) => {
  const settings = await getPrintSettingsData()
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  let qrDataUrl: string | null = null

  const addHeader = () => {
    doc.setDrawColor(ONEC_GREEN)
    doc.setLineWidth(3)
    doc.line(10, 40, pageWidth - 10, 40)

    doc.setFontSize(18)
    doc.setTextColor(ONEC_GREEN)
    doc.setFont('helvetica', 'bold')
    doc.text('ORDRE NATIONAL DES EXPERTS-COMPTABLES', pageWidth / 2, 15, { align: 'center' })

    doc.setFontSize(14)
    doc.setTextColor(0, 0, 0)
    doc.setFont('times', 'bolditalic')
    doc.text(settings?.organization_name || DEFAULT_TENANT_NAME, pageWidth / 2, 23, { align: 'center' })

    doc.setFontSize(12)
    doc.setTextColor(0, 0, 0)
    doc.setFont('helvetica', 'normal')
    doc.text("Plateforme intelligente de gestion intégrée de l'ONEC-RDC", pageWidth / 2, 32, { align: 'center' })
  }

  const addFooter = (pageNumber: number) => {
    doc.setFontSize(8)
    doc.setTextColor(100)
    doc.text(`${format(new Date(), 'dd/MM/yyyy HH:mm')}`, 10, pageHeight - 10)
    doc.text(getReportLabel('Rapport budgétaire', settings?.organization_name), pageWidth / 2, pageHeight - 10, { align: 'center' })
    doc.text(`Page ${pageNumber}`, pageWidth - 20, pageHeight - 10)
  }

  // Totaux calculés sur les seules feuilles : un poste parent (ligne annuelle)
  // étant la somme de ses sous-postes, l'inclure double-compterait le budget.
  const feuilles = lignes.filter(l => !l.is_parent)
  const totalPrevu = feuilles.reduce((sum, l) => sum + toNumber(l.montant_prevu), 0)
  const totalEngage = feuilles.reduce((sum, l) => sum + toNumber(l.montant_engage), 0)
  const totalPaye = feuilles.reduce((sum, l) => sum + toNumber(l.montant_paye), 0)
  const totalDisponible = feuilles.reduce((sum, l) => sum + toNumber(l.montant_disponible), 0)
  try {
    const { default: QRCode } = await import('qrcode')
    const qrPayload = `BUDGET:${annee}:${vue}|PREVU:${formatAmount(totalPrevu)}|ENG:${formatAmount(totalEngage)}|PAYE:${formatAmount(totalPaye)}`
    qrDataUrl = await QRCode.toDataURL(qrPayload, { margin: 1, width: 120 })
  } catch (_err) {
    qrDataUrl = null
  }

  addHeader()

  doc.setFontSize(16)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text(`BUDGET ${vue === 'RECETTE' ? 'RECETTES' : 'DÉPENSES'} ${annee}`, pageWidth / 2, 50, { align: 'center' })

  doc.setFontSize(10)
  doc.setTextColor(0)
  doc.setFont('helvetica', 'normal')
  doc.text(
    vue === 'RECETTE'
      ? 'Suivi de la réalisation des recettes par poste et sous-poste'
      : "Suivi de l'exécution des dépenses par poste et sous-poste",
    pageWidth / 2,
    60,
    { align: 'center' }
  )

  // Statistiques par ligne : montants + taux d'exécution (consommé / plafond).
  const rowStats = lignes.map(ligne => {
    const prevu = toNumber(ligne.montant_prevu)
    const consomme = toNumber(ligne.montant_paye)
    const pct = prevu > 0 ? (consomme / prevu) * 100 : 0
    return { ligne, prevu, consomme, pct }
  })

  const tableData = rowStats.map(({ ligne, prevu, consomme, pct }) => [
    // Marqueur hiérarchique : « » » répété selon le niveau signale un poste parent.
    ligne.is_parent
      ? `${'»'.repeat(Math.min((ligne.level ?? 0) + 1, 3))} ${ligne.code || ''}`
      : (ligne.code || ''),
    ligne.libelle || '',
    `${formatAmount(prevu)} $`,
    `${formatAmount(consomme)} $`,
    prevu > 0 ? `${pct.toFixed(1)} %` : '—',
    vue === 'RECETTE'
      ? `${formatAmount(consomme - prevu)} $`
      : `${formatAmount(ligne.montant_disponible)} $`
  ])

  autoTable(doc, {
    head: [[
      'Code',
      'Poste budgétaire',
      vue === 'RECETTE' ? 'Objectif' : 'Plafond',
      vue === 'RECETTE' ? 'Atteint' : 'Consommé',
      vue === 'RECETTE' ? "Taux d'atteinte" : "Taux d'exéc.",
      vue === 'RECETTE' ? 'Écart' : 'Disponible'
    ]],
    body: tableData,
    startY: 70,
    theme: 'grid',
    headStyles: {
      fillColor: ONEC_GREEN,
      textColor: 255,
      fontStyle: 'bold',
      fontSize: 9
    },
    bodyStyles: {
      fontSize: 8,
      cellPadding: 3
    },
    alternateRowStyles: {
      fillColor: [245, 245, 245]
    },
    columnStyles: {
      0: { cellWidth: 24 },
      1: { cellWidth: 54 },
      2: { cellWidth: 26, halign: 'right' },
      3: { cellWidth: 26, halign: 'right' },
      4: { cellWidth: 24, halign: 'right', fontStyle: 'bold' },
      5: { cellWidth: 26, halign: 'right' }
    },
    didParseCell: (data: any) => {
      if (data.section !== 'body') return
      const stat = rowStats[data.row.index]
      const lvl = Math.max(0, stat?.ligne.level ?? 0)
      // Poste parent : gras + fond vert d'autant plus intense qu'il est haut dans
      // la hiérarchie (niveau 0 = plus foncé), pour bien distinguer les niveaux.
      if (stat?.ligne.is_parent) {
        const parentFills = ['#6ee7b7', '#a7f3d0', '#c6f6df', '#d1fae5']
        data.cell.styles.fillColor = parentFills[Math.min(lvl, parentFills.length - 1)]
        data.cell.styles.fontStyle = 'bold'
        data.cell.styles.textColor = '#064e3b'
      }
      // Indentation du libellé selon le niveau dans l'arborescence.
      if (data.column.index === 1) {
        data.cell.styles.cellPadding = { top: 3, right: 3, bottom: 3, left: 3 + lvl * 4 }
      }
      // Code couleur du taux d'exécution : vert < 90 %, orange 90-99 %, rouge >= 100 %.
      if (data.column.index === 4) {
        const pct = parseFloat(String(data.cell.raw))
        if (!isNaN(pct)) {
          if (pct >= 100) data.cell.styles.textColor = '#dc2626'
          else if (pct >= 90) data.cell.styles.textColor = '#b45309'
          else data.cell.styles.textColor = ONEC_GREEN
        }
      }
    },
    didDrawPage: () => {
      addFooter(doc.getNumberOfPages())
    }
  })

  // ── Synthèse budgétaire enrichie + représentation graphique ───────────────
  const isRecette = vue === 'RECETTE'
  const totalConsomme = totalPaye
  const tauxGlobal = totalPrevu > 0 ? (totalConsomme / totalPrevu) * 100 : 0
  // Indicateurs et top 5 comptent les sous-postes réels (feuilles), pas les parents.
  const leafStats = rowStats.filter(r => !r.ligne.is_parent)
  const nbPostes = leafStats.length
  const nbEntames = leafStats.filter(r => r.consomme > 0).length
  const nbProches = leafStats.filter(r => r.pct >= 90 && r.pct < 100).length
  const nbDepassements = leafStats.filter(r => r.pct >= 100).length

  const marginX = 10
  const contentW = pageWidth - marginX * 2

  // Saut de page si l'espace restant est insuffisant pour la synthèse complète.
  let y = (doc as any).lastAutoTable.finalY + 10
  if (y + 118 > pageHeight - 12) {
    doc.addPage()
    addFooter(doc.getNumberOfPages())
    y = 20
  }

  // Bandeau de section
  doc.setFillColor(ONEC_GREEN)
  doc.rect(marginX, y, contentW, 8, 'F')
  doc.setFontSize(11)
  doc.setTextColor(255)
  doc.setFont('helvetica', 'bold')
  doc.text('SYNTHÈSE BUDGÉTAIRE', marginX + 4, y + 5.6)
  y += 13

  // Cartes KPI (3 colonnes)
  const kpis = isRecette
    ? [
        { label: 'Objectif total', value: `${formatAmount(totalPrevu)} $` },
        { label: 'Recettes atteintes', value: `${formatAmount(totalConsomme)} $` },
        { label: "Taux d'atteinte", value: `${tauxGlobal.toFixed(1)} %` },
      ]
    : [
        { label: 'Plafond total', value: `${formatAmount(totalPrevu)} $` },
        { label: 'Total consommé', value: `${formatAmount(totalConsomme)} $` },
        { label: 'Disponible', value: `${formatAmount(totalDisponible)} $` },
      ]
  const cardW = (contentW - 8) / 3
  kpis.forEach((k, i) => {
    const cx = marginX + i * (cardW + 4)
    doc.setDrawColor(ONEC_GREEN)
    doc.setFillColor(ONEC_LIGHT_GREEN)
    doc.roundedRect(cx, y, cardW, 18, 2, 2, 'FD')
    doc.setFontSize(7.5)
    doc.setTextColor(90)
    doc.setFont('helvetica', 'normal')
    doc.text(k.label.toUpperCase(), cx + 3, y + 6)
    doc.setFontSize(12)
    doc.setTextColor(ONEC_GREEN)
    doc.setFont('helvetica', 'bold')
    doc.text(k.value, cx + 3, y + 14)
  })
  y += 24

  // Jauge d'exécution globale
  const level = tauxGlobal >= 100 ? '#dc2626' : tauxGlobal >= 90 ? '#b45309' : ONEC_GREEN
  doc.setFontSize(8.5)
  doc.setTextColor(0)
  doc.setFont('helvetica', 'bold')
  doc.text(isRecette ? "Taux d'atteinte global" : "Taux d'exécution global du budget", marginX, y)
  const gaugeY = y + 2.5
  const gaugeH = 6
  doc.setFillColor(230, 230, 230)
  doc.roundedRect(marginX, gaugeY, contentW, gaugeH, 1.5, 1.5, 'F')
  const fillW = Math.max(0, Math.min(1, tauxGlobal / 100)) * contentW
  if (fillW > 0.5) {
    doc.setFillColor(level)
    doc.roundedRect(marginX, gaugeY, fillW, gaugeH, 1.5, 1.5, 'F')
  }
  doc.setFontSize(8)
  doc.setFont('helvetica', 'bold')
  if (fillW > 22) {
    doc.setTextColor(255)
    doc.text(`${tauxGlobal.toFixed(1)} %`, marginX + 3, gaugeY + 4.3)
  } else {
    doc.setTextColor(0)
    doc.text(`${tauxGlobal.toFixed(1)} %`, marginX + fillW + 3, gaugeY + 4.3)
  }
  y = gaugeY + gaugeH + 8

  // Indicateurs de suivi (dépenses)
  if (!isRecette) {
    doc.setFontSize(8)
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(60)
    doc.text(
      `${nbPostes} postes  ·  ${nbEntames} entamés  ·  ${nbProches} proche(s) du plafond (90-99 %)`,
      marginX,
      y
    )
    y += 5
    if (nbDepassements > 0) {
      doc.setTextColor('#dc2626')
      doc.setFont('helvetica', 'bold')
      doc.text(`Attention : ${nbDepassements} poste(s) au plafond ou en dépassement (>= 100 %)`, marginX, y)
      y += 5
    }
  }
  y += 3

  // Top 5 postes consommés — barres horizontales
  const top = [...leafStats]
    .filter(r => r.consomme > 0)
    .sort((a, b) => b.consomme - a.consomme)
    .slice(0, 5)
  if (top.length > 0) {
    doc.setFontSize(8.5)
    doc.setTextColor(0)
    doc.setFont('helvetica', 'bold')
    doc.text(isRecette ? 'Top 5 des recettes' : 'Top 5 des postes les plus consommés', marginX, y)
    y += 4.5
    const maxV = top[0].consomme || 1
    const labelW = 56
    const barMaxW = contentW - labelW - 32
    top.forEach(r => {
      const label = (r.ligne.libelle || r.ligne.code || '').slice(0, 36)
      doc.setFontSize(7)
      doc.setTextColor(60)
      doc.setFont('helvetica', 'normal')
      doc.text(label, marginX, y + 3)
      const bw = Math.max(1, (r.consomme / maxV) * barMaxW)
      const barColor = r.pct >= 100 ? '#dc2626' : r.pct >= 90 ? '#b45309' : ONEC_GREEN
      doc.setFillColor(barColor)
      doc.roundedRect(marginX + labelW, y, bw, 4, 0.8, 0.8, 'F')
      doc.setTextColor(0)
      doc.setFontSize(6.5)
      doc.text(`${formatAmount(r.consomme)} $`, marginX + labelW + bw + 2, y + 3.2)
      y += 6
    })
  }

  // QR d'authenticité (bas de page)
  if (qrDataUrl) {
    const qrSize = 18
    const qrX = pageWidth - marginX - qrSize
    const qrY = pageHeight - 26
    doc.setFontSize(7)
    doc.setTextColor(110)
    doc.setFont('helvetica', 'normal')
    doc.text("Scannez pour vérifier l'authenticité", qrX + qrSize, qrY - 2, { align: 'right' })
    doc.addImage(qrDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
  }

  doc.save(`budget_${annee}_${vue}.pdf`)
}

export const generateServiceBudgetReportPDF = async ({
  lignes,
  annee,
  vue,
  serviceLabel,
  totals,
}: {
  lignes: Array<{
    code: string
    libelle: string
    type?: string | null
    montant_prevu: string | number
    montant_engage: string | number
    montant_paye: string | number
    montant_disponible: string | number
    pourcentage_consomme: string | number
  }>
  annee: number
  vue: 'DEPENSE' | 'RECETTE'
  serviceLabel: string
  totals: { recettes: number; depenses: number; solde: number }
}) => {
  const settings = await getPrintSettingsData()
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()

  const addHeader = () => {
    doc.setDrawColor(ONEC_GREEN)
    doc.setLineWidth(3)
    doc.line(10, 40, pageWidth - 10, 40)

    doc.setFontSize(18)
    doc.setTextColor(ONEC_GREEN)
    doc.setFont('helvetica', 'bold')
    doc.text('ORDRE NATIONAL DES EXPERTS-COMPTABLES', pageWidth / 2, 15, { align: 'center' })

    doc.setFontSize(14)
    doc.setTextColor(0, 0, 0)
    doc.setFont('times', 'bolditalic')
    doc.text(settings?.organization_name || DEFAULT_TENANT_NAME, pageWidth / 2, 23, { align: 'center' })

    doc.setFontSize(12)
    doc.setTextColor(0, 0, 0)
    doc.setFont('helvetica', 'normal')
    doc.text("Plateforme intelligente de gestion intégrée de l'ONEC-RDC", pageWidth / 2, 32, { align: 'center' })
  }

  const addFooter = (pageNumber: number) => {
    doc.setFontSize(8)
    doc.setTextColor(100)
    doc.text(`${format(new Date(), 'dd/MM/yyyy HH:mm')}`, 10, pageHeight - 10)
    doc.text(getReportLabel('Rapport de consommation', settings?.organization_name), pageWidth / 2, pageHeight - 10, { align: 'center' })
    doc.text(`Page ${pageNumber}`, pageWidth - 20, pageHeight - 10)
  }

  addHeader()

  doc.setFontSize(15)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text(`Rapport de consommation - ${serviceLabel}`, pageWidth / 2, 50, { align: 'center' })

  doc.setFontSize(11)
  doc.setTextColor(0)
  doc.setFont('helvetica', 'normal')
  doc.text(`Exercice ${annee} · Vue ${vue === 'RECETTE' ? 'Recettes' : 'Dépenses'}`, pageWidth / 2, 58, {
    align: 'center',
  })

  const cardY = 66
  const cardWidth = (pageWidth - 30) / 3
  const cardHeight = 16
  const cardTitles = ['Recettes', 'Dépenses', 'Solde']
  const cardValues = [totals.recettes, totals.depenses, totals.solde]

  cardTitles.forEach((title, index) => {
    const x = 10 + index * (cardWidth + 5)
    doc.setDrawColor(ONEC_GREEN)
    doc.setFillColor(ONEC_LIGHT_GREEN)
    doc.roundedRect(x, cardY, cardWidth, cardHeight, 2, 2, 'FD')
    doc.setFontSize(9)
    doc.setTextColor(0)
    doc.text(title, x + 4, cardY + 6)
    doc.setFontSize(11)
    doc.setTextColor(ONEC_GREEN)
    doc.text(`${formatAmount(cardValues[index])} $`, x + 4, cardY + 13)
  })

  const tableData = lignes.map((ligne) => [
    ligne.code || '',
    ligne.libelle || '',
    `${formatAmount(ligne.montant_prevu)} $`,
    `${formatAmount(ligne.montant_paye)} $`,
    vue === 'RECETTE'
      ? `${formatAmount(toNumber(ligne.montant_paye) - toNumber(ligne.montant_prevu))} $`
      : `${formatAmount(ligne.montant_disponible)} $`,
  ])

  autoTable(doc, {
    head: [[
      'Code',
      'Poste budgétaire',
      vue === 'RECETTE' ? 'Objectif' : 'Plafond',
      vue === 'RECETTE' ? 'Atteint' : 'Consommé',
      vue === 'RECETTE' ? 'Écart' : 'Disponible',
    ]],
    body: tableData,
    startY: cardY + cardHeight + 8,
    theme: 'grid',
    headStyles: {
      fillColor: ONEC_GREEN,
      textColor: 255,
      fontStyle: 'bold',
      fontSize: 9,
    },
    bodyStyles: {
      fontSize: 8,
      cellPadding: 3,
    },
    alternateRowStyles: {
      fillColor: [245, 245, 245],
    },
    columnStyles: {
      0: { cellWidth: 22 },
      1: { cellWidth: 70 },
      2: { cellWidth: 28, halign: 'right' },
      3: { cellWidth: 28, halign: 'right' },
      4: { cellWidth: 28, halign: 'right' },
    },
    didDrawPage: () => {
      addFooter(doc.getNumberOfPages())
    },
  })

  doc.save(`rapport_service_${annee}_${serviceLabel.replace(/\s+/g, '_')}.pdf`)
}

export const generateSingleRequisitionPDF = async (
  requisition: any,
  lignes: any[],
  action: 'print' | 'download' | 'blob' = 'download',
  _userName: string
): Promise<Blob | void> => {
  const settings = await getPrintSettingsData()
  const historicalSettings = requisition?.print_settings_snapshot || null
  const effectiveSettings = historicalSettings || settings
  const logoDataUrl = effectiveSettings?.show_header_logo === false ? null : await getLogoDataUrl()
  const stampDataUrl = await getStampDataUrl()
  const exchangeRate = requisition?.exchange_rate_snapshot
    ? Number(requisition.exchange_rate_snapshot)
    : effectiveSettings?.exchange_rate_cdf
    ? Number(effectiveSettings.exchange_rate_cdf)
    : effectiveSettings?.exchange_rate
      ? Number(effectiveSettings.exchange_rate)
      : 0
  const formatUserName = (user: any) => {
    if (!user) return 'N/A'
    const fullName = `${user.prenom || ''} ${user.nom || ''}`.trim()
    return fullName || 'N/A'
  }

  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const pageMargin = 15
  const contentWidth = pageWidth - (pageMargin * 2)
  const footerReserve = 18
  const contentBottomLimit = pageHeight - footerReserve
  const signatureBlockHeight = 24
  const qrBlockHeight = 18
  const stampBlockHeight = stampDataUrl ? 28 : 0
  const footerGap = 8
  const ensureSpace = (currentY: number, requiredHeight: number, nextStartY = 22) => {
    if (currentY + requiredHeight <= contentBottomLimit) {
      return currentY
    }
    doc.addPage()
    return nextStartY
  }
  const drawPageFooter = (pageNumber: number, totalPages: number) => {
    doc.setPage(pageNumber)
    doc.setDrawColor(220)
    doc.setLineWidth(0.2)
    doc.line(pageMargin, pageHeight - 14, pageWidth - pageMargin, pageHeight - 14)
    doc.setFontSize(8)
    doc.setTextColor(100)
    const footerLabel = getReportLabel('Réquisition de fonds', effectiveSettings?.organization_name)
    const footerDate = requisition?.snapshot_created_at
      ? format(new Date(requisition.snapshot_created_at), 'dd/MM/yyyy')
      : format(new Date(), 'dd/MM/yyyy')
    doc.text(`${footerLabel} | ${footerDate}`, pageWidth / 2, pageHeight - 9, { align: 'center' })
    doc.text(`Page ${pageNumber}/${totalPages}`, pageWidth - pageMargin, pageHeight - 9, { align: 'right' })
  }

  const orgSnapshot = requisition?.organisation_snapshot || null
  const orgName =
    getTrimmedSetting(effectiveSettings?.organization_name) ||
    getTrimmedSetting(orgSnapshot?.nom) ||
    DEFAULT_REQUISITION_ORG_NAME
  const orgSubtitle = getTrimmedSetting(effectiveSettings?.organization_subtitle)
  const fiscalYear = effectiveSettings?.fiscal_year || new Date().getFullYear()
  const refNumber = requisition.numero_requisition || requisition.id || 'N/A'
  const createdAt = requisition.created_at ? new Date(requisition.created_at) : new Date()
  const logoX = 15
  const logoY = 12
  const logoSize = 26
  const leftStartX = logoDataUrl ? logoX + logoSize + 9 : pageMargin
  const rightBlockWidth = 58
  const rightStartX = pageWidth - pageMargin - rightBlockWidth
  const leftBlockWidth = Math.max(55, rightStartX - leftStartX - 8)

  if (logoDataUrl) {
    addLogo(doc, logoX, logoY, logoSize, logoDataUrl)
  }

  const orgNameLines = doc.splitTextToSize(orgName.toUpperCase(), leftBlockWidth)
  const orgSubtitleLines = orgSubtitle ? doc.splitTextToSize(orgSubtitle, leftBlockWidth) : []
  const headerText = effectiveSettings?.header_text ? String(effectiveSettings.header_text).trim() : ''
  const headerTextLines = headerText ? doc.splitTextToSize(headerText, leftBlockWidth) : []
  const rightInfoLines = [
    `N° ${refNumber}`,
    `Date : ${format(createdAt, 'dd/MM/yyyy')}`,
    `Exercice : ${fiscalYear}`,
    ...(requisition.reference_numero ? [`Réf. Externe : ${requisition.reference_numero}`] : []),
  ].flatMap((line) => doc.splitTextToSize(line, rightBlockWidth))

  doc.setTextColor(0)
  doc.setFont('times', 'bold')
  doc.setFontSize(14)
  let currentLeftY = 20
  doc.text(orgNameLines, leftStartX, currentLeftY)
  doc.setFont('times', 'normal')
  doc.setFontSize(10)
  currentLeftY += orgNameLines.length * 5.5
  if (orgSubtitleLines.length > 0) {
    doc.text(orgSubtitleLines, leftStartX, currentLeftY)
    currentLeftY += orgSubtitleLines.length * 4.5
  }
  if (headerTextLines.length > 0) {
    doc.setFontSize(9)
    doc.setTextColor(70)
    doc.text(headerTextLines, leftStartX, currentLeftY)
    currentLeftY += headerTextLines.length * 4
  }

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(60)
  
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.setTextColor(41, 128, 185)
  let currentRightY = 20
  if (rightInfoLines.length > 0) {
    doc.text(rightInfoLines[0], pageWidth - pageMargin, currentRightY, { align: 'right' })
    currentRightY += 5.5
  }
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(100)
  const secondaryRightLines = rightInfoLines.slice(1)
  secondaryRightLines.forEach((line, index) => {
    doc.setFontSize(index >= 2 ? 8 : 9)
    doc.text(line, pageWidth - pageMargin, currentRightY, { align: 'right' })
    currentRightY += index >= 2 ? 4 : 4.5
  })

  const headerBottomY = Math.max(logoY + logoSize, currentLeftY, currentRightY) + 6
  const titleY = headerBottomY + 10
  const infoTableStartY = titleY + 8
  const separatorY = headerBottomY

  if (separatorY > 44) {
    doc.setDrawColor(230)
    doc.setLineWidth(0.2)
    doc.line(rightStartX - 4, 14, rightStartX - 4, separatorY - 2)
  }
  
  doc.setTextColor(0)

  doc.setDrawColor(0)
  doc.setLineWidth(0.5)
  doc.line(15, separatorY, pageWidth - 15, separatorY)
  doc.setFont('times', 'bold')
  doc.setFontSize(16)
  doc.text(
    requisition.req_titre_officiel_hist ||
      effectiveSettings?.req_titre_officiel ||
      'BON DE RÉQUISITION DE FONDS',
    pageWidth / 2,
    titleY,
    { align: 'center' }
  )

  const rawStatus = String((requisition as any).statut ?? (requisition as any).status ?? '').toUpperCase()
  const statut = rawStatus === 'EN_ATTENTE_COMMISSION'
    ? 'Attente signature commission'
    : rawStatus === 'EN_ATTENTE' || rawStatus === 'BROUILLON' || rawStatus === 'A_VALIDER'
    ? 'En attente validation 1/2'
    : rawStatus === 'AUTORISEE' || rawStatus === 'VALIDEE'
    ? 'Validation 1/2'
    : rawStatus === 'APPROUVEE'
    ? 'Validation 2/2'
    : rawStatus === 'PAYEE'
    ? 'Payée'
    : rawStatus === 'REJETEE'
    ? 'Rejetée'
    : rawStatus || 'En attente validation 1/2'
  const modePaiement = requisition.mode_paiement === 'cash' ? 'Caisse' :
    requisition.mode_paiement === 'mobile_money' ? 'Mobile Money' :
    requisition.mode_paiement === 'card' ? 'Carte (Visa)' : 'Opération bancaire'

  const infoLeft: [string, string][] = [
    ['Objet / Motif', requisition.objet || '-'],
    ['Poste budgétaire principal', lignes?.[0]?.rubrique || '-'],
  ]
  const infoRight: [string, string][] = [
    ['Demandeur', formatUserName(requisition.demandeur)],
    ['Mode de paiement', modePaiement],
    ['Statut', statut],
  ]
  const examinateur = formatUserName(requisition.examinateur)
  const val1 = formatUserName(requisition.validateur)
  const val2 = formatUserName(requisition.approbateur)
  infoRight.push(['Examinateur', examinateur])
  infoRight.push(['Validation 1/2', val1])
  infoRight.push(['Validation 2/2', val2])

  const maxInfoRows = Math.max(infoLeft.length, infoRight.length)
  const infoRows = Array.from({ length: maxInfoRows }).map((_, idx) => {
    const left = infoLeft[idx] || ['', '']
    const right = infoRight[idx] || ['', '']
    return [left[0], left[1], right[0], right[1]]
  })

  autoTable(doc, {
    tableWidth: contentWidth,
    margin: { left: pageMargin, right: pageMargin },
    startY: infoTableStartY,
    theme: 'grid',
    styles: { font: 'times', fontSize: 9, cellPadding: 2.6, lineColor: [215, 215, 215], lineWidth: 0.15, valign: 'middle' },
    columnStyles: {
      0: { cellWidth: 40, fontStyle: 'bold' },
      1: { cellWidth: 70 },
      2: { cellWidth: 40, fontStyle: 'bold' },
      3: { cellWidth: 40 },
    },
    body: infoRows,
  })

  let yPos = (doc as any).lastAutoTable.finalY + 8

  const tableData = lignes.map(ligne => {
    const devise = (ligne.devise || 'USD').toUpperCase()
    const isCdf = devise === 'CDF'
    const montantUnitaire = isCdf && exchangeRate ? toNumber(ligne.montant_unitaire) * exchangeRate : ligne.montant_unitaire
    const montantTotal = isCdf && exchangeRate ? toNumber(ligne.montant_total) * exchangeRate : ligne.montant_total
    const currencyLabel = devise === 'CDF' ? 'CDF' : '$'
    return [
      ligne.rubrique,
      ligne.description,
      devise,
      ligne.quantite.toString(),
      `${formatAmount(montantUnitaire)} ${currencyLabel}`,
      `${formatAmount(montantTotal)} ${currencyLabel}`
    ]
  })

  autoTable(doc, {
    tableWidth: contentWidth,
    margin: { left: pageMargin, right: pageMargin },
    head: [['Poste budgétaire', 'Description', 'Devise', 'Qté', 'PU', 'Total']],
    body: tableData,
    startY: yPos,
    theme: 'grid',
    pageBreak: 'auto',
    rowPageBreak: 'avoid',
    headStyles: {
      fillColor: [31, 41, 55],
      textColor: 255,
      fontStyle: 'bold',
      fontSize: 8.5,
      font: 'times',
      cellPadding: 3
    },
    bodyStyles: {
      fontSize: 8,
      cellPadding: 2.8,
      font: 'times',
      lineColor: [225, 225, 225],
      lineWidth: 0.15,
      overflow: 'linebreak',
      valign: 'top'
    },
    alternateRowStyles: {
      fillColor: [249, 250, 251]
    },
    columnStyles: {
      0: { cellWidth: 32 },
      1: { cellWidth: 76 },
      2: { cellWidth: 14, halign: 'center' },
      3: { cellWidth: 12, halign: 'center' },
      4: { cellWidth: 23, halign: 'right' },
      5: { cellWidth: 23, halign: 'right' }
    },
    foot: [[
      { content: 'MONTANT TOTAL', colSpan: 5, styles: { halign: 'right', fontStyle: 'bold' } },
      { content: `${formatAmount(requisition.montant_total)} USD`, styles: { fontStyle: 'bold', halign: 'right' } }
    ]],
    footStyles: {
      fillColor: [241, 245, 249],
      textColor: 15,
      fontStyle: 'bold',
      lineColor: [203, 213, 225],
      lineWidth: 0.2,
    },
  })

  let finalY = (doc as any).lastAutoTable.finalY + 8

  const totalUsd = Number(requisition.montant_total || 0)
  const totalCdf = exchangeRate ? totalUsd * exchangeRate : 0
  finalY = ensureSpace(finalY, 28)
  autoTable(doc, {
    tableWidth: contentWidth,
    margin: { left: pageMargin, right: pageMargin },
    startY: finalY,
    theme: 'grid',
    styles: { font: 'times', fontSize: 8.5, cellPadding: 2.5, lineColor: [220, 220, 220], lineWidth: 0.15 },
    columnStyles: { 0: { cellWidth: 55, fontStyle: 'bold' } },
    body: [
      ['Montant sollicité (USD)', `${formatAmount(totalUsd)} USD`],
      ['Taux de change', exchangeRate ? `1 USD = ${formatAmount(exchangeRate)} CDF` : 'Non défini'],
      ['Équivalent (CDF)', exchangeRate ? `${formatAmount(totalCdf)} CDF` : 'Non défini'],
    ],
  })

  finalY = (doc as any).lastAutoTable.finalY + 8

  doc.setFontSize(9)
  doc.setFont('times', 'italic')
  doc.setTextColor(60)
  const montantEnLettres = numberToWords(Number(requisition.montant_total))
  const montantLines = doc.splitTextToSize(`Montant total en lettres : ${montantEnLettres}`, pageWidth - 30)
  finalY = ensureSpace(finalY, (montantLines.length * 5) + 10)
  doc.text(montantLines, 15, finalY)
  finalY += (montantLines.length * 5) + 8

  if (requisition.a_valoir) {
    const notesLines = requisition.notes_a_valoir
      ? doc.splitTextToSize(`Notes: ${requisition.notes_a_valoir}`, pageWidth - 30)
      : []
    const aValoirHeight = Math.max(25, 18 + (notesLines.length * 5))
    finalY = ensureSpace(finalY, aValoirHeight + footerGap)
    doc.setDrawColor('#f59e0b')
    doc.setFillColor('#fef3c7')
    doc.roundedRect(10, finalY, pageWidth - 20, aValoirHeight, 3, 3, 'FD')

    doc.setFontSize(10)
    doc.setTextColor('#92400e')
    doc.setFont('times', 'bold')
    doc.text('⚠ RÉQUISITION À VALOIR', 15, finalY + 8)

    doc.setFont('times', 'normal')
    doc.setFontSize(9)
    doc.text(`Instance bénéficiaire: ${requisition.instance_beneficiaire || 'N/A'}`, 15, finalY + 15)
    if (notesLines.length > 0) {
      doc.text(notesLines, 15, finalY + 20)
    }
    finalY += aValoirHeight + 6
  }

  const signatureAreaHeight = Math.max(signatureBlockHeight + stampBlockHeight, qrBlockHeight + 22)
  finalY = ensureSpace(finalY + 2, signatureAreaHeight + footerGap, 24)
  const signatureY = Math.max(finalY + 10, 34)
  const labelGauche =
    requisition.signataire_g_label ||
    requisition.req_label_gauche_hist ||
    effectiveSettings?.req_label_gauche ||
    'Établi par'
  const nomGauche =
    requisition.signataire_g_nom ||
    requisition.req_nom_gauche_hist ||
    effectiveSettings?.req_nom_gauche ||
    ''
  const labelDroite =
    requisition.signataire_d_label ||
    requisition.req_label_droite_hist ||
    effectiveSettings?.req_label_droite ||
    'Approuvé par'
  const nomDroite =
    requisition.signataire_d_nom ||
    requisition.req_nom_droite_hist ||
    effectiveSettings?.req_nom_droite ||
    ''

  doc.setFont('times', 'bold')
  doc.setFontSize(10)
  doc.setTextColor(0)
  doc.text(labelGauche, 20, signatureY)
  doc.text(labelDroite, pageWidth - 70, signatureY)
  doc.setFont('times', 'normal')
  doc.setDrawColor(120)
  doc.setLineWidth(0.2)
  doc.line(20, signatureY + 14, 78, signatureY + 14)
  doc.line(pageWidth - 70, signatureY + 14, pageWidth - 20, signatureY + 14)
  if (nomGauche) {
    doc.text(nomGauche, 20, signatureY + 6)
  } else {
    doc.text('................................', 20, signatureY + 6)
  }
  if (nomDroite) {
    doc.text(nomDroite, pageWidth - 70, signatureY + 6)
  } else {
    doc.text('................................', pageWidth - 70, signatureY + 6)
  }

  if (stampDataUrl) {
    const stampSize = 26
    const stampX = pageWidth - stampSize - 20
    const stampY = signatureY + 16
    doc.addImage(stampDataUrl, 'PNG', stampX, stampY, stampSize, stampSize)
  }

  const baseUrl = typeof window !== 'undefined' ? window.location.origin : ''
  const qrPayload = baseUrl
    ? `${baseUrl}/api/v1/requisitions/verify?ref=${encodeURIComponent(String(refNumber))}&amount=${encodeURIComponent(totalUsd.toFixed(2))}`
    : `REQ:${refNumber}|AMT:${formatAmount(totalUsd)}USD|ORG:${orgName}`
  if (settings?.afficher_qr_code !== false) {
    try {
      const { default: QRCode } = await import('qrcode')
      const qrDataUrl = await QRCode.toDataURL(qrPayload, { margin: 1, width: 80 })
      const qrX = 15
      const qrY = Math.min(pageHeight - 40, signatureY + 18)
      const qrSize = 16
      doc.setFontSize(8)
      doc.setTextColor(90)
      doc.setFillColor(255, 255, 255)
      doc.rect(qrX, qrY - 8, 76, 6, 'F')
      doc.text("Scannez pour vérifier l'authenticité", qrX, qrY - 4)
      doc.addImage(qrDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
    } catch (_err) {
      // Si QRCode n'est pas disponible, on ignore sans bloquer le PDF.
    }
  }

  const totalPages = doc.getNumberOfPages()
  for (let page = 1; page <= totalPages; page += 1) {
    drawPageFooter(page, totalPages)
  }

  if (action === 'print') {
    openPdfInNewTab(doc)
  } else if (action === 'blob') {
    return doc.output('blob')
  } else {
    doc.save(`requisition_${requisition.numero_requisition}.pdf`)
  }
}

export const generateGroupedRequisitionPDF = async (dossier: any) => {
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()

  doc.setFontSize(18)
  doc.setTextColor(0, 160, 157)
  doc.text(`DOSSIER D'EXAMEN ${dossier.reference || ''}`, 14, 22)
  doc.setDrawColor(0, 160, 157)
  doc.line(14, 26, pageWidth - 14, 26)

  const requisitions = Array.isArray(dossier.requisitions) ? dossier.requisitions : []
  autoTable(doc, {
    startY: 32,
    head: [['ID', 'Bénéficiaire', 'Objet', 'Montant']],
    body: requisitions.map((r: any) => [
      r.numero_requisition || r.id || '-',
      r.demandeur ? `${r.demandeur.prenom || ''} ${r.demandeur.nom || ''}`.trim() : '-',
      r.objet || '-',
      `${Number(r.montant_total || 0).toLocaleString('fr-FR')} USD`,
    ]),
    theme: 'striped',
    headStyles: { fillColor: [0, 160, 157] },
    styles: { fontSize: 9 },
  })

  const finalY = (doc as any).lastAutoTable?.finalY || 60
  const boxY = finalY + 16
  doc.setDrawColor(200)
  doc.rect(14, boxY, pageWidth - 28, 26)
  doc.setFontSize(10)
  doc.setTextColor(60)
  doc.text("VISA SECRÉTARIAT EXÉCUTIF (EXAMEN)", 20, boxY + 10)
  doc.text(`Date : ____/____/${new Date().getFullYear()}`, 20, boxY + 20)

  doc.save(`Dossier_Requisition_${dossier.reference || dossier.id || 'groupe'}.pdf`)
}
