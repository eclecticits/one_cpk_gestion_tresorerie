/**
 * Qui peut encore modifier une réquisition — miroir de la règle serveur.
 *
 * La règle vit dans `backend/app/services/historical_snapshots.py`
 * (`requisition_lock_reason`) ; c'est elle qui décide, le serveur refuse de
 * toute façon. Ce module ne sert qu'à ne pas proposer un bouton qui finirait
 * en 409. Les deux doivent dire la même chose : toute évolution de l'un
 * appelle l'autre.
 */

/** Statuts qui ferment la pièce à tout le monde, examinateur compris. */
const STATUTS_VERROUILLES = new Set([
  'AUTORISEE',
  'APPROUVEE',
  'PAYEE',
  'SIGNEE',
  'EN_DECAISSEMENT',
])

type RequisitionVerrouillable = {
  status?: string | null
  statut?: string | null
  examen_status?: string | null
  examen_par?: string | null
  workflow_snapshot?: any
  montant_total?: number | string | null
}

const majuscules = (valeur?: string | null) => String(valeur ?? '').trim().toUpperCase()

export function requisitionFinalisee(req: RequisitionVerrouillable): boolean {
  return STATUTS_VERROUILLES.has(majuscules(req.status ?? req.statut))
}

/** L'examen fait-il partie du circuit figé sur CETTE pièce ? */
export function examenAuCircuit(req: RequisitionVerrouillable): boolean {
  const etape = req.workflow_snapshot?.steps?.examen
  // Sans snapshot, le circuit par défaut est le circuit complet : l'examen en
  // fait partie. Supposer l'inverse afficherait un bouton que le serveur
  // refuserait.
  if (etape === undefined || etape === null) return true
  if (typeof etape === 'boolean') return etape
  return etape.enabled !== false
}

/**
 * Le motif qui ferme la pièce à cet utilisateur, ou null s'il peut la modifier.
 */
export function motifVerrouRequisition(
  req: RequisitionVerrouillable | null | undefined,
  utilisateurId?: string | null
): string | null {
  if (!req) return 'Réquisition introuvable'
  if (requisitionFinalisee(req)) {
    return `Réquisition validée (${majuscules(req.status ?? req.statut)}) : elle n'est plus modifiable.`
  }
  if (examenAuCircuit(req) && majuscules(req.examen_status) === 'EXAMINE') {
    const examinateur = req.examen_par ? String(req.examen_par) : null
    if (utilisateurId && examinateur && String(utilisateurId) === examinateur) return null
    return "Réquisition visée par l'examen : seul l'examinateur qui l'a visée peut la modifier."
  }
  return null
}

export function peutModifierRequisition(
  req: RequisitionVerrouillable | null | undefined,
  utilisateurId?: string | null
): boolean {
  return motifVerrouRequisition(req, utilisateurId) === null
}
