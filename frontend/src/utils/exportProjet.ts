import { jsPDF } from 'jspdf'
import { autoTable } from 'jspdf-autotable'
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
const MARGE_HAUT_PAGE_SUIVANTE = 22
const MARGE_BAS = 20
const VERT: Rgb = [6, 95, 70]
const VERT_PALE: Rgb = [236, 253, 245]
const ROUGE: Rgb = [185, 28, 28]
const ROUGE_PALE: Rgb = [254, 242, 242]
const AMBRE: Rgb = [180, 83, 9]
const AMBRE_PALE: Rgb = [255, 251, 235]
const ENCRE: Rgb = [15, 23, 42]
const GRIS: Rgb = [100, 116, 139]
const BORDURE: Rgb = [226, 232, 240]
const FOND: Rgb = [248, 250, 252]

const MODES: Record<string, string> = { CAISSE: 'Caisse', BANQUE: 'Banque' }

const dateCourte = (valeur: string | null) => (valeur ? format(new Date(valeur), 'dd/MM/yyyy') : '—')
const jourFr = (iso?: string) => (iso ? format(new Date(`${iso}T00:00:00`), 'dd/MM/yyyy') : '')

const libelleDates = (periode: PeriodeProjet) => {
  if (periode.date_debut && periode.date_fin) return `du ${jourFr(periode.date_debut)} au ${jourFr(periode.date_fin)}`
  if (periode.date_debut) return `depuis le ${jourFr(periode.date_debut)}`
  if (periode.date_fin) return `jusqu'au ${jourFr(periode.date_fin)}`
  return 'toutes périodes'
}

/** « du 01/01/2026 au 29/10/2026 », suivi du filtre s'il y en a un : un
 * export filtré doit le dire, sinon ses totaux passent pour ceux du projet. */
export const libellePeriode = (periode: PeriodeProjet) =>
  periode.filtre?.trim() ? `${libelleDates(periode)} · filtre « ${periode.filtre.trim()} »` : libelleDates(periode)

const nomFichier = (m: MouvementsProjet, extension: string) =>
  `projet_${m.projet.code.replace(/[^\w-]+/g, '_')}_${format(new Date(), 'yyyy-MM-dd')}.${extension}`

/** « 1 200,00 USD · 350 000,00 CDF » : jamais d'addition entre devises. */
export const sortiesParDevise = (sorties: Record<string, string>) => {
  const devises = Object.keys(sorties).sort((a, b) => (a === 'USD' ? -1 : b === 'USD' ? 1 : a.localeCompare(b)))
  return devises.length ? devises.map((d) => `${formatAmount(sorties[d])} ${d}`).join(' · ') : `${formatAmount(0)} USD`
}

const finTableau = (doc: jsPDF, y: number): number => (doc as any).lastAutoTable?.finalY ?? y

const place = (doc: jsPDF, y: number, besoin: number) => {
  if (y + besoin <= doc.internal.pageSize.getHeight() - MARGE_BAS) return y
  doc.addPage()
  return MARGE_HAUT_PAGE_SUIVANTE
}

const titreSection = (doc: jsPDF, y: number, titre: string, complement: string, ton: 'vert' | 'rouge') => {
  // Réserve le titre, l'en-tête du tableau et sa première ligne pour éviter un
  // titre orphelin en bas de page.
  y = place(doc, y, 28)
  const largeur = doc.internal.pageSize.getWidth() - MARGE * 2
  const accent = ton === 'rouge' ? ROUGE : VERT
  const fond = ton === 'rouge' ? ROUGE_PALE : VERT_PALE
  doc.setFillColor(...fond)
  doc.roundedRect(MARGE, y, largeur, 9, 2, 2, 'F')
  doc.setFillColor(...accent)
  doc.roundedRect(MARGE, y, 2.2, 9, 1.1, 1.1, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9.2)
  doc.setTextColor(...accent)
  doc.text(titre.toUpperCase(), MARGE + 5, y + 5.8)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.8)
  doc.setTextColor(...GRIS)
  doc.text(complement, MARGE + largeur - 4, y + 5.8, { align: 'right' })
  return y + 13
}

