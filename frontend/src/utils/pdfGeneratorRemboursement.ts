import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { numberToWords } from './numberToWords'
import { toNumber } from './amount'

const ONEC_GREEN = '#2d6a4f'
const ONEC_LIGHT_BG = '#ecfdf5'
const HEADER_HEIGHT = 26
const LOGO_SIZE = 18
const HEADER_CENTER_X = (docWidth: number) => docWidth / 2

let cachedLogoDataUrl: string | null = null
const getLogoDataUrl = async () => {
  if (cachedLogoDataUrl) return cachedLogoDataUrl
  try {
    const res = await fetch('/imge_onec.png', { credentials: 'include' })
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
  _userName?: string
) => {
  const logoDataUrl = await getLogoDataUrl()
  const formatUserName = (user: any) => {
    if (!user) return 'N/A'
    const fullName = `${user.prenom || ''} ${user.nom || ''}`.trim()
    return fullName || 'N/A'
  }

  const doc = new jsPDF()
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()

  const principaux = participants.filter(p => p.type_participant === 'principal')
  const assistants = participants.filter(p => p.type_participant === 'assistant')

  doc.setDrawColor(ONEC_GREEN)
  doc.setLineWidth(2)
  doc.line(10, 37, pageWidth - 10, 37)

  doc.setFillColor(ONEC_LIGHT_BG)
  doc.roundedRect(10, 8, pageWidth - 20, HEADER_HEIGHT, 3, 3, 'F')
  addLogo(doc, 12, 10, LOGO_SIZE, logoDataUrl)

  let yPos = 12

  doc.setFontSize(14)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text('ORDRE NATIONAL DES EXPERTS-COMPTABLES', HEADER_CENTER_X(pageWidth), yPos + 4, { align: 'center' })

  yPos += 8

  doc.setFontSize(12)
  doc.setTextColor(0, 0, 0)
  doc.setFont('times', 'bolditalic')
  doc.text('Conseil Provincial de Kinshasa', HEADER_CENTER_X(pageWidth), yPos + 2, { align: 'center' })

  yPos += 8

  doc.setFontSize(10)
  doc.setTextColor(0, 0, 0)
  doc.setFont('helvetica', 'normal')
  doc.text('Gestion de la Trésorerie', HEADER_CENTER_X(pageWidth), yPos + 2, { align: 'center' })

  yPos += 12

  doc.setFontSize(13)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text('REMBOURSEMENT FRAIS DE TRANSPORT DES PARTICIPANTS', pageWidth / 2, yPos, { align: 'center' })

  yPos += 12

  doc.setFontSize(10)
  doc.setTextColor(0, 128, 0)
  doc.setFont('helvetica', 'bold')
  const natureReunionText = `Nature de la réunion : ${remboursement.nature_reunion}`
  doc.text(natureReunionText, 15, yPos)

  yPos += 10

  doc.setFontSize(10)
  doc.setTextColor(0, 128, 0)
  doc.setFont('helvetica', 'bold')
  doc.text('Nature du travail', 15, yPos)

  yPos += 7
  doc.setTextColor(0)
  doc.setFont('helvetica', 'normal')
  if (remboursement.nature_travail && remboursement.nature_travail.length > 0) {
    remboursement.nature_travail.forEach((ligne: string, index: number) => {
      if (ligne.trim()) {
        doc.text(`${index + 1}. ${ligne}`, 15, yPos)
        yPos += 6
      }
    })
  }

  yPos += 5

  doc.setFontSize(10)
  doc.setTextColor(0, 128, 0)
  doc.setFont('helvetica', 'bold')
  doc.text(`Lieu de la réunion : ${remboursement.lieu}`, 15, yPos)

  yPos += 8

  const requisitionUsers = remboursement.requisition || {}
  doc.setFontSize(10)
  doc.setTextColor(0, 128, 0)
  doc.setFont('helvetica', 'bold')
  doc.text('Traçabilité', 15, yPos)

  yPos += 6
  doc.setTextColor(0)
  doc.setFont('helvetica', 'normal')
  doc.text(`Demandeur : ${formatUserName(requisitionUsers.demandeur)}`, 15, yPos)

  yPos += 5
  doc.text(`Validateur / Rejeteur : ${formatUserName(requisitionUsers.approbateur || requisitionUsers.validateur)}`, 15, yPos)

  yPos += 5
  doc.text(`Caissier(e) : ${formatUserName(requisitionUsers.caissier)}`, 15, yPos)

  yPos += 8

  autoTable(doc, {
    startY: yPos,
    head: [['DATE DE LA\nREUNION', 'DEBUT', 'FIN']],
    body: [[
      format(new Date(remboursement.date_reunion), 'dd/MM/yyyy'),
      remboursement.heure_debut || '-',
      remboursement.heure_fin || '-'
    ]],
    theme: 'grid',
    headStyles: {
      fillColor: [255, 255, 255],
      textColor: 0,
      fontStyle: 'bold',
      fontSize: 9,
      halign: 'center',
      lineWidth: 0.5,
      lineColor: 0
    },
    bodyStyles: {
      fontSize: 10,
      cellPadding: 5,
      halign: 'center',
      lineWidth: 0.5,
      lineColor: 0
    },
    columnStyles: {
      0: { cellWidth: 40 },
      1: { cellWidth: 30 },
      2: { cellWidth: 30 }
    },
    margin: { left: 15 }
  })

  yPos = (doc as any).lastAutoTable.finalY + 10

  const principauxData = principaux.map((p: any) => [
    p.nom,
    p.titre_fonction,
    toNumber(p.montant),
    ''
  ])

  autoTable(doc, {
    head: [['Noms des Participants', 'Titres des\nParticipants', 'Montant\nUSD', 'Signature']],
    body: principauxData,
    startY: yPos,
    theme: 'grid',
    headStyles: {
      fillColor: [255, 255, 255],
      textColor: 0,
      fontStyle: 'bold',
      fontSize: 9,
      halign: 'center',
      lineWidth: 0.5,
      lineColor: 0
    },
    bodyStyles: {
      fontSize: 9,
      cellPadding: 5,
      lineWidth: 0.5,
      lineColor: 0
    },
    columnStyles: {
      0: { cellWidth: 70 },
      1: { cellWidth: 50 },
      2: { cellWidth: 30, halign: 'center' },
      3: { cellWidth: 35, halign: 'center' }
    },
    margin: { left: 15, right: 15 }
  })

  yPos = (doc as any).lastAutoTable.finalY + 5

  if (assistants.length > 0) {
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(10)
    doc.setTextColor(0)
    doc.text('Assistance', 15, yPos)
    yPos += 5

    const assistantsData = assistants.map((p: any) => [
      p.nom,
      p.titre_fonction,
      toNumber(p.montant),
      ''
    ])

    autoTable(doc, {
      body: assistantsData,
      startY: yPos,
      theme: 'grid',
      bodyStyles: {
        fontSize: 9,
        cellPadding: 5,
        lineWidth: 0.5,
        lineColor: 0
      },
      columnStyles: {
        0: { cellWidth: 70 },
        1: { cellWidth: 50 },
        2: { cellWidth: 30, halign: 'center' },
        3: { cellWidth: 35, halign: 'center' }
      },
      margin: { left: 15, right: 15 }
    })

    yPos = (doc as any).lastAutoTable.finalY + 5
  }

  autoTable(doc, {
    body: [['TOTAL', '', toNumber(remboursement.montant_total), '']],
    startY: yPos,
    theme: 'grid',
    bodyStyles: {
      fontSize: 10,
      cellPadding: 5,
      fontStyle: 'bold',
      lineWidth: 0.5,
      lineColor: 0
    },
    columnStyles: {
      0: { cellWidth: 70 },
      1: { cellWidth: 50 },
      2: { cellWidth: 30, halign: 'center' },
      3: { cellWidth: 35, halign: 'center' }
    },
    margin: { left: 15, right: 15 }
  })

  yPos = (doc as any).lastAutoTable.finalY + 8

  doc.setFontSize(9)
  doc.setFont('helvetica', 'italic')
  doc.setTextColor(80)
  const montantEnLettres = numberToWords(toNumber(remboursement.montant_total))
  const montantLines = doc.splitTextToSize(`Montant total en lettres : ${montantEnLettres}`, pageWidth - 30)
  doc.text(montantLines, 15, yPos)
  yPos += (montantLines.length * 5) + 10

  doc.setFontSize(10)
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(0)
  doc.text(`Fait à Kinshasa, le ${format(new Date(remboursement.date_reunion), 'dd MMMM yyyy')}`, 15, yPos)

  yPos += 15
  const colWidth = (pageWidth - 30) / 2

  doc.setFont('helvetica', 'normal')
  doc.text('Vu par le Trésorier Adjoint du CPK', 25, yPos)
  doc.text('Approuvé par le Rapporteur du CPK', 25 + colWidth, yPos)

  doc.setFontSize(8)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(100)
  doc.text(
    `${format(new Date(), 'dd/MM/yyyy HH:mm')}`,
    10,
    pageHeight - 10
  )

  doc.text(
    'Remboursement frais de transport - ONEC/CPK',
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
  } else {
    doc.save(`remboursement_transport_${remboursement.numero_remboursement}.pdf`)
  }
}
