import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { toNumber } from './amount'

type ClotureReport = {
  date: string | Date
  reference_numero?: string
  caissier_nom?: string
  total?: number | string
  details?: { reference_numero?: string | null; beneficiaire?: string | null; motif?: string | null; montant_paye?: number | string | null }[]
  solde_theorique_usd?: number | string
  solde_physique_usd?: number | string
  ecart_usd?: number | string
  solde_theorique_cdf?: number | string
  solde_physique_cdf?: number | string
  ecart_cdf?: number | string
  observation?: string | null
}

const formatMoney = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(value)

const formatMoneyCdf = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(value)

const formatDateValue = (value: string | Date) => {
  const parsed = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return parsed.toLocaleDateString('fr-FR')
}

export const generateCloturePDF = (
  data: ClotureReport,
  options: { save?: boolean; returnBlob?: boolean } = {}
) => {
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const dateLabel = formatDateValue(data.date)
  const reference = data.reference_numero || `PVC-${dateLabel.replace(/\//g, '-')}`
  const hasBalance =
    data.solde_theorique_usd !== undefined ||
    data.solde_theorique_cdf !== undefined ||
    data.solde_physique_usd !== undefined ||
    data.solde_physique_cdf !== undefined

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(14)
  doc.text('ONEC / CPK - TRÉSORERIE', pageWidth / 2, 15, { align: 'center' })
  doc.setFontSize(10)
  doc.setFont('helvetica', 'normal')
  doc.text(
    hasBalance ? "PROCÈS-VERBAL D'ARRÊTÉ DE CAISSE" : 'RAPPORT JOURNALIER DES SORTIES',
    pageWidth / 2,
    22,
    { align: 'center' }
  )
  doc.line(pageWidth / 2 - 35, 24, pageWidth / 2 + 35, 24)

  doc.setFontSize(10)
  doc.text(`Référence : ${reference}`, 14, 35)
  doc.text(`Date de clôture : ${dateLabel}`, 14, 40)
  doc.text(`Caissier : ${data.caissier_nom || '—'}`, 14, 45)

  if (hasBalance) {
    const theoUsd = toNumber(data.solde_theorique_usd || 0)
    const physUsd = toNumber(data.solde_physique_usd || 0)
    const ecartUsd = toNumber(data.ecart_usd || 0)
    const theoCdf = toNumber(data.solde_theorique_cdf || 0)
    const physCdf = toNumber(data.solde_physique_cdf || 0)
    const ecartCdf = toNumber(data.ecart_cdf || 0)

    autoTable(doc, {
      startY: 55,
      head: [['Désignation', 'Solde Théorique (Logiciel)', 'Solde Physique (Compté)', 'Écart']],
      body: [
        [
          'Caisse USD',
          formatMoney(theoUsd),
          formatMoney(physUsd),
          {
            content: formatMoney(ecartUsd),
            styles: { textColor: ecartUsd < 0 ? [200, 0, 0] : [0, 0, 0], fontStyle: 'bold' },
          },
        ],
        [
          'Caisse CDF',
          formatMoneyCdf(theoCdf),
          formatMoneyCdf(physCdf),
          {
            content: formatMoneyCdf(ecartCdf),
            styles: { textColor: ecartCdf < 0 ? [200, 0, 0] : [0, 0, 0], fontStyle: 'bold' },
          },
        ],
      ],
      theme: 'striped',
      headStyles: { fillColor: [240, 240, 240], textColor: [0, 0, 0], fontStyle: 'bold' },
    })

    const finalY = (doc as any).lastAutoTable.finalY + 15
    doc.setFont('helvetica', 'bold')
    doc.text('Observations :', 14, finalY)
    doc.setFont('helvetica', 'normal')
    doc.text(data.observation || 'Aucune observation particulière.', 14, finalY + 7, { maxWidth: 180 })

    const signY = finalY + 40
    doc.setFontSize(9)
    doc.text('Le Caissier', 40, signY, { align: 'center' })
    doc.text('Le Secrétaire Exécutif', 160, signY, { align: 'center' })
    doc.setDrawColor(200)
    doc.rect(20, signY + 5, 50, 25)
    doc.rect(135, signY + 5, 50, 25)
  } else {
    const body = (data.details || []).map((s) => [
      s.reference_numero || '',
      s.beneficiaire || '',
      s.motif || '',
      formatMoney(toNumber(s.montant_paye || 0)),
    ])
    autoTable(doc, {
      startY: 55,
      head: [['N° PAY', 'Bénéficiaire', 'Motif', 'Montant']],
      body,
      foot: [['', '', 'TOTAL DÉCAISSÉ', formatMoney(toNumber(data.total || 0))]],
      theme: 'striped',
    })
  }

  if (options.save !== false) {
    doc.save(`PV_Cloture_${dateLabel.replace(/\//g, '-')}.pdf`)
  }
  if (options.returnBlob) {
    return doc.output('blob')
  }
}
