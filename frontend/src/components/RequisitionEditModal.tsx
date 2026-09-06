import { useEffect, useMemo, useState } from 'react'
import { Plus, Trash2, X } from 'lucide-react'
import BudgetPosteSelect from './BudgetPosteSelect'
import { apiRequest } from '../lib/apiClient'
import {
  createLignesRequisition,
  deleteLigneRequisition,
  updateLigneRequisition,
  updateRequisition,
  type LigneRequisitionApi,
} from '../api/lignesRequisition'
import type { BudgetPosteSummary } from '../types/budget'
import { toNumber } from '../utils/amount'
import { motifVerrouRequisition } from '../utils/requisitionLock'
import styles from './RequisitionEditModal.module.css'

interface RequisitionAModifier {
  id: string
  numero_requisition?: string | null
  objet?: string | null
  beneficiaire?: string | null
  notes_a_valoir?: string | null
  service_id?: number | null
  status?: string | null
  statut?: string | null
  examen_status?: string | null
  examen_par?: string | null
  montant_total?: number | string | null
}

interface Props {
  requisition: RequisitionAModifier
  /** Identifiant de l'utilisateur courant : décide du droit de modifier. */
  utilisateurId?: string | null
  onClose: () => void
  /** Appelé après enregistrement, pour que l'écran appelant se recharge. */
  onSaved: () => void
}

type LigneEditable = {
  /** Absent = ligne nouvelle, pas encore écrite. */
  id?: string
  budget_poste_id: number | null
  rubrique: string
  description: string
  quantite: string
  montant_unitaire: string
  devise: string
  /** Ligne existante inchangée : rien à envoyer. */
  origine?: LigneRequisitionApi
}

const montantLigne = (ligne: LigneEditable) =>
  toNumber(ligne.quantite || 0) * toNumber(ligne.montant_unitaire || 0)

