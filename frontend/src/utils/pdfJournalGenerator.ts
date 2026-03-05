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
}

const formatAmount = (value: number) =>
  new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)

export const generateJournalPDF = (data: JournalLine[], filtre: JournalFilter) => {
  const doc = new jsPDF('p', 'mm', 'a4')
  const startLabel = filtre.date_debut ? format(new Date(filtre.date_debut), 'dd/MM/yyyy') : '—'
  const endLabel = filtre.date_fin ? format(new Date(filtre.date_fin), 'dd/MM/yyyy') : '—'

  doc.setFontSize(16)
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

  autoTable(doc, {
    startY: 35,
    head: [columns.map((col) => col.header)],
    body: rows.map((row) => columns.map((col) => (row as any)[col.dataKey])),
    theme: 'grid',
    headStyles: { fillColor: [240, 240, 240], textColor: [0, 0, 0] },
    columnStyles: {
      2: { halign: 'right' },
      3: { halign: 'right' },
      4: { halign: 'right', fontStyle: 'bold' },
    },
  })

  doc.save(`Journal_${filtre.nom_compte}_${endLabel.replace(/\//g, '-')}.pdf`)
}
