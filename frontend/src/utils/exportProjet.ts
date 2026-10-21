import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import type { MouvementsProjet, PeriodeProjet } from '../api/projetsActivites'
import { formatAmount, toNumber } from './amount'
import { drawTenantFooter, drawTenantHeader, loadTenantIdentity } from './pdfTenantIdentity'
import { createReportListSheet, createReportSummarySheet, jourExcel, telechargerClasseur } from './reportExcelStyles'

/**
 * Rapport d'un projet ou d'une activité : ce qui est entré, ce qui est sorti,
 * et ce qu'il reste, en PDF et en Excel. Les sorties restent par devise.
 */

type Rgb = [number, number, number]
type XlsxModule = typeof import('xlsx')

const MARGE = 12
const VERT: Rgb = [6, 95, 70]
const ROUGE: Rgb = [185, 28, 28]
const ENCRE: Rgb = [15, 23, 42]
const GRIS: Rgb = [100, 116, 139]
const BORDURE: Rgb = [226, 232, 240]
const FOND: Rgb = [248, 250, 252]

const MODES: Record<string, string> = { CAISSE: 'Caisse', BANQUE: 'Banque' }

const dateCourte = (valeur: string | null) => (valeur ? format(new Date(valeur), 'dd/MM/yyyy') : '—')
const jourFr = (iso?: string) => (iso ? format(new Date(`${iso}T00:00:00`), 'dd/MM/yyyy') : '')

export const libellePeriode = (periode: PeriodeProjet) => {
  if (periode.date_debut && periode.date_fin) return `du ${jourFr(periode.date_debut)} au ${jourFr(periode.date_fin)}`
  if (periode.date_debut) return `depuis le ${jourFr(periode.date_debut)}`
  if (periode.date_fin) return `jusqu'au ${jourFr(periode.date_fin)}`
  return 'toutes périodes'
}

const nomFichier = (m: MouvementsProjet, extension: string) =>
  `projet_${m.projet.code.replace(/[^\w-]+/g, '_')}_${format(new Date(), 'yyyy-MM-dd')}.${extension}`

/** « 1 200,00 USD · 350 000,00 CDF » : jamais d'addition entre devises. */
export const sortiesParDevise = (sorties: Record<string, string>) => {
  const devises = Object.keys(sorties).sort((a, b) => (a === 'USD' ? -1 : b === 'USD' ? 1 : a.localeCompare(b)))
  return devises.length ? devises.map((d) => `${formatAmount(sorties[d])} ${d}`).join(' · ') : `${formatAmount(0)} USD`
}

const finTableau = (doc: jsPDF, y: number): number => (doc as any).lastAutoTable?.finalY ?? y

const place = (doc: jsPDF, y: number, besoin: number) => {
  if (y + besoin <= doc.internal.pageSize.getHeight() - 20) return y
  doc.addPage()
  return 20
}

const titreSection = (doc: jsPDF, y: number, titre: string, complement: string) => {
  y = place(doc, y, 18)
  const largeur = doc.internal.pageSize.getWidth() - MARGE * 2
  doc.setFillColor(...VERT)
  doc.roundedRect(MARGE, y - 3.2, 1.4, 4.2, 0.7, 0.7, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9.5)
  doc.setTextColor(...ENCRE)
  doc.text(titre, MARGE + 3.5, y)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.setTextColor(...GRIS)
  doc.text(complement, MARGE + largeur, y, { align: 'right' })
  doc.setDrawColor(...BORDURE)
  doc.setLineWidth(0.3)
  doc.line(MARGE, y + 2.2, MARGE + largeur, y + 2.2)
  return y + 6
}

const styleTableau = (entete: Rgb) => ({
  theme: 'plain' as const,
  margin: { left: MARGE, right: MARGE },
  styles: {
    font: 'helvetica',
    fontSize: 8,
    cellPadding: 2,
    textColor: ENCRE,
    valign: 'middle' as const,
    lineColor: BORDURE,
    lineWidth: { bottom: 0.2 },
  },
  headStyles: { fillColor: entete, textColor: [255, 255, 255] as Rgb, fontStyle: 'bold' as const, fontSize: 7.5 },
  alternateRowStyles: { fillColor: FOND },
  footStyles: { fillColor: [241, 245, 249] as Rgb, textColor: ENCRE, fontStyle: 'bold' as const },
})

