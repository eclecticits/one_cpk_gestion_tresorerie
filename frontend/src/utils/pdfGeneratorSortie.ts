import jsPDF from 'jspdf'
import QRCode from 'qrcode'
import { format } from 'date-fns'
import { API_BASE_URL } from '../lib/apiClient'
import { numberToWords } from './numberToWords'
import { formatAmount, toNumber } from './amount'

let cachedSettings: any | null = null
let cachedLogoDataUrl: string | null = null
let cachedLogoUrl: string | null = null
let cachedStampDataUrl: string | null = null
let cachedStampUrl: string | null = null
const ONEC_GREEN = '#2d6a4f'

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

export const generateSortieFondsPDF = async (
  sortie: any,
  budgetLabel?: string,
  output: 'download' | 'blob' = 'download'
) => {
  const settings = await getPrintSettingsData()
  const logoDataUrl = await getLogoDataUrl()
  const stampDataUrl = settings?.show_footer_signature === false ? null : await getStampDataUrl()
  const doc = new jsPDF({ orientation: 'l', unit: 'mm', format: 'a4' })

  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = 10

  const orgName = settings?.organization_name || 'ONEC / CPK'
  const subtitle = settings?.organization_subtitle || 'RÉPUBLIQUE DÉMOCRATIQUE DU CONGO'
  const ref = sortie?.reference_numero || sortie?.reference || sortie?.id || 'N/A'
  const systemId = sortie?.id ? String(sortie.id) : ''
  const datePaiement = sortie?.date_paiement ? new Date(sortie.date_paiement) : new Date()
  const sourceNumero = sortie?.requisition?.numero_requisition || sortie?.requisition_id || '-'
  const sourceLabel = sortie?.type_sortie === 'remboursement' ? 'Remboursement transport' : 'Réquisition'
  const requisition = sortie?.requisition || {}
  const formatUserName = (user: any, fallbackId?: string) => {
    const first = String(user?.prenom || '').trim()
    const last = String(user?.nom || '').trim()
    const full = `${first} ${last}`.trim()
    if (full) return full
    if (fallbackId) return `ID ${String(fallbackId).slice(0, 8)}`
    return '—'
  }
  const autorisateurName = formatUserName(requisition?.validateur, requisition?.validee_par)
  const viseurName = formatUserName(requisition?.approbateur, requisition?.approuvee_par)
  const autorisateurDate = requisition?.validee_le ? format(new Date(requisition.validee_le), 'dd/MM/yyyy HH:mm') : ''
  const viseurDate = requisition?.approuvee_le ? format(new Date(requisition.approuvee_le), 'dd/MM/yyyy HH:mm') : ''
  const buildQrValue = () => {
    const base = String(settings?.sortie_qr_base_url || '').trim()
    if (base) {
      if (base.includes('{ref}')) return base.replace('{ref}', encodeURIComponent(String(ref)))
      if (base.includes('{id}')) return base.replace('{id}', encodeURIComponent(String(systemId || '')))
      const sep = base.includes('?') ? '&' : '?'
      return `${base}${sep}ref=${encodeURIComponent(String(ref))}`
    }
    return [
      `REF:${ref}`,
      `AMT:${toNumber(sortie?.montant_paye || 0)}`,
      `DATE:${format(datePaiement, 'yyyy-MM-dd')}`,
      systemId ? `ID:${systemId}` : null,
    ]
      .filter(Boolean)
      .join('|')
  }

  // --- FILIGRANE DE SÉCURITÉ ---
  if (settings?.show_sortie_watermark !== false) {
    const watermarkText = String(settings?.sortie_watermark_text || 'PAYÉ').trim()
    if (watermarkText) {
      const opacityRaw = Number(settings?.sortie_watermark_opacity ?? 0.15)
      const opacity = Math.min(0.6, Math.max(0.05, Number.isFinite(opacityRaw) ? opacityRaw : 0.15))
      doc.setTextColor(240, 240, 240)
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(60)
      try {
        doc.saveGraphicsState()
        const GState = (doc as any).GState
        if (GState && (doc as any).setGState) {
          const gs = new GState({ opacity })
          ;(doc as any).setGState(gs)
        }
        doc.text(watermarkText, pageWidth / 2, pageHeight / 2 + 8, { align: 'center', angle: 45 })
      } finally {
        doc.restoreGraphicsState()
      }
    }
  }

  // --- CADRE EXTÉRIEUR ---
  doc.setLineWidth(0.5)
  doc.rect(5, 5, pageWidth - 10, pageHeight - 10)

  // --- EN-TÊTE ---
  if (logoDataUrl) {
    doc.addImage(logoDataUrl, 'PNG', margin, 8, 16, 16)
  }

  doc.setFont('times', 'bold')
  doc.setFontSize(12)
  doc.text(orgName.toUpperCase(), logoDataUrl ? margin + 20 : margin, 14)
  doc.setFont('times', 'normal')
  doc.setFontSize(8.5)
  if (subtitle) doc.text(subtitle, logoDataUrl ? margin + 20 : margin, 19)

  doc.setDrawColor(45, 106, 79)
  doc.setLineWidth(0.6)
  doc.line(margin, 24, pageWidth - margin, 24)

  doc.setFont('times', 'bold')
  doc.setFontSize(14)
  doc.text('BON DE SORTIE DE CAISSE', pageWidth / 2, 31, { align: 'center' })

  // --- QR CODE ---
  if (settings?.show_sortie_qr !== false) {
    try {
      const qrCodeDataUrl = await QRCode.toDataURL(buildQrValue(), { margin: 0, width: 120 })
      const qrSize = 20
      const qrX = pageWidth - 35
      const qrY = 28
      doc.setFont('times', 'normal')
      doc.setFontSize(7)
      doc.setTextColor(90)
      doc.setFillColor(255, 255, 255)
      doc.rect(qrX - 10, qrY - 6, 40, 6, 'F')
      doc.text('Scanner pour valider', qrX + 10, qrY - 2, { align: 'center' })
      doc.addImage(qrCodeDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
    } catch {
      // QR code is optional; continue without failing the PDF
    }
  }

  doc.setFont('times', 'bold')
  doc.setFontSize(10)
  doc.text(`N°: ${ref}`, pageWidth - margin, 14, { align: 'right' })
  doc.setFont('times', 'normal')
  doc.setFontSize(8)
  doc.text(`Lié à : ${String(sourceNumero).slice(0, 24) || 'N/A'}`, pageWidth - margin, 19, { align: 'right' })
  if (systemId) {
    doc.text(`ID système: ${systemId.slice(0, 24)}`, pageWidth - margin, 23, { align: 'right' })
  }

  // --- CORPS DU DOCUMENT ---
  let y = 38
  doc.setFont('times', 'bold')
  doc.setFontSize(10)
  doc.text('Date :', margin + 5, y)
  doc.setFont('times', 'normal')
  doc.text(format(datePaiement, 'dd/MM/yyyy'), margin + 28, y)

  y += 8
  doc.setFont('times', 'bold')
  doc.text('Bénéficiaire :', margin + 5, y)
  doc.setFont('times', 'normal')
  doc.text(String(sortie?.beneficiaire || '-').toUpperCase(), margin + 28, y)

  y += 8
  doc.setFont('times', 'bold')
  doc.text('Motif :', margin + 5, y)
  doc.setFont('times', 'normal')
  const motifLines = doc.splitTextToSize(String(sortie?.motif || '-'), pageWidth - margin * 2 - 30)
  doc.text(motifLines, margin + 28, y)

  y += 12
  doc.setFont('times', 'bold')
  doc.text('Rubrique :', margin + 5, y)
  doc.setFont('times', 'normal')
  doc.text(String(budgetLabel || '-'), margin + 28, y)

  y += 8
  doc.setFont('times', 'bold')
  doc.text('Source :', margin + 5, y)
  doc.setFont('times', 'normal')
  doc.text(`${sourceLabel} N° ${String(sourceNumero).slice(0, 24)}`, margin + 28, y)

  const montant = toNumber(sortie?.montant_paye || 0)
  const montantLettres = numberToWords(montant)
  const tauxSnapshot = sortie?.exchange_rate_snapshot
  const tauxLabel =
    tauxSnapshot && Number(tauxSnapshot) > 0 ? `Taux appliqué: 1 USD = ${formatAmount(tauxSnapshot)} CDF` : ''

  // Bloc montant
  const amountY = 78
  doc.setFillColor(240, 240, 240)
  doc.rect(margin + 5, amountY - 6, pageWidth - (margin + 5) * 2, 12, 'F')
  doc.setFont('times', 'bold')
  doc.setFontSize(12)
  doc.text('MONTANT :', margin + 8, amountY + 2)
  doc.setFontSize(14)
  doc.text(`${formatAmount(montant)} USD`, margin + 40, amountY + 2)

  doc.setFontSize(9)
  doc.setFont('times', 'italic')
  doc.text(`Soit en lettres : ${montantLettres}`, margin + 5, amountY + 14)
  if (tauxLabel) {
    doc.setFont('times', 'normal')
    doc.setFontSize(8)
    doc.text(tauxLabel, margin + 5, amountY + 20)
  }

  const ySign = pageHeight - 28
  // --- VALIDATION CROISÉE ---
  const validationY = ySign - 16
  doc.setFont('times', 'normal')
  doc.setFontSize(8)
  doc.text(`Validation 1: ${autorisateurName}${autorisateurDate ? ` • ${autorisateurDate}` : ''}`, margin + 5, validationY)
  doc.text(`Validation 2: ${viseurName}${viseurDate ? ` • ${viseurDate}` : ''}`, margin + 5, validationY + 6)

  // --- ZONE DE SIGNATURES ---
  doc.setFont('times', 'bold')
  doc.setFontSize(9)
  doc.text('LE CAISSIER', margin + 25, ySign)
  doc.text('LE BÉNÉFICIAIRE', pageWidth / 2, ySign, { align: 'center' })
  doc.text('LE COMPTABLE', pageWidth - margin - 28, ySign)

  doc.setFont('times', 'italic')
  doc.setFontSize(7)
  doc.text('(Signature et date)', margin + 18, ySign + 10)
  doc.text("(Signature précédée de 'Reçu')", pageWidth / 2, ySign + 10, { align: 'center' })
  doc.text('(Visa pour contrôle)', pageWidth - margin - 33, ySign + 10)

  if (settings?.show_footer_signature !== false) {
    const sortieLabel = settings?.sortie_label_signature || settings?.recu_label_signature || 'Cachet & signature'
    const sortieNom = settings?.sortie_nom_signataire || settings?.recu_nom_signataire || ''
    const signX = pageWidth - margin - 46
    const signY = ySign - 18
    doc.setFont('times', 'bold')
    doc.setFontSize(8)
    doc.text(sortieLabel, signX, signY)
    doc.setFont('times', 'normal')
    if (sortieNom) {
      doc.text(sortieNom, signX, signY + 4)
    }
    if (stampDataUrl) {
      const stampSize = 20
      doc.addImage(stampDataUrl, 'PNG', signX, signY + 6, stampSize, stampSize)
    }
  }

  doc.setFont('times', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(90)
  doc.text(format(new Date(), 'dd/MM/yyyy HH:mm'), margin, pageHeight - 6)
  doc.text(
    settings?.pied_de_page_legal || 'Sortie de caisse - ONEC/CPK',
    pageWidth / 2,
    pageHeight - 6,
    { align: 'center' }
  )
  doc.text('Page 1/1', pageWidth - margin, pageHeight - 6, { align: 'right' })

  if (output === 'blob') {
    return doc.output('blob')
  }
  doc.save(`Sortie_Fonds_${String(ref).slice(0, 16)}.pdf`)
  return null
}
