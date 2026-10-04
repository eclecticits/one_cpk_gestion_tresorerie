import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { fr } from 'date-fns/locale'
import type { CompteDePaiement, DocumentNote, ExpertDocument, MiseEnDemeure } from '../api/notesDebit'
import { formatAmount, toNumber } from './amount'
import { numberToWords } from './numberToWords'
import { drawTenantFooter, drawTenantHeader, loadTenantIdentity, type TenantIdentity } from './pdfTenantIdentity'

/**
 * Documents de recouvrement des experts-comptables : la note de débit détaillée
 * (une page par note, imprimable en lot) et la mise en demeure d'un membre.
 *
 * La note de débit reprend les lignes de la note telles qu'elles ont été
 * émises — une par libellé de l'import —, là où le reçu de caisse
 * (`generateReceiptPDF`) n'en donne que le libellé global : un membre doit
 * pouvoir lire ce qu'on lui réclame, cotisation, pénalités et arriérés.
 */

const MARGE = 12
const VERT: [number, number, number] = [6, 95, 70]
const ROUGE: [number, number, number] = [180, 35, 24]
const GRIS: [number, number, number] = [90, 100, 115]

const usd = (valeur: string | number) => `${formatAmount(valeur)} USD`
const dateLongue = (valeur: string | Date) => format(new Date(valeur), 'dd MMMM yyyy', { locale: fr })

const typeMembre = (expert: ExpertDocument) =>
  expert.type_ec === 'SEC' ? "Société d'expertise comptable" : 'Expert-comptable'

/** Échéance réglementaire de la cotisation : 31 octobre de l'exercice (art. 112 du RI). */
const echeanceCotisation = (dateNote: string | null) => {
  const annee = dateNote ? new Date(dateNote).getFullYear() : new Date().getFullYear()
  return { date: new Date(annee, 9, 31), annee }
}

/** Passe à la page suivante si `besoin` mm ne tiennent plus au-dessus du pied de page. */
const place = (doc: jsPDF, y: number, besoin: number) => {
  if (y + besoin <= doc.internal.pageSize.getHeight() - 20) return y
  doc.addPage()
  return 20
}

const ouvrir = (doc: jsPDF, identity: TenantIdentity) => {
  const pages = doc.getNumberOfPages()
  for (let page = 1; page <= pages; page += 1) {
    doc.setPage(page)
    drawTenantFooter(doc, identity, { pageNumber: page, pageCount: pages })
  }
  const url = URL.createObjectURL(doc.output('blob'))
  window.open(url, '_blank', 'noopener,noreferrer')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

/** Bloc « Débiteur » à gauche, informations du document à droite. Rend l'ordonnée suivante. */
const blocDebiteur = (doc: jsPDF, y: number, expert: ExpertDocument, droite: [string, string][]) => {
  const largeur = doc.internal.pageSize.getWidth() - MARGE * 2
  const moitie = largeur / 2 - 3
  const hauteur = 30
  doc.setDrawColor(219, 227, 238)
  doc.setLineWidth(0.3)
  doc.roundedRect(MARGE, y, moitie, hauteur, 2, 2)
  doc.roundedRect(MARGE + moitie + 6, y, moitie, hauteur, 2, 2)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(7.5)
  doc.setTextColor(...GRIS)
  doc.text('DÉBITEUR', MARGE + 4, y + 6)
  doc.setFontSize(11)
  doc.setTextColor(15, 23, 42)
  doc.text(doc.splitTextToSize(expert.nom, moitie - 8)[0], MARGE + 4, y + 12.5)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  doc.setTextColor(51, 65, 85)
  const details = [
    `N° d'ordre : ${expert.numero_ordre}`,
    typeMembre(expert) + (expert.province ? ` · ${expert.province}` : ''),
    [expert.email, expert.telephone].filter(Boolean).join(' · '),
  ].filter(Boolean)
  details.forEach((ligne, i) => doc.text(doc.splitTextToSize(ligne, moitie - 8)[0], MARGE + 4, y + 18 + i * 4.5))

  const x = MARGE + moitie + 10
  droite.forEach(([libelle, valeur], i) => {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8.5)
    doc.setTextColor(...GRIS)
    doc.text(libelle, x, y + 7 + i * 6.5)
    doc.setFont('helvetica', 'bold')
    doc.setTextColor(15, 23, 42)
    doc.text(valeur, MARGE + largeur - 4, y + 7 + i * 6.5, { align: 'right' })
  })
  return y + hauteur + 6
}