const styleTableau = (entete: Rgb) => ({
  theme: 'grid' as const,
  showHead: 'everyPage' as const,
  showFoot: 'lastPage' as const,
  rowPageBreak: 'avoid' as const,
  margin: { left: MARGE, right: MARGE, top: MARGE_HAUT_PAGE_SUIVANTE, bottom: MARGE_BAS },
  styles: {
    font: 'helvetica',
    fontSize: 7.7,
    cellPadding: { top: 2.3, right: 2.1, bottom: 2.3, left: 2.1 },
    textColor: ENCRE,
    valign: 'middle' as const,
    lineColor: BORDURE,
    lineWidth: 0.12,
    overflow: 'linebreak' as const,
    minCellHeight: 7,
  },
  headStyles: {
    fillColor: entete,
    textColor: [255, 255, 255] as Rgb,
    fontStyle: 'bold' as const,
    fontSize: 7.8,
    minCellHeight: 8,
  },
  alternateRowStyles: { fillColor: FOND },
  footStyles: {
    fillColor: [241, 245, 249] as Rgb,
    textColor: ENCRE,
    fontStyle: 'bold' as const,
    fontSize: 8,
    minCellHeight: 8,
  },
})

const pluriel = (nombre: number, singulier: string, plurielValeur = `${singulier}s`) =>
  `${nombre} ${nombre > 1 ? plurielValeur : singulier}`

const lignesLimitees = (doc: jsPDF, texte: string, largeur: number, maximum: number): string[] => {
  const lignes = doc.splitTextToSize(texte, largeur) as string[]
  if (lignes.length <= maximum) return lignes
  const resultat = lignes.slice(0, maximum)
  let derniere = resultat[maximum - 1].replace(/\s+$/, '')
  while (derniere && doc.getTextWidth(`${derniere}…`) > largeur) derniere = derniere.slice(0, -1)
  resultat[maximum - 1] = `${derniere.replace(/[\s,;:.—-]+$/, '')}…`
  return resultat
}

const drawCarteSynthese = (
  doc: jsPDF,
  x: number,
  y: number,
  largeur: number,
  libelle: string,
  valeur: string,
  couleur: Rgb,
  detail?: string,
) => {
  doc.setDrawColor(...BORDURE)
  doc.setLineWidth(0.25)
  doc.setFillColor(255, 255, 255)
  doc.roundedRect(x, y, largeur, 22, 2, 2, 'FD')
  doc.setFillColor(...couleur)
  doc.roundedRect(x, y, 2.2, 22, 1.1, 1.1, 'F')

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7)
  doc.setTextColor(...GRIS)
  doc.text(libelle.toUpperCase(), x + 6, y + 6.2)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(valeur.length > 22 ? 10 : 12.5)
  doc.setTextColor(...couleur)
  doc.text(valeur, x + 6, y + 14.2)

  if (detail) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(6.8)
    doc.setTextColor(...GRIS)
    doc.text(detail, x + 6, y + 19)
  }
}

const drawEnteteSuite = (doc: jsPDF, m: MouvementsProjet, periode: PeriodeProjet) => {
  const pageWidth = doc.internal.pageSize.getWidth()
  doc.setFillColor(...FOND)
  doc.rect(0, 0, pageWidth, 18, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.setTextColor(...VERT)
  doc.text(`RAPPORT FINANCIER · ${m.projet.code}`, MARGE, 9)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(...GRIS)
  const projet = lignesLimitees(doc, m.projet.libelle, pageWidth * 0.42, 1)[0] ?? m.projet.libelle
  doc.text(projet, MARGE, 13.2)
  doc.text(libellePeriode(periode), pageWidth - MARGE, 11, { align: 'right' })
  doc.setDrawColor(...BORDURE)
  doc.setLineWidth(0.3)
  doc.line(MARGE, 17, pageWidth - MARGE, 17)
}

const drawEtatVide = (doc: jsPDF, y: number, message: string, detail: string): number => {
  y = place(doc, y, 25)
  const largeur = doc.internal.pageSize.getWidth() - MARGE * 2
  doc.setFillColor(...FOND)
  doc.setDrawColor(...BORDURE)
  doc.setLineWidth(0.25)
  doc.roundedRect(MARGE, y, largeur, 20, 2, 2, 'FD')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9)
  doc.setTextColor(...ENCRE)
  doc.text(message, MARGE + largeur / 2, y + 8, { align: 'center' })
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(...GRIS)
  doc.text(detail, MARGE + largeur / 2, y + 13.7, { align: 'center' })
  return y + 27
}

