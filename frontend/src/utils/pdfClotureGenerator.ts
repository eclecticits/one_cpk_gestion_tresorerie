import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { toNumber } from './amount'

type ClotureDetail = {
  reference_numero?: string | null
  beneficiaire?: string | null
  motif?: string | null
  montant_paye?: number | string | null
}

type ClotureReport = {
  date: string | Date
  total: number | string
  details: ClotureDetail[]
}

const formatMoney = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(value)

const formatDateValue = (value: string | Date) => {
  const parsed = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return format(parsed, 'yyyy-MM-dd')
}

export const generateCloturePDF = (data: ClotureReport) => {
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const dateLabel = formatDateValue(data.date)

  doc.setFont('times', 'bold')
  doc.setFontSize(16)
  doc.text('PROCÈS-VERBAL DE CLÔTURE DE CAISSE', pageWidth / 2, 20, { align: 'center' })

  doc.setFont('times', 'normal')
  doc.setFontSize(10)
  doc.text(`Date : ${dateLabel}`, 15, 30)
  doc.text(`Réf : CLOT-${dateLabel.replace(/-/g, '')}`, 15, 35)

  const body = (data.details || []).map((s) => [
    s.reference_numero || '',
    s.beneficiaire || '',
    s.motif || '',
    formatMoney(toNumber(s.montant_paye || 0)),
  ])

  autoTable(doc, {
    startY: 45,
    head: [['N° PAY', 'Bénéficiaire', 'Motif', 'Montant']],
    body,
    foot: [['', '', 'TOTAL DÉCAISSÉ', formatMoney(toNumber(data.total || 0))]],
    theme: 'striped',
  })

  const finalY = (doc as any).lastAutoTable.finalY + 20
  doc.setFont('times', 'normal')
  doc.text('Le Caissier', 30, finalY)
  doc.text('Le Superviseur / Trésorier', 130, finalY)

  doc.save(`Cloture_Caisse_${dateLabel}.pdf`)
}
