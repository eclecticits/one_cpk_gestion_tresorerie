import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { fr } from 'date-fns/locale'
import type { PrintSettings } from '../api/settings'
import { numberToWords } from './numberToWords'
import { formatAmount, toNumber } from './amount'
import { normalizeBudgetCode } from './budgetCode'
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
let cachedServicesMap: Map<number, string> | null = null
let cachedComptesMap: Map<number, string> | null = null
let cachedTenantHint: string | null = null

const resetPrintAssetCache = () => {
  cachedLogoDataUrl = null
  cachedLogoUrl = null
  cachedStampDataUrl = null
  cachedStampUrl = null
  cachedSettings = null
  cachedServicesMap = null
  cachedComptesMap = null
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

/**
 * Libellés des services, pour afficher un nom lisible là où la pièce ne porte
 * que `service_id`. Mis en cache comme les autres ressources d'impression et
 * purgé au changement de tenant.
 */
const getServicesMap = async (): Promise<Map<number, string>> => {
  ensureTenantScopedPrintCache()
  if (cachedServicesMap) return cachedServicesMap
  try {
    // Pas de filtre `active` : un service désactivé depuis doit rester lisible
    // sur les pièces déjà émises.
    const res = await fetch(`${API_BASE_URL}/services`, {
      headers: getAuthHeaders(),
      credentials: 'include',
    })
    if (!res.ok) return new Map()
    const payload = await res.json()
    const items = Array.isArray(payload) ? payload : (payload?.items ?? payload?.data ?? [])
    const map = new Map<number, string>()
    items.forEach((service: any) => {
      const id = Number(service?.id)
      if (!Number.isFinite(id)) return
      const libelle = String(service?.libelle || '').trim()
      const code = String(service?.code || '').trim()
      if (!libelle && !code) return
      map.set(id, code && libelle ? `${code} - ${libelle}` : libelle || code)
    })
    cachedServicesMap = map
    return map
  } catch {
    return new Map()
  }
}

/**
 * Intitulés des comptes bancaires, pour nommer le compte d'un volet de
 * règlement là où la pièce ne porte qu'un identifiant. Même cache et même
 * cycle de vie que les autres ressources d'impression.
 */
const getComptesBancairesMap = async (): Promise<Map<number, string>> => {
  ensureTenantScopedPrintCache()
  if (cachedComptesMap) return cachedComptesMap
  try {
    const res = await fetch(`${API_BASE_URL}/comptes-bancaires`, {
      headers: getAuthHeaders(),
      credentials: 'include',
    })
    if (!res.ok) return new Map()
    const payload = await res.json()
    const items = Array.isArray(payload) ? payload : (payload?.items ?? payload?.data ?? [])
    const map = new Map<number, string>()
    items.forEach((compte: any) => {
      const id = Number(compte?.id)
      if (!Number.isFinite(id)) return
      const banque = String(compte?.banque?.nom || '').trim()
      const intitule = String(compte?.intitule || '').trim()
      const label = [banque, intitule].filter(Boolean).join(' - ')
      if (label) map.set(id, label)
    })
    cachedComptesMap = map
    return map
  } catch {
    return new Map()
  }
}

const SCRIPT_FONT_NAME = 'GreatVibes'

/**
 * Enregistre dans le document la police calligraphique portant le nom de
 * l'organisation, pour retrouver l'identité visuelle de la page de connexion.
 * Chargée à la demande : le fichier base64 ne pèse sur le bundle que si un
 * document qui l'utilise est réellement généré.
 *
 * Renvoie `false` si l'enregistrement échoue, l'appelant devant alors retomber
 * sur une police standard plutôt que de produire un PDF vide.
 */
const registerScriptFont = async (doc: jsPDF): Promise<boolean> => {
  try {
    if ((doc as any).getFontList?.()?.[SCRIPT_FONT_NAME]) return true
    const { GREAT_VIBES_REGULAR_BASE64 } = await import('./fonts/greatVibes')
    doc.addFileToVFS(`${SCRIPT_FONT_NAME}-Regular.ttf`, GREAT_VIBES_REGULAR_BASE64)
    doc.addFont(`${SCRIPT_FONT_NAME}-Regular.ttf`, SCRIPT_FONT_NAME, 'normal')
    return true
  } catch {
    return false
  }
}

/**
 * Dessine le logo dans une boîte `size` x `boxHeight` en respectant ses
 * proportions : un logo non carré était auparavant étiré de force sur un carré.
 * L'image reste centrée dans la boîte réservée, donc l'encombrement est au pire
 * identique à l'ancien et les mises en page appelantes ne bougent pas.
 */
const addLogo = (doc: jsPDF, x: number, y: number, size: number, dataUrl?: string | null, boxHeight?: number) => {
  if (!dataUrl) return
  const maxWidth = size
  const maxHeight = boxHeight ?? size
  let width = maxWidth
  let height = maxHeight
  let format = 'PNG'
  try {
    const props: any = (doc as any).getImageProperties?.(dataUrl)
    if (props?.width > 0 && props?.height > 0) {
      const ratio = props.width / props.height
      height = Math.min(maxHeight, maxWidth / ratio)
      width = height * ratio
      if (width > maxWidth) {
        width = maxWidth
        height = width / ratio
      }
      if (props.fileType) format = String(props.fileType).toUpperCase()
    }
  } catch {
    // Propriétés illisibles : on retombe sur le carré historique.
  }
  doc.addImage(dataUrl, format, x + (maxWidth - width) / 2, y + (maxHeight - height) / 2, width, height)
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
  const documentTitle = isProforma ? 'PRO FORMA DE NOTE DE DÉBIT' : 'NOTE DE DÉBIT'
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
    doc.text('PRO FORMA', pageWidth / 2, pageHeight / 2, { align: 'center', angle: 35 })
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
  doc.text(`${documentTitle} N° ${headerNumero || ''}`, pageWidth / 2, headerBottom + 10, {
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
    ['Débiteur', clientName],
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
    format(new Date(req.date_requisition ?? req.created_at), 'dd/MM/yyyy'),
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
    req.mode_paiement === 'card' ? 'Carte (Visa)' : 'Opération bancaire',
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
    head: [['Date', 'N° Note de débit', 'Matricule', 'Client / Membre', 'Poste budgétaire', 'Libellé', 'Montant', 'Statut']],
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

  // Devise regardée (filtre de l'écran Rapports). 'ALL' = cumul non converti.
  const deviseVue = String(rapport?.devise || 'USD').toUpperCase()
  // `montant_paye` d'un encaissement est toujours le pivot USD, `montant_percu`
  // le montant réellement perçu : en vue CDF, c'est le second qu'il faut, sans
  // quoi le détail afficherait des dollars sous un total en francs. Les sorties,
  // elles, sont stockées dans LEUR devise, d'où leur colonne Devise plus bas.
  const encRows = encaissements.map((e: any) => [
    formatPdfDate(e.date_encaissement),
    e.numero_recu || '-',
    e.expert_comptable?.nom_denomination || e.client_nom || '-',
    formatAmount(
      deviseVue === 'CDF'
        ? toNumber(e.montant_percu ?? 0)
        : toNumber(e.montant_paye ?? e.montant_total ?? e.montant ?? 0)
    ),
  ])
  addSection(
    'ENCAISSEMENTS',
    ['Date', 'Note de débit', 'Client', `Montant${deviseVue === 'ALL' ? '' : ` (${deviseVue})`}`],
    encRows
  )

  const sortieRows = sorties.map((s: any) => [
    formatPdfDate(s.date_paiement),
    s.reference || '-',
    s.requisition?.numero_requisition || s.requisition_id || '-',
    formatAmount(toNumber(s.montant_paye ?? 0)),
    (s.devise || 'USD').toUpperCase(),
  ])
  addSection(
    'SORTIES DE FONDS',
    ['Date', 'Référence', 'Réquisition', 'Montant', 'Devise'],
    sortieRows
  )

  // Transferts internes REÇUS par le canal du rapport (versements encaissés par
  // la banque, approvisionnements reçus en caisse). Ils n'apparaissent dans
  // aucune des deux sections ci-dessus : ce ne sont pas des recettes, et leur
  // ligne de sortie appartient au canal opposé.
  const transfertsRecus = Array.isArray(rapport?.transfertsRecus) ? rapport.transfertsRecus : []
  const entreesInternes =
    toNumber(rapport?.entreesInternes ?? 0) ||
    transfertsRecus.reduce((sum: number, t: any) => sum + toNumber(t.montant_paye ?? 0), 0)
  if (transfertsRecus.length) {
    addSection(
      rapport?.canal === 'CAISSE'
        ? 'TRANSFERTS INTERNES REÇUS (APPROVISIONNEMENTS DE LA CAISSE)'
        : 'TRANSFERTS INTERNES REÇUS (VERSEMENTS À LA BANQUE)',
      ['Date', 'Référence', 'Motif', 'Montant', 'Devise'],
      transfertsRecus.map((t: any) => [
        formatPdfDate(t.date_paiement),
        t.reference_numero || t.reference || '-',
        t.motif || t.beneficiaire || '-',
        formatAmount(toNumber(t.montant_paye ?? 0)),
        (t.devise || 'USD').toUpperCase(),
      ])
    )
  }

  const totalEnc =
    toNumber(rapport?.totalEncaissements) ||
    encaissements.reduce((sum: number, e: any) => sum + toNumber(e.montant_paye ?? e.montant_total ?? e.montant ?? 0), 0)
  const totalSorties =
    toNumber(rapport?.totalSorties) ||
    sorties.reduce((sum: number, s: any) => sum + toNumber(s.montant_paye ?? 0), 0)
  const soldeNet = toNumber(
    rapport?.soldeFinal ?? rapport?.solde ?? totalEnc + entreesInternes - totalSorties
  )
  const showEntreesInternes = entreesInternes > 0 || transfertsRecus.length > 0

  // Ventilation par devise servie par /reports/summary : montants bruts, non
  // convertis. Elle couvre TOUTES les devises, y compris quand le rapport est
  // filtré sur l'une d'elles — d'où la distinction ci-dessous.
  const parDevise = Array.isArray(rapport?.parDevise) ? rapport.parDevise : []
  const devisesSorties = new Set<string>(
    parDevise.length
      ? parDevise.map((l: any) => String(l.devise || 'USD').toUpperCase())
      : [...sorties, ...transfertsRecus].map((row: any) => (row.devise || 'USD').toUpperCase())
  )
  // Rapport filtré sur une devise : les totaux ne portent que celle-là, on les
  // étiquette. Vue « Toutes » avec plusieurs devises en jeu : les totaux sont des
  // cumuls non convertis, on retire l'étiquette et on détaille devise par devise.
  const devisesMelangees = deviseVue === 'ALL' && devisesSorties.size > 1
  const uniteSorties = devisesMelangees ? '' : ` ${deviseVue === 'ALL' ? [...devisesSorties][0] || 'USD' : deviseVue}`
  const uniteSolde = uniteSorties

  const summaryLines =
    3 + (showEntreesInternes ? 1 : 0) + (devisesMelangees ? 2 + parDevise.length * 2 : 0)
  if (currentY + 14 + summaryLines * 6 > pageHeight - 20) {
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
  doc.text(
    `Total entrées : ${formatAmount(totalEnc)}${deviseVue === 'ALL' ? '' : ` ${deviseVue}`}`,
    summaryX,
    currentY + 16
  )
  let summaryOffset = 22
  if (showEntreesInternes) {
    doc.text(
      `Transferts reçus : ${formatAmount(entreesInternes)}${uniteSorties}`,
      summaryX,
      currentY + summaryOffset
    )
    summaryOffset += 6
  }
  doc.text(`Total sorties : ${formatAmount(totalSorties)}${uniteSorties}`, summaryX, currentY + summaryOffset)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(textMain[0], textMain[1], textMain[2])
  doc.text(`Solde net : ${formatAmount(soldeNet)}${uniteSolde}`, summaryX, currentY + summaryOffset + 8)

  if (devisesMelangees) {
    let detailY = currentY + summaryOffset + 15
    doc.setFont('helvetica', 'italic')
    doc.setFontSize(7.5)
    doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
    doc.text(
      `Totaux ci-dessus : ${[...devisesSorties].sort().join(' + ')} cumulés, non convertis.`,
      summaryX,
      detailY
    )
    detailY += 5

    // Détail réel par devise, quand /reports/summary a pu le calculer. Sans lui,
    // on se contente d'avertir : mieux vaut pas de chiffre qu'un chiffre faux.
    if (parDevise.length) {
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(8)
      doc.setTextColor(textMain[0], textMain[1], textMain[2])
      doc.text('Par devise :', summaryX, detailY)
      detailY += 4
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(7.5)
      doc.setTextColor(textMuted[0], textMuted[1], textMuted[2])
      parDevise.forEach((ligne: any) => {
        const devise = String(ligne.devise || 'USD').toUpperCase()
        doc.text(
          `${devise} — entrées ${formatAmount(toNumber(ligne.encaissements))}, ` +
            `transferts ${formatAmount(toNumber(ligne.entreesInternes))},`,
          summaryX,
          detailY
        )
        detailY += 4
        doc.text(
          `        sorties ${formatAmount(toNumber(ligne.sorties))}, ` +
            `solde ${formatAmount(toNumber(ligne.solde))}`,
          summaryX,
          detailY
        )
        detailY += 5
      })
    } else {
      doc.text('Voir la colonne Devise du détail.', summaryX, detailY)
    }
  }

  doc.save(`rapport_tresorerie_${formatPdfDate(dateDebut).split('/').join('-')}.pdf`)
}

/** Bloc « Commentaire général » posé sous le tableau d'un document budgétaire.
 *
 *  Renvoie l'ordonnée atteinte, pour que l'appelant continue à empiler ses
 *  sections. Le texte est découpé à la largeur utile et paginé : un
 *  commentaire long est justement celui qui ne doit pas être tronqué.
 *  Comme dans le reste des exports, ni auteur ni date — l'attribution se lit
 *  dans l'application.
 */
const drawCommentaireGeneral = (
  doc: jsPDF,
  {
    texte,
    y,
    marginX,
    contentW,
    pageHeight,
    onNewPage,
  }: {
    texte: string
    y: number
    marginX: number
    contentW: number
    pageHeight: number
    onNewPage: () => void
  }
): number => {
  const contenu = texte.trim()
  if (!contenu) return y

  // Le commentaire est présenté comme une vraie carte : titre détaché, fond
  // clair, marges intérieures et filet d'accent vert à gauche. Surtout, le
  // texte n'est jamais tronqué — s'il est long, il se pagine bloc par bloc,
  // chaque bloc restant une carte complète et lisible.
  const TITLE_H = 7
  const PAD_X = 5
  const PAD_TOP = 5
  const PAD_BOTTOM = 5
  const LINE_H = 5.2
  const ACCENT_W = 1.4
  const MIN_BODY_H = 17
  const BOTTOM_LIMIT = pageHeight - 16

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(10)
  const textW = contentW - PAD_X * 2 - ACCENT_W
  const lignes: string[] = doc.splitTextToSize(contenu, textW)

  const drawTitre = (yTitre: number) => {
    doc.setFillColor(ONEC_GREEN)
    doc.rect(marginX, yTitre + 0.5, 2.6, TITLE_H - 1, 'F')
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11)
    doc.setTextColor(ONEC_GREEN)
    doc.text('COMMENTAIRE GÉNÉRAL', marginX + 5.5, yTitre + TITLE_H - 1.7)
  }

  const drawCarte = (yCarte: number, hCarte: number) => {
    doc.setFillColor(247, 251, 249)
    doc.setDrawColor(205, 224, 216)
    doc.setLineWidth(0.3)
    doc.roundedRect(marginX, yCarte, contentW, hCarte, 2.2, 2.2, 'FD')
    doc.setFillColor(ONEC_GREEN)
    doc.rect(marginX, yCarte + 1, ACCENT_W, hCarte - 2, 'F')
  }

  // Le titre ne part jamais seul en bas de page : il lui faut la place du titre
  // et d'au moins une ligne de texte.
  if (y + TITLE_H + 2 + PAD_TOP + LINE_H + PAD_BOTTOM > BOTTOM_LIMIT) {
    doc.addPage()
    onNewPage()
    y = 20
  }

  drawTitre(y)
  y += TITLE_H + 2

  // Pagination du corps : chaque page reçoit le bloc de lignes qui y tient,
  // encadré par sa propre carte — un long commentaire n'est jamais coupé au
  // milieu d'une ligne ni tronqué.
  let i = 0
  const n = lignes.length
  while (i < n) {
    const carteTop = y
    const dispo = BOTTOM_LIMIT - (carteTop + PAD_TOP + PAD_BOTTOM)
    const maxLignes = Math.max(1, Math.floor(dispo / LINE_H))
    const bloc = lignes.slice(i, i + maxLignes)
    const carteH = Math.max(MIN_BODY_H, PAD_TOP + bloc.length * LINE_H + PAD_BOTTOM)

    drawCarte(carteTop, carteH)

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(10)
    doc.setTextColor(45, 61, 53)
    let ty = carteTop + PAD_TOP + 3.6
    bloc.forEach((ligne) => {
      doc.text(ligne, marginX + ACCENT_W + PAD_X, ty)
      ty += LINE_H
    })

    i += maxLignes
    y = carteTop + carteH

    if (i < n) {
      doc.addPage()
      onNewPage()
      y = 20
    }
  }

  return y + 6
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
    /** Faux = ligne affichée mais exclue des totaux et de la synthèse. */
    inclure_dans_calculs?: boolean
  }>,
  annee: number,
  vue: 'DEPENSE' | 'RECETTE',
  options?: {
    /** Fil de commentaires par code de poste. Sa présence déclenche la variante
     *  paysage : une colonne de texte libre ne tient pas dans les 190 mm utiles
     *  d'un A4 portrait déjà occupé par six colonnes chiffrées. */
    commentaires?: Map<string, Array<{
      texte: string
      auteur_nom?: string | null
      created_at: string
      statut_budget?: string | null
    }>>
    /** Commentaire général de l'exercice pour la vue exportée. Rendu sous le
     *  tableau dans les deux variantes : il justifie l'ensemble du budget, pas
     *  une ligne, et n'a donc pas à dépendre de la version annotée. */
    commentaireGeneral?: string | null
    /** Prévision de l'exercice N-1 par code de poste normalisé. Sa présence ajoute
     *  les colonnes « Budget N-1 » et « Solde budgétaire » et bascule en paysage : huit
     *  colonnes chiffrées ne tiennent pas dans les 182 mm utiles d'un A4
     *  portrait, déjà remplis à 180 mm par les six colonnes actuelles. */
    comparaisonN1?: Map<string, number>
  }
) => {
  const settings = await getPrintSettingsData()
  const logoDataUrl = settings?.show_header_logo === false ? null : await getLogoDataUrl()
  const commentaires = options?.commentaires
  const avecCommentaires = !!commentaires && commentaires.size > 0
  const comparaisonN1 = options?.comparaisonN1
  const avecComparaison = !!comparaisonN1 && comparaisonN1.size > 0
  const doc = new jsPDF({
    orientation: avecCommentaires || avecComparaison ? 'l' : 'p',
    unit: 'mm',
    format: 'a4',
  })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  let qrDataUrl: string | null = null

  const addHeader = () => {
    doc.setDrawColor(ONEC_GREEN)
    doc.setLineWidth(3)
    doc.line(10, 40, pageWidth - 10, 40)

    // En-tête : logo officiel centré (ratio d'origine préservé pour ne pas le
    // déformer). À défaut de logo disponible, on retombe sur le titre texte
    // pour ne jamais laisser l'en-tête vide.
    let sousTitreY = 16
    let logoAffiche = false
    if (logoDataUrl) {
      try {
        const props = doc.getImageProperties(logoDataUrl)
        const logoH = 16
        const logoW = logoH * (props.width / props.height)
        doc.addImage(logoDataUrl, 'PNG', pageWidth / 2 - logoW / 2, 5, logoW, logoH)
        sousTitreY = 27
        logoAffiche = true
      } catch {
        logoAffiche = false
      }
    }
    if (!logoAffiche) {
      doc.setFontSize(19)
      doc.setTextColor(ONEC_GREEN)
      doc.setFont('helvetica', 'bold')
      doc.text('ORDRE NATIONAL DES EXPERTS-COMPTABLES', pageWidth / 2, 15, { align: 'center' })
      sousTitreY = 24
    }

    doc.setFontSize(14)
    doc.setTextColor(0, 0, 0)
    doc.setFont('times', 'bolditalic')
    doc.text(settings?.organization_name || DEFAULT_TENANT_NAME, pageWidth / 2, sousTitreY, { align: 'center' })

    doc.setFontSize(12)
    doc.setTextColor(0, 0, 0)
    doc.setFont('helvetica', 'normal')
    doc.text("Plateforme intelligente de gestion intégrée de l'ONEC-RDC", pageWidth / 2, sousTitreY + 8, { align: 'center' })
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
  // Une ligne hors calcul reste imprimée avec ses montants, mais ne pèse ni
  // dans les totaux, ni dans les taux, ni dans la synthèse : c'est tout l'objet
  // du drapeau (un report d'exercice antérieur n'est pas une recette de l'année).
  const estCompte = (l: { inclure_dans_calculs?: boolean }) => l.inclure_dans_calculs !== false
  const feuilles = lignes.filter(l => !l.is_parent && estCompte(l))
  const totalPrevu = feuilles.reduce((sum, l) => sum + toNumber(l.montant_prevu), 0)
  const totalEngage = feuilles.reduce((sum, l) => sum + toNumber(l.montant_engage), 0)
  const totalPaye = feuilles.reduce((sum, l) => sum + toNumber(l.montant_paye), 0)
  const totalDisponible = feuilles.reduce((sum, l) => sum + toNumber(l.montant_disponible), 0)
  const formatBudgetAmount = (value: string | number, fractionDigits = 2) =>
    formatAmount(value, fractionDigits).replace(/[\u00a0\u202f]/g, ' ')
  try {
    const { default: QRCode } = await import('qrcode')
    const qrPayload = `BUDGET:${annee}:${vue}|PREVU:${formatBudgetAmount(totalPrevu)}|ENG:${formatBudgetAmount(totalEngage)}|PAYE:${formatBudgetAmount(totalPaye)}`
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
    (vue === 'RECETTE'
      ? 'Suivi de la réalisation des recettes par poste et sous-poste'
      : "Suivi de l'exécution des dépenses par poste et sous-poste") +
      // Le lecteur doit savoir laquelle des deux versions il a en main : les
      // chiffres sont identiques, seules les justifications s'ajoutent.
      (avecCommentaires ? '  —  version annotée (commentaires par ligne)' : ''),
    pageWidth / 2,
    60,
    { align: 'center' }
  )

  // Statistiques par ligne : montants + taux de réalisation.
  const rowStats = lignes.map(ligne => {
    const prevu = toNumber(ligne.montant_prevu)
    const consomme = toNumber(ligne.montant_paye)
    const pct = prevu > 0 ? (consomme / prevu) * 100 : 0
    return { ligne, prevu, consomme, pct }
  })

  // Largeur cumulée des six colonnes chiffrées, identiques dans les deux
  // versions. La marge n'est fixée explicitement que pour la variante paysage :
  // toucher aux marges du portrait modifierait un rendu déjà validé.
  // Décalage des colonnes situées après « Prévision ». Tous les index qui suivent
  // en dépendent : les coder en dur casserait silencieusement la colorisation
  // du taux et l'indentation du libellé dès qu'une variante s'ajoute.
  const DECALAGE = avecComparaison ? 2 : 0
  const COL_TAUX = 4 + DECALAGE
  const COL_COMMENTAIRES = 6 + DECALAGE
  const LARGEUR_PREVISION = 27
  const LARGEUR_REALISATION = 27
  const LARGEUR_TAUX = 28
  const LARGEUR_SOLDE = 28
  const codeCell = (ligne: { code?: string; is_parent?: boolean; level?: number }) =>
    ligne.is_parent
      ? `${'»'.repeat(Math.min((ligne.level ?? 0) + 1, 3))} ${ligne.code || ''}`
      : (ligne.code || '')
  const codeWidthContent = Math.max(
    doc.getTextWidth('Code'),
    ...rowStats.map(({ ligne }) => doc.getTextWidth(codeCell(ligne)))
  )
  // La colonne Code suit son contenu au lieu de prendre une largeur fixe.
  // Le reste du couple Code + Poste budgétaire revient au libellé.
  const LARGEUR_CODE = Math.min(avecComparaison ? 18 : 20, Math.max(12, Math.ceil(codeWidthContent + 7)))
  const LARGEUR_CODE_LIBELLE = avecComparaison ? 64 : 72
  const LARGEUR_LIBELLE = LARGEUR_CODE_LIBELLE - LARGEUR_CODE
  const LARGEUR_COMPARAISON = avecComparaison ? 24 + 24 : 0
  const FIXED_COLS_WIDTH =
    LARGEUR_CODE + LARGEUR_LIBELLE + LARGEUR_PREVISION + LARGEUR_REALISATION +
    LARGEUR_TAUX + LARGEUR_SOLDE + LARGEUR_COMPARAISON
  const TABLE_MARGIN_X = 10

  /** Prévision N-1 d'un poste, ou null s'il n'existait pas l'exercice précédent. */
  const prevuN1 = (code?: string): number | null => {
    if (!avecComparaison || !code) return null
    const valeur = comparaisonN1!.get(normalizeBudgetCode(code))
    return valeur === undefined ? null : valeur
  }

  const commentaireCell = (code?: string) => {
    if (!avecCommentaires || !code) return ''
    // Même normalisation que celle qui a servi à construire la carte, sinon la
    // colonne ressort vide sans qu'aucune erreur ne le signale.
    const fil = commentaires!.get(normalizeBudgetCode(code)) || []
    if (fil.length === 0) return ''
    // Le texte seul : l'auteur et la date restent à l'écran, où le fil se
    // discute et s'attribue. Le document exporté, lui, circule à l'extérieur —
    // il porte la justification du montant, pas le nom de qui l'a écrite.
    return fil.map((c) => `• ${c.texte}`).join('\n')
  }

  const tableData = rowStats.map(({ ligne, prevu, consomme, pct }) => {
    const row: string[] = [
      // Marqueur hiérarchique : « » » répété selon le niveau signale un poste parent.
      codeCell(ligne),
      ligne.libelle || '',
      `${formatBudgetAmount(prevu)} $`,
    ]
    if (avecComparaison) {
      const n1 = prevuN1(ligne.code)
      // Un tiret dit « pas d'homologue l'an dernier ». Un zéro dirait
      // « budgété à zéro » — ce n'est pas la même information, et l'écart
      // affiché vaudrait alors le budget entier.
      row.push(n1 === null ? '—' : `${formatBudgetAmount(n1)} $`)
      row.push(n1 === null ? '—' : `${formatBudgetAmount(prevu - n1)} $`)
    }
    row.push(
      `${formatBudgetAmount(consomme)} $`,
      prevu > 0 ? `${pct.toFixed(1)} %` : '—',
      vue === 'RECETTE'
        ? `${formatBudgetAmount(consomme - prevu)} $`
        : `${formatBudgetAmount(ligne.montant_disponible)} $`,
    )
    if (avecCommentaires) row.push(commentaireCell(ligne.code))
    // Le lecteur doit pouvoir refaire l'addition : sans cette mention, une
    // ligne visible mais absente du total ferait passer le document pour faux.
    if (!estCompte(ligne)) {
      row[1] = `${row[1]}  (hors calcul)`
    }
    return row
  })
  const HEADER_TAUX_REALISATION = 'Taux de\nréalisation'
  const HEADER_SOLDE_BUDGETAIRE = 'Solde\nbudgétaire'
  const isRecette = vue === 'RECETTE'

  autoTable(doc, {
    head: [[
      'Code',
      'Poste budgétaire',
      'Prévision',
      ...(avecComparaison ? ['Budget N-1', HEADER_SOLDE_BUDGETAIRE] : []),
      'Réalisation',
      HEADER_TAUX_REALISATION,
      HEADER_SOLDE_BUDGETAIRE,
      ...(avecCommentaires ? ['Commentaires'] : []),
    ]],
    body: tableData,
    startY: 70,
    theme: 'grid',
    headStyles: {
      fillColor: ONEC_GREEN,
      textColor: 255,
      fontStyle: 'bold',
      fontSize: 8.5,
      cellPadding: { top: 2.2, right: 2, bottom: 2.2, left: 2 },
      valign: 'middle',
    },
    bodyStyles: {
      fontSize: 9.5,
      cellPadding: 3.2
    },
    styles: {
      overflow: 'linebreak',
      valign: 'middle',
    },
    alternateRowStyles: {
      fillColor: [245, 245, 245]
    },
    // Les six premières colonnes gardent exactement les largeurs de la version
    // portrait : les deux PDF doivent se superposer à la lecture. Le paysage
    // n'ajoute pas d'air ailleurs, il ouvre seulement la colonne commentaires.
    columnStyles: {
      0: { cellWidth: LARGEUR_CODE },
      1: { cellWidth: LARGEUR_LIBELLE },
      2: { cellWidth: LARGEUR_PREVISION, halign: 'right' },
      ...(avecComparaison
        ? {
            3: { cellWidth: 24, halign: 'right' as const },
            4: { cellWidth: 24, halign: 'right' as const },
          }
        : {}),
      [3 + DECALAGE]: { cellWidth: LARGEUR_REALISATION, halign: 'right' as const },
      [COL_TAUX]: { cellWidth: LARGEUR_TAUX, halign: 'right' as const, fontStyle: 'bold' as const },
      [5 + DECALAGE]: { cellWidth: LARGEUR_SOLDE, halign: 'right' as const },
      ...(avecCommentaires
        ? {
            [COL_COMMENTAIRES]: {
              // Tout l'espace restant, calculé et non codé en dur : la largeur
              // dépend de la page et des marges, une valeur figée déborderait
              // au moindre changement de format.
              cellWidth: pageWidth - TABLE_MARGIN_X * 2 - FIXED_COLS_WIDTH,
              halign: 'left' as const,
              fontSize: 7,
              textColor: '#334155',
            },
          }
        : {}),
    },
    ...(avecCommentaires || avecComparaison
      ? { margin: { left: TABLE_MARGIN_X, right: TABLE_MARGIN_X } }
      : {}),
    didParseCell: (data: any) => {
      if (data.section !== 'body') return
      const stat = rowStats[data.row.index]
      const lvl = Math.max(0, stat?.ligne.level ?? 0)
      if (stat && !estCompte(stat.ligne)) {
        data.cell.styles.textColor = '#94a3b8'
        data.cell.styles.fontStyle = 'italic'
      }
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
      const isTauxCell = data.column.index === COL_TAUX
      const isSoldeCell = data.column.index === 5 + DECALAGE
      if (!stat) return
      const depassement = stat.pct > 100
      const seuilAtteint = stat.pct >= 100 && !depassement
      if (isTauxCell) {
        if (isRecette) {
          if (depassement) {
            data.cell.styles.textColor = '#047857'
            data.cell.styles.fontStyle = 'bold'
            data.cell.styles.fillColor = '#ecfdf5'
          } else if (seuilAtteint) {
            data.cell.styles.textColor = '#0f766e'
            data.cell.styles.fontStyle = 'bold'
          } else if (stat.pct >= 90) {
            data.cell.styles.textColor = ONEC_GREEN
          }
        } else if (depassement) {
          data.cell.styles.textColor = '#dc2626'
          data.cell.styles.fontStyle = 'bold'
          data.cell.styles.fillColor = '#fef2f2'
        } else if (seuilAtteint) {
          data.cell.styles.textColor = '#b45309'
          data.cell.styles.fontStyle = 'bold'
        } else if (stat.pct >= 90) {
          data.cell.styles.textColor = '#b45309'
        } else {
          data.cell.styles.textColor = ONEC_GREEN
        }
      }
      if (isSoldeCell) {
        const solde = isRecette
          ? stat.consomme - stat.prevu
          : toNumber(stat.ligne.montant_disponible)
        if (isRecette && solde >= 0 && stat.pct >= 100) {
          data.cell.styles.textColor = '#047857'
          data.cell.styles.fontStyle = 'bold'
          if (depassement) data.cell.styles.fillColor = '#ecfdf5'
        } else if (!isRecette && solde < 0) {
          data.cell.styles.textColor = '#dc2626'
          data.cell.styles.fontStyle = 'bold'
          if (depassement) data.cell.styles.fillColor = '#fef2f2'
        }
      }
    },
    didDrawPage: () => {
      addFooter(doc.getNumberOfPages())
    }
  })

  // ── Synthèse budgétaire enrichie + représentation graphique ───────────────
  const totalConsomme = totalPaye
  const tauxGlobal = totalPrevu > 0 ? (totalConsomme / totalPrevu) * 100 : 0
  // Indicateurs et top 5 comptent les sous-postes réels (feuilles), pas les parents.
  const leafStats = rowStats.filter(r => !r.ligne.is_parent && estCompte(r.ligne))
  const nbPostes = leafStats.length
  const nbEntames = leafStats.filter(r => r.consomme > 0).length
  const nbProches = leafStats.filter(r => r.pct >= 90 && r.pct < 100).length
  const nbDepassements = leafStats.filter(r => r.pct >= 100).length

  const marginX = 10
  const contentW = pageWidth - marginX * 2

  let y = (doc as any).lastAutoTable.finalY + 10

  // Le commentaire général se lit immédiatement sous le tableau qu'il commente,
  // avant la synthèse : c'est la lecture attendue d'un document budgétaire.
  y = drawCommentaireGeneral(doc, {
    texte: options?.commentaireGeneral || '',
    y,
    marginX,
    contentW,
    pageHeight,
    onNewPage: () => addFooter(doc.getNumberOfPages()),
  })

  // Saut de page si l'espace restant est insuffisant pour la synthèse complète.
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
        { label: 'Prévision totale', value: `${formatBudgetAmount(totalPrevu)} $` },
        { label: 'Recettes réalisées', value: `${formatBudgetAmount(totalConsomme)} $` },
        { label: 'Taux de réalisation', value: `${tauxGlobal.toFixed(1)} %` },
      ]
    : [
        { label: 'Prévision totale', value: `${formatBudgetAmount(totalPrevu)} $` },
        { label: 'Total réalisé', value: `${formatBudgetAmount(totalConsomme)} $` },
        { label: 'Solde budgétaire', value: `${formatBudgetAmount(totalDisponible)} $` },
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
  const level = isRecette
    ? (tauxGlobal >= 100 ? '#047857' : ONEC_GREEN)
    : (tauxGlobal > 100 ? '#dc2626' : tauxGlobal >= 100 ? '#b45309' : tauxGlobal >= 90 ? '#b45309' : ONEC_GREEN)
  doc.setFontSize(8.5)
  doc.setTextColor(0)
  doc.setFont('helvetica', 'bold')
  doc.text('Taux de réalisation global', marginX, y)
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

  // Top 5 postes réalisés — barres horizontales
  const top = [...leafStats]
    .filter(r => r.consomme > 0)
    .sort((a, b) => b.consomme - a.consomme)
    .slice(0, 5)
  if (top.length > 0) {
    doc.setFontSize(8.5)
    doc.setTextColor(0)
    doc.setFont('helvetica', 'bold')
    doc.text(isRecette ? 'Top 5 des recettes' : 'Top 5 des postes les plus réalisés', marginX, y)
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
      const barColor = isRecette
        ? (r.pct >= 100 ? '#047857' : ONEC_GREEN)
        : (r.pct > 100 ? '#dc2626' : r.pct >= 90 ? '#b45309' : ONEC_GREEN)
      doc.setFillColor(barColor)
      doc.roundedRect(marginX + labelW, y, bw, 4, 0.8, 0.8, 'F')
      doc.setTextColor(0)
      doc.setFontSize(6.5)
      doc.text(`${formatBudgetAmount(r.consomme)} $`, marginX + labelW + bw + 2, y + 3.2)
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
  commentaireGeneral,
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
    /** Faux = ligne affichée mais exclue des totaux et de la synthèse. */
    inclure_dans_calculs?: boolean
  }>
  annee: number
  vue: 'DEPENSE' | 'RECETTE'
  serviceLabel: string
  totals: { recettes: number; depenses: number; solde: number }
  /** Commentaire général de l'exercice : le rapport d'un service reste un
   *  document budgétaire, il porte le même chapeau que l'export complet. */
  commentaireGeneral?: string | null
}) => {
  const settings = await getPrintSettingsData()
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const formatBudgetAmount = (value: string | number, fractionDigits = 2) =>
    formatAmount(value, fractionDigits).replace(/[\u00a0\u202f]/g, ' ')

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

  addHeader()

  doc.setFontSize(15)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text(`Rapport budgétaire - ${serviceLabel}`, pageWidth / 2, 50, { align: 'center' })

  doc.setFontSize(11)
  doc.setTextColor(0)
  doc.setFont('helvetica', 'normal')
  doc.text(`Exercice ${annee} · Vue ${vue === 'RECETTE' ? 'Recettes' : 'Dépenses'}`, pageWidth / 2, 58, {
    align: 'center',
  })

  const cardY = 66
  const cardWidth = (pageWidth - 30) / 3
  const cardHeight = 20
  const cardTitles = ['Recettes', 'Dépenses', 'Solde']
  const cardValues = [totals.recettes, totals.depenses, totals.solde]

  cardTitles.forEach((title, index) => {
    const x = 10 + index * (cardWidth + 5)
    doc.setDrawColor(ONEC_GREEN)
    doc.setFillColor(ONEC_LIGHT_GREEN)
    doc.roundedRect(x, cardY, cardWidth, cardHeight, 2, 2, 'FD')
    doc.setFontSize(7.5)
    doc.setTextColor(90)
    doc.setFont('helvetica', 'normal')
    doc.text(title, x + 4, cardY + 6)
    doc.setFontSize(10)
    doc.setTextColor(ONEC_GREEN)
    doc.setFont('helvetica', 'bold')
    doc.text(`${formatBudgetAmount(cardValues[index])} $`, x + cardWidth - 4, cardY + 14.5, { align: 'right' })
  })

  const tableData = lignes.map((ligne) => [
    ligne.code || '',
    // Les cartes de synthèse en tête de page excluent déjà ces lignes : sans la
    // mention, le tableau semblerait les contredire.
    ligne.inclure_dans_calculs === false
      ? `${ligne.libelle || ''}  (hors calcul)`
      : ligne.libelle || '',
    `${formatBudgetAmount(ligne.montant_prevu)} $`,
    `${formatBudgetAmount(ligne.montant_paye)} $`,
    vue === 'RECETTE'
      ? `${formatBudgetAmount(toNumber(ligne.montant_paye) - toNumber(ligne.montant_prevu))} $`
      : `${formatBudgetAmount(ligne.montant_disponible)} $`,
  ])
  const HEADER_SOLDE_BUDGETAIRE = 'Solde\nbudgétaire'
  const serviceCodeWidthContent = Math.max(
    doc.getTextWidth('Code'),
    ...lignes.map((ligne) => doc.getTextWidth(ligne.code || ''))
  )
  const SERVICE_CODE_WIDTH = Math.min(20, Math.max(12, Math.ceil(serviceCodeWidthContent + 7)))
  const SERVICE_LABEL_WIDTH = 92 - SERVICE_CODE_WIDTH

  autoTable(doc, {
    head: [[
      'Code',
      'Poste budgétaire',
      'Prévision',
      'Réalisation',
      HEADER_SOLDE_BUDGETAIRE,
    ]],
    body: tableData,
    startY: cardY + cardHeight + 8,
    theme: 'grid',
    headStyles: {
      fillColor: ONEC_GREEN,
      textColor: 255,
      fontStyle: 'bold',
      fontSize: 8,
      cellPadding: { top: 2.2, right: 2, bottom: 2.2, left: 2 },
      valign: 'middle',
    },
    bodyStyles: {
      fontSize: 7.8,
      cellPadding: 2.2,
    },
    styles: {
      overflow: 'linebreak',
      valign: 'middle',
    },
    alternateRowStyles: {
      fillColor: [245, 245, 245],
    },
    columnStyles: {
      0: { cellWidth: SERVICE_CODE_WIDTH },
      1: { cellWidth: SERVICE_LABEL_WIDTH },
      2: { cellWidth: 30, halign: 'right' },
      3: { cellWidth: 30, halign: 'right' },
      4: { cellWidth: 38, halign: 'right' },
    },
    didParseCell: (data: any) => {
      if (data.section !== 'body' || data.column.index !== 4) return
      const ligne = lignes[data.row.index]
      if (!ligne) return
      const pct = toNumber(ligne.pourcentage_consomme)
      const solde = vue === 'RECETTE'
        ? toNumber(ligne.montant_paye) - toNumber(ligne.montant_prevu)
        : toNumber(ligne.montant_disponible)
      if (vue === 'RECETTE' && solde >= 0 && pct >= 100) {
        data.cell.styles.textColor = '#047857'
        data.cell.styles.fontStyle = 'bold'
        if (pct > 100) data.cell.styles.fillColor = '#ecfdf5'
      } else if (vue === 'DEPENSE' && solde < 0) {
        data.cell.styles.textColor = '#dc2626'
        data.cell.styles.fontStyle = 'bold'
        if (pct > 100) data.cell.styles.fillColor = '#fef2f2'
      }
    },
    didDrawPage: () => {
      addFooter(doc.getNumberOfPages())
    },
  })

  drawCommentaireGeneral(doc, {
    texte: commentaireGeneral || '',
    y: (doc as any).lastAutoTable.finalY + 10,
    marginX: 10,
    contentW: pageWidth - 20,
    pageHeight,
    onNewPage: () => addFooter(doc.getNumberOfPages()),
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
  const servicesMap = await getServicesMap()
  const comptesMap = await getComptesBancairesMap()

  // --- Volets de règlement.
  // Une réquisition peut se régler en plusieurs fois, depuis des origines
  // différentes (caisse, ou telle banque). Le backend renvoie ce découpage ;
  // à défaut — pièce ancienne, prévisualisation avant enregistrement — on le
  // recalcule depuis les lignes pour que le bon reste fidèle.
  const modeReglementLabel = (mode?: string | null) => {
    const value = String(mode || '').toLowerCase()
    if (value === 'cash') return 'Caisse'
    if (value === 'mobile_money') return 'Mobile Money'
    if (value === 'card') return 'Carte'
    if (value === 'cheque') return 'Chèque'
    if (value === 'mixte') return 'Mixte'
    return 'Banque'
  }
  const voletKey = (mode?: string | null, compteId?: any) => {
    const value = String(mode || 'cash').toLowerCase()
    // Le compte ne distingue que les volets bancaires : côté caisse il n'a pas
    // de sens et scinderait le volet à tort.
    return value === 'cash' ? 'cash|' : `${value}|${compteId ?? ''}`
  }
  const voletsFournis: any[] = Array.isArray(requisition.volets_reglement)
    ? requisition.volets_reglement
    : []
  const volets = voletsFournis.length > 0
    ? voletsFournis
    : (() => {
        const groupes = new Map<string, any>()
        lignes.forEach((ligne: any) => {
          const mode = String(ligne.mode_paiement || requisition.mode_paiement || 'cash').toLowerCase()
          const compteId = mode === 'cash' ? null : (ligne.compte_bancaire_id ?? requisition.compte_bancaire_id ?? null)
          const key = voletKey(mode, compteId)
          const existant = groupes.get(key)
          if (existant) {
            existant.montant_total = toNumber(existant.montant_total) + toNumber(ligne.montant_total)
          } else {
            groupes.set(key, {
              mode_paiement: mode,
              compte_bancaire_id: compteId,
              montant_total: toNumber(ligne.montant_total),
            })
          }
        })
        return Array.from(groupes.values())
      })()
  const multiVolets = volets.length > 1
  // Taux USD -> CDF, utilisé pour la ligne « 1 USD = X CDF » et pour convertir
  // les lignes libellées en CDF.
  //
  // Attention : `exchange_rate_snapshot` N'EST PAS ce taux. Il vaut « unités de
  // la devise de la réquisition pour 1 USD » (cf. exchange_rate_for_currency),
  // donc 1 pour une réquisition en USD — d'où l'absurde « 1 USD = 1.00 CDF »
  // qu'affichait cette ligne. On ne l'utilise que si la réquisition est en CDF,
  // cas où il coïncide effectivement avec le taux USD -> CDF.
  //
  // Priorité au taux figé dans print_settings_snapshot : c'est celui qui était
  // configuré au moment de la réquisition, donc le seul fidèle à la pièce.
  const snapshotCdfRate = Number(
    (requisition?.print_settings_snapshot as any)?.exchange_rate_cdf ?? 0,
  )
  const reqDevise = String(requisition?.devise || 'USD').toUpperCase()
  const exchangeRate =
    snapshotCdfRate > 0
      ? snapshotCdfRate
      : reqDevise === 'CDF' && Number(requisition?.exchange_rate_snapshot) > 0
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
  // Le filet de pied de page est tracé à `pageHeight - 14` : la limite basse du
  // contenu lui laisse 2 mm de dégagement, sans gaspiller le reste.
  const footerReserve = 16
  const contentBottomLimit = pageHeight - footerReserve
  // Le bon porte deux rangées de signatures : demandeur et Secrétaire exécutif
  // d'abord, signataires statutaires ensuite. Une rangée = label, espace de
  // paraphe, trait, puis nom imprimé sous le trait.
  // Le pas sépare franchement les deux rangées : à 21 mm, le libellé statutaire
  // suivait le nom du demandeur de 4 mm et les deux rangées se lisaient comme un
  // seul bloc de quatre signatures.
  const signatureRowPitch = 28
  const signatureLineOffset = 12
  const signatureBlockHeight = signatureRowPitch + signatureLineOffset + 10
  const qrBlockHeight = 15
  // Écart entre le trait de signature et le QR, pour que les deux ne soient pas
  // lus comme un même bloc.
  const QR_SIGNATURE_GAP = 13
  const stampBlockHeight = stampDataUrl ? 24 : 0
  const footerGap = 8
  // Les pages 2 et suivantes reçoivent un bandeau de rappel : le contenu y
  // démarre donc plus bas que la marge haute habituelle.
  const continuationTopY = 24
  const ensureSpace = (currentY: number, requiredHeight: number, nextStartY = continuationTopY) => {
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
  // Date MÉTIER de la réquisition (antidatable), avec repli sur l'horodatage
  // technique pour les pièces antérieures à son introduction.
  const createdAt = requisition.date_requisition
    ? new Date(requisition.date_requisition)
    : requisition.created_at
      ? new Date(requisition.created_at)
      : new Date()
  const logoX = 15
  const logoY = 9
  // Boîte réservée au logo : légèrement plus large que haute pour laisser
  // respirer les logos horizontaux, l'image étant ajustée à ses proportions.
  const logoBoxWidth = 36
  const logoBoxHeight = 29
  const leftStartX = logoDataUrl ? logoX + logoBoxWidth + 6 : pageMargin
  // Le bloc de droite ne porte plus que la date et l'exercice : le reste de la
  // largeur revient au nom calligraphié de l'organisation.
  const rightBlockWidth = 36
  const rightStartX = pageWidth - pageMargin - rightBlockWidth
  const leftBlockWidth = Math.max(55, rightStartX - leftStartX - 8)

  if (logoDataUrl) {
    addLogo(doc, logoX, logoY, logoBoxWidth, logoDataUrl, logoBoxHeight)
  }

  // Le nom de l'organisation reprend la calligraphie de la page de connexion.
  // Sans la police embarquée on retombe sur Times, qui reste lisible.
  const scriptFontReady = await registerScriptFont(doc)
  const orgNameFont = scriptFontReady ? SCRIPT_FONT_NAME : 'times'
  const orgNameStyle = scriptFontReady ? 'normal' : 'bold'
  const orgNameSize = scriptFontReady ? 21 : 14
  const orgNameLeading = scriptFontReady ? 7.5 : 5.5
  // Une calligraphie ne se met pas en capitales : on garde la casse d'origine,
  // comme sur l'écran de connexion.
  const orgNameText = scriptFontReady ? orgName : orgName.toUpperCase()

  // jsPDF mesure avec la police courante : sans la régler avant de découper, le
  // texte était calibré sur la taille par défaut (16 pt) et cassait bien plus
  // tôt qu'à l'affichage — d'où les retours à la ligne au milieu des mots.
  doc.setFont(orgNameFont, orgNameStyle)
  doc.setFontSize(orgNameSize)
  const orgNameLines = doc.splitTextToSize(orgNameText, leftBlockWidth)
  doc.setFont('times', 'normal')
  doc.setFontSize(10)
  const orgSubtitleLines = orgSubtitle ? doc.splitTextToSize(orgSubtitle, leftBlockWidth) : []
  // Le numéro identifie la pièce : il ferme le bloc d'identité de gauche, à la
  // place de la mention libre `header_text` qui n'apportait rien au document.
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  const refLines: string[] = doc.splitTextToSize(`N° ${refNumber}`, leftBlockWidth)

  // La référence externe a été retirée de l'en-tête : elle doublonnait avec le
  // numéro de réquisition sans être exploitée par les destinataires.
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  const rightInfoLines: string[] = [
    `Date : ${format(createdAt, 'dd/MM/yyyy')}`,
    `Exercice : ${fiscalYear}`,
  ].flatMap((line) => doc.splitTextToSize(line, rightBlockWidth))

  doc.setTextColor(0)
  doc.setFont(orgNameFont, orgNameStyle)
  doc.setFontSize(orgNameSize)
  let currentLeftY = scriptFontReady ? 17 : 16
  doc.text(orgNameLines, leftStartX, currentLeftY)
  currentLeftY += orgNameLines.length * orgNameLeading
  if (orgSubtitleLines.length > 0) {
    doc.setFont('times', 'normal')
    doc.setFontSize(10)
    doc.text(orgSubtitleLines, leftStartX, currentLeftY)
    currentLeftY += orgSubtitleLines.length * 4.5
  }
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.setTextColor(41, 128, 185)
  currentLeftY += 1
  doc.text(refLines, leftStartX, currentLeftY)
  currentLeftY += refLines.length * 5

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(100)
  let currentRightY = 16
  rightInfoLines.forEach((line) => {
    doc.text(line, pageWidth - pageMargin, currentRightY, { align: 'right' })
    currentRightY += 4.5
  })

  const headerBottomY = Math.max(logoY + logoBoxHeight, currentLeftY, currentRightY) + 3
  const titleY = headerBottomY + 8.5
  const infoTableStartY = titleY + 6
  const separatorY = headerBottomY

  // Plus de filet vertical de séparation : la colonne de droite ne porte plus
  // que la date et l'exercice, un trait pleine hauteur pointait vers du vide.

  doc.setTextColor(0)

  doc.setDrawColor(0)
  doc.setLineWidth(0.5)
  doc.line(15, separatorY, pageWidth - 15, separatorY)

  // Bandeau de titre : donne un point d'ancrage visuel entre l'en-tête et le
  // corps du document, là où il n'y avait qu'un texte flottant.
  doc.setFillColor(241, 245, 249)
  doc.setDrawColor(203, 213, 225)
  doc.setLineWidth(0.2)
  doc.roundedRect(pageMargin, separatorY + 2, contentWidth, 10, 1.5, 1.5, 'FD')
  const documentTitle =
    requisition.req_titre_officiel_hist ||
    effectiveSettings?.req_titre_officiel ||
    'BON DE RÉQUISITION DE FONDS'
  doc.setFont('times', 'bold')
  doc.setFontSize(15)
  doc.setTextColor(15, 23, 42)
  doc.text(documentTitle, pageWidth / 2, titleY, { align: 'center' })
  doc.setTextColor(0)

  /**
   * Bandeau de rappel sur les pages 2 et suivantes : sans lui, une réquisition
   * à nombreuses lignes produisait des feuilles de tableau anonymes, impossibles
   * à rattacher à leur bon une fois imprimées et détachées.
   */
  const drawContinuationHeader = (pageNumber: number) => {
    doc.setPage(pageNumber)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8.5)
    doc.setTextColor(60)
    const orgLabel = doc.splitTextToSize(orgName, 85)[0]
    doc.text(orgLabel, pageMargin, 13)
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(110)
    // Les deux mentions se font face : si le titre officiel est long, on ne
    // garde que la référence plutôt que de laisser les textes se chevaucher.
    const rightRoom = contentWidth - doc.getTextWidth(orgLabel) - 6
    const fullRightLabel = `${documentTitle} — N° ${refNumber} (suite)`
    const rightLabel = doc.getTextWidth(fullRightLabel) <= rightRoom
      ? fullRightLabel
      : `N° ${refNumber} (suite)`
    doc.text(rightLabel, pageWidth - pageMargin, 13, { align: 'right' })
    doc.setDrawColor(220)
    doc.setLineWidth(0.2)
    doc.line(pageMargin, 16.5, pageWidth - pageMargin, 16.5)
    doc.setTextColor(0)
  }

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
  // Règlement en plusieurs volets : la case unique n'a plus de sens, on annonce
  // le découpage et le détail est donné plus bas.
  const modePaiement = multiVolets
    ? `Règlement en ${volets.length} volets`
    : requisition.mode_paiement === 'cash' ? 'Caisse' :
      requisition.mode_paiement === 'mobile_money' ? 'Mobile Money' :
      requisition.mode_paiement === 'card' ? 'Carte (Visa)' : 'Opération bancaire'

  // Le service est porté par `service_id` ; on résout son libellé via le cache
  // des services, avec repli sur un libellé déjà embarqué dans la pièce.
  const serviceLabel =
    getTrimmedSetting(requisition.service_libelle) ||
    getTrimmedSetting(requisition.service_nom) ||
    servicesMap.get(Number(requisition.service_id)) ||
    '-'
  const formatDateField = (value: any) => {
    if (!value) return '-'
    const parsed = new Date(value)
    return Number.isNaN(parsed.getTime()) ? '-' : format(parsed, 'dd/MM/yyyy')
  }
  const examinateur = formatUserName(requisition.examinateur)
  const val1 = formatUserName(requisition.validateur)
  const val2 = formatUserName(requisition.approbateur)

  // Le poste budgétaire est propre à chaque ligne : il est affiché dans le
  // tableau des dépenses, pas ici (un « poste principal » déduit de la première
  // ligne serait faux dès que la réquisition couvre plusieurs postes).
  const infoRows: any[] = [
    [
      { content: 'Objet / Motif', styles: { fontStyle: 'bold' } },
      { content: requisition.objet || '-', colSpan: 3 },
    ],
    ['Service', serviceLabel, 'Demandeur', formatUserName(requisition.demandeur)],
    ['Mode de paiement', modePaiement, 'Statut', statut],
    // Libellés distincts de la valeur du champ « Statut », qui emploie déjà
    // « Validation 1/2 » : côte à côte, les deux prêtaient à confusion.
    ['Examinateur', examinateur, 'Examiné le', formatDateField(requisition.examen_le)],
    ['Validé par (1/2)', val1, 'Approuvé par (2/2)', val2],
  ]

  autoTable(doc, {
    tableWidth: contentWidth,
    margin: { left: pageMargin, right: pageMargin },
    startY: infoTableStartY,
    theme: 'grid',
    styles: { font: 'times', fontSize: 9, cellPadding: 2.3, lineColor: [215, 215, 215], lineWidth: 0.15, valign: 'middle' },
    columnStyles: {
      0: { cellWidth: 38, fontStyle: 'bold', fillColor: [248, 250, 252] },
      1: { cellWidth: 52 },
      2: { cellWidth: 38, fontStyle: 'bold', fillColor: [248, 250, 252] },
      3: { cellWidth: 52 },
    },
    didParseCell: (data) => {
      // Le statut est l'information la plus scannée du bloc : on la met en avant.
      if (data.row.index === 2 && data.column.index === 3) {
        data.cell.styles.fontStyle = 'bold'
        data.cell.styles.textColor = rawStatus === 'REJETEE'
          ? [185, 28, 28]
          : rawStatus === 'PAYEE'
            ? [21, 128, 61]
            : [180, 83, 9]
      }
    },
    body: infoRows,
  })

  let yPos = (doc as any).lastAutoTable.finalY + 6

  const tableData = lignes.map(ligne => {
    const devise = (ligne.devise || 'USD').toUpperCase()
    const isCdf = devise === 'CDF'
    const montantUnitaire = isCdf && exchangeRate ? toNumber(ligne.montant_unitaire) * exchangeRate : ligne.montant_unitaire
    const montantTotal = isCdf && exchangeRate ? toNumber(ligne.montant_total) * exchangeRate : ligne.montant_total
    const currencyLabel = devise === 'CDF' ? 'CDF' : '$'
    return [
      ligne.rubrique,
      ligne.description,
      // La colonne « Règlement » n'apparaît que sur les pièces à plusieurs
      // volets : ailleurs elle répéterait le mode déjà donné en tête.
      ...(multiVolets
        ? [modeReglementLabel(ligne.mode_paiement || requisition.mode_paiement)]
        : []),
      devise,
      ligne.quantite.toString(),
      `${formatAmount(montantUnitaire)} ${currencyLabel}`,
      `${formatAmount(montantTotal)} ${currencyLabel}`
    ]
  })

  autoTable(doc, {
    tableWidth: contentWidth,
    // `top` s'applique aux pages suivantes : le tableau reprend sous le bandeau
    // de rappel, `bottom` lui laisse le pied de page.
    margin: { left: pageMargin, right: pageMargin, top: continuationTopY, bottom: footerReserve + 2 },
    head: [[
      'Poste budgétaire',
      'Description',
      ...(multiVolets ? ['Règlement'] : []),
      'Devise',
      'Qté',
      'PU',
      'Total',
    ]],
    body: tableData,
    startY: yPos,
    theme: 'grid',
    pageBreak: 'auto',
    rowPageBreak: 'avoid',
    // L'en-tête de colonnes est répété sur chaque page du tableau.
    showHead: 'everyPage',
    headStyles: {
      fillColor: [31, 41, 55],
      textColor: 255,
      fontStyle: 'bold',
      fontSize: 9,
      font: 'times',
      cellPadding: 2.6
    },
    bodyStyles: {
      fontSize: 8.5,
      cellPadding: 2.4,
      font: 'times',
      lineColor: [225, 225, 225],
      lineWidth: 0.15,
      overflow: 'linebreak',
      valign: 'top'
    },
    alternateRowStyles: {
      fillColor: [249, 250, 251]
    },
    // Les chiffres sont ce que le lecteur vient chercher : Qté, PU et Total
    // sont composés plus gros que le texte, le total de ligne en gras. Les
    // colonnes de gauche cèdent la largeur nécessaire.
    // La colonne « Règlement » se finance sur la description : une pièce à
    // plusieurs volets est intrinsèquement plus dense.
    columnStyles: multiVolets
      ? {
          0: { cellWidth: 22 },
          1: { cellWidth: 46 },
          2: { cellWidth: 22, halign: 'center' },
          3: { cellWidth: 14, halign: 'center' },
          4: { cellWidth: 13, halign: 'center', fontSize: 10.5 },
          5: { cellWidth: 30, halign: 'right', fontSize: 10.5 },
          6: { cellWidth: 33, halign: 'right', fontSize: 10.5, fontStyle: 'bold' },
        }
      : {
          // Les codes de poste sont courts, la colonne n'a pas besoin de la
          // largeur de son intitulé (qui se replie sur deux lignes en en-tête).
          0: { cellWidth: 24 },
          1: { cellWidth: 61 },
          2: { cellWidth: 17, halign: 'center' },
          3: { cellWidth: 14, halign: 'center', fontSize: 10.5 },
          4: { cellWidth: 31, halign: 'right', fontSize: 10.5 },
          // Assez large pour que « 12 345.67 USD » tienne sur une seule ligne.
          5: { cellWidth: 33, halign: 'right', fontSize: 10.5, fontStyle: 'bold' },
        },
    foot: [[
      { content: 'MONTANT TOTAL', colSpan: multiVolets ? 6 : 5, styles: { halign: 'right', fontStyle: 'bold' } },
      { content: `${formatAmount(requisition.montant_total)} USD`, styles: { fontStyle: 'bold', halign: 'right', fontSize: 11 } }
    ]],
    footStyles: {
      fillColor: [241, 245, 249],
      textColor: 15,
      fontStyle: 'bold',
      fontSize: 9.5,
      font: 'times',
      cellPadding: 2.8,
      lineColor: [203, 213, 225],
      lineWidth: 0.2,
    },
  })

  let finalY = (doc as any).lastAutoTable.finalY + 6

  // --- Détail des volets de règlement.
  // Chaque volet sera autorisé puis payé séparément : le bon doit dire d'où
  // sort chaque part, sans quoi le caissier ne peut pas exécuter la pièce.
  if (multiVolets) {
    finalY = ensureSpace(finalY, 14 + volets.length * 7)
    autoTable(doc, {
      tableWidth: contentWidth,
      margin: { left: pageMargin, right: pageMargin },
      startY: finalY,
      theme: 'grid',
      styles: { font: 'times', fontSize: 8.5, cellPadding: 2.4, lineColor: [220, 220, 220], lineWidth: 0.15 },
      head: [['Volet de règlement', 'Origine des fonds', 'Montant']],
      headStyles: {
        fillColor: [241, 245, 249],
        textColor: 15,
        fontStyle: 'bold',
        fontSize: 8.5,
        font: 'times',
        cellPadding: 2.4,
        lineColor: [203, 213, 225],
        lineWidth: 0.2,
      },
      columnStyles: {
        0: { cellWidth: 45, fontStyle: 'bold' },
        1: { cellWidth: 100 },
        2: { cellWidth: 35, halign: 'right', fontStyle: 'bold' },
      },
      body: volets.map((volet: any, index: number) => [
        `Volet ${index + 1} — ${modeReglementLabel(volet.mode_paiement)}`,
        volet.compte_bancaire_id
          ? (comptesMap.get(Number(volet.compte_bancaire_id)) || `Compte n° ${volet.compte_bancaire_id}`)
          : 'Caisse centrale',
        `${formatAmount(volet.montant_total)} USD`,
      ]),
    })
    finalY = (doc as any).lastAutoTable.finalY + 6
  }

  const totalUsd = Number(requisition.montant_total || 0)
  const totalCdf = exchangeRate ? totalUsd * exchangeRate : 0
  // Récapitulatif adossé à la marge droite, dans l'axe de la colonne « Total »
  // du tableau : le pleine largeur d'avant étirait trois lignes courtes sur 180 mm.
  const recapWidth = 88
  const lettresBoxWidth = contentWidth - recapWidth - 6
  doc.setFont('times', 'italic')
  doc.setFontSize(9)
  const montantEnLettres = numberToWords(Number(requisition.montant_total))
  const montantLines = doc.splitTextToSize(montantEnLettres, lettresBoxWidth - 8)
  // On réserve la hauteur du plus grand des deux blocs côte à côte.
  finalY = ensureSpace(finalY, Math.max(28, (montantLines.length * 4.6) + 13))
  autoTable(doc, {
    tableWidth: recapWidth,
    margin: { left: pageWidth - pageMargin - recapWidth, right: pageMargin },
    startY: finalY,
    theme: 'grid',
    styles: { font: 'times', fontSize: 8.5, cellPadding: 2.5, lineColor: [220, 220, 220], lineWidth: 0.15 },
    columnStyles: {
      0: { cellWidth: 46, fontStyle: 'bold', fillColor: [248, 250, 252] },
      1: { cellWidth: recapWidth - 46, halign: 'right' },
    },
    body: [
      ['Montant sollicité (USD)', `${formatAmount(totalUsd)} USD`],
      ['Taux de change', exchangeRate ? `1 USD = ${formatAmount(exchangeRate)} CDF` : 'Non défini'],
      ['Équivalent (CDF)', exchangeRate ? `${formatAmount(totalCdf)} CDF` : 'Non défini'],
    ],
  })

  const recapFinalY = (doc as any).lastAutoTable.finalY

  // Montant en lettres : encadré, à gauche du récapitulatif, pour occuper la
  // place laissée libre plutôt que de repousser tout le bloc signatures.
  const lettresBoxHeight = Math.max(recapFinalY - finalY, (montantLines.length * 4.6) + 11)
  doc.setDrawColor(220)
  doc.setFillColor(252, 252, 253)
  doc.setLineWidth(0.15)
  doc.roundedRect(pageMargin, finalY, lettresBoxWidth, lettresBoxHeight, 1.5, 1.5, 'FD')
  doc.setFont('times', 'bold')
  doc.setFontSize(8)
  doc.setTextColor(100)
  doc.text('ARRÊTÉ LE PRÉSENT BON À LA SOMME DE', pageMargin + 4, finalY + 5.5)
  doc.setFont('times', 'italic')
  doc.setFontSize(9)
  doc.setTextColor(30)
  doc.text(montantLines, pageMargin + 4, finalY + 11)
  doc.setTextColor(0)

  finalY = Math.max(recapFinalY, finalY + lettresBoxHeight) + 6

  if (requisition.a_valoir) {
    const notesLines = requisition.notes_a_valoir
      ? doc.splitTextToSize(`Notes : ${requisition.notes_a_valoir}`, contentWidth - 8)
      : []
    const aValoirHeight = Math.max(25, 18 + (notesLines.length * 5))
    finalY = ensureSpace(finalY, aValoirHeight + footerGap)
    doc.setDrawColor('#f59e0b')
    doc.setFillColor('#fef3c7')
    doc.setLineWidth(0.3)
    // Aligné sur les marges du reste de la pièce (le bloc débordait à 10 mm).
    doc.roundedRect(pageMargin, finalY, contentWidth, aValoirHeight, 2, 2, 'FD')

    doc.setFontSize(10)
    doc.setTextColor('#92400e')
    doc.setFont('times', 'bold')
    doc.text('RÉQUISITION À VALOIR', pageMargin + 4, finalY + 8)

    doc.setFont('times', 'normal')
    doc.setFontSize(9)
    doc.text(`Instance bénéficiaire : ${requisition.instance_beneficiaire || 'N/A'}`, pageMargin + 4, finalY + 15)
    if (notesLines.length > 0) {
      doc.text(notesLines, pageMargin + 4, finalY + 20)
    }
    doc.setTextColor(0)
    finalY += aValoirHeight + 6
  }

  // Hauteur réellement occupée sous `signatureY`, et non une marge forfaitaire :
  // la surestimation d'avant renvoyait le bloc signatures sur une page vide
  // alors qu'il restait la place sur la première.
  // Hauteurs mesurées depuis `signatureY` : label, trait à +14, puis nom, QR ou
  // cachet sous le trait.
  const qrVisible = settings?.afficher_qr_code !== false
  const signatureLeadGap = 6
  // Cachet et QR pendent sous la rangée du bas : leur dégagement se mesure
  // depuis celle-ci, pas depuis le haut du bloc.
  const signatureAreaHeight = Math.max(
    signatureBlockHeight,
    qrVisible ? signatureRowPitch + signatureLineOffset + QR_SIGNATURE_GAP + qrBlockHeight : 0,
    stampDataUrl ? signatureRowPitch + signatureLineOffset + 6 + stampBlockHeight : 0,
  )
  finalY = ensureSpace(finalY + 2, signatureLeadGap + signatureAreaHeight + 2, 24)
  const signatureY = Math.max(finalY + signatureLeadGap, 34)
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

  // Le demandeur signe ce qu'il sollicite, le Secrétaire exécutif ce qu'il a
  // examiné : sans emplacement prévu, ces deux visas se posaient dans la marge
  // ou en travers du tableau.
  //
  // Le Secrétaire exécutif est un poste dont le titulaire change de mandat en
  // mandat : son nom vient des paramètres d'impression, figés dans le snapshot
  // pour une pièce déjà émise. À défaut de paramétrage, on retombe sur celui
  // qui a réellement examiné — c'est le plus souvent la même personne. Sans
  // l'un ni l'autre, la ligne reste vierge : un bon tiré avant l'examen se
  // signe à la main.
  const labelDemandeur = 'Le demandeur'
  const labelSecretaire = effectiveSettings?.secretaire_executif_label || 'Le Secrétaire exécutif'
  const nomDemandeur = requisition.demandeur ? formatUserName(requisition.demandeur) : ''
  const nomSecretaire =
    effectiveSettings?.secretaire_executif_nom ||
    (requisition.examinateur ? formatUserName(requisition.examinateur) : '')

  // Deux blocs de signature de même largeur, calés sur les marges du document
  // (les traits faisaient auparavant 58 mm à gauche contre 50 mm à droite).
  const signatureColWidth = 62
  const signatureLeftX = pageMargin
  const signatureRightX = pageWidth - pageMargin - signatureColWidth
  const signatureStatutaireY = signatureY + signatureRowPitch
  const signatureLineY = signatureStatutaireY + signatureLineOffset

  const dessinerSignature = (x: number, y: number, label: string, nom: string) => {
    doc.setFont('times', 'bold')
    doc.setFontSize(9.5)
    doc.setTextColor(80)
    doc.text(label.toUpperCase(), x, y)

    doc.setDrawColor(120)
    doc.setLineWidth(0.2)
    doc.line(x, y + signatureLineOffset, x + signatureColWidth, y + signatureLineOffset)

    // Le nom se lit sous le trait, à la place d'une signature manuscrite.
    if (nom && nom !== 'N/A') {
      doc.setFont('times', 'normal')
      doc.setFontSize(9)
      doc.setTextColor(30)
      doc.text(nom, x, y + signatureLineOffset + 4.5)
    }
    doc.setTextColor(0)
  }

  // Rangée du haut : ceux qui attestent la demande. Rangée du bas : ceux qui
  // l'autorisent. L'ordre de lecture reproduit le circuit du bon ; les quatre
  // alignés sur une seule ligne, plus rien n'aurait dit qui signe avant qui.
  dessinerSignature(signatureLeftX, signatureY, labelDemandeur, nomDemandeur)
  dessinerSignature(signatureRightX, signatureY, labelSecretaire, nomSecretaire)
  dessinerSignature(signatureLeftX, signatureStatutaireY, labelGauche, nomGauche)
  dessinerSignature(signatureRightX, signatureStatutaireY, labelDroite, nomDroite)

  if (stampDataUrl) {
    const stampSize = stampBlockHeight
    // Sous le trait de la colonne de droite, sans recouvrir le nom du signataire.
    const stampX = signatureRightX + signatureColWidth - stampSize
    const stampY = signatureLineY + 6
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
      const qrSize = qrBlockHeight
      const qrX = pageMargin
      // Bien détaché du nom du signataire de gauche : collé sous le trait, il
      // se lisait comme un élément de la signature.
      const qrY = Math.min(pageHeight - 20 - qrSize, signatureLineY + QR_SIGNATURE_GAP)
      doc.addImage(qrDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(7)
      doc.setTextColor(120)
      doc.text("Scannez pour vérifier", qrX + qrSize + 2.5, qrY + 6.5)
      doc.text("l'authenticité du bon", qrX + qrSize + 2.5, qrY + 10)
      doc.setTextColor(0)
    } catch (_err) {
      // Si QRCode n'est pas disponible, on ignore sans bloquer le PDF.
    }
  }

  const totalPages = doc.getNumberOfPages()
  for (let page = 1; page <= totalPages; page += 1) {
    if (page > 1) drawContinuationHeader(page)
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
