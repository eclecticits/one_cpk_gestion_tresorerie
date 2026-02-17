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
  const subtitle = settings?.organization_subtitle || 'CONSEIL PROVINCIAL DE KINSHASA'
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
  doc.setLineWidth(0.6)
  doc.setDrawColor(226, 232, 240)
  doc.rect(5, 5, pageWidth - 10, pageHeight - 10)

  // --- EN-TÊTE ---
  if (logoDataUrl) {
    doc.addImage(logoDataUrl, 'PNG', margin, 8, 18, 18)
  }

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(12)
  doc.setTextColor(15, 23, 42)
  doc.text(orgName.toUpperCase(), logoDataUrl ? margin + 22 : margin, 14)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  doc.setTextColor(71, 85, 105)
  if (subtitle) doc.text(subtitle, logoDataUrl ? margin + 22 : margin, 19)

  const metaW = 70
  const metaH = 22
  const metaX = pageWidth - margin - metaW
  const metaY = 8
  doc.setFillColor(15, 23, 42)
  doc.roundedRect(metaX, metaY, metaW, metaH, 3, 3, 'F')
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(226, 232, 240)
  doc.text('N° BON', metaX + 6, metaY + 6)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.text(String(ref).slice(0, 22), metaX + 6, metaY + 14)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.text(`Date: ${format(datePaiement, 'dd/MM/yyyy')}`, metaX + 6, metaY + 19)

  doc.setDrawColor(226, 232, 240)
  doc.setLineWidth(0.6)
  doc.line(margin, 28, pageWidth - margin, 28)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(15)
  doc.setTextColor(15, 23, 42)
  doc.text('BON DE SORTIE DE CAISSE', pageWidth / 2, 33, { align: 'center' })

  const statusRaw = String(sortie?.statut || sortie?.status || '').toUpperCase()
  const statusLabel =
    statusRaw === 'VALIDE' || statusRaw === 'APPROUVEE' ? 'APPROUVÉ' :
    statusRaw === 'ANNULEE' ? 'ANNULÉ' :
    statusRaw === 'PAYEE' ? 'PAYÉ' : 'EN ATTENTE'
  const statusColor =
    statusLabel === 'APPROUVÉ' || statusLabel === 'PAYÉ' ? [22, 163, 74] :
    statusLabel === 'ANNULÉ' ? [220, 38, 38] :
    [245, 158, 11]
  const badgeW = 36
  const badgeH = 7
  const badgeX = pageWidth - margin - badgeW
  const badgeY = 31
  doc.setFillColor(statusColor[0], statusColor[1], statusColor[2])
  doc.roundedRect(badgeX, badgeY, badgeW, badgeH, 2, 2, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(7.5)
  doc.setTextColor(255, 255, 255)
  doc.text(statusLabel, badgeX + badgeW / 2, badgeY + 5, { align: 'center' })

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.setTextColor(71, 85, 105)
  doc.text(`Lié à : ${String(sourceNumero).slice(0, 26) || 'N/A'}`, margin, 36)
  if (systemId) {
    doc.text(`ID système: ${systemId.slice(0, 24)}`, margin, 40)
  }

  // --- CORPS DU DOCUMENT ---
  const infoY = 42
  const infoH = 38
  doc.setFillColor(248, 250, 252)
  doc.roundedRect(margin, infoY, pageWidth - margin * 2, infoH, 3, 3, 'F')

  const colGap = 6
  const leftX = margin + 6
  const rightX = pageWidth / 2 + colGap
  const labelColor = [100, 116, 139]
  const valueColor = [15, 23, 42]

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Bénéficiaire', leftX, infoY + 7)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.text(String(sortie?.beneficiaire || '-').toUpperCase(), leftX, infoY + 13)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Motif', leftX, infoY + 20)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(9)
  const motifLines = doc.splitTextToSize(String(sortie?.motif || '-'), pageWidth / 2 - margin - 12)
  doc.text(motifLines.slice(0, 2), leftX, infoY + 26)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Date', rightX, infoY + 7)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(9)
  doc.text(format(datePaiement, 'dd/MM/yyyy'), rightX, infoY + 12)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Mode de paiement', rightX, infoY + 19)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(9)
  const modeLabel =
    sortie?.mode_paiement === 'mobile_money'
      ? 'Mobile Money'
      : sortie?.mode_paiement === 'virement'
      ? 'Virement'
      : 'Cash'
  doc.text(modeLabel, rightX, infoY + 24)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Réquisition', rightX, infoY + 30)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(9)
  doc.text(`${sourceLabel} ${String(sourceNumero).slice(0, 20)}`, rightX + 20, infoY + 30)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Rubrique', rightX, infoY + 36)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(9)
  doc.text(String(budgetLabel || '-').slice(0, 32), rightX + 18, infoY + 36)

  const montant = toNumber(sortie?.montant_paye || 0)
  const montantLettres = numberToWords(montant)
  const tauxSnapshot = sortie?.exchange_rate_snapshot
  const tauxLabel =
    tauxSnapshot && Number(tauxSnapshot) > 0 ? `Taux appliqué : 1 USD = ${formatAmount(tauxSnapshot)} CDF` : ''

  // Bloc montant
  const amountY = infoY + infoH + 6
  const amountH = 18
  doc.setFillColor(241, 245, 249)
  doc.roundedRect(margin, amountY, pageWidth - margin * 2, amountH, 3, 3, 'F')
  doc.setFillColor(34, 197, 94)
  doc.rect(margin, amountY, 4, amountH, 'F')
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(71, 85, 105)
  doc.text('Montant total', margin + 8, amountY + 7)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(18)
  doc.setTextColor(15, 23, 42)
  doc.text(`${formatAmount(montant)} USD`, margin + 8, amountY + 15)

  doc.setFont('helvetica', 'italic')
  doc.setFontSize(8.5)
  doc.setTextColor(71, 85, 105)
  doc.text(`Soit en lettres : ${montantLettres}`, margin, amountY + amountH + 7)
  if (tauxLabel) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    doc.text(tauxLabel, margin, amountY + amountH + 12)
  }

  // --- VALIDATION CROISÉE ---
  const validationY = amountY + amountH + 18
  const validationH = 14
  doc.setFillColor(250, 250, 250)
  doc.roundedRect(margin, validationY - 5, pageWidth - margin * 2, validationH, 2, 2, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8.5)
  doc.setTextColor(15, 23, 42)
  doc.text('Circuit de validation', margin + 4, validationY)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.setTextColor(71, 85, 105)
  const validation1 = autorisateurName === '—' ? 'Non renseigné' : autorisateurName
  const validation2 = viseurName === '—' ? 'Non renseigné' : viseurName
  doc.text(`Validation 1: ${validation1}${autorisateurDate ? ` • ${autorisateurDate}` : ''}`, margin + 4, validationY + 5)
  doc.text(`Validation 2: ${validation2}${viseurDate ? ` • ${viseurDate}` : ''}`, margin + 4, validationY + 10)

  const ySign = pageHeight - 30
  const sigGap = 5
  const sigW = (pageWidth - margin * 2 - sigGap * 2) / 3
  const sigH = 16
  const sigY = ySign - sigH
  const sigLabels = [
    settings?.sortie_sig_label_1 || 'CAISSIER',
    settings?.sortie_sig_label_2 || 'COMPTABLE',
    settings?.sortie_sig_label_3 || 'AUTORITÉ (TRÉSORERIE)',
  ]
  const sigHint = settings?.sortie_sig_hint || 'Signature & date'
  for (let i = 0; i < 3; i += 1) {
    const x = margin + i * (sigW + sigGap)
    doc.setDrawColor(226, 232, 240)
    doc.rect(x, sigY, sigW, sigH)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8)
    doc.setTextColor(15, 23, 42)
    doc.text(sigLabels[i], x + sigW / 2, sigY + 6, { align: 'center' })
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(100, 116, 139)
    doc.text(sigHint, x + sigW / 2, sigY + 11, { align: 'center' })
  }

  if (settings?.show_footer_signature !== false) {
    const sortieLabel = settings?.sortie_label_signature || settings?.recu_label_signature || 'Cachet & signature'
    const sortieNom = settings?.sortie_nom_signataire || settings?.recu_nom_signataire || ''
    const signX = pageWidth - margin - 50
    const signY = sigY - 4
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8)
    doc.setTextColor(15, 23, 42)
    doc.text(sortieLabel, signX, signY)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(71, 85, 105)
    if (sortieNom) {
      doc.text(sortieNom, signX, signY + 4)
    }
    if (stampDataUrl) {
      const stampSize = 18
      doc.addImage(stampDataUrl, 'PNG', signX, signY + 6, stampSize, stampSize)
    }
  }

  // --- QR CODE ---
  if (settings?.show_sortie_qr !== false) {
    try {
      const qrCodeDataUrl = await QRCode.toDataURL(buildQrValue(), { margin: 0, width: 100 })
      const qrSize = 16
      const qrX = pageWidth - margin - qrSize
      const qrY = pageHeight - 26 - qrSize
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(6.5)
      doc.setTextColor(100, 116, 139)
      doc.text('Scanner pour vérifier', qrX + qrSize / 2, qrY - 2, { align: 'center' })
      doc.addImage(qrCodeDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
    } catch {
      // QR code is optional; continue without failing the PDF
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
