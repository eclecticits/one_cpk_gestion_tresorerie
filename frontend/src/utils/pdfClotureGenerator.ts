import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import type { CloturePdfData, CloturePdfDetail, CloturePdfEntree, CloturePdfRegularisation } from '../api/clotures'
import { formatAmount, toNumber } from './amount'
import {
  drawTenantFooter,
  drawTenantHeader,
  loadTenantIdentity,
} from './pdfTenantIdentity'

type Montant = number | string | null | undefined

type ClotureReport = {
  organisation_name?: string
  date: string | Date
  date_debut?: string | Date | null
  reference_numero?: string
  caissier_nom?: string | null
  solde_initial_usd?: Montant
  solde_initial_cdf?: Montant
  total_entrees_usd?: Montant
  total_entrees_cdf?: Montant
  total_sorties_usd?: Montant
  total_sorties_cdf?: Montant
  solde_theorique_usd?: Montant
  solde_physique_usd?: Montant
  ecart_usd?: Montant
  solde_theorique_cdf?: Montant
  solde_physique_cdf?: Montant
  ecart_cdf?: Montant
  billetage_usd?: Record<string, number | string> | null
  billetage_cdf?: Record<string, number | string> | null
  observation?: string | null
  entrees?: CloturePdfEntree[]
  sorties?: CloturePdfDetail[]
  regularisations?: CloturePdfRegularisation[]
}

// Un seul passage de la clôture au PV : le tableau de bord et l'écran de clôture
// impriment ainsi exactement le même document.
export const clotureDataToReport = (data: CloturePdfData): ClotureReport => ({
  date: data.cloture.date_cloture,
  date_debut: data.cloture.date_debut,
  reference_numero: data.cloture.reference_numero,
  caissier_nom: data.caissier_nom,
  solde_initial_usd: data.cloture.solde_initial_usd,
  solde_initial_cdf: data.cloture.solde_initial_cdf,
  total_entrees_usd: data.cloture.total_entrees_usd,
  total_entrees_cdf: data.cloture.total_entrees_cdf,
  total_sorties_usd: data.cloture.total_sorties_usd,
  total_sorties_cdf: data.cloture.total_sorties_cdf,
  solde_theorique_usd: data.cloture.solde_theorique_usd,
  solde_physique_usd: data.cloture.solde_physique_usd,
  ecart_usd: data.cloture.ecart_usd,
  solde_theorique_cdf: data.cloture.solde_theorique_cdf,
  solde_physique_cdf: data.cloture.solde_physique_cdf,
  ecart_cdf: data.cloture.ecart_cdf,
  billetage_usd: data.cloture.billetage_usd,
  billetage_cdf: data.cloture.billetage_cdf,
  observation: data.cloture.observation,
  entrees: data.entrees,
  sorties: data.details,
  regularisations: data.regularisations,
})

const formatNumber = (value: number) => formatAmount(value)

const formatMoney = (value: number) => `${formatNumber(value)} USD`

const formatMoneyCdf = (value: number) => `${formatNumber(value)} CDF`

const formatDevise = (value: number, devise: string) => `${formatNumber(value)} ${devise}`

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

const formatDateHeure = (value: string | Date | null | undefined) => {
  if (!value) return '—'
  const parsed = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return format(parsed, 'dd/MM/yyyy HH:mm')
}

const MARGE_BAS = 20
const DEVISES = ['USD', 'CDF'] as const

