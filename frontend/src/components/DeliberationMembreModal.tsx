import { useEffect, useState } from 'react'
import { AlertTriangle, FileText, Gavel, Save, Undo2, X } from 'lucide-react'
import {
  delibererMembre,
  getDeliberationMembre,
  revoquerDeliberation,
  type ConclusionTableau,
  type CritereTableau,
  type TableauSituationDeliberation,
} from '../api/tableau'
import { buildUploadUrl, openUploadUrl } from '../utils/uploads'

/** Le membre de la ligne de la base : assez pour le désigner. */
export interface MembreDeliberation {
  numero_ordre: string | null
  nom: string
  categorie: string
}

export const LIBELLES_DECISION: Record<ConclusionTableau, string> = {
  INSCRIT: 'En règle',
  'NON INSCRIT': 'Non en règle',
  'À DÉLIBÉRER': 'À délibérer',
}

export const LIBELLES_CRITERE: Record<CritereTableau, string> = {
  cotisation: 'Cotisation',
  formation: 'Formation (NHV)',
  assurance: 'Assurance',
  chiffre_affaires: "Chiffre d'affaires",
}

export const champ: React.CSSProperties = { display: 'grid', gap: '5px', fontSize: '12px', fontWeight: 600 }
export const saisie: React.CSSProperties = { padding: '8px 10px', border: '1px solid #c9ccd2', borderRadius: '5px', fontWeight: 400 }
export const bouton: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '8px 12px',
  border: '1px solid #c9ccd2', borderRadius: '5px', background: '#fff', cursor: 'pointer', fontSize: '13px',
}
export const puce: React.CSSProperties = {
  padding: '4px 9px', border: '1px solid #c9ccd2', borderRadius: '999px', background: '#f9fafb',
  cursor: 'pointer', fontSize: '12px', fontWeight: 400,
}

const libelle = (conclusion: string | null | undefined) =>
  (conclusion && LIBELLES_DECISION[conclusion as ConclusionTableau]) || conclusion || 'Sans conclusion'

const dateFr = (valeur: string | null | undefined) => (valeur ? new Date(valeur).toLocaleDateString('fr-FR') : '')

/**
 * Délibération de la commission sur un membre : le mettre en règle, ou l'en
 * retirer, pour l'exercice. Le calcul automatique reste affiché à côté ; une
 * nouvelle délibération remplace celle qui était en vigueur.
 */