const blocPaiement = (doc: jsPDF, yDepart: number, comptes: CompteDePaiement[], reference: string) => {
  const largeur = doc.internal.pageSize.getWidth() - MARGE * 2
  const y = place(doc, yDepart, 14 + Math.max(comptes.length, 1) * 4.5)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9)
  doc.setTextColor(15, 23, 42)
  doc.text('Modalités de paiement', MARGE, y)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  doc.setTextColor(51, 65, 85)
  let ligneY = y + 5
  const lignes = comptes.length
    ? comptes.map(
        (c) =>
          `${c.banque ? `${c.banque} — ` : ''}${c.intitule} — N° ${c.numero_compte} (${c.devise})${
            c.code_swift_bic ? ` — SWIFT ${c.code_swift_bic}` : ''
          }`,
      )
    : ["À la caisse du Conseil, contre reçu."]
  for (const ligne of lignes) {
    for (const morceau of doc.splitTextToSize(`• ${ligne}`, largeur)) {
      doc.text(morceau, MARGE, ligneY)
      ligneY += 4.5
    }
  }
  doc.setFont('helvetica', 'bold')
  const refs = doc.splitTextToSize(`Référence à rappeler lors du paiement : ${reference}`, largeur)
  doc.text(refs, MARGE, ligneY + 1)
  return ligneY + refs.length * 4.5 + 3
}

const encadre = (doc: jsPDF, yDepart: number, texte: string, couleur: [number, number, number]) => {
  const largeur = doc.internal.pageSize.getWidth() - MARGE * 2
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(9)
  const lignes = doc.splitTextToSize(texte, largeur - 10)
  const hauteur = lignes.length * 4.6 + 6
  const y = place(doc, yDepart, hauteur)
  doc.setFillColor(248, 250, 252)
  doc.rect(MARGE, y, largeur, hauteur, 'F')
  doc.setFillColor(...couleur)
  doc.rect(MARGE, y, 1.6, hauteur, 'F')
  doc.setTextColor(15, 23, 42)
  doc.text(lignes, MARGE + 6, y + 6)
  return y + hauteur + 6
}

/**
 * `signataireRecus` : reprendre la fonction et le nom réglés pour les reçus
 * (le trésorier). Une mise en demeure est signée par le Président, pas par lui.
 */
const signature = (
  doc: jsPDF,
  y: number,
  identity: TenantIdentity,
  fonctionParDefaut: string,
  lieuDate: string,
  signataireRecus: boolean,
) => {
  const pageWidth = doc.internal.pageSize.getWidth()
  const haut = place(doc, y, 25)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(51, 65, 85)
  doc.text(lieuDate, MARGE, haut)
  const x = pageWidth - MARGE - 60
  doc.setFont('helvetica', 'bold')
  doc.setTextColor(15, 23, 42)
  doc.text((signataireRecus && identity.settings?.recu_label_signature) || fonctionParDefaut, x, haut)
  if (signataireRecus && identity.settings?.recu_nom_signataire) {
    doc.setFont('helvetica', 'normal')
    doc.text(identity.settings.recu_nom_signataire, x, haut + 5)
  }
}

const lieu = (identity: TenantIdentity) => {
  const adresse = String(identity.settings?.address || '')
  const ville = adresse.split(',').map((s) => s.trim()).filter(Boolean).pop()
  return ville || 'Kinshasa'
}

