import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { apiRequest } from '../lib/apiClient'
import type { LigneRequisition, Requisition, SortieFonds } from '../types'
import { formatAmount, toNumber } from './amount'
import { numberToWords } from './numberToWords'
import { getStatusMeta } from './statusMapper'
import { drawTenantFooter, drawTenantHeader, loadTenantIdentity, type TenantIdentity } from './pdfTenantIdentity'

/**
 * Rapport de décaissement d'une réquisition : ce qui a été autorisé, ce qui
 * est sorti (bon par bon, avec le cumul), ce qui reste à payer, où la dépense
 * est imputée et si les justificatifs sont rentrés.
 */

type Rgb = [number, number, number]

const MARGE = 12
const VERT: Rgb = [6, 95, 70]
const VERT_PALE: Rgb = [240, 253, 244]
const ENCRE: Rgb = [15, 23, 42]
const ARDOISE: Rgb = [71, 85, 105]
const GRIS: Rgb = [100, 116, 139]
const BORDURE: Rgb = [226, 232, 240]
const FOND: Rgb = [248, 250, 252]
const AMBRE: Rgb = [180, 83, 9]
const ROUGE: Rgb = [220, 38, 38]

type Personne = { prenom?: string | null; nom?: string | null } | null | undefined

export type RapportDecaissementInput = {
  requisition: Requisition
  lignes: LigneRequisition[]
  demandeur?: Personne
  validateur?: Personne
  approbateur?: Personne
  emisPar?: string | null
}

const nomComplet = (p: Personne) => [p?.prenom, p?.nom].filter(Boolean).join(' ') || '—'

const dateCourte = (valeur?: string | null) => (valeur ? format(new Date(valeur), 'dd/MM/yyyy') : '—')
const dateHeure = (valeur?: string | null) => (valeur ? format(new Date(valeur), 'dd/MM/yyyy à HH:mm') : '—')

const MODES: Record<string, string> = {
  cash: 'Caisse',
  mobile_money: 'Mobile Money',
  virement: 'Banque',
}

const JUSTIFICATIFS: Record<string, string> = {
  NON_REQUIS: 'Non requis',
  ATTENDU: 'Attendu',
  EN_RETARD: 'En retard',
  RECU: 'Reçu',
  DISPENSE: 'Dispensé',
}

const COULEUR_JUSTIFICATIF: Record<string, Rgb> = {
  'En retard': ROUGE,
  Attendu: AMBRE,
  Reçu: VERT,
}

const estAnnulee = (s: SortieFonds) =>
  Boolean(s.annulee_le) || String(s.statut || '').toUpperCase().startsWith('ANNUL')
const estExecutee = (s: SortieFonds) => !estAnnulee(s) && String(s.statut || 'VALIDE').toUpperCase() === 'VALIDE'

const hexVersRgb = (hex: string, repli: Rgb): Rgb => {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '')
  return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : repli
}

const finTableau = (doc: jsPDF, y: number): number => (doc as any).lastAutoTable?.finalY ?? y

/** Passe à la page suivante si `besoin` mm ne tiennent plus au-dessus du pied de page. */
const place = (doc: jsPDF, y: number, besoin: number) => {
  if (y + besoin <= doc.internal.pageSize.getHeight() - 20) return y
  doc.addPage()
  return 20
}

/** Titre de section : pastille verte, intitulé, filet sur toute la largeur. */
const titreSection = (doc: jsPDF, y: number, titre: string, complement?: string) => {
  y = place(doc, y, 18)
  const largeur = doc.internal.pageSize.getWidth() - MARGE * 2
  doc.setFillColor(...VERT)
  doc.roundedRect(MARGE, y - 3.2, 1.4, 4.2, 0.7, 0.7, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9.5)
  doc.setTextColor(...ENCRE)
  doc.text(titre, MARGE + 3.5, y)
  if (complement) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    doc.setTextColor(...GRIS)
    doc.text(complement, MARGE + largeur, y, { align: 'right' })
  }
  doc.setDrawColor(...BORDURE)
  doc.setLineWidth(0.3)
  doc.line(MARGE, y + 2.2, MARGE + largeur, y + 2.2)
  return y + 6
}

