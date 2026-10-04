import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { LIBELLE_TRANCHE } from '../api/creances'
import { LIBELLE_STATUT_NOTE, type NoteDebitExpert, type TableauDeBordNotes } from '../api/notesDebit'
import { formatAmount, toNumber } from './amount'
import { buildListReport, type ReportFilter } from './pdfGeneratorReports'
import { drawTenantFooter, drawTenantHeader, loadTenantIdentity } from './pdfTenantIdentity'
import {
  createReportListSheet,
  createReportSummarySheet,
  jourExcel,
  telechargerClasseur,
} from './reportExcelStyles'

/**
 * Exports des notes de débit : la liste (toute la sélection filtrée, pas la
 * seule page affichée) et le tableau de bord du recouvrement, en PDF et en
 * Excel, à la charte des autres rapports.
 */

type XlsxModule = typeof import('xlsx')

async function chargerXlsx(): Promise<XlsxModule> {
  const module = (await import('xlsx')) as XlsxModule & { default?: XlsxModule }
  return module.utils ? module : module.default || module
}

const LIBELLE_TYPE: Record<string, string> = { expert_comptable: 'Experts-comptables', sec: 'SEC' }

export const statutNote = (note: Pick<NoteDebitExpert, 'statut_operation' | 'statut_paiement'>) =>
  note.statut_operation === 'ANNULEE'
    ? 'Annulée'
    : (LIBELLE_STATUT_NOTE[note.statut_paiement] ?? note.statut_paiement)

const usd = (valeur: string | number) => `${formatAmount(valeur)} USD`
const dateCourte = (valeur: string | null) => (valeur ? format(new Date(valeur), 'dd/MM/yyyy') : '—')
const pourcent = (taux: number) => `${taux.toLocaleString('fr-FR')} %`
const horodatage = () => format(new Date(), 'yyyy-MM-dd')

export interface ExportListeNotes {
  notes: NoteDebitExpert[]
  totaux: { montant_total: string; montant_paye: string; reste_du: string }
  /** Critères de la liste, rappelés en tête du document. */
  filtres: ReportFilter[]
  organisation: string
}

// ---------------------------------------------------------------------------
//  Liste des notes
// ---------------------------------------------------------------------------

export async function exporterListeNotesPDF({ notes, totaux, filtres }: ExportListeNotes) {
  await buildListReport({
    title: 'NOTES DE DÉBIT DES EXPERTS-COMPTABLES',
    footerLabel: 'Notes de débit',
    columns: [
      { header: 'N° note', width: 30 },
      { header: 'Date', width: 20, halign: 'center' },
      { header: "N° d'ordre", width: 22, halign: 'center' },
      { header: 'Membre', width: 48 },
      { header: 'Libellés', width: 45 },
      { header: 'Montant', width: 24, halign: 'right' },
      { header: 'Payé', width: 24, halign: 'right' },
      { header: 'Reste', width: 24, halign: 'right' },
      // « État » plutôt que « Statut » : le moteur colore la colonne Statut
      // sur des mots-clés qui peindraient en vert une note partiellement payée.
      { header: 'État', width: 28, halign: 'center' },
    ],
    rows: notes.map((note) => [
      note.numero_note_externe || note.numero_recu || '—',
      dateCourte(note.date_encaissement),
      note.expert.numero_ordre,
      note.type_client === 'sec' ? `${note.expert.nom} (SEC)` : note.expert.nom,
      note.libelle,
      formatAmount(note.montant_total),
      formatAmount(note.montant_paye),
      formatAmount(note.reste_du),
      statutNote(note),
    ]),
    footRow: [
      '',
      '',
      '',
      '',
      'TOTAL (USD)',
      formatAmount(totaux.montant_total),
      formatAmount(totaux.montant_paye),
      formatAmount(totaux.reste_du),
      '',
    ],
    summary: [
      { label: 'Notes', value: String(notes.length) },
      { label: 'Émis', value: usd(totaux.montant_total) },
      { label: 'Encaissé', value: usd(totaux.montant_paye) },
      { label: 'Reste à recouvrer', value: usd(totaux.reste_du) },
    ],
    options: { filters: filtres },
    fileNameBase: `notes_de_debit_${horodatage()}`,
  })
}

