import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { formatAmount, toNumber } from './amount'
import {
  drawTenantFooter,
  drawTenantHeader,
  loadTenantIdentity,
  type TenantIdentity,
} from './pdfTenantIdentity'

type JournalLine = {
  date: string | Date
  libelle?: string | null
  reference?: string | null
  entree?: number | string | null
  sortie?: number | string | null
  solde?: number | string | null
}

type JournalFilter = {
  nom_compte: string
  date_debut?: string | null
  date_fin?: string | null
  devise: string
  solde_initial?: number | string | null
  total_entrees?: number | string | null
  total_sorties?: number | string | null
  solde_final?: number | string | null
  user_name?: string | null
}

/** Cartouche de synthèse : solde d'ouverture, flux, solde de clôture. */
const drawSummary = (
  doc: jsPDF,
  y: number,
  devise: string,
  values: { initial: number; entrees: number; sorties: number; final: number },
): number => {
  const pageWidth = doc.internal.pageSize.getWidth()
  const margin = 12
  const gap = 4
  const cardW = (pageWidth - margin * 2 - gap * 3) / 4
  const cardH = 17

  const cards: Array<{ label: string; value: number; tone: [number, number, number] }> = [
    { label: 'Solde initial', value: values.initial, tone: [241, 245, 249] },
    { label: 'Total entrées', value: values.entrees, tone: [236, 253, 245] },
    { label: 'Total sorties', value: values.sorties, tone: [254, 242, 242] },
    { label: 'Solde final', value: values.final, tone: [6, 95, 70] },
  ]

  cards.forEach((card, i) => {
    const x = margin + i * (cardW + gap)
    const isFinal = i === cards.length - 1
    doc.setFillColor(card.tone[0], card.tone[1], card.tone[2])
    doc.roundedRect(x, y, cardW, cardH, 2, 2, 'F')

    const [lr, lg, lb] = isFinal ? [220, 252, 231] : [90, 100, 115]
    const [vr, vg, vb] = isFinal ? [255, 255, 255] : [15, 23, 42]
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(lr, lg, lb)
    doc.text(card.label.toUpperCase(), x + 3, y + 6)

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(10)
    doc.setTextColor(vr, vg, vb)
    doc.text(`${formatAmount(card.value)} ${devise}`, x + 3, y + 13)
  })

  return y + cardH + 6
}

/** Cadre de signatures, gardé sur une seule page pour ne pas être coupé. */
const drawSignatures = (doc: jsPDF, y: number, userName?: string | null): void => {
  const pageWidth = doc.internal.pageSize.getWidth()
  const margin = 12
  const gap = 5
  const boxW = (pageWidth - margin * 2 - gap * 2) / 3
  const boxH = 26

  const boxes = [
    { title: 'Établi par (Caissier)', name: userName || '' },
    { title: 'Vérifié par (Comptabilité)', name: '' },
    { title: 'Approuvé par (Direction)', name: '' },
  ]

  boxes.forEach((box, i) => {
    const x = margin + i * (boxW + gap)
    doc.setDrawColor(203, 213, 225)
    doc.setLineWidth(0.3)
    doc.roundedRect(x, y, boxW, boxH, 2, 2, 'S')

    doc.setFont('helvetica', 'bold')
    doc.setFontSize(7.5)
    doc.setTextColor(90, 100, 115)
    doc.text(box.title, x + 3, y + 5.5)

    doc.setDrawColor(226, 232, 240)
    doc.line(x + 3, y + boxH - 7, x + boxW - 3, y + boxH - 7)

    if (box.name) {
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(8.5)
      doc.setTextColor(15, 23, 42)
      doc.text(box.name, x + 3, y + boxH - 2.5)
    }
  })
}