const formatUsd = (valeur: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(valeur || 0)

function versEditable(ligne: LigneRequisitionApi): LigneEditable {
  return {
    id: ligne.id,
    budget_poste_id: ligne.budget_poste_id,
    rubrique: ligne.rubrique || '',
    description: ligne.description || '',
    quantite: String(ligne.quantite ?? 1),
    montant_unitaire: String(toNumber(ligne.montant_unitaire) || 0),
    devise: ligne.devise || 'USD',
    origine: ligne,
  }
}

function aChange(ligne: LigneEditable): boolean {
  const origine = ligne.origine
  if (!origine) return true
  return (
    origine.budget_poste_id !== ligne.budget_poste_id ||
    (origine.description || '') !== ligne.description ||
    Number(origine.quantite ?? 1) !== toNumber(ligne.quantite) ||
    toNumber(origine.montant_unitaire) !== toNumber(ligne.montant_unitaire)
  )
}

/**
 * Correction d'une réquisition déjà en circuit.
 *
 * Ouverte depuis la fiche de détail, elle sert d'abord à l'examinateur : après
 * son visa, il est le seul à pouvoir reprendre le texte qu'il a validé. Le
 * droit lui-même est tranché par le serveur ; ce composant ne fait que refuser
 * d'ouvrir ce que le serveur refuserait.
 */
export default function RequisitionEditModal({ requisition, utilisateurId, onClose, onSaved }: Props) {
  const [objet, setObjet] = useState(requisition.objet || '')
  const [beneficiaire, setBeneficiaire] = useState(requisition.beneficiaire || '')
  const [notes, setNotes] = useState(requisition.notes_a_valoir || '')
  const [lignes, setLignes] = useState<LigneEditable[]>([])
  const [supprimees, setSupprimees] = useState<string[]>([])
  const [postes, setPostes] = useState<BudgetPosteSummary[]>([])
  const [chargement, setChargement] = useState(true)
  const [enregistrement, setEnregistrement] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)

  const motifVerrou = motifVerrouRequisition(requisition, utilisateurId)

  useEffect(() => {
    let annule = false
    const charger = async () => {
      setChargement(true)
      setErreur(null)
      try {
        const [lignesRes, postesRes] = await Promise.all([
          apiRequest('GET', '/lignes-requisition', { params: { requisition_id: requisition.id } }),
          apiRequest('GET', '/budget/lines/autorisees', {
            params: {
              active: true,
              type: 'DEPENSE',
              service_id: requisition.service_id ?? undefined,
            },
          }),
        ])
        if (annule) return
        const brutes = Array.isArray(lignesRes)
          ? lignesRes
          : (lignesRes as any)?.items ?? (lignesRes as any)?.data ?? []
        setLignes((brutes as LigneRequisitionApi[]).map(versEditable))
        const dispo = (postesRes as any)?.lignes ?? []
        setPostes(Array.isArray(dispo) ? dispo : [])
      } catch (e: any) {
        if (!annule) setErreur(e?.message || 'Chargement impossible.')
      } finally {
        if (!annule) setChargement(false)
      }
    }
    charger()
    return () => {
      annule = true
    }
  }, [requisition.id, requisition.service_id])

  const total = useMemo(
    () => lignes.reduce((somme, ligne) => somme + montantLigne(ligne), 0),
    [lignes]
  )

  const majLigne = (index: number, champs: Partial<LigneEditable>) => {
    setLignes((precedentes) =>
      precedentes.map((ligne, i) => (i === index ? { ...ligne, ...champs } : ligne))
    )
  }

  const retirerLigne = (index: number) => {
    setLignes((precedentes) => {
      const ligne = precedentes[index]
      if (ligne?.id) setSupprimees((ids) => [...ids, ligne.id as string])
      return precedentes.filter((_, i) => i !== index)
    })
  }

  const ajouterLigne = () => {
    setLignes((precedentes) => [
      ...precedentes,
      {
        budget_poste_id: null,
        rubrique: '',
        description: '',
        quantite: '1',
        montant_unitaire: '',
        devise: 'USD',
      },
    ])
  }

  const libellePoste = (posteId: number | null) => {
    const poste = postes.find((p) => p.id === posteId)
    if (!poste) return ''
    return poste.code && poste.libelle ? `${poste.code} - ${poste.libelle}` : poste.code || poste.libelle || ''
  }

  const valider = (): string | null => {
    if (objet.trim().length < 3) return "L'objet doit faire au moins 3 caractères."
    if (lignes.length === 0) return 'Une réquisition budgétaire garde au moins une ligne.'
    for (const [index, ligne] of lignes.entries()) {
      if (!ligne.budget_poste_id) return `Ligne ${index + 1} : poste budgétaire manquant.`
      if (ligne.description.trim().length < 3) return `Ligne ${index + 1} : description trop courte.`
      if (toNumber(ligne.quantite) <= 0) return `Ligne ${index + 1} : quantité invalide.`
      if (toNumber(ligne.montant_unitaire) <= 0) return `Ligne ${index + 1} : prix unitaire invalide.`
    }
    return null
  }

  const enregistrer = async () => {
    const probleme = valider()
    if (probleme) {
      setErreur(probleme)
      return
    }
    setEnregistrement(true)
    setErreur(null)
    try {
      // Les suppressions d'abord : elles libèrent du disponible que les
      // corrections suivantes peuvent réclamer.
      for (const id of supprimees) {
        await deleteLigneRequisition(id)
      }

      for (const ligne of lignes) {
        if (!aChange(ligne)) continue
        const charge = {
          budget_poste_id: ligne.budget_poste_id,
          rubrique: ligne.rubrique || libellePoste(ligne.budget_poste_id) || 'Ligne',
          description: ligne.description.trim(),
          quantite: Math.trunc(toNumber(ligne.quantite)),
          montant_unitaire: toNumber(ligne.montant_unitaire),
          montant_total: montantLigne(ligne),
          devise: ligne.devise || 'USD',
        }
        if (ligne.id) await updateLigneRequisition(ligne.id, charge)
        else await createLignesRequisition([{ ...charge, requisition_id: requisition.id }])
      }

      // L'en-tête en dernier : le montant total est recalculé côté serveur
      // depuis les lignes, inutile de le lui envoyer.
      const enTete: Record<string, unknown> = {}
      if (objet.trim() !== (requisition.objet || '')) enTete.objet = objet.trim()
      if (beneficiaire.trim() !== (requisition.beneficiaire || '')) {
        enTete.beneficiaire = beneficiaire.trim() || null
      }
      if (notes !== (requisition.notes_a_valoir || '')) enTete.notes_a_valoir = notes || null
      if (Object.keys(enTete).length > 0) {
        await updateRequisition(requisition.id, enTete)
      }

      onSaved()
      onClose()
    } catch (e: any) {
      setErreur(e?.message || "L'enregistrement a échoué.")
    } finally {
      setEnregistrement(false)
    }
  }

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby="edit-req-titre">
      <div className={styles.panneau}>
        <div className={styles.entete}>
          <div>
            <h2 id="edit-req-titre">
              Modifier la réquisition {requisition.numero_requisition || ''}
            </h2>
            <p className={styles.sousTitre}>
              La correction repasse par les contrôles budgétaires : poste actif, rubrique autorisée,
              disponible suffisant.
            </p>
          </div>
          <button type="button" className={styles.fermer} onClick={onClose} aria-label="Fermer">
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        {motifVerrou ? (
          <div className={styles.corps}>
            <p className={styles.blocage}>{motifVerrou}</p>
          </div>
        ) : (
          <div className={styles.corps}>
            {erreur && <p className={styles.erreur}>{erreur}</p>}

            <section className={styles.section}>
              <h3>En-tête</h3>
              <div className={styles.grilleChamps}>
                <label className={styles.champ}>
                  <span>Objet</span>
                  <input value={objet} onChange={(e) => setObjet(e.target.value)} />
                </label>
                <label className={styles.champ}>
                  <span>Bénéficiaire</span>
                  <input value={beneficiaire} onChange={(e) => setBeneficiaire(e.target.value)} />
                </label>
                <label className={`${styles.champ} ${styles.champLarge}`}>
                  <span>Notes</span>
                  <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
                </label>
              </div>
            </section>

            <section className={styles.section}>
              <div className={styles.enteteSection}>
                <h3>Lignes de dépense</h3>
                <button type="button" className={styles.ajouter} onClick={ajouterLigne}>
                  <Plus size={14} aria-hidden="true" /> Ajouter une ligne
                </button>
              </div>

              {chargement ? (
                <p className={styles.attente}>Chargement des lignes…</p>
              ) : (
                <div className={styles.lignes}>
                  {lignes.map((ligne, index) => (
                    <div className={styles.ligne} key={ligne.id || `nouvelle-${index}`}>
                      <div className={styles.champPoste}>
                        <span className={styles.etiquette}>Poste budgétaire</span>
                        <BudgetPosteSelect
                          postes={postes}
                          value={ligne.budget_poste_id}
                          onChange={(posteId) =>
                            majLigne(index, {
                              budget_poste_id: posteId,
                              rubrique: libellePoste(posteId) || ligne.rubrique,
                            })
                          }
                          placeholder="Rechercher par code ou libellé"
                          emptyHint="Aucun poste autorisé pour ce service."
                          ariaLabel={`Poste budgétaire de la ligne ${index + 1}`}
                        />
                      </div>
                      <label className={styles.champLigne}>
                        <span className={styles.etiquette}>Description</span>
                        <input
                          value={ligne.description}
                          onChange={(e) => majLigne(index, { description: e.target.value })}
                        />
                      </label>
                      <label className={styles.champPetit}>
                        <span className={styles.etiquette}>Qté</span>
                        <input
                          type="number"
                          min="1"
                          value={ligne.quantite}
                          onChange={(e) => majLigne(index, { quantite: e.target.value })}
                        />
                      </label>
                      <label className={styles.champPetit}>
                        <span className={styles.etiquette}>Prix unitaire</span>
                        <input
                          type="number"
                          min="0"
                          step="0.01"
                          value={ligne.montant_unitaire}
                          onChange={(e) => majLigne(index, { montant_unitaire: e.target.value })}
                        />
                      </label>
                      <div className={styles.champPetit}>
                        <span className={styles.etiquette}>Total</span>
                        <output className={styles.totalLigne}>{formatUsd(montantLigne(ligne))}</output>
                      </div>
                      <button
                        type="button"
                        className={styles.supprimer}
                        onClick={() => retirerLigne(index)}
                        title="Retirer cette ligne"
                        aria-label={`Retirer la ligne ${index + 1}`}
                      >
                        <Trash2 size={15} aria-hidden="true" />
                      </button>
                    </div>
                  ))}
                  {lignes.length === 0 && (
                    <p className={styles.attente}>Aucune ligne : ajoutez-en une avant d'enregistrer.</p>
                  )}
                </div>
              )}

              <div className={styles.totalGeneral}>
                <span>Total de la réquisition</span>
                <strong>{formatUsd(total)}</strong>
              </div>
            </section>
          </div>
        )}

        <div className={styles.pied}>
          <button type="button" className={styles.secondaire} onClick={onClose}>
            {motifVerrou ? 'Fermer' : 'Annuler'}
          </button>
          {!motifVerrou && (
            <button
              type="button"
              className={styles.principal}
              onClick={enregistrer}
              disabled={enregistrement || chargement}
            >
              {enregistrement ? 'Enregistrement…' : 'Enregistrer les corrections'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