const dessinerNote = (doc: jsPDF, identity: TenantIdentity, note: DocumentNote, comptes: CompteDePaiement[]) => {
  const numero = note.numero_recu || '—'
  const emise = note.date_encaissement ? dateLongue(note.date_encaissement) : '—'
  let y = drawTenantHeader(doc, identity, { title: 'Note de débit', subtitle: `N° ${numero} · émise le ${emise}` })
  const { date: echeance, annee } = echeanceCotisation(note.date_encaissement)
  const emiseApresEcheance = note.date_encaissement ? new Date(note.date_encaissement) > echeance : false

  y = blocDebiteur(doc, y + 2, note.expert, [
    ['N° de note', numero],
    ['Exercice', String(annee)],
    ['Échéance', emiseApresEcheance ? 'À réception' : format(echeance, 'dd/MM/yyyy')],
  ])

  const total = toNumber(note.montant_total)
  const paye = toNumber(note.montant_paye)
  const reste = toNumber(note.reste_du)
  const corps = note.articles.map((a) => [
    a.libelle,
    toNumber(a.quantite) === 1 ? '1' : formatAmount(a.quantite, toNumber(a.quantite) % 1 ? 2 : 0),
    formatAmount(a.prix_unitaire),
    formatAmount(a.montant),
  ])
  const pied: any[] = [
    [{ content: 'Total de la note', colSpan: 3, styles: { halign: 'right' } }, formatAmount(total)],
  ]
  if (paye > 0) {
    pied.push([{ content: 'Déjà réglé', colSpan: 3, styles: { halign: 'right' } }, `- ${formatAmount(paye)}`])
  }
  pied.push([
    { content: 'RESTE À PAYER (USD)', colSpan: 3, styles: { halign: 'right', fontStyle: 'bold' } },
    { content: formatAmount(reste), styles: { fontStyle: 'bold' } },
  ])

  autoTable(doc, {
    startY: y,
    head: [['Désignation', 'Qté', 'Prix unitaire', 'Montant (USD)']],
    body: corps,
    foot: pied,
    theme: 'grid',
    margin: { left: MARGE, right: MARGE },
    styles: { font: 'helvetica', fontSize: 9, cellPadding: 2.4, lineColor: [226, 232, 240], lineWidth: 0.2 },
    headStyles: { fillColor: VERT, textColor: 255, fontStyle: 'bold' },
    footStyles: { fillColor: [240, 253, 244], textColor: [15, 23, 42], fontStyle: 'normal' },
    columnStyles: {
      1: { halign: 'right', cellWidth: 16 },
      2: { halign: 'right', cellWidth: 32 },
      3: { halign: 'right', cellWidth: 36 },
    },
  })
  y = ((doc as any).lastAutoTable?.finalY ?? y) + 6

  y = place(doc, y, 10)
  doc.setFont('helvetica', 'italic')
  doc.setFontSize(8.5)
  doc.setTextColor(51, 65, 85)
  const enLettres = doc.splitTextToSize(
    `Arrêtée la présente note à la somme de : ${numberToWords(reste)}.`,
    doc.internal.pageSize.getWidth() - MARGE * 2,
  )
  doc.text(enLettres, MARGE, y)
  y += enLettres.length * 4.5 + 5

  y = blocPaiement(doc, y, comptes, numero)
  if (reste > 0) {
    y = encadre(
      doc,
      y,
      `À défaut de paiement avant le 31 décembre ${annee}, le membre ne pourra être inscrit au Tableau de l'Ordre ${
        annee + 1
      } (art. 12 du Règlement intérieur).`,
      VERT,
    )
  }
  signature(doc, y + 4, identity, 'Le Trésorier', `Fait à ${lieu(identity)}, le ${format(new Date(), 'dd/MM/yyyy')}`, true)
}

/** Une page par note : la sélection de la liste, ou toutes les notes d'un import. */
export async function generateNotesDebitPDF(notes: DocumentNote[], comptes: CompteDePaiement[]) {
  if (!notes.length) return
  const identity = await loadTenantIdentity()
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  notes.forEach((note, index) => {
    if (index > 0) doc.addPage()
    dessinerNote(doc, identity, note, comptes)
  })
  ouvrir(doc, identity)
}