export async function exporterProjetPDF(m: MouvementsProjet, periode: PeriodeProjet, emisPar?: string | null) {
  const identity = await loadTenantIdentity()
  const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
  const largeur = doc.internal.pageSize.getWidth() - MARGE * 2
  const nature = m.projet.type === 'ACTIVITE' ? 'Activité' : 'Projet'

  let y = drawTenantHeader(doc, identity, {
    title: `Rapport ${nature.toLowerCase() === 'projet' ? 'du projet' : "de l'activité"}`,
    subtitle: `${m.projet.code} — ${m.projet.libelle} · ${libellePeriode(periode)}`,
  })

  // Trois tuiles : entrées, sorties, solde.
  const solde = toNumber(m.totaux.solde_usd)
  const tuiles: [string, string, Rgb][] = [
    ['Entrées', `${formatAmount(m.totaux.entrees_usd)} USD`, VERT],
    ['Sorties', sortiesParDevise(m.totaux.sorties), ROUGE],
    ['Solde (USD)', `${formatAmount(solde)} USD`, solde < 0 ? ROUGE : ENCRE],
  ]
  const lTuile = (largeur - 8) / 3
  tuiles.forEach(([libelle, valeur, couleur], i) => {
    const x = MARGE + i * (lTuile + 4)
    doc.setDrawColor(...BORDURE)
    doc.setLineWidth(0.3)
    doc.setFillColor(255, 255, 255)
    doc.roundedRect(x, y, lTuile, 19, 1.8, 1.8, 'FD')
    doc.setFillColor(...couleur)
    doc.rect(x, y + 3, 1.2, 13, 'F')
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(...GRIS)
    doc.text(libelle.toUpperCase(), x + 5, y + 6.5)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(valeur.length > 22 ? 9 : 12)
    doc.setTextColor(...couleur)
    doc.text(doc.splitTextToSize(valeur, lTuile - 8)[0] ?? '', x + 5, y + 14.5)
  })
  y += 25

  if (Object.keys(m.totaux.sorties).some((d) => d !== 'USD')) {
    doc.setFont('helvetica', 'italic')
    doc.setFontSize(7.5)
    doc.setTextColor(...GRIS)
    doc.text('Le solde ne tient compte que des sorties en USD ; les sorties en CDF sont présentées à part.', MARGE, y)
    y += 6
  }

  y = titreSection(doc, y + 2, 'Entrées', `${m.entrees.length} encaissement${m.entrees.length > 1 ? 's' : ''}`)
  autoTable(doc, {
    ...styleTableau(VERT),
    startY: y,
    head: [['Date', 'Reçu', 'Payeur', 'Canal', 'Perçu', 'Montant (USD)']],
    body: m.entrees.length
      ? m.entrees.map((e) => [
          dateCourte(e.date),
          e.numero || '—',
          e.tiers || '—',
          MODES[e.canal] || e.canal,
          `${formatAmount(e.montant_percu)} ${e.devise_perception}`,
          formatAmount(e.montant_usd),
        ])
      : [[{ content: 'Aucune entrée sur la période.', colSpan: 6, styles: { halign: 'center', textColor: GRIS } }]],
    foot: m.entrees.length
      ? [[{ content: 'Total des entrées', colSpan: 5, styles: { halign: 'right' } }, { content: formatAmount(m.totaux.entrees_usd), styles: { halign: 'right' } }]]
      : undefined,
    columnStyles: { 0: { cellWidth: 20 }, 1: { cellWidth: 26 }, 3: { cellWidth: 18 }, 4: { cellWidth: 30, halign: 'right' }, 5: { cellWidth: 28, halign: 'right', fontStyle: 'bold' } },
    didParseCell: (data) => {
      if (data.section === 'head' && data.column.index >= 4) data.cell.styles.halign = 'right'
    },
  })
  y = finTableau(doc, y) + 9

  y = titreSection(doc, y, 'Sorties', `${m.sorties.length} décaissement${m.sorties.length > 1 ? 's' : ''}`)
  autoTable(doc, {
    ...styleTableau([153, 27, 27]),
    startY: y,
    head: [['Date', 'Bon', 'Bénéficiaire · motif', 'Réquisition', 'Canal', 'Montant']],
    body: m.sorties.length
      ? m.sorties.map((s) => [
          dateCourte(s.date),
          s.numero || '—',
          [s.beneficiaire, s.motif].filter(Boolean).join('\n') || '—',
          s.requisition || 'Sortie directe',
          MODES[s.canal] || s.canal,
          `${formatAmount(s.montant)} ${s.devise}`,
        ])
      : [[{ content: 'Aucune sortie sur la période.', colSpan: 6, styles: { halign: 'center', textColor: GRIS } }]],
    foot: m.sorties.length
      ? [[
          { content: 'Total des sorties', colSpan: 5, styles: { halign: 'right' } },
          // Une ligne par devise : un total ne se coupe jamais au milieu d'un montant.
          { content: sortiesParDevise(m.totaux.sorties).split(' · ').join('\n'), styles: { halign: 'right' } },
        ]]
      : undefined,
    columnStyles: { 0: { cellWidth: 20 }, 1: { cellWidth: 26 }, 3: { cellWidth: 38 }, 4: { cellWidth: 16 }, 5: { cellWidth: 34, halign: 'right', fontStyle: 'bold' } },
    didParseCell: (data) => {
      if (data.section === 'head' && data.column.index === 5) data.cell.styles.halign = 'right'
    },
  })

  const pages = doc.getNumberOfPages()
  for (let page = 1; page <= pages; page += 1) {
    doc.setPage(page)
    drawTenantFooter(doc, identity, { pageNumber: page, pageCount: pages, generatedBy: emisPar })
  }
  doc.save(nomFichier(m, 'pdf'))
}

