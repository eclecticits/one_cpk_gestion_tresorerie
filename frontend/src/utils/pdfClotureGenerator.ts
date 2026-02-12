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
  reference_numero?: string
  solde_initial_usd?: number | string
  total_entrees_usd?: number | string
  total_sorties_usd?: number | string
  solde_theorique_usd?: number | string
  solde_physique_usd?: number | string
  ecart_usd?: number | string
  solde_initial_cdf?: number | string
  total_entrees_cdf?: number | string
  total_sorties_cdf?: number | string
  solde_theorique_cdf?: number | string
  solde_physique_cdf?: number | string
  ecart_cdf?: number | string
  taux_change_applique?: number | string
  billetage_usd?: Record<string, number>
  billetage_cdf?: Record<string, number>
}

const formatMoney = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(value)

const formatMoneyCdf = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(value)

const formatDateValue = (value: string | Date) => {
  const parsed = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return format(parsed, 'yyyy-MM-dd')
}

export const generateCloturePDF = (
  data: ClotureReport,
  options: { save?: boolean; returnBlob?: boolean } = {}
) => {
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const dateLabel = formatDateValue(data.date)

  doc.setFont('times', 'bold')
  doc.setFontSize(16)
  doc.text('PROCÈS-VERBAL DE CLÔTURE DE CAISSE', pageWidth / 2, 20, { align: 'center' })

  doc.setFont('times', 'normal')
  doc.setFontSize(10)
  doc.text(`Date : ${dateLabel}`, 15, 30)
  doc.text(`Réf : ${data.reference_numero || `CLOT-${dateLabel.replace(/-/g, '')}`}`, 15, 35)

  const hasBalance =
    data.solde_theorique_usd !== undefined || data.solde_theorique_cdf !== undefined

  if (hasBalance) {
    const tauxChange = toNumber(data.taux_change_applique || 1)
    const soldeInitUsd = toNumber(data.solde_initial_usd || 0)
    const entreeUsd = toNumber(data.total_entrees_usd || 0)
    const sortieUsd = toNumber(data.total_sorties_usd || 0)
    const theoUsd = toNumber(data.solde_theorique_usd || 0)
    const physUsd = toNumber(data.solde_physique_usd || 0)
    const ecartUsd = toNumber(data.ecart_usd || 0)

    const soldeInitCdf = toNumber(data.solde_initial_cdf || 0)
    const entreeCdf = toNumber(data.total_entrees_cdf || 0)
    const sortieCdf = toNumber(data.total_sorties_cdf || 0)
    const theoCdf = toNumber(data.solde_theorique_cdf || 0)
    const physCdf = toNumber(data.solde_physique_cdf || 0)
    const ecartCdf = toNumber(data.ecart_cdf || 0)
    const physUsdEquiv = physUsd + (tauxChange > 0 ? physCdf / tauxChange : 0)

    autoTable(doc, {
      startY: 40,
      head: [['Bilan', 'USD', 'CDF']],
      body: [
        ['Taux de change', tauxChange.toFixed(2), ''],
        ['Solde initial', formatMoney(soldeInitUsd), formatMoneyCdf(soldeInitCdf)],
        ['Total entrées', formatMoney(entreeUsd), formatMoneyCdf(entreeCdf)],
        ['Total sorties', formatMoney(sortieUsd), formatMoneyCdf(sortieCdf)],
        ['Solde théorique', formatMoney(theoUsd), formatMoneyCdf(theoCdf)],
        ['Solde physique', formatMoney(physUsd), formatMoneyCdf(physCdf)],
        ['Solde physique (USD equiv.)', formatMoney(physUsdEquiv), ''],
      ],
      theme: 'striped',
    })

    const ecartY = (doc as any).lastAutoTable.finalY + 6
    doc.setFont('times', 'bold')
    doc.text('Écart de caisse', 15, ecartY)
    const ecartUsdLabel = formatMoney(ecartUsd)
    const ecartCdfLabel = formatMoneyCdf(ecartCdf)
    if (ecartUsd !== 0 || ecartCdf !== 0) {
      doc.setTextColor(185, 28, 28)
    }
    doc.setFont('times', 'normal')
    doc.text(`USD : ${ecartUsdLabel} | CDF : ${ecartCdfLabel}`, 15, ecartY + 5)
    doc.setTextColor(0, 0, 0)

    const billetageUsd = data.billetage_usd || {}
    const billetageCdf = data.billetage_cdf || {}
    const hasBilletage = Object.keys(billetageUsd).length > 0 || Object.keys(billetageCdf).length > 0
    if (hasBilletage) {
      const billetStart = ecartY + 10
      const usdRows = Object.entries(billetageUsd).map(([denom, qty]) => [
        `USD ${denom}`,
        String(qty),
        formatMoney(toNumber(denom) * Number(qty || 0)),
      ])
      const cdfRows = Object.entries(billetageCdf).map(([denom, qty]) => [
        `CDF ${denom}`,
        String(qty),
        formatMoneyCdf(toNumber(denom) * Number(qty || 0)),
      ])
      autoTable(doc, {
        startY: billetStart,
        head: [['Billetage', 'Qté', 'Total']],
        body: [...usdRows, ...cdfRows],
        theme: 'striped',
        styles: { fontSize: 8 },
      })
    }
  }

  const body = (data.details || []).map((s) => [
    s.reference_numero || '',
    s.beneficiaire || '',
    s.motif || '',
    formatMoney(toNumber(s.montant_paye || 0)),
  ])

  const tableStart = hasBalance ? (doc as any).lastAutoTable.finalY + 10 : 45
  autoTable(doc, {
    startY: tableStart,
    head: [['N° PAY', 'Bénéficiaire', 'Motif', 'Montant']],
    body,
    foot: [['', '', 'TOTAL DÉCAISSÉ', formatMoney(toNumber(data.total || 0))]],
    theme: 'striped',
  })

  const finalY = (doc as any).lastAutoTable.finalY + 16
  doc.setFont('times', 'normal')
  doc.text('Le Caissier', 30, finalY)
  doc.text('Le Superviseur / Trésorier', 130, finalY)

  if (options.save !== false) {
    doc.save(`Cloture_Caisse_${dateLabel}.pdf`)
  }
  if (options.returnBlob) {
    return doc.output('blob')
  }
}
