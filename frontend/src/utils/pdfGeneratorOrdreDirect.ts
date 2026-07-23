import jsPDF from 'jspdf'
import QRCode from 'qrcode'
import { format } from 'date-fns'
import { API_BASE_URL, getAuthHeaders } from '../lib/apiClient'
import { numberToWords } from './numberToWords'
import { formatAmount, toNumber } from './amount'
import { buildUploadUrl } from './uploads'

let cachedSettings: any | null = null
let cachedLogoDataUrl: string | null = null

const getPrintSettingsData = async () => {
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
  if (cachedLogoDataUrl) return cachedLogoDataUrl
  try {
    const settings = await getPrintSettingsData()
    const logoPath = settings?.logo_url ? buildUploadUrl(settings.logo_url) : '/imge_onec.png'
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

const personName = (u?: { prenom?: string | null; nom?: string | null; email?: string | null } | null) => {
  if (!u) return ''
  const full = `${u.prenom || ''} ${u.nom || ''}`.trim()
  return full || u.email || ''
}

/**
 * Bon d'ordre de sortie directe programmée : document imprimable destiné à
 * la signature physique (programmateur, caisse, bénéficiaire), à l'image du
 * bon produit pour une réquisition classique.
 */
export const generateOrdreDirectPDF = async (
  ordre: any,
  options?: { serviceLabel?: string; posteLabels?: Map<number, string> },
  output: 'download' | 'blob' = 'download'
) => {
  const settings = await getPrintSettingsData()
  const logoDataUrl = await getLogoDataUrl()
  const doc = new jsPDF({ orientation: 'l', unit: 'mm', format: 'a4' })

  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = 10

  const orgName = settings?.organization_name || 'ONEC'
  const subtitle = settings?.organization_subtitle || "Plateforme intelligente de gestion intégrée de l'ONEC-RDC"
  const numero = String(ordre?.numero_ordre || ordre?.id || 'N/A')
  const devise = String(ordre?.devise || 'USD').toUpperCase()
  const montant = toNumber(ordre?.montant || 0)
  const statutRaw = String(ordre?.statut || 'AUTORISE').toUpperCase()
  const dateProg = ordre?.autorise_le ? new Date(ordre.autorise_le) : new Date()
  const programmeur = personName(ordre?.autorise_par_user) || '—'
  const payeur = personName(ordre?.paye_par_user)

  // --- FILIGRANE selon le statut ---
  const watermarkText =
    statutRaw === 'PAYE' ? 'PAYÉ' : statutRaw === 'ANNULE' ? 'ANNULÉ' : 'À PAYER'
  doc.setTextColor(240, 240, 240)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(60)
  try {
    doc.saveGraphicsState()
    const GState = (doc as any).GState
    if (GState && (doc as any).setGState) {
      ;(doc as any).setGState(new GState({ opacity: 0.12 }))
    }
    doc.text(watermarkText, pageWidth / 2, pageHeight / 2 + 8, { align: 'center', angle: 45 })
  } finally {
    doc.restoreGraphicsState()
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
  doc.text(numero.slice(0, 22), metaX + 6, metaY + 14)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.text(`Programmé le : ${format(dateProg, 'dd/MM/yyyy HH:mm')}`, metaX + 6, metaY + 19)

  doc.setDrawColor(226, 232, 240)
  doc.setLineWidth(0.6)
  doc.line(margin, 28, pageWidth - margin, 28)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(15)
  doc.setTextColor(15, 23, 42)
  doc.text('BON DE SORTIE DIRECTE', pageWidth / 2, 33, { align: 'center' })

  const statusLabel =
    statutRaw === 'PAYE' ? 'PAYÉ PAR LA CAISSE' : statutRaw === 'ANNULE' ? 'ANNULÉ' : 'EN ATTENTE CAISSE'
  const statusColor =
    statutRaw === 'PAYE' ? [22, 163, 74] : statutRaw === 'ANNULE' ? [220, 38, 38] : [245, 158, 11]
  const badgeW = 48
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
  doc.text(
    'Dépense plafonnée (équivalent 100 USD) définie en amont — la caisse exécute sans modification.',
    margin,
    38
  )

  // --- BLOC INFOS ---
  const infoY = 42
  const infoH = 34
  doc.setFillColor(248, 250, 252)
  doc.roundedRect(margin, infoY, pageWidth - margin * 2, infoH, 3, 3, 'F')

  const leftX = margin + 6
  const rightX = pageWidth / 2 + 6
  const labelColor = [100, 116, 139]
  const valueColor = [15, 23, 42]

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Bénéficiaire', leftX, infoY + 7)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.text(String(ordre?.beneficiaire || '-').toUpperCase(), leftX, infoY + 13)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Motif', leftX, infoY + 20)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(9)
  const motifLines = doc.splitTextToSize(String(ordre?.motif || '-'), pageWidth / 2 - margin - 12)
  doc.text(motifLines.slice(0, 2), leftX, infoY + 26)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Service / Commission', rightX, infoY + 7)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(9)
  doc.text(String(options?.serviceLabel || '-').slice(0, 60), rightX, infoY + 12)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Programmé par', rightX, infoY + 19)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(9)
  doc.text(programmeur, rightX, infoY + 24)

  if (statutRaw === 'PAYE') {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.5)
    doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
    doc.text('Réf. sortie de caisse', rightX, infoY + 30)
    doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
    doc.setFontSize(8.5)
    doc.text(String(ordre?.sortie_reference_numero || '-'), rightX + 30, infoY + 30)
  }

  // --- LIGNES BUDGÉTAIRES ---
  let contentY = infoY + infoH + 5
  const lignes: any[] = Array.isArray(ordre?.lignes) ? ordre.lignes : []
  if (lignes.length > 0) {
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8.5)
    doc.setTextColor(15, 23, 42)
    doc.text('Lignes budgétaires', margin, contentY + 3)
    contentY += 6
    const rowH = 6
    const col1 = margin
    const col2 = margin + 55
    const col3 = pageWidth - margin - 40
    doc.setFillColor(241, 245, 249)
    doc.rect(margin, contentY, pageWidth - margin * 2, rowH, 'F')
    doc.setFontSize(7.5)
    doc.text('Poste budgétaire', col1 + 2, contentY + 4)
    doc.text('Description', col2 + 2, contentY + 4)
    doc.text(`Montant (${devise})`, col3 + 2, contentY + 4)
    contentY += rowH
    doc.setFont('helvetica', 'normal')
    lignes.slice(0, 5).forEach((l) => {
      const posteId = Number(l?.budget_poste_id)
      const posteLabel =
        (Number.isFinite(posteId) && options?.posteLabels?.get(posteId)) || String(l?.rubrique || '-')
      doc.setDrawColor(226, 232, 240)
      doc.rect(margin, contentY, pageWidth - margin * 2, rowH)
      doc.setTextColor(15, 23, 42)
      doc.setFontSize(7.5)
      doc.text(String(posteLabel).slice(0, 38), col1 + 2, contentY + 4)
      doc.text(String(l?.description || '-').slice(0, 80), col2 + 2, contentY + 4)
      doc.text(formatAmount(toNumber(l?.montant_total || 0)), col3 + 2, contentY + 4)
      contentY += rowH
    })
    contentY += 3
  }

  // --- BLOC MONTANT ---
  const amountH = 16
  doc.setFillColor(241, 245, 249)
  doc.roundedRect(margin, contentY, pageWidth - margin * 2, amountH, 3, 3, 'F')
  doc.setFillColor(217, 119, 6)
  doc.rect(margin, contentY, 4, amountH, 'F')
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  doc.setTextColor(71, 85, 105)
  doc.text('Montant total à payer', margin + 8, contentY + 6)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(16)
  doc.setTextColor(15, 23, 42)
  doc.text(`${formatAmount(montant)} ${devise}`, margin + 8, contentY + 13)
  doc.setFont('helvetica', 'italic')
  doc.setFontSize(8.5)
  doc.setTextColor(71, 85, 105)
  doc.text(`Soit en lettres : ${numberToWords(montant)}`, margin, contentY + amountH + 6)

  // --- SIGNATURES ---
  const sigGap = 5
  const sigW = (pageWidth - margin * 2 - sigGap * 2) / 3
  const sigH = 18
  const sigY = pageHeight - 32
  const sigLabels = ['PROGRAMMÉ PAR (AUTORISATION)', 'LA CAISSE (EXÉCUTION)', 'BÉNÉFICIAIRE']
  const sigNames = [
    programmeur,
    payeur || '',
    String(ordre?.beneficiaire || '').trim(),
  ]
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
    doc.text(String(sigNames[i] || '—').slice(0, 34), x + sigW / 2, sigY + 11, { align: 'center' })
    doc.setFontSize(6.5)
    doc.text('Signature & date', x + sigW / 2, sigY + 15.5, { align: 'center' })
  }

  // --- QR CODE ---
  try {
    const qrValue = [
      `ORDRE:${numero}`,
      `AMT:${montant}`,
      `DEV:${devise}`,
      `DATE:${format(dateProg, 'yyyy-MM-dd')}`,
      ordre?.id ? `ID:${String(ordre.id)}` : null,
    ]
      .filter(Boolean)
      .join('|')
    const qrCodeDataUrl = await QRCode.toDataURL(qrValue, { margin: 0, width: 100 })
    const qrSize = 16
    const qrX = pageWidth - margin - qrSize
    const qrY = sigY - qrSize - 6
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(6.5)
    doc.setTextColor(100, 116, 139)
    doc.text('Scanner pour vérifier', qrX + qrSize / 2, qrY - 2, { align: 'center' })
    doc.addImage(qrCodeDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
  } catch {
    // QR optionnel
  }

  // --- PIED DE PAGE ---
  doc.setFont('times', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(90)
  doc.text(format(new Date(), 'dd/MM/yyyy HH:mm'), margin, pageHeight - 6)
  doc.text(
    orgName ? `Bon de sortie directe - ${orgName}` : 'Bon de sortie directe',
    pageWidth / 2,
    pageHeight - 6,
    { align: 'center' }
  )
  doc.text('Page 1/1', pageWidth - margin, pageHeight - 6, { align: 'right' })

  if (output === 'blob') {
    return doc.output('blob')
  }
  doc.save(`Bon_Sortie_Directe_${numero.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 24)}.pdf`)
  return null
}
