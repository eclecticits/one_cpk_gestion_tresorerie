import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { formatAmount, toNumber } from './amount'
import {
  drawTenantFooter,
  drawTenantHeader,
  loadTenantIdentity,
} from './pdfTenantIdentity'

type ClotureReport = {
  organisation_name?: string
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
  billetage_usd?: Record<string, number | string> | null
  billetage_cdf?: Record<string, number | string> | null
  observation?: string | null
}

const formatNumber = (value: number) => formatAmount(value)

const formatMoney = (value: number) => `${formatNumber(value)} USD`

const formatMoneyCdf = (value: number) => `${formatNumber(value)} CDF`

const billetageRows = (data: ClotureReport) => {
  const rows: (string | number)[][] = []
  const addCurrency = (
    devise: 'USD' | 'CDF',
    billetage: Record<string, number | string> | null | undefined,
  ) => {
    if (billetage == null) return
    // « autres » : montant compté hors des coupures listées, pas une coupure.
    const autres = Number(billetage.autres || 0)
    const entries = Object.entries(billetage)
      .filter(([valeur]) => valeur !== 'autres')
      .map(([valeur, quantite]) => ({ valeur: Number(valeur), quantite: Number(quantite) }))
      .filter((entry) => Number.isFinite(entry.valeur) && entry.valeur > 0 && entry.quantite > 0)
      .sort((a, b) => b.valeur - a.valeur)

    const format = devise === 'USD' ? formatMoney : formatMoneyCdf
    if (entries.length === 0 && !(autres > 0)) {
      rows.push([devise, 'Aucune coupure', 0, format(0)])
      return
    }
    entries.forEach(({ valeur, quantite }) => {
      rows.push([devise, format(valeur), quantite, format(valeur * quantite)])
    })
    if (autres > 0) rows.push([devise, 'Autres (voir observation)', '—', format(autres)])
  }

  addCurrency('USD', data.billetage_usd)
  addCurrency('CDF', data.billetage_cdf)
  return rows
}

const formatDateValue = (value: string | Date) => {
  const parsed = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return parsed.toLocaleDateString('fr-FR')
}

export const generateCloturePDF = async (
  data: ClotureReport,
  options: { save?: boolean; returnBlob?: boolean } = {}
) => {
  // Identité de l'organisation émettrice : aucun document ne sort sans elle.
  // `data.organisation_name` n'était pas renseigné par l'appelant, le PV
  // retombait donc sur un « ONEC » générique, identique pour tous les tenants.
  const identity = await loadTenantIdentity()
  if (data.organisation_name) {
    identity.orgName = String(data.organisation_name).trim() || identity.orgName
  }

  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const dateLabel = formatDateValue(data.date)
  const reference = data.reference_numero || `PVC-${dateLabel.replace(/\//g, '-')}`
  const hasBalance =
    data.solde_theorique_usd !== undefined ||
    data.solde_theorique_cdf !== undefined ||
    data.solde_physique_usd !== undefined ||
    data.solde_physique_cdf !== undefined

  const headerBottom = drawTenantHeader(doc, identity, {
    title: hasBalance ? "Procès-verbal d'arrêté de caisse" : 'Rapport journalier des sorties',
    subtitle: `Référence ${reference}  •  Clôture du ${dateLabel}  •  Caissier : ${data.caissier_nom || '—'}`,
  })
  const infoBottom = headerBottom + 4

  if (hasBalance) {
    const theoUsd = toNumber(data.solde_theorique_usd || 0)
    const physUsd = toNumber(data.solde_physique_usd || 0)
    const ecartUsd = toNumber(data.ecart_usd || 0)
    const theoCdf = toNumber(data.solde_theorique_cdf || 0)
    const physCdf = toNumber(data.solde_physique_cdf || 0)
    const ecartCdf = toNumber(data.ecart_cdf || 0)

    autoTable(doc, {
      startY: infoBottom,
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

    let finalY = (doc as any).lastAutoTable.finalY + 10
    const rows = billetageRows(data)
    if (rows.length > 0) {
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(11)
      doc.text('Détail du billetage', 14, finalY)
      autoTable(doc, {
        startY: finalY + 3,
        head: [['Devise', 'Coupure', 'Quantité', 'Sous-total']],
        body: rows,
        theme: 'grid',
        headStyles: { fillColor: [30, 64, 175], textColor: [255, 255, 255], fontStyle: 'bold' },
        columnStyles: {
          2: { halign: 'right' },
          3: { halign: 'right' },
        },
        styles: { fontSize: 8.5, cellPadding: 2.2 },
      })
      finalY = (doc as any).lastAutoTable.finalY + 10
    } else {
      finalY += 5
    }
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
      startY: infoBottom,
      head: [['N° PAY', 'Bénéficiaire', 'Motif', 'Montant']],
      body,
      foot: [['', '', 'TOTAL DÉCAISSÉ', formatMoney(toNumber(data.total || 0))]],
      theme: 'striped',
    })
  }

  const pageCount = doc.getNumberOfPages()
  for (let page = 1; page <= pageCount; page += 1) {
    doc.setPage(page)
    drawTenantFooter(doc, identity, {
      pageNumber: page,
      pageCount,
      generatedBy: data.caissier_nom,
    })
  }

  if (options.save !== false) {
    const safeOrg = String(identity.orgName || 'organisation').replace(/[^\w\-]+/g, '_')
    doc.save(`PV_Cloture_${safeOrg}_${dateLabel.replace(/\//g, '-')}.pdf`)
  }
  if (options.returnBlob) {
    return doc.output('blob')
  }
}