/** Style commun des tableaux : lignes alternées, pas de quadrillage vertical. */
const styleTableau = (entete: { fond: Rgb; texte: Rgb }) => ({
  theme: 'plain' as const,
  margin: { left: MARGE, right: MARGE },
  styles: {
    font: 'helvetica',
    fontSize: 8,
    cellPadding: { top: 2, bottom: 2, left: 2, right: 2 },
    textColor: ENCRE,
    valign: 'middle' as const,
    lineColor: BORDURE,
    lineWidth: { bottom: 0.2 },
  },
  headStyles: { fillColor: entete.fond, textColor: entete.texte, fontStyle: 'bold' as const, fontSize: 7.5 },
  alternateRowStyles: { fillColor: FOND },
  footStyles: { fillColor: VERT_PALE, textColor: ENCRE, fontStyle: 'bold' as const },
})

const chargerSorties = async (requisitionId: string): Promise<SortieFonds[]> => {
  const res: any = await apiRequest('GET', '/sorties-fonds', {
    params: { requisition_id: requisitionId, order: 'date_paiement.asc', limit: 500 },
  })
  return Array.isArray(res) ? res : res?.items ?? res?.data ?? []
}

/** Construit le document, sans rien charger ni ouvrir : testable à part. */
export const construireRapportDecaissement = (
  input: RapportDecaissementInput,
  sortiesBrutes: SortieFonds[],
  identity: TenantIdentity,
): jsPDF => {
  const { requisition: req, lignes } = input
  const r = req as any
  const devise = String(r.devise || 'USD')
  const sorties = [...sortiesBrutes].sort(
    (a, b) => new Date(a.date_paiement || 0).getTime() - new Date(b.date_paiement || 0).getTime()
  )

  const executees = sorties.filter(estExecutee)
  const annulees = sorties.filter(estAnnulee)
  const autorise = toNumber(req.montant_total)
  const decaisse = executees.reduce((somme, s) => somme + toNumber(s.montant_paye), 0)
  const reste = Math.max(0, autorise - decaisse)
  const taux = autorise > 0 ? Math.min(100, (decaisse / autorise) * 100) : 0
  const soldee = autorise > 0 && reste <= 0

  const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
  const largeur = doc.internal.pageSize.getWidth() - MARGE * 2

  let y = drawTenantHeader(doc, identity, {
    title: 'Rapport de décaissement',
    subtitle: `Réquisition ${req.numero_requisition} · situation au ${format(new Date(), 'dd/MM/yyyy à HH:mm')}`,
  })

  // Statut en pastille, aligné à droite du titre.
  const statut = getStatusMeta(r.status ?? req.statut)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  const lPastille = doc.getTextWidth(statut.label) + 8
  doc.setFillColor(...hexVersRgb(statut.bg, FOND))
  doc.roundedRect(MARGE + largeur - lPastille, 39.5, lPastille, 6, 3, 3, 'F')
  doc.setTextColor(...hexVersRgb(statut.color, ENCRE))
  doc.text(statut.label, MARGE + largeur - lPastille / 2, 43.6, { align: 'center' })

  // ── Fiche de la réquisition : objet en tête, puis une grille 3 × 2 ──────
  y = place(doc, y, 44)
  const hFiche = 40
  doc.setDrawColor(...BORDURE)
  doc.setFillColor(...FOND)
  doc.setLineWidth(0.3)
  doc.roundedRect(MARGE, y, largeur, hFiche, 2, 2, 'FD')

  const champ = (x: number, yy: number, libelle: string, valeur: string, largeurMax: number) => {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(6.8)
    doc.setTextColor(...GRIS)
    doc.text(libelle.toUpperCase(), x, yy)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8.8)
    doc.setTextColor(...ENCRE)
    doc.text(doc.splitTextToSize(valeur, largeurMax)[0] ?? '', x, yy + 4.4)
  }

  const interieur = largeur - 10
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(6.8)
  doc.setTextColor(...GRIS)
  doc.text('OBJET', MARGE + 5, y + 6)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.setTextColor(...ENCRE)
  doc.text(doc.splitTextToSize(req.objet || '—', interieur)[0] ?? '', MARGE + 5, y + 11)

  doc.setDrawColor(...BORDURE)
  doc.line(MARGE + 5, y + 14.5, MARGE + largeur - 5, y + 14.5)

  const col = interieur / 3
  const xCol = (i: number) => MARGE + 5 + i * col
  const mode = MODES[String(req.mode_paiement)] || String(req.mode_paiement || '—')
  champ(xCol(0), y + 20, 'Demandeur', nomComplet(input.demandeur), col - 4)
  champ(xCol(1), y + 20, 'Date de la demande', dateHeure(req.created_at), col - 4)
  champ(xCol(2), y + 20, 'Paiement', r.decaissement_progressif ? `${mode} · par tranches` : mode, col - 4)
  champ(xCol(0), y + 31, 'Validation 1/2', `${nomComplet(input.validateur)} · ${dateCourte(r.validee_le)}`, col - 4)
  champ(xCol(1), y + 31, 'Validation 2/2', `${nomComplet(input.approbateur)} · ${dateCourte(r.approuvee_le)}`, col - 4)
  champ(xCol(2), y + 31, 'Numéro', req.numero_requisition, col - 4)
  y += hFiche + 8

  // ── Synthèse : trois montants, puis l'avancement ────────────────────────
  y = titreSection(doc, y, 'Synthèse')
  y = place(doc, y, 34)
  const tuiles: [string, number, Rgb][] = [
    ['Montant autorisé', autorise, ENCRE],
    ['Total décaissé', decaisse, VERT],
    ['Reste à décaisser', reste, reste > 0 ? AMBRE : GRIS],
  ]
  const lTuile = (largeur - 8) / 3
  tuiles.forEach(([libelle, montant, couleur], i) => {
    const x = MARGE + i * (lTuile + 4)
    doc.setDrawColor(...BORDURE)
    doc.setFillColor(255, 255, 255)
    doc.roundedRect(x, y, lTuile, 19, 1.8, 1.8, 'FD')
    // Liseré de couleur à gauche : la tuile se reconnaît avant d'être lue.
    doc.setFillColor(...couleur)
    doc.rect(x, y + 3, 1.2, 13, 'F')
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(...GRIS)
    doc.text(libelle.toUpperCase(), x + 5, y + 6.5)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(13)
    doc.setTextColor(...couleur)
    doc.text(formatAmount(montant), x + 5, y + 14.5)
    const lMontant = doc.getTextWidth(formatAmount(montant))
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    doc.setTextColor(...GRIS)
    doc.text(devise, x + 5 + lMontant + 1.5, y + 14.5)
  })
  y += 25

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.setTextColor(...ENCRE)
  doc.text(`${taux.toFixed(taux % 1 ? 1 : 0).replace('.', ',')} % exécuté`, MARGE, y)
  doc.setFont('helvetica', 'normal')
  doc.setTextColor(...GRIS)
  const nbTexte = `${executees.length} décaissement${executees.length > 1 ? 's' : ''}`
  doc.text(`${nbTexte} · ${soldee ? 'réquisition soldée' : 'réquisition non soldée'}`, MARGE + largeur, y, { align: 'right' })
  y += 2.5
  doc.setFillColor(...BORDURE)
  doc.roundedRect(MARGE, y, largeur, 2.6, 1.3, 1.3, 'F')
  if (taux > 0) {
    doc.setFillColor(...VERT)
    doc.roundedRect(MARGE, y, Math.max(2.6, (largeur * taux) / 100), 2.6, 1.3, 1.3, 'F')
  }
  y += 11

  // ── Détail des décaissements, avec le cumul après chaque bon ────────────
  y = titreSection(doc, y, 'Décaissements effectués')
  if (executees.length === 0) {
    doc.setFont('helvetica', 'italic')
    doc.setFontSize(8.5)
    doc.setTextColor(...GRIS)
    doc.text('Aucun décaissement enregistré à ce jour.', MARGE, y + 3)
    y += 11
  } else {
    let cumul = 0
    const corps = executees.map((s, i) => {
      cumul += toNumber(s.montant_paye)
      const tranche = s.tranche ? `Tranche ${s.tranche.numero}/${s.tranche.nombre}` : null
      return [
        String(i + 1),
        dateCourte(s.date_paiement),
        [s.reference_numero || s.reference || '—', tranche].filter(Boolean).join('\n'),
        [s.beneficiaire || '—', s.motif].filter(Boolean).join('\n'),
        MODES[String(s.mode_paiement)] || String(s.mode_paiement || '—'),
        `${formatAmount(s.montant_paye)} ${(s as any).devise || devise}`,
        formatAmount(cumul),
        JUSTIFICATIFS[String((s as any).justificatif_statut || 'NON_REQUIS')] || '—',
      ]
    })
    autoTable(doc, {
      ...styleTableau({ fond: VERT, texte: [255, 255, 255] }),
      startY: y,
      head: [['#', 'Date', 'Bon', 'Bénéficiaire · motif', 'Canal', 'Montant', 'Cumul', 'Justificatif']],
      body: corps,
      foot: [[
        { content: 'Total décaissé', colSpan: 5, styles: { halign: 'right' } },
        { content: `${formatAmount(decaisse)} ${devise}`, styles: { halign: 'right' } },
        '',
        '',
      ]],
      columnStyles: {
        0: { cellWidth: 7, halign: 'center', textColor: GRIS },
        1: { cellWidth: 18 },
        2: { cellWidth: 28 },
        4: { cellWidth: 19 },
        5: { cellWidth: 26, halign: 'right', fontStyle: 'bold' },
        6: { cellWidth: 22, halign: 'right', textColor: ARDOISE },
        7: { cellWidth: 20 },
      },
      didParseCell: (data) => {
        if (data.section === 'head' && [5, 6].includes(data.column.index)) data.cell.styles.halign = 'right'
        if (data.section !== 'body' || data.column.index !== 7) return
        const couleur = COULEUR_JUSTIFICATIF[String(data.cell.raw)]
        if (couleur) {
          data.cell.styles.textColor = couleur
          data.cell.styles.fontStyle = 'bold'
        }
      },
    })
    y = finTableau(doc, y) + 5

    // numberToWords écrit des dollars : la mention n'a de sens qu'en USD.
    if (devise === 'USD' && decaisse > 0) {
      y = place(doc, y, 12)
      doc.setFillColor(...FOND)
      const enLettres = doc.splitTextToSize(
        `Arrêté à la somme décaissée de ${numberToWords(decaisse)}.`,
        largeur - 8,
      )
      const hLettres = enLettres.length * 4 + 4
      doc.roundedRect(MARGE, y, largeur, hLettres, 1.5, 1.5, 'F')
      doc.setFont('helvetica', 'italic')
      doc.setFontSize(8)
      doc.setTextColor(...ARDOISE)
      doc.text(enLettres, MARGE + 4, y + 4.8)
      y += hLettres + 7
    }
  }

  // ── Imputation budgétaire ───────────────────────────────────────────────
  if (lignes.length > 0) {
    y = titreSection(doc, y, 'Imputation budgétaire')
    const totalLignes = lignes.reduce((somme, l) => somme + toNumber(l.montant_total), 0)
    autoTable(doc, {
      ...styleTableau({ fond: [241, 245, 249], texte: ARDOISE }),
      startY: y,
      head: [['Poste budgétaire', 'Rubrique · description', 'Montant']],
      body: lignes.map((l) => [
        [l.budget_poste_code_snapshot, l.budget_poste_libelle_snapshot].filter(Boolean).join(' — ') || '—',
        [l.rubrique, l.description].filter(Boolean).join('\n'),
        `${formatAmount(l.montant_total)} ${devise}`,
      ]),
      foot: lignes.length > 1
        ? [[{ content: 'Total', colSpan: 2, styles: { halign: 'right' } }, { content: `${formatAmount(totalLignes)} ${devise}`, styles: { halign: 'right' } }]]
        : undefined,
      columnStyles: { 0: { cellWidth: 62, fontStyle: 'bold' }, 2: { cellWidth: 30, halign: 'right' } },
      didParseCell: (data) => {
        if (data.section === 'head' && data.column.index === 2) data.cell.styles.halign = 'right'
      },
    })
    y = finTableau(doc, y) + 9
  }

  // ── Justificatifs : ce qui reste à rapporter ────────────────────────────
  const attendus = executees.filter((s) => ['ATTENDU', 'EN_RETARD'].includes(String((s as any).justificatif_statut)))
  if (attendus.length > 0) {
    y = titreSection(doc, y, 'Justificatifs à produire', `${attendus.length} en attente`)
    autoTable(doc, {
      ...styleTableau({ fond: [254, 243, 199], texte: [120, 53, 15] }),
      startY: y,
      head: [['Bon', 'Bénéficiaire', 'Échéance', 'Relances', 'Statut']],
      body: attendus.map((s) => [
        s.reference_numero || s.reference || '—',
        s.beneficiaire || '—',
        dateCourte((s as any).justificatif_echeance),
        String((s as any).justificatif_nb_relances ?? 0),
        JUSTIFICATIFS[String((s as any).justificatif_statut)] || '—',
      ]),
      columnStyles: { 0: { cellWidth: 32 }, 2: { cellWidth: 24 }, 3: { cellWidth: 18, halign: 'center' }, 4: { cellWidth: 22 } },
      didParseCell: (data) => {
        if (data.section !== 'body' || data.column.index !== 4) return
        const couleur = COULEUR_JUSTIFICATIF[String(data.cell.raw)]
        if (couleur) {
          data.cell.styles.textColor = couleur
          data.cell.styles.fontStyle = 'bold'
        }
      },
    })
    y = finTableau(doc, y) + 9
  }

  // ── Opérations annulées : gardées pour la traçabilité, hors totaux ──────
  if (annulees.length > 0) {
    y = titreSection(doc, y, 'Opérations annulées', 'non comptées dans les totaux')
    autoTable(doc, {
      ...styleTableau({ fond: [241, 245, 249], texte: ARDOISE }),
      startY: y,
      head: [['Bon', 'Date', 'Montant', 'Annulée le', 'Motif']],
      body: annulees.map((s) => [
        s.reference_numero || s.reference || '—',
        dateCourte(s.date_paiement),
        `${formatAmount(s.montant_paye)} ${(s as any).devise || devise}`,
        dateCourte(s.annulee_le),
        s.motif_annulation || '—',
      ]),
      bodyStyles: { textColor: GRIS },
      columnStyles: { 0: { cellWidth: 32 }, 1: { cellWidth: 20 }, 2: { cellWidth: 28, halign: 'right' }, 3: { cellWidth: 22 } },
      didParseCell: (data) => {
        if (data.section === 'head' && data.column.index === 2) data.cell.styles.halign = 'right'
      },
    })
  }

  const pages = doc.getNumberOfPages()
  for (let page = 1; page <= pages; page += 1) {
    doc.setPage(page)
    drawTenantFooter(doc, identity, { pageNumber: page, pageCount: pages, generatedBy: input.emisPar })
  }
  return doc
}

export const genererRapportDecaissement = async (input: RapportDecaissementInput): Promise<void> => {
  const [identity, sorties] = await Promise.all([loadTenantIdentity(), chargerSorties(String(input.requisition.id))])
  const doc = construireRapportDecaissement(input, sorties, identity)
  const url = URL.createObjectURL(doc.output('blob'))
  window.open(url, '_blank', 'noopener,noreferrer')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