async function chargerXlsx(): Promise<XlsxModule> {
  const module = (await import('xlsx')) as XlsxModule & { default?: XlsxModule }
  return module.utils ? module : module.default || module
}

export async function exporterProjetExcel(m: MouvementsProjet, periode: PeriodeProjet) {
  const [XLSX, identity] = await Promise.all([chargerXlsx(), loadTenantIdentity()])
  const organisation = identity.orgName
  const titre = `${m.projet.code} — ${m.projet.libelle}`.toUpperCase()
  const sousTitre = `${m.projet.type === 'ACTIVITE' ? 'Activité' : 'Projet'} · ${libellePeriode(periode)}`
  const wb = XLSX.utils.book_new()

  const devises = Object.keys(m.totaux.sorties).sort((a, b) => (a === 'USD' ? -1 : b === 'USD' ? 1 : a.localeCompare(b)))
  XLSX.utils.book_append_sheet(
    wb,
    createReportSummarySheet(XLSX, {
      title: titre,
      organisation,
      subtitle: sousTitre,
      items: [
        { label: 'Entrées (USD)', value: toNumber(m.totaux.entrees_usd), format: 'money', tone: 'positive' },
        ...(devises.length ? devises : ['USD']).map((d) => ({
          label: `Sorties (${d})`,
          value: toNumber(m.totaux.sorties[d] ?? 0),
          format: 'money' as const,
          tone: 'negative' as const,
        })),
        { label: 'Solde (USD)', value: toNumber(m.totaux.solde_usd), format: 'money', tone: 'accent' },
        { label: 'Encaissements', value: m.entrees.length, format: 'integer' },
        { label: 'Décaissements', value: m.sorties.length, format: 'integer' },
      ],
      notice: devises.some((d) => d !== 'USD')
        ? 'Le solde ne tient compte que des sorties en USD ; les sorties en CDF sont présentées à part.'
        : undefined,
    }),
    'Synthèse',
  )

  XLSX.utils.book_append_sheet(
    wb,
    createReportListSheet(XLSX, {
      title: 'ENTRÉES',
      organisation,
      subtitle: `${titre} · ${libellePeriode(periode)}`,
      headers: ['Date', 'Reçu', 'Payeur', 'Canal', 'Montant perçu', 'Devise perçue', 'Montant (USD)'],
      rows: m.entrees.map((e) => [
        jourExcel(e.date),
        e.numero || '',
        e.tiers || '',
        MODES[e.canal] || e.canal,
        toNumber(e.montant_percu),
        e.devise_perception,
        toNumber(e.montant_usd),
      ]),
      widths: [12, 18, 36, 10, 16, 10, 16],
      moneyColumns: [4, 6],
      dateColumns: [0],
      centerColumns: [3, 5],
      footerRow: ['TOTAL', '', '', '', '', '', toNumber(m.totaux.entrees_usd)],
    }),
    'Entrées',
  )

  XLSX.utils.book_append_sheet(
    wb,
    createReportListSheet(XLSX, {
      title: 'SORTIES',
      organisation,
      subtitle: `${titre} · ${libellePeriode(periode)}`,
      headers: ['Date', 'Bon', 'Bénéficiaire', 'Motif', 'Réquisition', 'Canal', 'Montant', 'Devise'],
      rows: m.sorties.map((s) => [
        jourExcel(s.date),
        s.numero || '',
        s.beneficiaire || '',
        s.motif || '',
        s.requisition || 'Sortie directe',
        MODES[s.canal] || s.canal,
        toNumber(s.montant),
        s.devise,
      ]),
      widths: [12, 18, 28, 40, 20, 10, 16, 8],
      moneyColumns: [6],
      dateColumns: [0],
      centerColumns: [5, 7],
      wrapColumns: [3],
    }),
    'Sorties',
  )

  telechargerClasseur(XLSX, wb, nomFichier(m, 'xlsx'))
}
