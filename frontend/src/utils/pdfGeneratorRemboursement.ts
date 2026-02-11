import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { numberToWords } from './numberToWords'
import { formatAmount, toNumber } from './amount'
import { API_BASE_URL } from '../lib/apiClient'

const ONEC_GREEN = '#2e7d32'

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
    if (!cachedLogoUrl) {
      const settings = await getPrintSettingsData()
      cachedLogoUrl = settings?.logo_url || null
    }
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

export const generateRemboursementTransportPDF = async (
  remboursement: any,
  participants: any[],
  action: 'print' | 'download' = 'download',
  _userName?: string,
  paperFormat: 'a4' | 'a5' = 'a4'
) => {
  const settings = await getPrintSettingsData()
  const logoDataUrl = await getLogoDataUrl()
  const stampDataUrl = await getStampDataUrl()
  const isA5 = paperFormat === 'a5'
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: paperFormat })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = isA5 ? 10 : 15

  const principaux = participants.filter(p => p.type_participant === 'principal')
  const beneficiaire =
    principaux.length === 1
      ? principaux[0].nom
      : principaux.length > 1
      ? `Participants principaux (${principaux.length})`
      : participants.length > 0
      ? `Participants (${participants.length})`
      : 'N/A'

  const montantTotal = toNumber(remboursement.montant_total)
  const montantEnLettres = numberToWords(montantTotal)
  const itineraire = remboursement.lieu ? `Kinshasa → ${remboursement.lieu}` : 'N/A'
  const motif =
    remboursement.nature_reunion ||
    (Array.isArray(remboursement.nature_travail) ? remboursement.nature_travail.join(' / ') : '') ||
    'N/A'

  if (logoDataUrl) {
    const logoSize = isA5 ? 18 : 24
    addLogo(doc, margin, 10, logoSize, logoDataUrl)
  }

  doc.setFont('times', 'bold')
  doc.setFontSize(isA5 ? 11 : 14)
  doc.setTextColor(0)
  doc.text(settings?.organization_name?.toUpperCase() || 'ONEC / CPK', margin + (isA5 ? 22 : 28), 16)
  doc.setFont('times', 'normal')
  doc.setFontSize(isA5 ? 8 : 10)
  doc.text('Conseil Provincial de Kinshasa', margin + (isA5 ? 22 : 28), 21)
  if (settings?.organization_subtitle) {
    doc.text(settings.organization_subtitle, margin + (isA5 ? 22 : 28), 25)
  }
  if (settings?.header_text) {
    doc.text(settings.header_text, margin + (isA5 ? 22 : 28), 29)
  }

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
    head: [['Rubrique', 'Détail des informations']],
    body: [
      ['Bénéficiaire', beneficiaire.toUpperCase()],
      ['Instance', remboursement.instance || 'N/A'],
      ['Type de réunion', remboursement.type_reunion || 'N/A'],
      ['Motif / Mission', motif],
      ['Date', format(new Date(remboursement.date_reunion), 'dd/MM/yyyy')],
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
    const participantsData = participants.map((p: any) => [
      String(p.nom || '').toUpperCase(),
      p.titre_fonction,
      `${formatAmount(p.montant)} $`,
      '..............................',
    ])
    autoTable(doc, {
      startY: yPos,
      theme: 'grid',
      head: [['Nom & Postnom', 'Fonction', 'Montant', 'Émargement']],
      body: participantsData,
      styles: { font: 'times', fontSize: isA5 ? 8.5 : 10, cellPadding: 3 },
      headStyles: { fillColor: [41, 128, 185], textColor: 255, fontStyle: 'bold' },
      margin: { left: margin, right: margin },
      columnStyles: {
        0: { cellWidth: isA5 ? 50 : 60 },
        1: { cellWidth: isA5 ? 35 : 40 },
        2: { cellWidth: isA5 ? 24 : 28, halign: 'right' },
        3: { cellWidth: 'auto', halign: 'center' },
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
      const qrData = `TRANS-${remboursement.id}-${formatAmount(montantTotal)}USD-${format(new Date(remboursement.date_reunion), 'yyyyMMdd')}`
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

  doc.setFontSize(8)
  doc.setFont('times', 'normal')
  doc.setTextColor(100)
  doc.text(`${format(new Date(), 'dd/MM/yyyy HH:mm')}`, margin, pageHeight - 6)
  doc.text(
    settings?.pied_de_page_legal || 'Remboursement frais de transport - ONEC/CPK',
    pageWidth / 2,
    pageHeight - 6,
    { align: 'center' }
  )
  doc.text('Page 1/1', pageWidth - margin, pageHeight - 6, { align: 'right' })

  if (action === 'print') {
    openPdfInNewTab(doc)
  } else {
    doc.save(`remboursement_transport_${remboursement.numero_remboursement}.pdf`)
  }
}
