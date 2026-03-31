import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { toNumber } from './amount'

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

const formatAmount = (value: number) =>
  new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    .format(value)
    .replace(/[\u202F\u00A0]/g, ' ')

export const generateJournalPDF = (data: JournalLine[], filtre: JournalFilter) => {
  const doc = new jsPDF('p', 'mm', 'a4')
  const startLabel = filtre.date_debut ? format(new Date(filtre.date_debut), 'dd/MM/yyyy') : '—'
  const endLabel = filtre.date_fin ? format(new Date(filtre.date_fin), 'dd/MM/yyyy') : '—'

  doc.setFontSize(14)
  doc.text(`JOURNAL DE TRÉSORERIE : ${filtre.nom_compte}`, 14, 15)
  doc.setFontSize(10)
  doc.text(`Période : Du ${startLabel} au ${endLabel}`, 14, 22)
  doc.text(`Devise : ${filtre.devise}`, 14, 27)

  const columns = [
    { header: 'Date', dataKey: 'date' },
    { header: 'Libellé / Référence', dataKey: 'libelle' },
    { header: 'Entrée (+)', dataKey: 'entree' },
    { header: 'Sortie (-)', dataKey: 'sortie' },
    { header: 'Solde', dataKey: 'solde' },
  ]

  const rows = data.map((m) => ({
    date: format(new Date(m.date), 'dd/MM/yyyy'),
    libelle: `${m.libelle || ''}${m.reference ? ` (${m.reference})` : ''}`.trim(),
    entree: toNumber(m.entree) > 0 ? formatAmount(toNumber(m.entree)) : '-',
    sortie: toNumber(m.sortie) > 0 ? formatAmount(toNumber(m.sortie)) : '-',
    solde: formatAmount(toNumber(m.solde)),
  }))

  const soldeInitial = formatAmount(toNumber(filtre.solde_initial))
  const totalEntrees = formatAmount(toNumber(filtre.total_entrees))
  const totalSorties = formatAmount(toNumber(filtre.total_sorties))
  const soldeFinal = formatAmount(toNumber(filtre.solde_final))

  const bodyRows: Array<Record<string, any>> = [
    {
      date: '',
      libelle: 'REPORT À NOUVEAU (Solde initial)',
      entree: '',
      sortie: '',
      solde: soldeInitial,
      __rowType: 'initial',
    },
    ...rows,
    {
      date: '',
      libelle: 'TOTAUX DE LA PÉRIODE',
      entree: totalEntrees,
      sortie: totalSorties,
      solde: soldeFinal,
      __rowType: 'total',
    },
  ]

  autoTable(doc, {
    startY: 35,
    head: [columns.map((col) => col.header)],
    body: bodyRows.map((row) => columns.map((col) => (row as any)[col.dataKey])),
    theme: 'grid',
    headStyles: { fillColor: [26, 74, 124], textColor: [255, 255, 255], fontStyle: 'bold', fontSize: 10 },
    bodyStyles: { fontSize: 9 },
    alternateRowStyles: { fillColor: [249, 249, 249] },
    columnStyles: {
      0: { cellWidth: 22 },
      1: { cellWidth: 86 },
      2: { halign: 'right', cellWidth: 24 },
      3: { halign: 'right', cellWidth: 24 },
      4: { halign: 'right', fontStyle: 'bold', cellWidth: 28 },
    },
    styles: { overflow: 'linebreak' },
    didParseCell: (hookData) => {
      const row = bodyRows[hookData.row.index]
      if (!row || !row.__rowType) return
      if (row.__rowType === 'initial' || row.__rowType === 'total') {
        hookData.cell.styles.fontStyle = 'bold'
      }
      if (row.__rowType === 'total') {
        hookData.cell.styles.fillColor = [238, 238, 238]
        if (hookData.column.index === 4) {
          hookData.cell.styles.fillColor = [26, 74, 124]
          hookData.cell.styles.textColor = [255, 255, 255]
        }
      }
    },
  })

  const finalY = (doc as any).lastAutoTable?.finalY || 35
  const footerY = Math.min(finalY + 15, 240)
  const boxWidth = 60
  const boxHeight = 30
  doc.setFontSize(9)
  doc.rect(14, footerY, boxWidth, boxHeight)
  doc.text('Établi par (Caissier)', 16, footerY + 6)
  if (filtre.user_name) {
    doc.text(filtre.user_name, 16, footerY + 20)
  }
  doc.rect(80, footerY, boxWidth, boxHeight)
  doc.text('Vérifié par (Comptabilité)', 82, footerY + 6)
  doc.rect(146, footerY, boxWidth, boxHeight)
  doc.text('Approuvé par (Direction)', 148, footerY + 6)

  doc.save(`Journal_${filtre.nom_compte}_${endLabel.replace(/\//g, '-')}.pdf`)
}