/** Mise en demeure d'un membre : toutes ses notes non soldées, un délai, une échéance. */
export async function generateMiseEnDemeurePDF(releve: MiseEnDemeure) {
  const identity = await loadTenantIdentity()
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const largeur = doc.internal.pageSize.getWidth() - MARGE * 2
  const echeance = format(new Date(releve.echeance), 'dd/MM/yyyy')
  const totalDu = toNumber(releve.total_du)

  let y = drawTenantHeader(doc, identity, {
    title: 'Mise en demeure',
    subtitle: `Émise le ${dateLongue(releve.emise_le)} · délai de ${releve.delai_jours} jours`,
  })
  doc.setDrawColor(...ROUGE)
  doc.setLineWidth(0.8)
  doc.line(MARGE, y - 3, MARGE + 40, y - 3)

  y = blocDebiteur(doc, y + 2, releve.expert, [
    ['Notes non soldées', String(releve.notes.length)],
    ['Total dû', usd(totalDu)],
    ['À régler au plus tard le', echeance],
  ])

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9.5)
  doc.setTextColor(15, 23, 42)
  const civilite = releve.expert.type_ec === 'SEC' ? 'Madame, Monsieur le Gérant,' : 'Chère Consœur, Cher Confrère,'
  const paragraphe = doc.splitTextToSize(
    `${civilite}\n\nSauf erreur de notre part, vous restez redevable envers l'Ordre de la somme de ${usd(
      totalDu,
    )} (${numberToWords(totalDu)}), au titre des notes de débit détaillées ci-dessous. Malgré les rappels qui vous ont été adressés, ces notes demeurent impayées.\n\nPar la présente, nous vous mettons en demeure de régler cette somme au plus tard le ${echeance}, soit dans un délai de ${
      releve.delai_jours
    } jours à compter de la date d'émission.`,
    largeur,
  )
  doc.text(paragraphe, MARGE, y)
  y += paragraphe.length * 4.1 + 2

  autoTable(doc, {
    startY: y,
    head: [['N° de note', 'Date', 'Libellés', 'Montant', 'Réglé', 'Reste dû']],
    body: releve.notes.map((n) => [
      n.numero_recu || '—',
      n.date_encaissement ? format(new Date(n.date_encaissement), 'dd/MM/yyyy') : '—',
      n.articles.map((a) => a.libelle).join(', '),
      formatAmount(n.montant_total),
      formatAmount(n.montant_paye),
      formatAmount(n.reste_du),
    ]),
    foot: [
      [
        { content: 'TOTAL DÛ (USD)', colSpan: 5, styles: { halign: 'right', fontStyle: 'bold' } },
        { content: formatAmount(totalDu), styles: { fontStyle: 'bold' } },
      ],
    ],
    theme: 'grid',
    margin: { left: MARGE, right: MARGE },
    styles: { font: 'helvetica', fontSize: 8.5, cellPadding: 2.2, lineColor: [226, 232, 240], lineWidth: 0.2 },
    headStyles: { fillColor: ROUGE, textColor: 255, fontStyle: 'bold' },
    footStyles: { fillColor: [254, 242, 242], textColor: [15, 23, 42] },
    columnStyles: {
      0: { cellWidth: 30 },
      1: { cellWidth: 20 },
      3: { halign: 'right', cellWidth: 24 },
      4: { halign: 'right', cellWidth: 22 },
      5: { halign: 'right', cellWidth: 24 },
    },
  })
  y = ((doc as any).lastAutoTable?.finalY ?? y) + 6

  y = encadre(
    doc,
    y,
    `À défaut de règlement dans ce délai, le Conseil se réserve d'engager les mesures prévues par le Règlement intérieur de l'Ordre, notamment la non-inscription au Tableau de l'Ordre de l'exercice suivant.`,
    ROUGE,
  )
  y = blocPaiement(doc, y, releve.comptes, releve.notes.map((n) => n.numero_recu).filter(Boolean).join(', ') || releve.expert.numero_ordre)
  y = place(doc, y, 10)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(51, 65, 85)
  doc.text(
    "Si vous avez réglé ces sommes entre-temps, nous vous prions de ne pas tenir compte de la présente.",
    MARGE,
    y,
  )
  signature(
    doc,
    y + 12,
    identity,
    'Le Président',
    `Fait à ${lieu(identity)}, le ${format(new Date(releve.emise_le), 'dd/MM/yyyy')}`,
    false,
  )
  ouvrir(doc, identity)
}
