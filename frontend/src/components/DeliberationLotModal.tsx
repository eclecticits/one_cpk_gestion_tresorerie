import { useEffect, useState } from 'react'
import { Gavel, X } from 'lucide-react'
import {
  delibererSelection,
  getMotifsDeliberation,
  type ConclusionTableau,
  type CritereTableau,
  type DeliberationLotSaisie,
  type TableauDeliberationLot,
} from '../api/tableau'
import { LIBELLES_CRITERE, LIBELLES_DECISION, bouton, champ, puce, saisie } from './DeliberationMembreModal'

/**
 * Délibération groupée : la même décision, le même motif et la même séance pour
 * toute une sélection de la Base. Chaque membre reçoit sa propre délibération,
 * révocable seule ; ceux qui ne peuvent pas l'être sont nommés avec la raison.
 */
export default function DeliberationLotModal({
  selection: selectionInitiale,
  libelleSelection: libelleInitial,
  categorieMotifs,
  criteres,
  onClose,
  onDone,
}: {
  selection: Pick<DeliberationLotSaisie, 'exercice' | 'numeros' | 'filtres'>
  libelleSelection: string
  /** « Société » quand la sélection ne vise que des sociétés : leurs motifs sont alors proposés. */
  categorieMotifs?: string
  /** Critères exigés pour la catégorie visée, ou tous si la sélection en mêle plusieurs. */
  criteres: CritereTableau[]
  onClose: () => void
  /** La Base a changé : à recharger, même si la fenêtre reste ouverte sur le résultat. */
  onDone: () => void
}) {
  // Figées à l'ouverture : la page vide sa sélection dès que le lot est enregistré.
  const [selection] = useState(selectionInitiale)
  const [libelleSelection] = useState(libelleInitial)
  const [decision, setDecision] = useState<ConclusionTableau>(categorieMotifs ? 'NON INSCRIT' : 'INSCRIT')
  const [motifs, setMotifs] = useState<{ mise_en_regle: string[]; retrait: string[] } | null>(null)
  const [motif, setMotif] = useState('')
  const [criteresCoches, setCriteresCoches] = useState<string[]>([])
  const [reference, setReference] = useState('')
  const [observation, setObservation] = useState('')
  const [confirme, setConfirme] = useState(false)
  const [resultat, setResultat] = useState<TableauDeliberationLot | null>(null)
  const [enCours, setEnCours] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    let actif = true
    getMotifsDeliberation(categorieMotifs)
      .then(donnees => { if (actif) setMotifs(donnees) })
      .catch(() => { if (actif) setMotifs({ mise_en_regle: [], retrait: [] }) })
    return () => { actif = false }
  }, [categorieMotifs])

  const suggestions = motifs ? (decision === 'INSCRIT' ? motifs.mise_en_regle : motifs.retrait) : []
  const manque = !motif.trim() ? 'Indiquez le motif.' : !confirme ? 'Cochez la confirmation.' : null

  const basculerCritere = (critere: string) =>
    setCriteresCoches(actuels => actuels.includes(critere) ? actuels.filter(c => c !== critere) : [...actuels, critere])

  const enregistrer = async () => {
    if (manque) return
    setEnCours(true)
    setErreur(null)
    try {
      setResultat(await delibererSelection({
        ...selection,
        conclusion: decision,
        motif,
        criteres: criteresCoches,
        reference_seance: reference || undefined,
        observation: observation || undefined,
      }))
      onDone()
    } catch (error: any) {
      setErreur(error?.message || "La délibération groupée n'a pas pu être enregistrée.")
    } finally {
      setEnCours(false)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="tableau-deliberation-lot-title"
      style={{ position: 'fixed', inset: 0, zIndex: 80, background: 'rgba(17, 24, 39, 0.45)', display: 'grid', placeItems: 'center', padding: '16px' }}
      onMouseDown={event => { if (event.target === event.currentTarget && !enCours) onClose() }}
    >
      <div style={{ width: 'min(600px, 100%)', maxHeight: '90vh', overflowY: 'auto', background: '#fff', borderRadius: '8px', border: '1px solid #d8dadd', boxShadow: '0 20px 50px rgba(0,0,0,.22)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', padding: '16px 16px 0' }}>
          <div>
            <h2 id="tableau-deliberation-lot-title" style={{ margin: 0, fontSize: '17px' }}>Délibération groupée</h2>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#6b7280' }}>{libelleSelection}</p>
          </div>
          <button type="button" style={bouton} onClick={onClose} disabled={enCours} title="Fermer" aria-label="Fermer">
            <X size={16} />
          </button>
        </div>

        {resultat ? (
          <div style={{ padding: '16px', display: 'grid', gap: '10px', fontSize: '13px' }}>
            <p style={{ margin: 0 }}>
              <strong>{resultat.deliberes.length}</strong> membre(s) délibéré(s) : {LIBELLES_DECISION[decision]}.
            </p>
            {resultat.ecartes.length > 0 && (
              <details open={resultat.deliberes.length === 0}>
                <summary style={{ cursor: 'pointer', fontWeight: 600 }}>{resultat.ecartes.length} écarté(s)</summary>
                <ul style={{ margin: '6px 0 0', paddingLeft: '18px', display: 'grid', gap: '3px' }}>
                  {resultat.ecartes.map((item, index) => (
                    <li key={`${item.numero_ordre}-${index}`}>{item.nom} ({item.numero_ordre || "sans N° d'ordre"}) : {item.raison}</li>
                  ))}
                </ul>
              </details>
            )}
            <p style={{ margin: 0, color: '#4b5563' }}>Chaque délibération se revoit ou se révoque seule, depuis le bouton de la ligne.</p>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button type="button" style={bouton} onClick={onClose}>Fermer</button>
            </div>
          </div>
        ) : (
          <>
            <div style={{ padding: '16px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' }}>
              <label style={champ}>
                Décision
                <select value={decision} onChange={event => setDecision(event.target.value as ConclusionTableau)} style={saisie}>
                  {(Object.keys(LIBELLES_DECISION) as ConclusionTableau[]).map(code => <option key={code} value={code}>{LIBELLES_DECISION[code]}</option>)}
                </select>
              </label>
              <label style={champ}>
                Séance ou référence (facultative)
                <input value={reference} onChange={event => setReference(event.target.value)} maxLength={200} placeholder="Séance du 24/11/2026, délibération n°…" style={saisie} />
              </label>

              <div style={{ ...champ, gridColumn: '1 / -1' }}>
                Motif
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {suggestions.map(texte => (
                    <button key={texte} type="button" style={{ ...puce, ...(motif === texte ? { borderColor: '#1f6b5c', background: '#e7f3ef' } : {}) }} onClick={() => setMotif(texte)}>
                      {texte}
                    </button>
                  ))}
                </div>
                <textarea
                  value={motif}
                  onChange={event => setMotif(event.target.value)}
                  rows={2}
                  maxLength={2000}
                  placeholder="Choisissez un motif ci-dessus ou écrivez le vôtre"
                  aria-label="Motif"
                  style={{ ...saisie, resize: 'vertical' }}
                />
              </div>

              {criteres.length > 0 && (
                <fieldset style={{ gridColumn: '1 / -1', border: 'none', padding: 0, margin: 0 }}>
                  <legend style={{ fontSize: '12px', fontWeight: 600, marginBottom: '5px' }}>
                    {decision === 'INSCRIT' ? 'Critères levés par la décision (facultatif)' : 'Critères retenus (facultatif)'}
                  </legend>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
                    {criteres.map(critere => (
                      <label key={critere} style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '13px' }}>
                        <input type="checkbox" checked={criteresCoches.includes(critere)} onChange={() => basculerCritere(critere)} />
                        {LIBELLES_CRITERE[critere]}
                      </label>
                    ))}
                  </div>
                </fieldset>
              )}

              <label style={{ ...champ, gridColumn: '1 / -1' }}>
                Observation (facultative)
                <textarea value={observation} onChange={event => setObservation(event.target.value)} rows={2} maxLength={2000} style={{ ...saisie, resize: 'vertical' }} />
              </label>

              <p style={{ gridColumn: '1 / -1', margin: 0, fontSize: '12px', color: '#4b5563' }}>
                Sont écartés et nommés : les membres sortis, sans N° d'ordre, déjà délibérés dans ce sens, ou pour qui le
                calcul conclut déjà ainsi. Une délibération en vigueur dans l'autre sens est remplacée.
              </p>
              <label style={{ gridColumn: '1 / -1', display: 'inline-flex', alignItems: 'center', gap: '8px', fontSize: '13px', fontWeight: 600 }}>
                <input type="checkbox" checked={confirme} onChange={event => setConfirme(event.target.checked)} />
                Je confirme : « {LIBELLES_DECISION[decision]} » pour {libelleSelection.toLowerCase()}.
              </label>
            </div>

            {erreur && <p role="alert" style={{ margin: '0 16px 12px', color: '#991b1b', fontSize: '13px' }}>{erreur}</p>}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', padding: '0 16px 16px', flexWrap: 'wrap', alignItems: 'center' }}>
              {manque && <span style={{ fontSize: '12px', color: '#6b7280' }}>{manque}</span>}
              <button type="button" style={bouton} onClick={onClose} disabled={enCours}>Annuler</button>
              <button
                type="button"
                disabled={enCours || !!manque}
                onClick={() => void enregistrer()}
                style={{ ...bouton, background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)', opacity: enCours || manque ? 0.6 : 1 }}
              >
                <Gavel size={15} /> {enCours ? 'Enregistrement...' : 'Délibérer la sélection'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