export async function exporterListeNotesExcel({ notes, totaux, filtres, organisation }: ExportListeNotes) {
  const XLSX = await chargerXlsx()
  const sheet = createReportListSheet(XLSX, {
    title: 'NOTES DE DÉBIT DES EXPERTS-COMPTABLES',
    organisation,
    subtitle: filtres.length
      ? filtres.map((f) => `${f.label} : ${f.value}`).join('  ·  ')
      : `Généré le ${format(new Date(), 'dd/MM/yyyy HH:mm')}`,
    headers: [
      'N° note',
      'Date',
      "N° d'ordre",
      'Membre',
      'Type',
      'Libellés',
      'Montant (USD)',
      'Payé (USD)',
      'Reste (USD)',
      'Statut',
      'Jours',
      'Relances',
    ],
    rows: notes.map((note) => [
      note.numero_note_externe || note.numero_recu || '',
      jourExcel(note.date_encaissement),
      note.expert.numero_ordre,
      note.expert.nom,
      note.type_client === 'sec' ? 'SEC' : 'EC',
      note.libelle,
      toNumber(note.montant_total),
      toNumber(note.montant_paye),
      toNumber(note.reste_du),
      statutNote(note),
      note.jours,
      note.relance_count,
    ]),
    widths: [22, 12, 13, 34, 7, 44, 15, 15, 15, 20, 8, 9],
    moneyColumns: [6, 7, 8],
    dateColumns: [1],
    centerColumns: [2, 4, 9],
    wrapColumns: [5],
    summaryCards: [
      { label: 'Notes', value: notes.length, format: 'integer' },
      { label: 'Émis', value: toNumber(totaux.montant_total), format: 'money' },
      { label: 'Encaissé', value: toNumber(totaux.montant_paye), format: 'money', tone: 'positive' },
      { label: 'Reste à recouvrer', value: toNumber(totaux.reste_du), format: 'money', tone: 'negative' },
    ],
    footerRow: [
      'TOTAL',
      '',
      '',
      '',
      '',
      '',
      toNumber(totaux.montant_total),
      toNumber(totaux.montant_paye),
      toNumber(totaux.reste_du),
      '',
      '',
      '',
    ],
    cellTone: (valeur, _ligne, colonne) => {
      if (colonne !== 9) return undefined
      if (valeur === 'Annulée') return undefined
      if (valeur === 'Partiellement payée') return 'warning'
      if (valeur === 'Émise') return 'negative'
      return 'positive'
    },
  })
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, sheet, 'Notes de débit')
  telechargerClasseur(XLSX, wb, `Notes_de_debit_${horodatage()}.xlsx`)
}

// ---------------------------------------------------------------------------
//  Tableau de bord du recouvrement
// ---------------------------------------------------------------------------

const VERT: [number, number, number] = [6, 95, 70]

