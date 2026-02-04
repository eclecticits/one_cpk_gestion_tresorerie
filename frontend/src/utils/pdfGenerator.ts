import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { numberToWords } from './numberToWords'
import { formatAmount, toNumber } from './amount'

const ONEC_GREEN = '#2d6a4f'
const ONEC_LIGHT_GREEN = '#95d5b2'
const ONEC_LIGHT_BG = '#ecfdf5'
const HEADER_HEIGHT = 28
const LOGO_SIZE = 20
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

  const doc = new jsPDF()
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()

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
      `Page ${pageNumber}`,
      pageWidth - 20,
      pageHeight - 10
    )
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

  const tableData = requisitions.map(req => [
    req.numero_requisition,
    format(new Date(req.created_at), 'dd/MM/yyyy'),
    req.objet.substring(0, 30) + (req.objet.length > 30 ? '...' : ''),
    req.rubriques || '',
    `${formatAmount(req.montant_total)} $`,
    req.statut === 'brouillon' ? 'Brouillon' :
    req.statut === 'validee_tresorerie' ? 'Validée' :
    req.statut === 'approuvee' ? 'Approuvée' :
    req.statut === 'payee' ? 'Payée' : 'Rejetée',
    req.mode_paiement === 'cash' ? 'Caisse' :
    req.mode_paiement === 'mobile_money' ? 'Mobile Money' : 'Virement',
    formatUserName(req.demandeur),
    formatUserName(req.approbateur || req.validateur)
  ])

  autoTable(doc, {
    head: [['N° Réquisition', 'Date', 'Objet', 'Rubrique', 'Montant', 'Statut', 'Paiement', 'Demandeur', 'Validateur']],
    body: tableData,
    startY: 70,
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
      0: { cellWidth: 28 },
      1: { cellWidth: 18 },
      2: { cellWidth: 35 },
      3: { cellWidth: 22 },
      4: { cellWidth: 18, halign: 'right' },
      5: { cellWidth: 18 },
      6: { cellWidth: 18 },
      7: { cellWidth: 25 },
      8: { cellWidth: 25 }
    },
    didDrawPage: () => {
      addFooter(doc.getNumberOfPages())
    }
  })

  const finalY = (doc as any).lastAutoTable.finalY + 10

  const normalizeStatut = (value: any) => {
    const raw = String(value || '').trim()
    if (!raw) return ''
    const lower = raw.toLowerCase()
    if (lower === 'en_attente') return 'en_attente'
    if (lower === 'validee') return 'validee'
    if (lower === 'rejetee' || lower === 'rejeté' || lower === 'rejetee') return 'rejetee'
    if (lower === 'brouillon') return 'brouillon'
    if (lower === 'validee_tresorerie') return 'validee_tresorerie'
    if (lower === 'approuvee') return 'approuvee'
    if (lower === 'payee') return 'payee'
    if (raw === 'EN_ATTENTE') return 'en_attente'
    if (raw === 'VALIDEE') return 'validee'
    if (raw === 'REJETEE') return 'rejetee'
    if (raw === 'PAYEE') return 'payee'
    if (raw === 'APPROUVEE') return 'approuvee'
    return lower
  }

  const getStatut = (r: any) => normalizeStatut(r?.statut ?? r?.status)
  const isPayee = (r: any) => {
    const statut = getStatut(r)
    return statut === 'payee' || !!r?.payee_par || !!r?.payee_le
  }

  const totalRequisitions = requisitions.length
  const totalApprouvees = requisitions.filter(r => getStatut(r) === 'validee').length
  const totalRejetees = requisitions.filter(r => getStatut(r) === 'rejetee').length
  const totalPayees = requisitions.filter(r => isPayee(r)).length
  const totalMontant = requisitions.reduce((sum, r) => sum + Number(r.montant_total || 0), 0)
  const totalDecaisse = requisitions.filter(r => isPayee(r)).reduce((sum, r) => sum + Number(r.montant_total || 0), 0)

  doc.setDrawColor(ONEC_GREEN)
  doc.setFillColor(ONEC_LIGHT_BG)
  doc.roundedRect(10, finalY, pageWidth - 20, 58, 3, 3, 'FD')

  doc.setFontSize(12)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text('RÉCAPITULATIF', 15, finalY + 10)

  doc.setDrawColor(ONEC_LIGHT_GREEN)
  doc.setLineWidth(0.5)
  doc.line(15, finalY + 14, pageWidth - 15, finalY + 14)

  const leftX = 15
  const rightX = pageWidth / 2 + 5
  let yPos = finalY + 22

  doc.setFontSize(9)
  doc.setTextColor(60)
  doc.setFont('helvetica', 'normal')
  doc.text('Total réquisitions', leftX, yPos)
  doc.text('Total payées', rightX, yPos)

  doc.setFont('helvetica', 'bold')
  doc.setTextColor(0)
  doc.setFontSize(12)
  doc.text(String(totalRequisitions), leftX, yPos + 6)
  doc.text(String(totalPayees), rightX, yPos + 6)

  yPos += 16
  doc.setFontSize(9)
  doc.setTextColor(60)
  doc.setFont('helvetica', 'normal')
  doc.text('Total approuvées', leftX, yPos)
  doc.text('Total rejetées', rightX, yPos)

  doc.setFont('helvetica', 'bold')
  doc.setTextColor(0)
  doc.setFontSize(12)
  doc.text(String(totalApprouvees), leftX, yPos + 6)
  doc.text(String(totalRejetees), rightX, yPos + 6)

  yPos += 16
  doc.setFontSize(9)
  doc.setTextColor(60)
  doc.setFont('helvetica', 'normal')
  doc.text('Montant total', leftX, yPos)
  doc.text('Total décaissé', rightX, yPos)

  doc.setFont('helvetica', 'bold')
  doc.setTextColor(0)
  doc.setFontSize(11)
  doc.text(`${formatAmount(totalMontant)} $`, leftX, yPos + 6)
  doc.text(`${formatAmount(totalDecaisse)} $`, rightX, yPos + 6)

  yPos += 14
  doc.setDrawColor(ONEC_LIGHT_GREEN)
  doc.setLineWidth(0.5)
  doc.line(15, yPos, pageWidth - 15, yPos)

  doc.setFont('helvetica', 'bold')
  doc.setTextColor(ONEC_GREEN)
  doc.setFontSize(11)
  doc.text(`Solde sur période : ${formatAmount(toNumber(totalMontant) - toNumber(totalDecaisse))} $`, 15, yPos + 8)

  doc.save(`requisitions_${dateDebut}_${dateFin}.pdf`)
}

