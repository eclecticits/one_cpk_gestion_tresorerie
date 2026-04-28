import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { numberToWords } from './numberToWords'
import { formatAmount, toNumber } from './amount'
import { API_BASE_URL, getAuthHeaders } from '../lib/apiClient'

let cachedLogoDataUrl: string | null = null
let cachedLogoUrl: string | null = null
let cachedStampDataUrl: string | null = null
let cachedStampUrl: string | null = null
let cachedSettings: any | null = null

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
    if (!cachedLogoUrl) {
      const settings = await getPrintSettingsData()
      cachedLogoUrl = settings?.logo_url || null
    }
    const logoPath = cachedLogoUrl || '/imge_onec.png'
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
  if (cachedStampDataUrl) return cachedStampDataUrl
  try {
    if (!cachedStampUrl) {
      const settings = await getPrintSettingsData()
      cachedStampUrl = settings?.stamp_url || null
    }
    if (!cachedStampUrl) return null
    const res = await fetch(cachedStampUrl, { 
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

const normalizeHeaderLine = (value: unknown) =>
  String(value || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')

const formatCommissionBeneficiaire = (remboursement: any) => {
  const serviceCode = String(
    remboursement?.service_code ||
    remboursement?.commission_code ||
    remboursement?.requisition?.service_code ||
    ''
  ).trim()
  const serviceLibelle = String(
    remboursement?.service_libelle ||
    remboursement?.commission_libelle ||
    remboursement?.requisition?.service_libelle ||
    ''
  ).trim()

  if (serviceCode && serviceLibelle) {
    return serviceLibelle.toLowerCase().includes(serviceCode.toLowerCase())
      ? serviceLibelle
      : `${serviceCode} - ${serviceLibelle}`
  }
  if (serviceCode) return serviceCode
  if (serviceLibelle) return serviceLibelle

  const instance = String(remboursement?.instance || '').trim()
  return instance || 'N/A'
}

const getTypeReunionLabel = (value: unknown) => {
  switch (String(value || '')) {
    case 'bureau':
      return 'Réunion du Bureau'
    case 'commission':
      return 'Réunion de la Commission permanente'
    case 'commission_ad_hoc':
      return 'Réunion de la Commission ad hoc'
    case 'conseil':
      return 'Réunion du Conseil'
    case 'atelier':
      return 'Atelier / Séminaire / Formation'
    default:
      return String(value || 'N/A')
  }
}

const openPdfInNewTab = (doc: jsPDF) => {
  const blob = doc.output('blob')
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank', 'noopener,noreferrer')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

const addFooter = (doc: jsPDF, pageNumber: number, pageCount: number, margin: number) => {
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  doc.setFontSize(8)
  doc.setFont('times', 'normal')
  doc.setTextColor(100)
  doc.text(`${format(new Date(), 'dd/MM/yyyy HH:mm')}`, margin, pageHeight - 6)
  doc.text(
    'Remboursement frais de transport - ONEC/CPK',
    pageWidth / 2,
    pageHeight - 6,
    { align: 'center' }
  )
  doc.text(`Page ${pageNumber}/${pageCount}`, pageWidth - margin, pageHeight - 6, { align: 'right' })
}

export const generateRemboursementTransportPDF = async (
  remboursement: any,
  participants: any[],
  action: 'print' | 'download' | 'blob' = 'download',
  _userName?: string,
  paperFormat: 'a4' | 'a5' = 'a4',
  onBlob?: (blob: Blob, filename: string) => Promise<void>
) => {
  const settings = await getPrintSettingsData()
  const logoDataUrl = await getLogoDataUrl()
  const stampDataUrl = await getStampDataUrl()
  const isA5 = paperFormat === 'a5'
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: paperFormat })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = isA5 ? 10 : 15

  const beneficiaire = formatCommissionBeneficiaire(remboursement)

  const montantTotal = toNumber(remboursement.montant_total)
  const montantEnLettres = numberToWords(montantTotal)
  const itineraire = remboursement.lieu || 'N/A'
  const motif =
    remboursement.nature_reunion ||
    (Array.isArray(remboursement.nature_travail) ? remboursement.nature_travail.join(' / ') : '') ||
    'N/A'

  const dateReunion = remboursement.date_reunion ? new Date(remboursement.date_reunion) : new Date()
  const formattedDate = Number.isNaN(dateReunion.getTime()) ? 'N/A' : format(dateReunion, 'dd/MM/yyyy')

  if (logoDataUrl) {
    const logoSize = isA5 ? 18 : 24
    addLogo(doc, margin, 10, logoSize, logoDataUrl)
  }

  doc.setFont('times', 'bold')
  doc.setFontSize(isA5 ? 11 : 14)
  doc.setTextColor(0)
  const organizationName = settings?.organization_name?.trim() || 'ONEC / CPK'
  const headerX = margin + (isA5 ? 22 : 28)
  doc.text(organizationName.toUpperCase(), headerX, 16)
  doc.setFont('times', 'normal')
  doc.setFontSize(isA5 ? 8 : 10)
  const organizationKey = normalizeHeaderLine(organizationName)
  const seenHeaderLines = new Set([organizationKey])
  const subtitleLines = [
    settings?.organization_subtitle,
    settings?.header_text,
  ].filter((line): line is string => {
    const normalized = normalizeHeaderLine(line)
    if (!normalized || seenHeaderLines.has(normalized)) return false
    seenHeaderLines.add(normalized)
    return true
  })
  subtitleLines.slice(0, 3).forEach((line, index) => {
    doc.text(line, headerX, 21 + index * 4)
  })

  doc.setDrawColor(46, 125, 50)
  doc.setLineWidth(0.8)
  doc.line(margin, isA5 ? 34 : 38, pageWidth - margin, isA5 ? 34 : 38)

  const transTitre = remboursement.trans_titre_officiel_hist || settings?.trans_titre_officiel || 'ÉTAT DE FRAIS DE DÉPLACEMENT'
  doc.setFont('times', 'bold')
  doc.setFontSize(isA5 ? 12 : 14)
  doc.setTextColor(0)
  doc.text(transTitre, pageWidth / 2, isA5 ? 44 : 50, { align: 'center' })

  if (remboursement.reference_numero) {
    doc.setFontSize(isA5 ? 9 : 11)
    doc.setFont('helvetica', 'bold')
    doc.text(`ÉTAT DE FRAIS N° : ${remboursement.reference_numero}`, pageWidth / 2, isA5 ? 38 : 44, { align: 'center' })
    doc.setFont('times', 'normal')
  }

  autoTable(doc, {
    startY: isA5 ? 52 : 60,
    theme: 'grid',
    head: [['Poste budgétaire', 'Détail des informations']],
    body: [
      ['Bénéficiaire', beneficiaire.toUpperCase()],
      ['Instance', remboursement.instance || 'N/A'],
      ['Type de réunion', getTypeReunionLabel(remboursement.type_reunion)],
      ['Motif / Mission', motif],
      ['Date', formattedDate],
      ['Itinéraire', itineraire],
      ['Montant USD', `${formatAmount(montantTotal)} $`],
      ['Somme en lettres', { content: montantEnLettres, styles: { fontStyle: 'italic' } }],
    ],
    styles: { font: 'times', fontSize: isA5 ? 9 : 11, cellPadding: isA5 ? 3 : 4 },
    headStyles: { fillColor: [46, 125, 50], textColor: 255, fontStyle: 'bold' },
    columnStyles: { 0: { cellWidth: isA5 ? 45 : 60, fillColor: [245, 245, 245], fontStyle: 'bold' } },
    margin: { left: margin, right: margin },
  })

  let yPos = (doc as any).lastAutoTable.finalY + (isA5 ? 6 : 10)

  if (participants.length > 0) {
    const participantsData = participants.map((p: any, index: number) => [
      index + 1,
      String(p.nom || '').toUpperCase(),
      p.titre_fonction,
      `${formatAmount(p.montant)} $`,
      '..............................',
    ])
    autoTable(doc, {
      startY: yPos,
      theme: 'grid',
      head: [['N°', 'Nom & Postnom', 'Fonction', 'Montant', 'Émargement']],
      body: participantsData,
      styles: { font: 'times', fontSize: isA5 ? 8.5 : 10, cellPadding: 3 },
      headStyles: { fillColor: [41, 128, 185], textColor: 255, fontStyle: 'bold' },
      margin: { left: margin, right: margin, bottom: isA5 ? 18 : 22 },
      showHead: 'firstPage',
      columnStyles: {
        0: { cellWidth: isA5 ? 8 : 10, halign: 'center' },
        1: { cellWidth: isA5 ? 45 : 55 },
        2: { cellWidth: isA5 ? 32 : 38 },
        3: { cellWidth: isA5 ? 22 : 26, halign: 'right' },
        4: { cellWidth: 'auto', halign: 'center' },
      },
    })
    yPos = (doc as any).lastAutoTable.finalY + (isA5 ? 6 : 10)
  }

  const labelGauche =
    remboursement.signataire_g_label ||
    remboursement.trans_label_gauche_hist ||
    settings?.trans_label_gauche ||
    'Vu par la Trésorière'
  const labelDroite =
    remboursement.signataire_d_label ||
    remboursement.trans_label_droite_hist ||
    settings?.trans_label_droite ||
    'Approuvé par :'
  const nomGauche =
    remboursement.signataire_g_nom ||
    remboursement.trans_nom_gauche_hist ||
    settings?.trans_nom_gauche ||
    'Esther BIMPE'
  const nomDroite =
    remboursement.signataire_d_nom ||
    remboursement.trans_nom_droite_hist ||
    settings?.trans_nom_droite ||
    '................................'

  const signatureBlockHeight = isA5 ? 38 : 50
  if (yPos + signatureBlockHeight > pageHeight - (isA5 ? 14 : 18)) {
    doc.addPage()
    yPos = margin
  }

  doc.setFontSize(isA5 ? 9 : 10)
  doc.setFont('times', 'bold')
  doc.text(labelGauche, margin, yPos)
  doc.text(labelDroite, pageWidth - margin - (isA5 ? 55 : 70), yPos)

  doc.setFont('times', 'normal')
  doc.text(nomGauche, margin, yPos + (isA5 ? 4 : 6))
  doc.text(nomDroite, pageWidth - margin - (isA5 ? 55 : 70), yPos + (isA5 ? 4 : 6))

  if (stampDataUrl) {
    const stampSize = isA5 ? 22 : 30
    doc.addImage(
      stampDataUrl,
      'PNG',
      pageWidth - margin - stampSize,
      yPos + (isA5 ? 10 : 12),
      stampSize,
      stampSize
    )
  }

  if (settings?.afficher_qr_code !== false) {
    try {
      const { default: QRCode } = await import('qrcode')
      const qrDate = !Number.isNaN(dateReunion.getTime()) ? format(dateReunion, 'yyyyMMdd') : '00000000'
      const qrData = `TRANS-${remboursement.id}-${formatAmount(montantTotal)}USD-${qrDate}`
      const qrCodeUrl = await QRCode.toDataURL(qrData, { margin: 1, width: 120 })
      const qrSize = isA5 ? 16 : 20
      const qrX = margin
      const qrY = pageHeight - (isA5 ? 24 : 28)
      doc.setFontSize(7.5)
      doc.setTextColor(90)
      doc.setFillColor(255, 255, 255)
      doc.rect(qrX, qrY - 8, 70, 6, 'F')
      doc.text("Scannez pour vérifier", qrX, qrY - 4)
      doc.addImage(qrCodeUrl, 'PNG', qrX, qrY, qrSize, qrSize)
    } catch {
      // ignore QR code failures
    }
  }

  const pageCount = doc.getNumberOfPages()
  for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
    doc.setPage(pageNumber)
    addFooter(doc, pageNumber, pageCount, margin)
  }

  const rawNumber = remboursement.reference_numero || remboursement.numero_remboursement || 'remboursement_transport'
  const safeNumber = String(rawNumber).trim().replace(/[\\/:*?"<>|]+/g, '-')
  const filename = `${safeNumber}.pdf`
  const blob = doc.output('blob')
  if (onBlob) {
    await onBlob(blob, filename)
  }
  if (action === 'print') {
    openPdfInNewTab(doc)
  } else if (action === 'blob') {
    return blob
  } else {
    doc.save(filename)
  }
}