/** Construit le PDF sans le télécharger, afin que le rendu puisse être vérifié séparément. */
export function construireRapportProjet(
  m: MouvementsProjet,
  periode: PeriodeProjet,
  identity: Awaited<ReturnType<typeof loadTenantIdentity>>,
  emisPar?: string | null,
): jsPDF {
  // Les deux journaux comportent des colonnes textuelles et monétaires : le
  // paysage évite les césures agressives observées dans l'ancien portrait.
  const doc = new jsPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' })
  const largeur = doc.internal.pageSize.getWidth() - MARGE * 2
  const nature = m.projet.type === 'ACTIVITE' ? 'Activité' : 'Projet'
  doc.setProperties({
    title: `Rapport ${nature.toLowerCase()} ${m.projet.code}`,
    subject: `Mouvements ${libellePeriode(periode)}`,
    author: identity.orgName,
    creator: 'ONEC Smart',
    keywords: `projet, activité, encaissements, décaissements, ${m.projet.code}`,
  })

  let y = drawTenantHeader(doc, identity, {
    title: `Rapport financier ${nature === 'Projet' ? 'du projet' : "de l'activité"}`,
    subtitle: `${nature} · code ${m.projet.code}`,
  })

  // Le libellé complet vit dans un cartouche borné : même un intitulé à la
  // longueur maximale du formulaire ne déborde plus de la page.
  const largeurProjet = largeur * 0.68
  const lignesProjet = lignesLimitees(doc, m.projet.libelle, largeurProjet - 10, 3)
  const hauteurCartouche = Math.max(22, 11 + lignesProjet.length * 4)
  doc.setDrawColor(...BORDURE)
  doc.setFillColor(...FOND)
  doc.setLineWidth(0.25)
  doc.roundedRect(MARGE, y, largeur, hauteurCartouche, 2, 2, 'FD')
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(6.8)
  doc.setTextColor(...GRIS)
  doc.text(nature.toUpperCase(), MARGE + 5, y + 5)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9.2)
  doc.setTextColor(...ENCRE)
  doc.text(lignesProjet, MARGE + 5, y + 10)
  const separateurX = MARGE + largeurProjet
  doc.setDrawColor(...BORDURE)
  doc.line(separateurX, y + 4, separateurX, y + hauteurCartouche - 4)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(6.8)
  doc.setTextColor(...GRIS)
  doc.text('PÉRIODE ANALYSÉE', separateurX + 5, y + 5)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8.8)
  doc.setTextColor(...ENCRE)
  doc.text(libellePeriode(periode), separateurX + 5, y + 10)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.4)
  doc.setTextColor(...GRIS)
  doc.text(
    `${pluriel(m.entrees.length, 'encaissement')} · ${pluriel(m.sorties.length, 'décaissement')}`,
    separateurX + 5,
    y + 15.3,
  )
  y += hauteurCartouche + 6

  // Synthèse de lecture : l'USD reste comparable, les autres devises sont
  // présentées séparément et ne peuvent plus être tronquées dans une tuile.
  const solde = toNumber(m.totaux.solde_usd)
  const sortiesUsd = Object.entries(m.totaux.sorties).reduce(
    (total, [devise, montant]) => total + (devise.toUpperCase() === 'USD' ? toNumber(montant) : 0),
    0,
  )
  const tuiles: [string, string, Rgb, string?][] = [
    ['Entrées', `${formatAmount(m.totaux.entrees_usd)} USD`, VERT, pluriel(m.entrees.length, 'opération')],
    ['Sorties', `${formatAmount(sortiesUsd)} USD`, ROUGE, pluriel(m.sorties.filter((s) => s.devise.toUpperCase() === 'USD').length, 'opération')],
    ['Solde', `${formatAmount(solde)} USD`, solde < 0 ? ROUGE : solde > 0 ? VERT : ENCRE, 'Entrées moins sorties en USD'],
    ['Mouvements', String(m.entrees.length + m.sorties.length), ENCRE, `${m.entrees.length} entrée${m.entrees.length > 1 ? 's' : ''} · ${m.sorties.length} sortie${m.sorties.length > 1 ? 's' : ''}`],
  ]
  const lTuile = (largeur - 12) / 4
  tuiles.forEach(([libelle, valeur, couleur, detail], i) => {
    drawCarteSynthese(doc, MARGE + i * (lTuile + 4), y, lTuile, libelle, valeur, couleur, detail)
  })
  y += 28

  const autresDevises = Object.keys(m.totaux.sorties)
    .filter((devise) => devise.toUpperCase() !== 'USD')
    .sort((a, b) => a.localeCompare(b))
  if (autresDevises.length > 0) {
    const texteDevises = autresDevises.map((devise) => `${formatAmount(m.totaux.sorties[devise])} ${devise}`).join('   ·   ')
    const lignesDevises = doc.splitTextToSize(texteDevises, largeur * 0.52) as string[]
    const note = 'Ces montants ne sont pas convertis et ne sont donc pas intégrés au solde en USD.'
    const lignesNote = doc.splitTextToSize(note, largeur * 0.38) as string[]
    const hauteurBande = Math.max(13, 7 + Math.max(lignesDevises.length, lignesNote.length) * 3.6)
    doc.setFillColor(...AMBRE_PALE)
    doc.setDrawColor(253, 230, 138)
    doc.roundedRect(MARGE, y, largeur, hauteurBande, 2, 2, 'FD')
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(7)
    doc.setTextColor(...AMBRE)
    doc.text('SORTIES DANS LES AUTRES DEVISES', MARGE + 5, y + 4.5)
    doc.setFontSize(8.8)
    doc.text(lignesDevises, MARGE + 5, y + 9)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.2)
    doc.setTextColor(...GRIS)
    doc.text(lignesNote, MARGE + largeur - 5, y + 6, { align: 'right' })
    y += hauteurBande + 6
  }

  if (m.entrees.length === 0 && m.sorties.length === 0) {
    drawEtatVide(
      doc,
      y + 2,
      'Aucun mouvement enregistré pour cette période',
      `${m.projet.code} · ${libellePeriode(periode)}`,
    )
    drawTenantFooter(doc, identity, { pageNumber: 1, pageCount: 1, generatedBy: emisPar })
    return doc
  }

  y = titreSection(
    doc,
    y + 1,
    'Journal des entrées',
    `${pluriel(m.entrees.length, 'encaissement')} · ${formatAmount(m.totaux.entrees_usd)} USD`,
    'vert',
  )
  if (m.entrees.length === 0) {
    y = drawEtatVide(doc, y, 'Aucune entrée sur la période', 'Aucun encaissement n’est rattaché à ce projet.')
  } else {
    autoTable(doc, {
      ...styleTableau(VERT),
      startY: y,
      head: [['N°', 'Date', 'Reçu', 'Payeur', 'Canal', 'Montant perçu', 'Équivalent USD']],
      body: m.entrees.map((e, index) => [
        index + 1,
        dateCourte(e.date),
        e.numero || '—',
        e.tiers || '—',
        MODES[e.canal] || e.canal,
        `${formatAmount(e.montant_percu)} ${e.devise_perception}`,
        `${formatAmount(e.montant_usd)} USD`,
      ]),
      foot: [[
        { content: 'TOTAL DES ENTRÉES', colSpan: 6, styles: { halign: 'right' } },
        {
          content: `${formatAmount(m.totaux.entrees_usd)} USD`,
          styles: { halign: 'right', textColor: VERT },
        },
      ]],
      columnStyles: {
        0: { cellWidth: 9, halign: 'center', textColor: GRIS },
        1: { cellWidth: 20 },
        2: { cellWidth: 30 },
        4: { cellWidth: 22 },
        5: { cellWidth: 38, halign: 'right' },
        6: { cellWidth: 36, halign: 'right', fontStyle: 'bold', textColor: VERT },
      },
      didParseCell: (data) => {
        if (data.section === 'head' && [5, 6].includes(data.column.index)) data.cell.styles.halign = 'right'
        if (data.section === 'head' && data.column.index === 0) data.cell.styles.halign = 'center'
      },
    })
    y = finTableau(doc, y) + 8
  }

  y = titreSection(
    doc,
    y,
    'Journal des sorties',
    pluriel(m.sorties.length, 'décaissement'),
    'rouge',
  )
  if (m.sorties.length === 0) {
    drawEtatVide(doc, y, 'Aucune sortie sur la période', 'Aucun décaissement n’est rattaché à ce projet.')
  } else {
    autoTable(doc, {
      // L'en-tête reste institutionnel ; le rouge est réservé aux flux sortants.
      ...styleTableau(VERT),
      startY: y,
      head: [['N°', 'Date', 'Bon', 'Bénéficiaire', 'Motif / objet', 'Réquisition', 'Canal', 'Montant']],
      body: m.sorties.map((s, index) => [
        index + 1,
        dateCourte(s.date),
        s.numero || '—',
        s.beneficiaire || '—',
        s.motif || '—',
        s.requisition || 'Sortie directe',
        MODES[s.canal] || s.canal,
        `${formatAmount(s.montant)} ${s.devise}`,
      ]),
      foot: [[
        { content: 'TOTAL DES SORTIES', colSpan: 7, styles: { halign: 'right' } },
        {
          content: sortiesParDevise(m.totaux.sorties).split(' · ').join('\n'),
          styles: { halign: 'right', textColor: ROUGE },
        },
      ]],
      columnStyles: {
        0: { cellWidth: 9, halign: 'center', textColor: GRIS },
        1: { cellWidth: 20 },
        2: { cellWidth: 29 },
        3: { cellWidth: 42 },
        5: { cellWidth: 35 },
        6: { cellWidth: 22 },
        7: { cellWidth: 38, halign: 'right', fontStyle: 'bold', textColor: ROUGE },
      },
      didParseCell: (data) => {
        if (data.section === 'head' && data.column.index === 7) data.cell.styles.halign = 'right'
        if (data.section === 'head' && data.column.index === 0) data.cell.styles.halign = 'center'
      },
    })
  }

  const pages = doc.getNumberOfPages()
  for (let page = 1; page <= pages; page += 1) {
    doc.setPage(page)
    if (page > 1) drawEnteteSuite(doc, m, periode)
    drawTenantFooter(doc, identity, { pageNumber: page, pageCount: pages, generatedBy: emisPar })
  }
  return doc
}

export async function exporterProjetPDF(m: MouvementsProjet, periode: PeriodeProjet, emisPar?: string | null) {
  const identity = await loadTenantIdentity()
  const doc = construireRapportProjet(m, periode, identity, emisPar)
  doc.save(nomFichier(m, 'pdf'))
}

/** Le même PDF, en mémoire : c'est lui qui part en pièce jointe au Bureau. */
export async function genererProjetPDF(m: MouvementsProjet, periode: PeriodeProjet, emisPar?: string | null) {
  const identity = await loadTenantIdentity()
  const doc = construireRapportProjet(m, periode, identity, emisPar)
  return { blob: doc.output('blob'), nom: nomFichier(m, 'pdf') }
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
