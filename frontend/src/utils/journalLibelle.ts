type LigneJournalLibelle = {
  libelle?: string | null
  libelle_base?: string | null
  precision?: string | null
  reference?: string | null
}

/**
 * Libellé complet d'une ligne du journal, pour le PDF et l'Excel :
 * « Cotisation (payé par X · note 123 · réf. VIR-45) ». Une seule parenthèse
 * réunit les précisions (qui a payé, qui a reçu) et la référence, plutôt que
 * d'en aligner deux à la suite.
 */
export function libelleJournalComplet(ligne: LigneJournalLibelle): string {
  const reference = (ligne.reference || '').trim()
  if (ligne.precision) {
    const base = (ligne.libelle_base || '').trim()
    const details = [ligne.precision, reference ? `réf. ${reference}` : ''].filter(Boolean).join(' · ')
    return base ? `${base} (${details})` : details
  }
  // Réponse d'une API antérieure aux précisions : forme historique.
  return `${(ligne.libelle || '').trim()}${reference ? ` (${reference})` : ''}`.trim()
}