export default function DeliberationMembreModal({
  membre,
  exercice,
  criteres,
  onClose,
  onSaved,
}: {
  membre: MembreDeliberation
  exercice?: string
  /** Critères exigés pour la catégorie du membre. */
  criteres: CritereTableau[]
  onClose: () => void
  onSaved: () => void
}) {
  const [situation, setSituation] = useState<TableauSituationDeliberation | null>(null)
  const [decision, setDecision] = useState<ConclusionTableau | ''>('')
  const [motif, setMotif] = useState('')
  const [criteresCoches, setCriteresCoches] = useState<string[]>([])
  const [reference, setReference] = useState('')
  const [observation, setObservation] = useState('')
  const [piece, setPiece] = useState<File | null>(null)
  const [revocation, setRevocation] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    if (!membre.numero_ordre) return
    let actif = true
    getDeliberationMembre(membre.numero_ordre, exercice)
      .then(donnees => {
        if (!actif) return
        setSituation(donnees)
        // Par défaut, l'inverse de ce que dit le calcul : retirer un membre en règle, mettre en règle les autres.
        setDecision(donnees.conclusion_automatique === 'INSCRIT' ? 'NON INSCRIT' : 'INSCRIT')
      })
      .catch((error: any) => { if (actif) setErreur(error?.message || 'La situation du membre est introuvable.') })
    return () => { actif = false }
  }, [membre.numero_ordre, exercice])

  const automatique = situation?.conclusion_automatique ?? null
  const enVigueur = situation?.deliberation ?? null
  const choix = (Object.keys(LIBELLES_DECISION) as ConclusionTableau[]).filter(code => code !== automatique)
  const miseEnRegle = decision === 'INSCRIT'
  const suggestions = situation ? (miseEnRegle ? situation.motifs_suggeres.mise_en_regle : situation.motifs_suggeres.retrait) : []
  const anciennes = (situation?.historique ?? []).filter(item => item.id !== enVigueur?.id)

  const manque = (() => {
    if (!membre.numero_ordre) return "Ce membre n'a pas de N° d'ordre : corrigez-le d'abord."
    if (!situation) return null
    if (!decision) return 'Choisissez la décision.'
    if (!motif.trim()) return 'Indiquez le motif.'
    return null
  })()

  const basculerCritere = (critere: string) =>
    setCriteresCoches(actuels => actuels.includes(critere) ? actuels.filter(c => c !== critere) : [...actuels, critere])

  const enregistrer = async () => {
    if (manque || !decision || !membre.numero_ordre || !situation) return
    setEnCours(true)
    setErreur(null)
    try {
      await delibererMembre({
        numero_ordre: membre.numero_ordre,
        exercice: situation.exercice,
        conclusion: decision,
        motif,
        criteres: criteresCoches,
        reference_seance: reference,
        observation,
        piece,
      })
      onSaved()
    } catch (error: any) {
      setErreur(error?.message || "La délibération n'a pas pu être enregistrée.")
    } finally {
      setEnCours(false)
    }
  }

  const revoquer = async () => {
    if (!enVigueur || !revocation?.trim()) return
    setEnCours(true)
    setErreur(null)
    try {
      await revoquerDeliberation(enVigueur.id, revocation)
      onSaved()
    } catch (error: any) {
      setErreur(error?.message || "La délibération n'a pas pu être révoquée.")
    } finally {
      setEnCours(false)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="tableau-deliberation-title"
      style={{ position: 'fixed', inset: 0, zIndex: 80, background: 'rgba(17, 24, 39, 0.45)', display: 'grid', placeItems: 'center', padding: '16px' }}
      onMouseDown={event => { if (event.target === event.currentTarget && !enCours) onClose() }}
    >
      <div style={{ width: 'min(600px, 100%)', maxHeight: '90vh', overflowY: 'auto', background: '#fff', borderRadius: '8px', border: '1px solid #d8dadd', boxShadow: '0 20px 50px rgba(0,0,0,.22)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', padding: '16px 16px 0' }}>
          <div>
            <h2 id="tableau-deliberation-title" style={{ margin: 0, fontSize: '17px' }}>Délibération de la commission</h2>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#6b7280' }}>
              {membre.nom} · {membre.numero_ordre || "sans N° d'ordre"} · {membre.categorie}
              {situation ? ` · exercice ${situation.exercice}` : ''}
            </p>
          </div>
          <button type="button" style={bouton} onClick={onClose} disabled={enCours} title="Fermer" aria-label="Fermer">
            <X size={16} />
          </button>
        </div>

        {!situation && !erreur && <p style={{ padding: '16px', margin: 0, fontSize: '13px', color: '#6b7280' }}>Chargement de la situation…</p>}

        {situation && (
          <div style={{ padding: '16px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' }}>
            <div style={{ gridColumn: '1 / -1', padding: '10px 12px', borderRadius: '6px', background: '#f3f4f6', fontSize: '13px' }}>
              Le calcul conclut : <strong>{libelle(automatique)}</strong>
              {situation.conclusion !== automatique && <> · conclusion retenue : <strong>{libelle(situation.conclusion)}</strong></>}
            </div>

            {enVigueur && (
              <div style={{ gridColumn: '1 / -1', padding: '10px 12px', borderRadius: '6px', border: '1px solid #c7d2fe', background: '#eef2ff', fontSize: '13px', display: 'grid', gap: '6px' }}>
                <span>
                  <strong>Délibération en vigueur</strong> du {dateFr(enVigueur.created_at)} : {enVigueur.libelle}
                </span>
                {enVigueur.diverge && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', color: '#92400e' }}>
                    <AlertTriangle size={14} /> Les données ont changé depuis : le calcul conclurait « {libelle(enVigueur.verdict_automatique)} ».
                  </span>
                )}
                {enVigueur.piece_path && (
                  <button type="button" style={{ ...bouton, justifySelf: 'start' }} onClick={() => void openUploadUrl(buildUploadUrl(enVigueur.piece_path!))}>
                    <FileText size={14} /> {enVigueur.piece_nom || 'Pièce enregistrée'}
                  </button>
                )}
                {revocation === null ? (
                  <button type="button" style={{ ...bouton, justifySelf: 'start' }} onClick={() => setRevocation('')} disabled={enCours}>
                    <Undo2 size={14} /> Révoquer cette délibération
                  </button>
                ) : (
                  <div style={{ display: 'grid', gap: '6px' }}>
                    <label style={champ}>
                      Motif de la révocation
                      <input value={revocation} onChange={event => setRevocation(event.target.value)} maxLength={2000} autoFocus style={saisie} />
                    </label>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button type="button" style={bouton} onClick={() => setRevocation(null)} disabled={enCours}>Annuler</button>
                      <button type="button" style={bouton} onClick={() => void revoquer()} disabled={enCours || !revocation.trim()}>
                        <Undo2 size={14} /> Révoquer : le calcul reprend la main
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            <label style={champ}>
              {enVigueur ? 'Nouvelle décision' : 'Décision'}
              <select value={decision} onChange={event => setDecision(event.target.value as ConclusionTableau)} style={saisie}>
                {choix.map(code => <option key={code} value={code}>{LIBELLES_DECISION[code]}</option>)}
              </select>
            </label>
            <label style={champ}>
              Séance ou référence (facultative)
              <input value={reference} onChange={event => setReference(event.target.value)} maxLength={200} placeholder="Séance du 20/11/2026, délibération n°…" style={saisie} />
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
              <fieldset style={{ gridColumn: '1 / -1', border: 'none', padding: 0, margin: 0, display: 'grid', gap: '6px' }}>
                <legend style={{ fontSize: '12px', fontWeight: 600, marginBottom: '5px' }}>
                  {miseEnRegle ? 'Critères levés par la décision (facultatif)' : 'Critères retenus contre le membre (facultatif)'}
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
              Pièce justificative (facultative)
              <input type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={event => setPiece(event.target.files?.[0] || null)} style={{ fontWeight: 400 }} />
              <span style={{ fontWeight: 400, color: '#6b7280' }}>Extrait du PV, preuve de paiement… · PDF, JPG ou PNG, 5 Mo au plus</span>
            </label>

            <label style={{ ...champ, gridColumn: '1 / -1' }}>
              Observation (facultative)
              <textarea value={observation} onChange={event => setObservation(event.target.value)} rows={2} maxLength={2000} style={{ ...saisie, resize: 'vertical' }} />
            </label>

            <p style={{ gridColumn: '1 / -1', margin: 0, fontSize: '12px', color: '#4b5563' }}>
              La décision vaut pour l'exercice {situation.exercice} et prime sur le calcul partout : Base, tableau de bord,
              exports, PV et relevé de situation. Si les données changent ensuite, l'écart sera signalé.
            </p>

            {anciennes.length > 0 && (
              <details style={{ gridColumn: '1 / -1', fontSize: '12px' }}>
                <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Délibérations précédentes ({anciennes.length})</summary>
                <ul style={{ margin: '6px 0 0', paddingLeft: '18px', display: 'grid', gap: '4px' }}>
                  {anciennes.map(item => (
                    <li key={item.id}>
                      {dateFr(item.created_at)} : {item.libelle}
                      {item.revoquee_le && <> — révoquée le {dateFr(item.revoquee_le)}{item.motif_revocation ? ` (${item.motif_revocation})` : ''}</>}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}

        {erreur && <p role="alert" style={{ margin: '0 16px 12px', color: '#991b1b', fontSize: '13px' }}>{erreur}</p>}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', padding: '0 16px 16px', flexWrap: 'wrap', alignItems: 'center' }}>
          {manque && <span style={{ fontSize: '12px', color: '#6b7280' }}>{manque}</span>}
          <button type="button" style={bouton} onClick={onClose} disabled={enCours}>Annuler</button>
          <button
            type="button"
            disabled={enCours || !!manque || !situation}
            onClick={() => void enregistrer()}
            style={{ ...bouton, background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)', opacity: enCours || manque || !situation ? 0.6 : 1 }}
          >
            {enCours ? <Save size={15} /> : <Gavel size={15} />} {enCours ? 'Enregistrement...' : 'Enregistrer la délibération'}
          </button>
        </div>
      </div>
    </div>
  )
}