export async function exporterTableauDeBordPDF(donnees: TableauDeBordNotes) {
  const { annee, kpi } = donnees
  const identity = await loadTenantIdentity()
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const marge = 12
  const largeur = doc.internal.pageSize.getWidth() - marge * 2
  const basPage = doc.internal.pageSize.getHeight() - 20

  let y = drawTenantHeader(doc, identity, {
    title: 'Recouvrement des notes de débit',
    subtitle: `Exercice ${annee} · situation au ${format(new Date(), 'dd/MM/yyyy')}`,
  })

  // Indicateurs : deux rangées de trois cartes.
  const cartes: [string, string, string][] = [
    ['Émis', usd(kpi.emis), `${kpi.nb_notes} note${kpi.nb_notes > 1 ? 's' : ''} en ${annee}`],
    ['Encaissé', usd(kpi.encaisse), "sur les notes de l'exercice"],
    [
      'Reste à recouvrer',
      usd(kpi.reste_total),
      toNumber(kpi.arrieres_anterieurs) > 0
        ? `dont ${usd(kpi.arrieres_anterieurs)} d'exercices antérieurs`
        : 'arriérés compris',
    ],
    ['Taux de recouvrement', pourcent(kpi.taux_recouvrement), ''],
    ['Pénalités dues', usd(kpi.penalites_dues), 'part non réglée des pénalités'],
    [`Non en règle — Tableau ${annee + 1}`, String(kpi.membres_non_en_regle), 'membres avec un reste dû'],
  ]
  const ecart = 4
  const largeurCarte = (largeur - ecart * 2) / 3
  const hauteurCarte = 20
  cartes.forEach(([libelle, valeur, detail], index) => {
    const x = marge + (index % 3) * (largeurCarte + ecart)
    const cy = y + Math.floor(index / 3) * (hauteurCarte + ecart)
    doc.setDrawColor(209, 250, 229)
    doc.setFillColor(255, 255, 255)
    doc.roundedRect(x, cy, largeurCarte, hauteurCarte, 2, 2, 'FD')
    doc.setFillColor(...VERT)
    doc.roundedRect(x, cy, 2.2, hauteurCarte, 1.1, 1.1, 'F')
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(92, 111, 106)
    doc.text(libelle.toUpperCase(), x + 5, cy + 5.5)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11.5)
    doc.setTextColor(...VERT)
    doc.text(valeur, x + 5, cy + 12.5)
    if (detail) {
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(6.8)
      doc.setTextColor(110, 120, 135)
      doc.text(doc.splitTextToSize(detail, largeurCarte - 7)[0], x + 5, cy + 17)
    }
  })
  y += hauteurCarte * 2 + ecart + 8

  const section = (titre: string, head: string[], body: (string | number)[][], droite: number[], vide: string) => {
    if (y + 20 > basPage) {
      doc.addPage()
      y = 20
    }
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(10.5)
    doc.setTextColor(...VERT)
    doc.text(titre, marge, y)
    const columnStyles: Record<number, { halign: 'right' }> = {}
    droite.forEach((i) => (columnStyles[i] = { halign: 'right' }))
    autoTable(doc, {
      head: [head],
      body: body.length ? body : [[{ content: vide, colSpan: head.length, styles: { halign: 'center' } }]],
      startY: y + 2.5,
      theme: 'grid',
      margin: { left: marge, right: marge, bottom: 20 },
      styles: { fontSize: 8, cellPadding: 1.8, lineColor: [226, 232, 240], lineWidth: 0.12, textColor: [31, 41, 55] },
      headStyles: { fillColor: VERT, textColor: 255, fontStyle: 'bold' },
      alternateRowStyles: { fillColor: [248, 253, 250] },
      columnStyles,
    })
    y = ((doc as any).lastAutoTable?.finalY ?? y) + 9
  }

  section(
    'Recouvrement par type de membre',
    ['Type', 'Notes', 'Émis', 'Encaissé', 'Reste', 'Taux'],
    donnees.par_type.map((t) => [
      LIBELLE_TYPE[t.type_client] ?? t.type_client,
      t.nb,
      usd(t.emis),
      usd(t.encaisse),
      usd(t.reste),
      pourcent(t.taux),
    ]),
    [1, 2, 3, 4, 5],
    'Aucune note pour cet exercice.',
  )
  section(
    'Ancienneté du reste dû',
    ['Tranche', 'Notes', 'Reste dû'],
    donnees.anciennete.map((t) => [LIBELLE_TRANCHE[t.tranche], t.nb, usd(t.reste)]),
    [1, 2],
    'Aucun reste dû.',
  )
  section(
    'Émis par libellé',
    ['Libellé', 'Notes', 'Émis'],
    donnees.par_libelle.map((l) => [l.libelle, l.nb, usd(l.emis)]),
    [1, 2],
    'Aucun libellé.',
  )
  section(
    'Principaux débiteurs',
    ["N° d'ordre", 'Membre', 'Type', 'Notes', 'Reste dû'],
    donnees.top_debiteurs.map((d) => [d.numero_ordre, d.nom, d.type_ec, d.nb_notes, usd(d.reste)]),
    [3, 4],
    'Aucun débiteur.',
  )
  section(
    'Par province',
    ['Province', 'Notes', 'Émis', 'Encaissé', 'Reste', 'Taux'],
    donnees.par_province.map((p) => [p.province, p.nb, usd(p.emis), usd(p.encaisse), usd(p.reste), pourcent(p.taux)]),
    [1, 2, 3, 4, 5],
    'Aucune province.',
  )

  const pages = doc.getNumberOfPages()
  for (let page = 1; page <= pages; page += 1) {
    doc.setPage(page)
    drawTenantFooter(doc, identity, { pageNumber: page, pageCount: pages })
  }
  doc.save(`recouvrement_notes_de_debit_${annee}.pdf`)
}

