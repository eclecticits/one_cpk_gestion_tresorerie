import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { fr } from 'date-fns/locale'
import type { PrintSettings } from '../api/settings'
import { numberToWords } from './numberToWords'
import { formatAmount, toNumber } from './amount'
import { API_BASE_URL } from '../lib/apiClient'
import { getOperationLabel, getTypeClientLabel } from './encaissementHelpers'

const ONEC_GREEN = '#2d6a4f'
const ONEC_LIGHT_GREEN = '#95d5b2'
const ONEC_LIGHT_BG = '#ecfdf5'
const HEADER_HEIGHT = 28
const LOGO_SIZE = 20
const HEADER_CENTER_X = (docWidth: number) => docWidth / 2

let cachedLogoDataUrl: string | null = null
let cachedLogoUrl: string | null = null
let cachedStampDataUrl: string | null = null
let cachedStampUrl: string | null = null
let cachedSettings: any | null = null

const getPrintSettingsData = async () => {
  if (cachedSettings) return cachedSettings
  try {
    const token =
      (typeof window !== 'undefined' &&
        (window.localStorage.getItem('access_token') ||
          window.localStorage.getItem('token') ||
          window.localStorage.getItem('onec_cpk_access_token'))) ||
      null
    const settingsRes = await fetch(`${API_BASE_URL}/print-settings`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
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
  if (cachedLogoDataUrl) return cachedLogoDataUrl
  try {
    const settings = await getPrintSettingsData()
    cachedLogoUrl = settings?.logo_url || null
    const logoPath = cachedLogoUrl || '/imge_onec.png'
    const res = await fetch(logoPath, { credentials: 'include' })
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
  if (cachedStampDataUrl) return cachedStampDataUrl
  try {
    if (!cachedStampUrl) {
      const settings = await getPrintSettingsData()
      cachedStampUrl = settings?.stamp_url || null
    }
    if (!cachedStampUrl) return null
    const res = await fetch(cachedStampUrl, { credentials: 'include' })
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

const DEFAULT_ORG_NAME = 'ONEC/CPK'
const DEFAULT_ORG_SUBTITLE = 'Conseil Provincial de Kinshasa'
const DEFAULT_FOOTER_TEXT = 'Document généré automatiquement © 2026 ONEC (Dev: kidikala@gmail.com)'

export const generateReceiptPDF = async (encaissement: any, options: ReceiptPdfOptions = {}) => {
  const paperFormat = options.format ?? 'a5'
  const isA5 = paperFormat === 'a5'
  const compactHeader = options.compactHeader ?? false
  const settings = options.settings ?? (await getPrintSettingsData())
  const logoDataUrl = settings?.show_header_logo === false ? null : await getLogoDataUrl()
  const stampDataUrl = settings?.show_footer_signature === false ? null : await getStampDataUrl()
  let receiptQrDataUrl: string | null = null
  const marginLeft = 0
  const marginRight = 0
  const marginTop = 0
  const marginBottom = 55

  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: paperFormat })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()

  if (options.duplicate) {
    doc.setTextColor(230)
    doc.setFont('times', 'bold')
    doc.setFontSize(isA5 ? 24 : 32)
    doc.text('DUPLICATA', pageWidth / 2, pageHeight / 2, { align: 'center', angle: 35 })
  }

  const headerTop = marginTop
  if (logoDataUrl) {
    const logoSize = compactHeader ? (isA5 ? 16 : 20) : isA5 ? 18 : 22
    doc.addImage(logoDataUrl, 'PNG', marginLeft, headerTop, logoSize, logoSize)
  }

  doc.setTextColor(0)
  doc.setFont('times', 'bold')
  doc.setFontSize(isA5 ? 11 : 14)
  const headerTextX = marginLeft + (isA5 ? 24 : 28) + 4
  const headerLineStartY = headerTop + (isA5 ? 4.5 : 6)
  const headerLineGap = compactHeader ? (isA5 ? 3.8 : 5) : isA5 ? 5 : 7
  let headerLineY = headerLineStartY
  doc.text(settings?.organization_name || DEFAULT_ORG_NAME, headerTextX, headerLineY)

  doc.setFont('times', 'normal')
  doc.setFontSize(isA5 ? 8 : 10)
  headerLineY += headerLineGap
  doc.text(DEFAULT_ORG_SUBTITLE, headerTextX, headerLineY)
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
  doc.setDrawColor(45, 106, 79)
  doc.setLineWidth(0.6)
  doc.line(marginLeft, headerBottom, pageWidth - marginRight, headerBottom)

  doc.setFont('times', 'bold')
  doc.setFontSize(isA5 ? 13 : 16)
  doc.text(`REÇU DE PAIEMENT N° ${encaissement.numero_recu || ''}`, pageWidth / 2, headerBottom + 10, {
    align: 'center',
  })

  const clientName = encaissement.expert_comptable
    ? encaissement.expert_comptable.nom_denomination
    : encaissement.client_nom || 'N/A'

  const clientInfo = encaissement.expert_comptable
    ? `N° Ordre: ${encaissement.expert_comptable.numero_ordre}`
    : 'Autre client'

  const modesPaiement: Record<string, string> = {
    cash: 'Espèces',
    check: 'Chèque',
    bank_transfer: 'Opération bancaire',
    mobile_money: 'Mobile Money',
    virement: 'Opération bancaire',
  }

  const totalMontant = toNumber(encaissement.montant_total || encaissement.montant || 0)
  const montantPaye = toNumber(encaissement.montant_paye || 0)
  const montantPercu = toNumber(encaissement.montant_percu || 0)
  const devisePercu = (encaissement.devise_perception || 'USD').toUpperCase()
  const tauxChange = toNumber(encaissement.taux_change_applique || 1)
  const soldeRestant = totalMontant - montantPaye

  if (settings?.afficher_qr_code !== false && encaissement.numero_recu) {
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
    const qrX = pageWidth - marginRight - qrSize - 8
    const qrY = headerBottom + (isA5 ? 2 : 3)
    doc.setFillColor(255, 255, 255)
    doc.setDrawColor(210)
    doc.rect(qrX - 1, qrY - 1, qrSize + 2, qrSize + 2, 'FD')
    doc.addImage(receiptQrDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
  }

  const infoBody: Array<[string, string]> = [
    ['Date d’encaissement', format(new Date(encaissement.date_encaissement), 'dd MMMM yyyy', { locale: fr })],
    ['Reçu de', clientName],
    ['Identification', clientInfo],
    ['Type de client', getTypeClientLabel(encaissement.type_client)],
    ['Type d’opération', getOperationLabel(encaissement.type_operation)],
    ['Mode de paiement', modesPaiement[encaissement.mode_paiement] || encaissement.mode_paiement || 'N/A'],
  ]

  if (encaissement.reference) {
    infoBody.push(['Référence', encaissement.reference])
  }
  if (encaissement.description) {
    infoBody.push(['Description', encaissement.description])
  }

  autoTable(doc, {
    startY: headerBottom + (isA5 ? 16 : 18),
    body: infoBody,
    theme: 'grid',
    tableWidth: pageWidth - marginLeft - marginRight,
    styles: {
      font: 'times',
      fontSize: isA5 ? 8.5 : 10,
      cellPadding: 3,
      valign: 'middle',
      fillColor: [255, 255, 255],
    },
    columnStyles: {
      0: { cellWidth: isA5 ? 38 : 50, fontStyle: 'bold', fillColor: [241, 245, 249] },
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
    paymentBody.push(['Taux appliqué', `${formatAmount(tauxChange, 2)} CDF/USD`])
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
    theme: 'grid',
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
    doc.text('Conseil Provincial de Kinshasa', HEADER_CENTER_X(pageWidth), 25, { align: 'center' })

    doc.setFontSize(10)
    doc.setTextColor(0, 0, 0)
    doc.setFont('helvetica', 'normal')
    doc.text('Gestion de la Trésorerie', HEADER_CENTER_X(pageWidth), 32, { align: 'center' })
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
      'Rapport des réquisitions - ONEC/CPK',
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
    if (lower === 'en_attente') return 'en_attente'
    if (lower === 'validee') return 'validee'
    if (lower === 'autorisee') return 'autorisee'
    if (lower === 'rejetee' || lower === 'rejeté' || lower === 'rejetee') return 'rejetee'
    if (lower === 'brouillon') return 'en_attente'
    if (lower === 'validee_tresorerie') return 'validee'
    if (lower === 'approuvee') return 'approuvee'
    if (lower === 'payee') return 'payee'
    if (raw === 'EN_ATTENTE') return 'en_attente'
    if (raw === 'VALIDEE') return 'validee'
    if (raw === 'AUTORISEE') return 'autorisee'
    if (raw === 'REJETEE') return 'rejetee'
    if (raw === 'PAYEE') return 'payee'
    if (raw === 'APPROUVEE') return 'approuvee'
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
  const totalApprouvees = requisitions.filter((r) => {
    const statut = normalizeStatut(r?.statut ?? r?.status)
    return statut === 'approuvee' || statut === 'payee' || statut === 'validee'
  }).length
  const totalRejetees = requisitions.filter(r => normalizeStatut(r?.statut ?? r?.status) === 'rejetee').length
  const totalPayees = requisitions.filter(r => isPayee(r)).length
  const totalMontant = requisitions.reduce((sum, r) => sum + Number(r.montant_total || 0), 0)
  const totalDecaisse = requisitions.filter(r => isPayee(r)).reduce((sum, r) => sum + Number(r.montant_total || 0), 0)
  const totalRejeteMontant = requisitions
    .filter(r => normalizeStatut(r?.statut ?? r?.status) === 'rejetee')
    .reduce((sum, r) => sum + Number(r.montant_total || 0), 0)
  const totalEnAttenteMontant = Math.max(0, totalMontant - totalDecaisse - totalRejeteMontant)

  const rubriqueTotals = new Map<string, { label: string; code: string; total: number }>()
  requisitions.forEach((req) => {
    const { key, label, code } = extractRubriqueKey(req.rubriques || req.rubrique || '')
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
  doc.text('RAPPORT DES RÉQUISITIONS DE FONDS', pageWidth / 2, 50, { align: 'center' })

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
    doc.text('Répartition par rubrique', 10, rubriqueY)
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
    normalizeRubrique(req.rubriques || req.rubrique || ''),
    `${formatAmount(req.montant_total)} $`,
    (() => {
      const statut = normalizeStatut(req?.statut ?? req?.status)
      if (statut === 'en_attente') return 'En attente'
      if (statut === 'autorisee' || statut === 'validee') return 'Autorisée (1/2)'
      if (statut === 'approuvee') return 'Approuvée'
      if (statut === 'payee') return 'Payée'
      return 'Rejetée'
    })(),
    req.mode_paiement === 'cash' ? 'Caisse' :
    req.mode_paiement === 'mobile_money' ? 'Mobile Money' : 'Virement',
    formatUserName(req.demandeur),
    formatUserName(req.validateur),
    formatUserName(req.approbateur)
  ])

  autoTable(doc, {
    head: [['N°', 'N° Réquisition', 'Date', 'Objet', 'Rubrique', 'Montant', 'Statut', 'Paiement', 'Demandeur', 'Autorisateur', 'Viseur']],
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
      8: { cellWidth: 28 },
      9: { cellWidth: 28 }
    },
    didParseCell: (data) => {
      if (data.section === 'body' && data.column.index === 5) {
        const value = String(data.cell.text?.[0] || '').toLowerCase()
        if (value.includes('rejet')) {
          data.cell.styles.fillColor = [254, 226, 226]
          data.cell.styles.textColor = [153, 27, 27]
        } else if (value.includes('payée') || value.includes('payee')) {
          data.cell.styles.fillColor = [220, 252, 231]
          data.cell.styles.textColor = [22, 101, 52]
        } else if (value.includes('autorisée') || value.includes('validée') || value.includes('approuvée')) {
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
    doc.text('Conseil Provincial de Kinshasa', pageWidth / 2, 23, { align: 'center' })

    doc.setFontSize(12)
    doc.setTextColor(0, 0, 0)
    doc.setFont('helvetica', 'normal')
    doc.text('Gestion de la Trésorerie', pageWidth / 2, 32, { align: 'center' })
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
      'Rapport des encaissements - ONEC/CPK',
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
  const totalPaye = encaissements.filter(e => e.statut_paiement === 'complet').reduce((sum, e) => sum + Number(e.montant_total), 0)
  try {
    const { default: QRCode } = await import('qrcode')
    const qrPayload = `ENC-RPT:${dateDebut}-${dateFin}|COUNT:${encaissements.length}|TOTAL:${formatAmount(totalMontant)}USD`
    qrDataUrl = await QRCode.toDataURL(qrPayload, { margin: 1, width: 120 })
  } catch (_err) {
    qrDataUrl = null
  }

  addHeader()

  doc.setFontSize(16)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text('RAPPORT DES ENCAISSEMENTS', pageWidth / 2, 50, { align: 'center' })

  doc.setFontSize(10)
  doc.setTextColor(0)
  doc.setFont('helvetica', 'normal')
  doc.text(
    `Période : du ${format(new Date(dateDebut), 'dd/MM/yyyy')} au ${format(new Date(dateFin), 'dd/MM/yyyy')}`,
    pageWidth / 2,
    60,
    { align: 'center' }
  )

  const tableData = encaissements.map(enc => {
    const devise = (enc.devise_perception || 'USD').toUpperCase()
    const percu = devise === 'CDF'
      ? `${formatAmount(enc.montant_percu, 0)} CDF`
      : `${formatAmount(enc.montant_total)} USD`
    return [
      format(new Date(enc.date_encaissement), 'dd/MM/yyyy'),
      enc.numero_recu,
      enc.client || '',
      enc.rubrique || '',
      percu,
      enc.statut_paiement === 'complet' ? 'Payé' :
      enc.statut_paiement === 'partiel' ? 'Partiel' :
      enc.statut_paiement === 'avance' ? 'Avance' : 'Non payé'
    ]
  })

  autoTable(doc, {
    head: [['Date', 'N° Reçu', 'Client', 'Rubrique', 'Montant perçu', 'Statut']],
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
      0: { cellWidth: 25 },
      1: { cellWidth: 35 },
      2: { cellWidth: 50 },
      3: { cellWidth: 30 },
      4: { cellWidth: 25, halign: 'right' },
      5: { cellWidth: 24 }
    },
    didDrawPage: () => {
      addFooter(doc.getNumberOfPages())
    }
  })

  const finalY = (doc as any).lastAutoTable.finalY + 10

  doc.setDrawColor(ONEC_GREEN)
  doc.setFillColor(ONEC_LIGHT_GREEN)
  doc.roundedRect(10, finalY, pageWidth - 20, 35, 3, 3, 'FD')

  doc.setFontSize(12)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text('RÉCAPITULATIF', 15, finalY + 8)

  doc.setFontSize(9)
  doc.setTextColor(0)
  doc.setFont('helvetica', 'normal')

  let yPos = finalY + 16
  doc.text(`Total encaissements : ${encaissements.length}`, 15, yPos)
  doc.text(`Montant total payé : ${formatAmount(totalPaye)} $`, 110, yPos)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.text(`Montant total : ${formatAmount(totalMontant)} $`, 15, yPos + 10)

  if (qrDataUrl) {
    const qrX = 15
    const qrY = pageHeight - 28
    const qrSize = 20
    doc.setFontSize(8)
    doc.setTextColor(90)
    doc.setFillColor(255, 255, 255)
    doc.rect(qrX, qrY - 8, 70, 6, 'F')
    doc.text("Scannez pour vérifier l'authenticité", qrX, qrY - 4)
    doc.addImage(qrDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
  }

  doc.save(`encaissements_${dateDebut}_${dateFin}.pdf`)
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
  }>,
  annee: number,
  vue: 'DEPENSE' | 'RECETTE'
) => {
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
    doc.text('Conseil Provincial de Kinshasa', pageWidth / 2, 23, { align: 'center' })

    doc.setFontSize(12)
    doc.setTextColor(0, 0, 0)
    doc.setFont('helvetica', 'normal')
    doc.text('Gestion de la Trésorerie', pageWidth / 2, 32, { align: 'center' })
  }

  const addFooter = (pageNumber: number) => {
    doc.setFontSize(8)
    doc.setTextColor(100)
    doc.text(`${format(new Date(), 'dd/MM/yyyy HH:mm')}`, 10, pageHeight - 10)
    doc.text('Rapport budgétaire - ONEC/CPK', pageWidth / 2, pageHeight - 10, { align: 'center' })
    doc.text(`Page ${pageNumber}`, pageWidth - 20, pageHeight - 10)
  }

  const totalPrevu = lignes.reduce((sum, l) => sum + toNumber(l.montant_prevu), 0)
  const totalEngage = lignes.reduce((sum, l) => sum + toNumber(l.montant_engage), 0)
  const totalPaye = lignes.reduce((sum, l) => sum + toNumber(l.montant_paye), 0)
  const totalDisponible = lignes.reduce((sum, l) => sum + toNumber(l.montant_disponible), 0)
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
      ? 'Objectifs à atteindre (recettes)'
      : 'Plafonds à ne pas dépasser (dépenses)',
    pageWidth / 2,
    60,
    { align: 'center' }
  )

  const tableData = lignes.map(ligne => [
    ligne.code || '',
    ligne.libelle || '',
    `${formatAmount(ligne.montant_prevu)} $`,
    vue === 'RECETTE' ? `${formatAmount(ligne.montant_paye)} $` : `${formatAmount(ligne.montant_paye)} $`,
    vue === 'RECETTE'
      ? `${formatAmount(toNumber(ligne.montant_paye) - toNumber(ligne.montant_prevu))} $`
      : `${formatAmount(ligne.montant_disponible)} $`
  ])

  autoTable(doc, {
    head: [[
      'Code',
      'Rubrique',
      vue === 'RECETTE' ? 'Objectif' : 'Plafond',
      vue === 'RECETTE' ? 'Atteint' : 'Consommé',
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
      0: { cellWidth: 22 },
      1: { cellWidth: 70 },
      2: { cellWidth: 28, halign: 'right' },
      3: { cellWidth: 28, halign: 'right' },
      4: { cellWidth: 28, halign: 'right' }
    },
    didDrawPage: () => {
      addFooter(doc.getNumberOfPages())
    }
  })

  const finalY = (doc as any).lastAutoTable.finalY + 10
  doc.setDrawColor(ONEC_GREEN)
  doc.setFillColor(ONEC_LIGHT_GREEN)
  doc.roundedRect(10, finalY, pageWidth - 20, 28, 3, 3, 'FD')

  doc.setFontSize(11)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text('RÉCAPITULATIF', 15, finalY + 8)

  doc.setFontSize(9)
  doc.setTextColor(0)
  doc.setFont('helvetica', 'normal')
  if (vue === 'RECETTE') {
    doc.text(`Objectif total : ${formatAmount(totalPrevu)} $`, 15, finalY + 18)
    doc.text(`Atteint : ${formatAmount(totalPaye)} $`, 115, finalY + 18)
  } else {
    doc.text(`Plafond total : ${formatAmount(totalPrevu)} $`, 15, finalY + 18)
    doc.text(`Engagé : ${formatAmount(totalEngage)} $`, 115, finalY + 18)
    doc.text(`Disponible : ${formatAmount(totalDisponible)} $`, 15, finalY + 24)
  }

  if (qrDataUrl) {
    const qrX = 15
    const qrY = pageHeight - 28
    const qrSize = 20
    doc.setFontSize(8)
    doc.setTextColor(90)
    doc.setFillColor(255, 255, 255)
    doc.rect(qrX, qrY - 8, 70, 6, 'F')
    doc.text("Scannez pour vérifier l'authenticité", qrX, qrY - 4)
    doc.addImage(qrDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
  }

  doc.save(`budget_${annee}_${vue}.pdf`)
}

export const generateSingleRequisitionPDF = async (
  requisition: any,
  lignes: any[],
  action: 'print' | 'download' | 'blob' = 'download',
  _userName: string
): Promise<Blob | void> => {
  const logoDataUrl = await getLogoDataUrl()
  const stampDataUrl = await getStampDataUrl()
  const settings = await getPrintSettingsData()
  const exchangeRate = settings?.exchange_rate ? Number(settings.exchange_rate) : 0
  const formatUserName = (user: any) => {
    if (!user) return 'N/A'
    const fullName = `${user.prenom || ''} ${user.nom || ''}`.trim()
    return fullName || 'N/A'
  }

  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()

  const orgName = settings?.organization_name || 'ONEC CPK'
  const orgSubtitle = settings?.organization_subtitle || ''
  const fiscalYear = settings?.fiscal_year || new Date().getFullYear()
  const refNumber = requisition.numero_requisition || requisition.id || 'N/A'
  const createdAt = requisition.created_at ? new Date(requisition.created_at) : new Date()

  if (logoDataUrl) {
    addLogo(doc, 15, 12, 26, logoDataUrl)
  }

  doc.setTextColor(0)
  doc.setFont('times', 'bold')
  doc.setFontSize(14)
  doc.text(orgName.toUpperCase(), 50, 20)
  doc.setFont('times', 'normal')
  doc.setFontSize(10)
  if (orgSubtitle) {
    doc.text(orgSubtitle, 50, 26)
  }

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(60)
  const metaLine = `Exercice ${fiscalYear} | Réf ${refNumber} | ${format(createdAt, 'dd/MM/yyyy')}`
  doc.text(metaLine, pageWidth - 18, 24, { align: 'right' })
  doc.setTextColor(0)

  doc.setDrawColor(0)
  doc.setLineWidth(0.5)
  doc.line(15, 50, pageWidth - 15, 50)
  doc.setFont('times', 'bold')
  doc.setFontSize(16)
  doc.text(requisition.req_titre_officiel_hist || settings?.req_titre_officiel || 'BON DE RÉQUISITION DE FONDS', pageWidth / 2, 60, { align: 'center' })

  if (requisition.reference_numero) {
    doc.setFontSize(10)
    doc.setFont('helvetica', 'bold')
    doc.setTextColor(41, 128, 185)
    doc.text(`Réf : ${requisition.reference_numero}`, pageWidth - 15, 20, { align: 'right' })
    doc.setTextColor(0)
  }

  const rawStatus = String((requisition as any).statut ?? (requisition as any).status ?? '').toUpperCase()
  const statut = rawStatus === 'BROUILLON' || rawStatus === 'EN_ATTENTE' || rawStatus === 'A_VALIDER'
    ? 'En attente'
    : rawStatus === 'AUTORISEE' || rawStatus === 'VALIDEE'
    ? 'Autorisée (1/2)'
    : rawStatus === 'APPROUVEE'
    ? 'Approuvée'
    : rawStatus === 'PAYEE'
    ? 'Payée'
    : rawStatus === 'REJETEE'
    ? 'Rejetée'
    : rawStatus || 'En attente'
  const statutRaw = rawStatus.toLowerCase()
  const modePaiement = requisition.mode_paiement === 'cash' ? 'Caisse' :
    requisition.mode_paiement === 'mobile_money' ? 'Mobile Money' : 'Opération bancaire'

  const infoLeft: [string, string][] = [
    ['Objet / Motif', requisition.objet || '-'],
    ['Rubrique principale', lignes?.[0]?.rubrique || '-'],
    ['Date de création', format(createdAt, 'dd/MM/yyyy')],
  ]
  const infoRight: [string, string][] = [
    ['Demandeur', formatUserName(requisition.demandeur)],
    ['Mode de paiement', modePaiement],
    ['Statut', statut],
  ]
  const val1 = formatUserName(requisition.validateur)
  const val2 = formatUserName(requisition.approbateur)
  const isRejected = statutRaw === 'rejetee'
  const isAuthorized = ['autorisee', 'validee'].includes(statutRaw)
  const isApproved = ['approuvee', 'payee'].includes(statutRaw)

  if (isRejected && val1 !== 'N/A') {
    infoRight.push(['Rejeté par', val1])
  } else if (isAuthorized) {
    if (val1 !== 'N/A') infoRight.push(['Autorisateur (1/2)', val1])
  } else if (isApproved) {
    if (val1 !== 'N/A') infoRight.push(['Autorisateur (1/2)', val1])
    if (val2 !== 'N/A') infoRight.push(['Viseur (2/2)', val2])
  }

  const maxInfoRows = Math.max(infoLeft.length, infoRight.length)
  const infoRows = Array.from({ length: maxInfoRows }).map((_, idx) => {
    const left = infoLeft[idx] || ['', '']
    const right = infoRight[idx] || ['', '']
    return [left[0], left[1], right[0], right[1]]
  })

  autoTable(doc, {
    tableWidth: pageWidth - 30,
    margin: { left: 15, right: 15 },
    startY: 68,
    theme: 'grid',
    styles: { font: 'times', fontSize: 9, cellPadding: 2 },
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
    tableWidth: pageWidth - 30,
    margin: { left: 15, right: 15 },
    head: [['Rubrique', 'Description', 'Devise', 'Qté', 'PU', 'Total']],
    body: tableData,
    startY: yPos,
    theme: 'grid',
    headStyles: {
      fillColor: [31, 41, 55],
      textColor: 255,
      fontStyle: 'bold',
      fontSize: 8.5,
      font: 'times'
    },
    bodyStyles: {
      fontSize: 8,
      cellPadding: 2,
      font: 'times'
    },
    alternateRowStyles: {
      fillColor: [245, 245, 245]
    },
    columnStyles: {
      0: { cellWidth: 28 },
      1: { cellWidth: 70 },
      2: { cellWidth: 12, halign: 'center' },
      3: { cellWidth: 12, halign: 'center' },
      4: { cellWidth: 26, halign: 'right' },
      5: { cellWidth: 26, halign: 'right' }
    },
    foot: [[
      { content: 'MONTANT TOTAL', colSpan: 5, styles: { halign: 'right', fontStyle: 'bold' } },
      { content: `${formatAmount(requisition.montant_total)} USD`, styles: { fontStyle: 'bold', halign: 'right' } }
    ]]
  })

  let finalY = (doc as any).lastAutoTable.finalY + 8

  const totalUsd = Number(requisition.montant_total || 0)
  const totalCdf = exchangeRate ? totalUsd * exchangeRate : 0
  autoTable(doc, {
    tableWidth: pageWidth - 30,
    margin: { left: 15, right: 15 },
    startY: finalY,
    theme: 'grid',
    styles: { font: 'times', fontSize: 8.5, cellPadding: 2 },
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
  doc.text(montantLines, 15, finalY)
  finalY += (montantLines.length * 5) + 8

  if (requisition.a_valoir) {
    doc.setDrawColor('#f59e0b')
    doc.setFillColor('#fef3c7')
    doc.roundedRect(10, finalY, pageWidth - 20, 25, 3, 3, 'FD')

    doc.setFontSize(10)
    doc.setTextColor('#92400e')
    doc.setFont('times', 'bold')
    doc.text('⚠ RÉQUISITION À VALOIR', 15, finalY + 8)

    doc.setFont('times', 'normal')
    doc.setFontSize(9)
    doc.text(`Instance bénéficiaire: ${requisition.instance_beneficiaire || 'N/A'}`, 15, finalY + 15)
    if (requisition.notes_a_valoir) {
      const notesLines = doc.splitTextToSize(`Notes: ${requisition.notes_a_valoir}`, pageWidth - 30)
      doc.text(notesLines, 15, finalY + 20)
    }
  }

  const signatureY = Math.min(pageHeight - 55, finalY + 15)
  const labelGauche =
    requisition.signataire_g_label ||
    requisition.req_label_gauche_hist ||
    settings?.req_label_gauche ||
    'Établi par'
  const nomGauche =
    requisition.signataire_g_nom ||
    requisition.req_nom_gauche_hist ||
    settings?.req_nom_gauche ||
    ''
  const labelDroite =
    requisition.signataire_d_label ||
    requisition.req_label_droite_hist ||
    settings?.req_label_droite ||
    'Approuvé par'
  const nomDroite =
    requisition.signataire_d_nom ||
    requisition.req_nom_droite_hist ||
    settings?.req_nom_droite ||
    ''

  doc.setFont('times', 'bold')
  doc.setFontSize(10)
  doc.setTextColor(0)
  doc.text(labelGauche, 20, signatureY)
  doc.text(labelDroite, pageWidth - 70, signatureY)
  doc.setFont('times', 'normal')
  if (nomGauche) {
    doc.text(nomGauche, 20, signatureY + 6)
  }
  if (nomDroite) {
    doc.text(nomDroite, pageWidth - 70, signatureY + 6)
  } else {
    doc.text('................................', pageWidth - 70, signatureY + 6)
  }

  if (stampDataUrl) {
    const stampSize = 30
    const stampX = pageWidth - stampSize - 20
    const stampY = signatureY + 5
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
      const qrY = pageHeight - 34
      const qrSize = 16
      doc.setFontSize(8)
      doc.setTextColor(90)
      doc.setFillColor(255, 255, 255)
      doc.rect(qrX, qrY - 8, 66, 6, 'F')
      doc.text("Scannez pour vérifier l'authenticité", qrX, qrY - 4)
      doc.addImage(qrDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
    } catch (_err) {
      // Si QRCode n'est pas disponible, on ignore sans bloquer le PDF.
    }
  }

  doc.setFontSize(8)
  doc.setTextColor(100)
  const footerLabel = settings?.pied_de_page_legal || 'Réquisition de fonds - ONEC/CPK'
  const footerDate = format(new Date(), 'dd/MM/yyyy')
  doc.text(
    `${footerLabel} | ${footerDate}`,
    pageWidth / 2,
    pageHeight - 10,
    { align: 'center' }
  )

  doc.text(
    'Page 1/1',
    pageWidth - 20,
    pageHeight - 10
  )

  if (action === 'print') {
    openPdfInNewTab(doc)
  } else if (action === 'blob') {
    return doc.output('blob')
  } else {
    doc.save(`requisition_${requisition.numero_requisition}.pdf`)
  }
}