export const generateJournalPDF = async (data: JournalLine[], filtre: JournalFilter) => {
  // Identité de l'organisation émettrice : chargée AVANT le tracé, car aucun
  // document ne doit sortir sans elle.
  const identity: TenantIdentity = await loadTenantIdentity()

  const doc = new jsPDF('p', 'mm', 'a4')
  const margin = 12
  const startLabel = filtre.date_debut ? format(new Date(filtre.date_debut), 'dd/MM/yyyy') : '—'
  const endLabel = filtre.date_fin ? format(new Date(filtre.date_fin), 'dd/MM/yyyy') : '—'

  const headerBottom = drawTenantHeader(doc, identity, {
    title: `Journal de trésorerie — ${filtre.nom_compte}`,
    subtitle: `Période du ${startLabel} au ${endLabel}  •  Devise : ${filtre.devise}`,
  })

  const soldeInitial = toNumber(filtre.solde_initial)
  const totalEntrees = toNumber(filtre.total_entrees)
  const totalSorties = toNumber(filtre.total_sorties)
  const soldeFinal = toNumber(filtre.solde_final)

  const tableTop = drawSummary(doc, headerBottom, filtre.devise, {
    initial: soldeInitial,
    entrees: totalEntrees,
    sorties: totalSorties,
    final: soldeFinal,
  })

  const rows = data.map((m) => ({
    date: format(new Date(m.date), 'dd/MM/yyyy'),
    libelle: `${m.libelle || ''}${m.reference ? ` (${m.reference})` : ''}`.trim(),
    entree: toNumber(m.entree) > 0 ? formatAmount(toNumber(m.entree)) : '—',
    sortie: toNumber(m.sortie) > 0 ? formatAmount(toNumber(m.sortie)) : '—',
    solde: formatAmount(toNumber(m.solde)),
  }))

  const bodyRows: Array<Record<string, any>> = [
    {
      date: '',
      libelle: 'REPORT À NOUVEAU (solde initial)',
      entree: '',
      sortie: '',
      solde: formatAmount(soldeInitial),
      __rowType: 'initial',
    },
    ...rows,
    {
      date: '',
      libelle: 'TOTAUX DE LA PÉRIODE',
      entree: formatAmount(totalEntrees),
      sortie: formatAmount(totalSorties),
      solde: formatAmount(soldeFinal),
      __rowType: 'total',
    },
  ]

  const columns = [
    { header: 'Date', dataKey: 'date' },
    { header: 'Libellé / Référence', dataKey: 'libelle' },
    { header: `Entrée (${filtre.devise})`, dataKey: 'entree' },
    { header: `Sortie (${filtre.devise})`, dataKey: 'sortie' },
    { header: `Solde (${filtre.devise})`, dataKey: 'solde' },
  ]

  autoTable(doc, {
    startY: tableTop,
    margin: { left: margin, right: margin, top: 20, bottom: 20 },
    head: [columns.map((col) => col.header)],
    body: bodyRows.map((row) => columns.map((col) => (row as any)[col.dataKey])),
    theme: 'grid',
    headStyles: {
      fillColor: [6, 95, 70],
      textColor: [255, 255, 255],
      fontStyle: 'bold',
      fontSize: 8.5,
      cellPadding: 2.5,
    },
    bodyStyles: { fontSize: 8.5, cellPadding: 2, textColor: [15, 23, 42] },
    alternateRowStyles: { fillColor: [248, 250, 252] },
    columnStyles: {
      0: { cellWidth: 21 },
      1: { cellWidth: 'auto' },
      2: { halign: 'right', cellWidth: 27 },
      3: { halign: 'right', cellWidth: 27 },
      4: { halign: 'right', cellWidth: 30, fontStyle: 'bold' },
    },
    styles: { overflow: 'linebreak', lineColor: [226, 232, 240], lineWidth: 0.15 },
    didParseCell: (hookData) => {
      if (hookData.section !== 'body') return
      const row = bodyRows[hookData.row.index]
      if (!row?.__rowType) return
      hookData.cell.styles.fontStyle = 'bold'
      if (row.__rowType === 'initial') {
        hookData.cell.styles.fillColor = [241, 245, 249]
      }
      if (row.__rowType === 'total') {
        hookData.cell.styles.fillColor = [6, 95, 70]
        hookData.cell.styles.textColor = [255, 255, 255]
      }
    },
  })

  // Signatures : sur la page courante si la place suffit, sinon sur une nouvelle.
  const pageHeight = doc.internal.pageSize.getHeight()
  let finalY = ((doc as any).lastAutoTable?.finalY ?? tableTop) + 10
  if (finalY + 26 > pageHeight - 20) {
    doc.addPage()
    finalY = 24
  }
  drawSignatures(doc, finalY, filtre.user_name)

  // Pied de page identifiant l'organisation sur CHAQUE page.
  const pageCount = doc.getNumberOfPages()
  for (let page = 1; page <= pageCount; page += 1) {
    doc.setPage(page)
    drawTenantFooter(doc, identity, {
      pageNumber: page,
      pageCount,
      generatedBy: filtre.user_name,
    })
  }

  const safeName = String(filtre.nom_compte || 'caisse').replace(/[^\w\-]+/g, '_')
  const safeOrg = String(identity.orgName || 'organisation').replace(/[^\w\-]+/g, '_')
  doc.save(`Journal_${safeOrg}_${safeName}_${endLabel.replace(/\//g, '-')}.pdf`)
}