export async function exporterTableauDeBordExcel(donnees: TableauDeBordNotes, organisation: string) {
  const XLSX = await chargerXlsx()
  const { annee, kpi } = donnees
  const sousTitre = `Exercice ${annee} · situation au ${format(new Date(), 'dd/MM/yyyy')}`
  const wb = XLSX.utils.book_new()

  XLSX.utils.book_append_sheet(
    wb,
    createReportSummarySheet(XLSX, {
      title: 'RECOUVREMENT DES NOTES DE DÉBIT',
      organisation,
      subtitle: sousTitre,
      items: [
        { label: `Notes ${annee}`, value: kpi.nb_notes, format: 'integer' },
        { label: 'Émis', value: toNumber(kpi.emis), format: 'money' },
        { label: 'Encaissé', value: toNumber(kpi.encaisse), format: 'money', tone: 'positive' },
        { label: 'Reste (arriérés compris)', value: toNumber(kpi.reste_total), format: 'money', tone: 'negative' },
        { label: "dont exercices antérieurs", value: toNumber(kpi.arrieres_anterieurs), format: 'money' },
        { label: 'Taux de recouvrement', value: pourcent(kpi.taux_recouvrement), tone: 'accent' },
        { label: 'Pénalités dues', value: toNumber(kpi.penalites_dues), format: 'money', tone: 'warning' },
        {
          label: `Non en règle — Tableau ${annee + 1}`,
          value: kpi.membres_non_en_regle,
          format: 'integer',
          tone: 'negative',
        },
      ],
      detailTitle: 'RECOUVREMENT PAR TYPE DE MEMBRE',
      detailHeaders: ['Type', 'Notes', 'Émis (USD)', 'Encaissé (USD)', 'Reste (USD)', 'Taux (%)'],
      detailRows: donnees.par_type.map((t) => [
        LIBELLE_TYPE[t.type_client] ?? t.type_client,
        t.nb,
        toNumber(t.emis),
        toNumber(t.encaisse),
        toNumber(t.reste),
        t.taux,
      ]),
      detailMoneyColumns: [2, 3, 4],
      detailWidths: [24, 10, 18, 18, 18, 10],
    }),
    'Synthèse',
  )

  const feuille = (
    nom: string,
    titre: string,
    headers: string[],
    rows: (string | number)[][],
    widths: number[],
    moneyColumns: number[],
    footerRow?: (string | number)[],
  ) =>
    XLSX.utils.book_append_sheet(
      wb,
      createReportListSheet(XLSX, { title: titre, organisation, subtitle: sousTitre, headers, rows, widths, moneyColumns, footerRow }),
      nom,
    )

  const somme = <T>(items: T[], champ: (item: T) => string) => items.reduce((s, i) => s + toNumber(champ(i)), 0)

  feuille(
    'Ancienneté',
    'ANCIENNETÉ DU RESTE DÛ',
    ['Tranche', 'Notes', 'Reste dû (USD)'],
    donnees.anciennete.map((t) => [LIBELLE_TRANCHE[t.tranche], t.nb, toNumber(t.reste)]),
    [20, 10, 18],
    [2],
    ['TOTAL', donnees.anciennete.reduce((s, t) => s + t.nb, 0), somme(donnees.anciennete, (t) => t.reste)],
  )
  feuille(
    'Par libellé',
    'ÉMIS PAR LIBELLÉ',
    ['Libellé', 'Notes', 'Émis (USD)'],
    donnees.par_libelle.map((l) => [l.libelle, l.nb, toNumber(l.emis)]),
    [44, 10, 18],
    [2],
  )
  feuille(
    'Débiteurs',
    'PRINCIPAUX DÉBITEURS',
    ["N° d'ordre", 'Membre', 'Type', 'Notes', 'Reste dû (USD)'],
    donnees.top_debiteurs.map((d) => [d.numero_ordre, d.nom, d.type_ec, d.nb_notes, toNumber(d.reste)]),
    [14, 36, 10, 10, 18],
    [4],
  )
  feuille(
    'Par province',
    'RECOUVREMENT PAR PROVINCE',
    ['Province', 'Notes', 'Émis (USD)', 'Encaissé (USD)', 'Reste (USD)', 'Taux (%)'],
    donnees.par_province.map((p) => [p.province, p.nb, toNumber(p.emis), toNumber(p.encaisse), toNumber(p.reste), p.taux]),
    [24, 10, 18, 18, 18, 10],
    [2, 3, 4],
    [
      'TOTAL',
      donnees.par_province.reduce((s, p) => s + p.nb, 0),
      somme(donnees.par_province, (p) => p.emis),
      somme(donnees.par_province, (p) => p.encaisse),
      somme(donnees.par_province, (p) => p.reste),
      '',
    ],
  )

  telechargerClasseur(XLSX, wb, `Recouvrement_notes_de_debit_${annee}.xlsx`)
}
