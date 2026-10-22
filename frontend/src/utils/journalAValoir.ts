import { formatAmount, toNumber } from './amount'

/**
 * Avances « à valoir » dans le journal de trésorerie : une créance sur le
 * bénéficiaire, qui doit sauter aux yeux des utilisateurs et des autorités.
 * Mêmes couleurs et mêmes mots dans l'Excel, le PDF, l'écran et les annexes
 * envoyées par le serveur (`backend/app/services/journaux_annexes.py`).
 */
export const A_VALOIR_BORDEAUX = '800020'
export const A_VALOIR_FOND = 'F8E1E6'
export const A_VALOIR_PREFIXE = 'À VALOIR — '

type LigneAValoir = {
  a_valoir?: boolean | null
  a_valoir_statut?: string | null
  a_valoir_reste?: number | string | null
}

/** Libellé d'export : le préfixe garde l'alerte lisible en impression noir et blanc. */
export function libelleAvecAValoir(ligne: LigneAValoir, libelle: string): string {
  return ligne.a_valoir ? `${A_VALOIR_PREFIXE}${libelle}` : libelle
}

/** Seconde ligne du libellé dans le PDF : où en est l'avance. */
export function etatAValoir(ligne: LigneAValoir, devise: string): string {
  const statut = ligne.a_valoir_statut === 'EN_RETARD'
    ? 'justificatif EN RETARD'
    : ligne.a_valoir_statut === 'RECU'
      ? 'justificatif reçu'
      : ligne.a_valoir_statut === 'DISPENSE'
        ? 'justificatif dispensé'
        : ligne.a_valoir_statut === 'ATTENDU'
          ? 'justificatif attendu'
          : 'justificatif non demandé'
  return `${statut} · reste à justifier : ${formatAmount(toNumber(ligne.a_valoir_reste))} ${devise}`
}

export type BilanAValoir = { nombre: number; enRetard: number; reste: number }

export function bilanAValoir(lignes: LigneAValoir[]): BilanAValoir {
  const avances = lignes.filter((ligne) => ligne.a_valoir)
  return {
    nombre: avances.length,
    enRetard: avances.filter((ligne) => ligne.a_valoir_statut === 'EN_RETARD').length,
    reste: avances.reduce((total, ligne) => total + toNumber(ligne.a_valoir_reste), 0),
  }
}

/** Phrase d'alerte en tête des exports, vide s'il n'y a aucune avance. */
export function alerteAValoir(bilan: BilanAValoir, devise: string): string {
  if (!bilan.nombre) return ''
  const retard = bilan.enRetard
    ? `, dont ${bilan.enRetard} au justificatif en retard`
    : ''
  return (
    `Avances à valoir : ${bilan.nombre} sur la période${retard} — reste à justifier : ` +
    `${formatAmount(bilan.reste)} ${devise}. Lignes signalées en bordeaux.`
  )
}