export const generateEncaissementsPDF = async (
  encaissements: any[],
  dateDebut: string,
  dateFin: string,
  _userName: string
) => {
  const doc = new jsPDF()
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

  const tableData = encaissements.map(enc => [
    format(new Date(enc.date_encaissement), 'dd/MM/yyyy'),
    enc.numero_recu,
    enc.client || '',
    enc.rubrique || '',
    `${formatAmount(enc.montant_total)} $`,
    enc.statut_paiement === 'complet' ? 'Payé' :
    enc.statut_paiement === 'partiel' ? 'Partiel' :
    enc.statut_paiement === 'avance' ? 'Avance' : 'Non payé'
  ])

  autoTable(doc, {
    head: [['Date', 'N° Reçu', 'Client', 'Rubrique', 'Montant', 'Statut']],
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

  const totalMontant = encaissements.reduce((sum, e) => sum + Number(e.montant_total), 0)
  const totalPaye = encaissements.filter(e => e.statut_paiement === 'complet').reduce((sum, e) => sum + Number(e.montant_total), 0)

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

  doc.save(`encaissements_${dateDebut}_${dateFin}.pdf`)
}

export const generateSingleRequisitionPDF = async (
  requisition: any,
  lignes: any[],
  action: 'print' | 'download' = 'download',
  _userName: string
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

  doc.setDrawColor(ONEC_GREEN)
  doc.setLineWidth(3)
  doc.line(10, 40, pageWidth - 10, 40)

  doc.setFillColor(ONEC_LIGHT_BG)
  doc.roundedRect(10, 8, pageWidth - 20, HEADER_HEIGHT, 3, 3, 'F')
  addLogo(doc, 12, 10, LOGO_SIZE, logoDataUrl)

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

  doc.setFontSize(16)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text('RÉQUISITION DE FONDS', pageWidth / 2, 50, { align: 'center' })

  doc.setFontSize(12)
  doc.setTextColor(0)
  doc.setFont('helvetica', 'normal')
  doc.text(`N° ${requisition.numero_requisition}`, pageWidth / 2, 60, { align: 'center' })

  doc.setDrawColor(ONEC_GREEN)
  doc.setFillColor(ONEC_LIGHT_BG)
  doc.roundedRect(10, 70, pageWidth - 20, 70, 3, 3, 'FD')

  let yPos = 78
  doc.setFontSize(10)
  doc.setTextColor(0)
  doc.setFont('helvetica', 'bold')

  doc.text('Date de création:', 15, yPos)
  doc.setFont('helvetica', 'normal')
  doc.text(format(new Date(requisition.created_at), 'dd/MM/yyyy'), 65, yPos)

  yPos += 8
  doc.setFont('helvetica', 'bold')
  doc.text('Objet:', 15, yPos)
  doc.setFont('helvetica', 'normal')
  const objetLines = doc.splitTextToSize(requisition.objet, pageWidth - 80)
  doc.text(objetLines, 65, yPos)
  yPos += (objetLines.length * 5)

  yPos += 3
  doc.setFont('helvetica', 'bold')
  doc.text('Mode de paiement:', 15, yPos)
  doc.setFont('helvetica', 'normal')
  const modePaiement = requisition.mode_paiement === 'cash' ? 'Caisse' :
                       requisition.mode_paiement === 'mobile_money' ? 'Mobile Money' : 'Virement bancaire'
  doc.text(modePaiement, 65, yPos)

  yPos += 8
  doc.setFont('helvetica', 'bold')
  doc.text('Statut:', 15, yPos)
  doc.setFont('helvetica', 'normal')
  const statut = requisition.statut === 'brouillon' ? 'Brouillon' :
                 requisition.statut === 'validee_tresorerie' ? 'Validée Trésorerie' :
                 requisition.statut === 'approuvee' ? 'Approuvée' :
                 requisition.statut === 'payee' ? 'Payée' : 'Rejetée'
  doc.text(statut, 65, yPos)

  yPos += 8
  doc.setFont('helvetica', 'bold')
  doc.text('Demandeur:', 15, yPos)
  doc.setFont('helvetica', 'normal')
  doc.text(formatUserName(requisition.demandeur), 65, yPos)

  yPos += 8
  doc.setFont('helvetica', 'bold')
  doc.text('Validateur / Rejeteur:', 15, yPos)
  doc.setFont('helvetica', 'normal')
  const validatorName = formatUserName(requisition.approbateur || requisition.validateur)
  doc.text(validatorName, 65, yPos)

  yPos += 8
  doc.setFont('helvetica', 'bold')
  doc.text('Caissier(e):', 15, yPos)
  doc.setFont('helvetica', 'normal')
  doc.text(formatUserName(requisition.caissier), 65, yPos)

  yPos = Math.max(150, yPos + 10)

  doc.setFontSize(12)
  doc.setTextColor(ONEC_GREEN)
  doc.setFont('helvetica', 'bold')
  doc.text('LIGNES DE DÉPENSE', 15, yPos)

  yPos += 5

  const tableData = lignes.map(ligne => [
    ligne.rubrique,
    ligne.description,
    ligne.quantite.toString(),
    `${formatAmount(ligne.montant_unitaire)} $`,
    `${formatAmount(ligne.montant_total)} $`
  ])

  autoTable(doc, {
    head: [['Rubrique', 'Description', 'Qté', 'Prix unitaire', 'Total']],
    body: tableData,
    startY: yPos,
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
      0: { cellWidth: 35 },
      1: { cellWidth: 70 },
      2: { cellWidth: 15, halign: 'center' },
      3: { cellWidth: 30, halign: 'right' },
      4: { cellWidth: 30, halign: 'right' }
    },
    foot: [[
      { content: 'MONTANT TOTAL', colSpan: 4, styles: { halign: 'right', fontStyle: 'bold', fillColor: ONEC_LIGHT_GREEN } },
      { content: `${formatAmount(requisition.montant_total)} $`, styles: { fontStyle: 'bold', fillColor: ONEC_LIGHT_GREEN, halign: 'right' } }
    ]],
    footStyles: {
      fillColor: ONEC_LIGHT_GREEN,
      textColor: 0,
      fontStyle: 'bold',
      fontSize: 10
    }
  })

  let finalY = (doc as any).lastAutoTable.finalY + 10

  doc.setFontSize(9)
  doc.setFont('helvetica', 'italic')
  doc.setTextColor(80)
  const montantEnLettres = numberToWords(Number(requisition.montant_total))
  const montantLines = doc.splitTextToSize(`Montant total en lettres : ${montantEnLettres}`, pageWidth - 30)
  doc.text(montantLines, 15, finalY)
  finalY += (montantLines.length * 5) + 10

  if (requisition.a_valoir) {
    doc.setDrawColor('#f59e0b')
    doc.setFillColor('#fef3c7')
    doc.roundedRect(10, finalY, pageWidth - 20, 25, 3, 3, 'FD')

    doc.setFontSize(10)
    doc.setTextColor('#92400e')
    doc.setFont('helvetica', 'bold')
    doc.text('⚠ RÉQUISITION À VALOIR', 15, finalY + 8)

    doc.setFont('helvetica', 'normal')
    doc.setFontSize(9)
    doc.text(`Instance bénéficiaire: ${requisition.instance_beneficiaire || 'N/A'}`, 15, finalY + 15)
    if (requisition.notes_a_valoir) {
      const notesLines = doc.splitTextToSize(`Notes: ${requisition.notes_a_valoir}`, pageWidth - 30)
      doc.text(notesLines, 15, finalY + 20)
    }
  }

  doc.setFontSize(8)
  doc.setTextColor(100)
  doc.text(
    `${format(new Date(), 'dd/MM/yyyy HH:mm')}`,
    10,
    pageHeight - 10
  )

  doc.text(
    'Réquisition de fonds - ONEC/CPK',
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
    doc.save(`requisition_${requisition.numero_requisition}.pdf`)
  }
}