// Total imprimé pour chaque devise, et écart éventuel avec le total figé à la
// clôture : une opération antidatée après coup entre dans le détail mais pas
// dans le total signé, et le document doit le dire plutôt que de le masquer.
const totauxParDevise = (lignes: { montant: number; devise: string }[], figes: Record<string, number>) => {
  const devises = DEVISES.filter((devise) => figes[devise] !== 0 || lignes.some((l) => l.devise === devise))
  const totaux = devises.map((devise) => ({
    devise,
    total: lignes.filter((l) => l.devise === devise).reduce((somme, l) => somme + l.montant, 0),
  }))
  const ecarts = devises.filter((devise) => {
    const ligne = totaux.find((t) => t.devise === devise)
    return Math.abs((ligne?.total ?? 0) - figes[devise]) >= 0.01
  })
  return { totaux, ecarts }
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
  const pageHeight = doc.internal.pageSize.getHeight()
  const dateLabel = formatDateValue(data.date)
  const reference = data.reference_numero || `PVC-${dateLabel.replace(/\//g, '-')}`
  const periode = data.date_debut
    ? `Période du ${formatDateHeure(data.date_debut)} au ${formatDateHeure(data.date)}`
    : `Période jusqu'au ${formatDateHeure(data.date)}`

  const headerBottom = drawTenantHeader(doc, identity, {
    title: "Procès-verbal d'arrêté de caisse",
    subtitle: `Référence ${reference}  •  Clôture du ${dateLabel}  •  Caissier : ${data.caissier_nom || '—'}`,
  })

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(71, 85, 105)
  doc.text(periode, 14, headerBottom + 5)
  doc.setTextColor(0, 0, 0)

  const ligneSituation = (
    libelle: string,
    fmt: (value: number) => string,
    initial: Montant,
    entrees: Montant,
    sorties: Montant,
    theorique: Montant,
    physique: Montant,
    ecart: Montant,
  ) => {
    const valeurEcart = toNumber(ecart || 0)
    return [
      libelle,
      fmt(toNumber(initial || 0)),
      fmt(toNumber(entrees || 0)),
      fmt(toNumber(sorties || 0)),
      fmt(toNumber(theorique || 0)),
      fmt(toNumber(physique || 0)),
      {
        content: fmt(valeurEcart),
        styles: { textColor: (valeurEcart < 0 ? [200, 0, 0] : [0, 0, 0]) as [number, number, number], fontStyle: 'bold' as const },
      },
    ]
  }

  autoTable(doc, {
    startY: headerBottom + 8,
    head: [['Désignation', 'Solde initial', 'Entrées', 'Sorties', 'Solde Théorique (Logiciel)', 'Solde Physique (Compté)', 'Écart']],
    body: [
      ligneSituation('Caisse USD', formatMoney, data.solde_initial_usd, data.total_entrees_usd, data.total_sorties_usd, data.solde_theorique_usd, data.solde_physique_usd, data.ecart_usd),
      ligneSituation('Caisse CDF', formatMoneyCdf, data.solde_initial_cdf, data.total_entrees_cdf, data.total_sorties_cdf, data.solde_theorique_cdf, data.solde_physique_cdf, data.ecart_cdf),
    ],
    theme: 'striped',
    headStyles: { fillColor: [240, 240, 240], textColor: [0, 0, 0], fontStyle: 'bold' },
    styles: { fontSize: 8, cellPadding: 2 },
    columnStyles: {
      1: { halign: 'right' },
      2: { halign: 'right' },
      3: { halign: 'right' },
      4: { halign: 'right' },
      5: { halign: 'right' },
      6: { halign: 'right' },
    },
    margin: { left: 14, right: 14, bottom: MARGE_BAS },
  })

  let finalY = (doc as any).lastAutoTable.finalY + 8

  const ensureSpace = (hauteur: number) => {
    if (finalY + hauteur > pageHeight - MARGE_BAS) {
      doc.addPage()
      finalY = 18
    }
  }

  const titreSection = (titre: string) => {
    ensureSpace(20)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11)
    doc.text(titre, 14, finalY)
  }

  const noteEcart = (ecarts: string[], libelle: string) => {
    if (ecarts.length === 0) return
    const note = doc.splitTextToSize(
      `Attention : le détail ci-dessus ne totalise pas les ${libelle} figées à la clôture (${ecarts.join(', ')}). Une opération a été saisie ou modifiée sur la période après la clôture.`,
      182,
    )
    ensureSpace(note.length * 4 + 2)
    doc.setFont('helvetica', 'italic')
    doc.setFontSize(8.5)
    doc.setTextColor(200, 0, 0)
    doc.text(note, 14, finalY)
    doc.setTextColor(0, 0, 0)
    finalY += note.length * 4 + 4
  }

  const sectionOperations = (
    titre: string,
    tiersEntete: string,
    libelleVide: string,
    libelleTotal: string,
    libelleEcart: string,
    lignes: { date?: string | null; reference: string; tiers: string; motif: string; montant: number; devise: string }[],
    figes: Record<string, number>,
  ) => {
    titreSection(titre)
    const { totaux, ecarts } = totauxParDevise(lignes, figes)
    autoTable(doc, {
      startY: finalY + 3,
      head: [['Date', 'N°', tiersEntete, 'Motif', 'Montant']],
      body: lignes.length > 0
        ? lignes.map((l) => [formatDateHeure(l.date), l.reference, l.tiers, l.motif, formatDevise(l.montant, l.devise)])
        : [[{ content: libelleVide, colSpan: 5, styles: { halign: 'center', textColor: [100, 116, 139] } }]],
      foot: totaux.map((t) => [
        { content: `${libelleTotal} ${t.devise}`, colSpan: 4, styles: { halign: 'right' } },
        { content: formatDevise(t.total, t.devise), styles: { halign: 'right' } },
      ]),
      showFoot: 'lastPage',
      theme: 'grid',
      headStyles: { fillColor: [30, 64, 175], textColor: [255, 255, 255], fontStyle: 'bold' },
      footStyles: { fillColor: [241, 245, 249], textColor: [0, 0, 0], fontStyle: 'bold' },
      styles: { fontSize: 8, cellPadding: 1.8, overflow: 'linebreak' },
      columnStyles: {
        0: { cellWidth: 26 },
        1: { cellWidth: 28 },
        4: { cellWidth: 30, halign: 'right' },
      },
      margin: { left: 14, right: 14, bottom: MARGE_BAS },
    })
    finalY = (doc as any).lastAutoTable.finalY + 6
    noteEcart(ecarts, libelleEcart)
    finalY += 2
  }

  sectionOperations(
    'Détail des entrées',
    'Origine',
    'Aucune entrée sur la période.',
    'Total entrées',
    'entrées',
    (data.entrees || []).map((e) => ({
      date: e.date,
      reference: e.reference_numero || '',
      tiers: [e.nature, e.tiers].filter(Boolean).join(' - '),
      motif: e.motif || '',
      montant: toNumber(e.montant || 0),
      devise: (e.devise || 'USD').toUpperCase(),
    })),
    { USD: toNumber(data.total_entrees_usd || 0), CDF: toNumber(data.total_entrees_cdf || 0) },
  )

  sectionOperations(
    'Détail des sorties',
    'Bénéficiaire',
    'Aucune sortie sur la période.',
    'Total sorties',
    'sorties',
    (data.sorties || []).map((s) => ({
      date: s.date,
      reference: s.reference_numero || '',
      tiers: s.beneficiaire || '',
      motif: s.motif || '',
      montant: toNumber(s.montant_paye || 0),
      devise: (s.devise || 'USD').toUpperCase(),
    })),
    { USD: toNumber(data.total_sorties_usd || 0), CDF: toNumber(data.total_sorties_cdf || 0) },
  )

  if (data.regularisations && data.regularisations.length > 0) {
    titreSection("Régularisation de l'écart")
    autoTable(doc, {
      startY: finalY + 3,
      head: [['Sens', 'Motif', 'Montant']],
      body: data.regularisations.map((r) => [
        r.sens === 'EXCEDENT' ? 'Excédent' : 'Déficit',
        r.motif || '',
        formatDevise(toNumber(r.montant || 0), r.devise),
      ]),
      theme: 'grid',
      headStyles: { fillColor: [30, 64, 175], textColor: [255, 255, 255], fontStyle: 'bold' },
      styles: { fontSize: 8, cellPadding: 1.8 },
      columnStyles: { 0: { cellWidth: 26 }, 2: { cellWidth: 30, halign: 'right' } },
      margin: { left: 14, right: 14, bottom: MARGE_BAS },
    })
    finalY = (doc as any).lastAutoTable.finalY + 8
  }

  const rows = billetageRows(data)
  if (rows.length > 0) {
    titreSection('Détail du billetage')
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
      margin: { left: 14, right: 14, bottom: MARGE_BAS },
    })
    finalY = (doc as any).lastAutoTable.finalY + 8
  }

  // Observation et signatures restent ensemble : une page de signatures seule
  // ne prouve rien de ce qu'elle signe.
  const observation = doc.splitTextToSize(data.observation || 'Aucune observation particulière.', 180)
  ensureSpace(observation.length * 5 + 52)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.text('Observations :', 14, finalY)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(10)
  doc.text(observation, 14, finalY + 6)

  const signY = finalY + 6 + observation.length * 5 + 6
  doc.setFontSize(9)
  doc.text('Le Caissier', 45, signY, { align: 'center' })
  doc.text('Le Secrétaire Exécutif', 160, signY, { align: 'center' })
  doc.setDrawColor(200)
  doc.rect(20, signY + 3, 50, 25)
  doc.rect(135, signY + 3, 50, 25)

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
