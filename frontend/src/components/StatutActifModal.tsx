import { useEffect, useState } from 'react'
import { FileText, Power, PowerOff, Undo2, X } from 'lucide-react'
import {
  annulerStatutActif,
  declarerStatutActif,
  getStatutActifMembre,
  type TableauSituationStatutActif,
} from '../api/tableau'
import { buildUploadUrl, openUploadUrl } from '../utils/uploads'
import { bouton, champ, puce, saisie } from './DeliberationMembreModal'

/** Le membre de la ligne de la base : assez pour le désigner. */
export interface MembreStatutActif {
  numero_ordre: string | null
  nom: string
  categorie: string
}

const aujourdHui = () => new Date().toISOString().slice(0, 10)
const dateFr = (valeur: string | null | undefined) => (valeur ? new Date(valeur).toLocaleDateString('fr-FR') : '')

/**
 * Rendre un membre inactif, ou le réactiver. Le statut déclaré prime sur le
 * fichier des personnes physiques ; une société, que son fichier ne dit pas
 * active ou non, est tenue pour active tant qu'on ne l'a pas déclarée inactive.
 * La conclusion ne change pas : le membre est seulement écarté des comptes « Actifs ».
 */
export default function StatutActifModal({
  membre,
  exercice,
  onClose,
  onSaved,
}: {
  membre: MembreStatutActif
  exercice?: string
  onClose: () => void
  onSaved: () => void
}) {
  const [situation, setSituation] = useState<TableauSituationStatutActif | null>(null)
  const [dateEffet, setDateEffet] = useState(aujourdHui())
  const [motif, setMotif] = useState('')
  const [reference, setReference] = useState('')
  const [observation, setObservation] = useState('')
  const [piece, setPiece] = useState<File | null>(null)
  const [annulation, setAnnulation] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    if (!membre.numero_ordre) return
    let actif = true
    getStatutActifMembre(membre.numero_ordre, exercice)
      .then(donnees => { if (actif) setSituation(donnees) })
      .catch((error: any) => { if (actif) setErreur(error?.message || 'La situation du membre est introuvable.') })
    return () => { actif = false }
  }, [membre.numero_ordre, exercice])

  const morale = situation?.personne === 'PM'
  const declaration = situation?.statut_actif ?? null
  // On déclare toujours l'inverse du statut retenu ; sans statut connu, on déclare inactif.
  const cible = situation?.actif === false
  const etat = (actif: boolean | null | undefined) =>
    actif == null ? 'non renseigné' : actif ? (morale ? 'active' : 'actif') : (morale ? 'inactive' : 'inactif')
  const source = declaration
    ? 'déclaré à la main'
    : situation?.actif_fichier != null ? 'fichier des personnes physiques' : morale ? 'par défaut, faute de déclaration' : 'non renseigné au fichier'
  const suggestions = situation ? (cible ? situation.motifs_suggeres.actif : situation.motifs_suggeres.inactif) : []
  const anciennes = (situation?.historique ?? []).filter(item => item.id !== declaration?.id)

  const manque = (() => {
    if (!membre.numero_ordre) return "Ce membre n'a pas de N° d'ordre : corrigez-le d'abord."
    if (!situation) return null
    if (!dateEffet) return "Indiquez la date d'effet."
    if (dateEffet > aujourdHui()) return 'La date ne peut pas être dans le futur.'
    if (!motif.trim()) return 'Indiquez le motif.'
    return null
  })()

  const enregistrer = async () => {
    if (manque || !membre.numero_ordre || !situation) return
    setEnCours(true)
    setErreur(null)
    try {
      await declarerStatutActif({
        numero_ordre: membre.numero_ordre,
        exercice: situation.exercice,
        actif: cible,
        date_effet: dateEffet,
        motif,
        reference,
        observation,
        piece,
      })
      onSaved()
    } catch (error: any) {
      setErreur(error?.message || "Le statut n'a pas pu être enregistré.")
    } finally {
      setEnCours(false)
    }
  }

  const annuler = async () => {
    if (!declaration || !annulation?.trim()) return
    setEnCours(true)
    setErreur(null)
    try {
      await annulerStatutActif(declaration.id, annulation)
      onSaved()
    } catch (error: any) {
      setErreur(error?.message || "La déclaration n'a pas pu être annulée.")
    } finally {
      setEnCours(false)
    }
  }

  const libelleAction = cible ? (morale ? 'Déclarer active' : 'Déclarer actif') : (morale ? 'Déclarer inactive' : 'Déclarer inactif')

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="tableau-statut-actif-title"
      style={{ position: 'fixed', inset: 0, zIndex: 80, background: 'rgba(17, 24, 39, 0.45)', display: 'grid', placeItems: 'center', padding: '16px' }}
      onMouseDown={event => { if (event.target === event.currentTarget && !enCours) onClose() }}
    >
      <div style={{ width: 'min(560px, 100%)', maxHeight: '90vh', overflowY: 'auto', background: '#fff', borderRadius: '8px', border: '1px solid #d8dadd', boxShadow: '0 20px 50px rgba(0,0,0,.22)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', padding: '16px 16px 0' }}>
          <div>
            <h2 id="tableau-statut-actif-title" style={{ margin: 0, fontSize: '17px' }}>Statut d'activité</h2>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#6b7280' }}>
              {membre.nom} · {membre.numero_ordre || "sans N° d'ordre"} · {membre.categorie}
            </p>
          </div>
          <button type="button" style={bouton} onClick={onClose} disabled={enCours} title="Fermer" aria-label="Fermer">
            <X size={16} />
          </button>
        </div>

        {!situation && !erreur && <p style={{ padding: '16px', margin: 0, fontSize: '13px', color: '#6b7280' }}>Chargement de la situation…</p>}

        {situation && (
          <div style={{ padding: '16px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
            <div style={{ gridColumn: '1 / -1', padding: '10px 12px', borderRadius: '6px', background: '#f3f4f6', fontSize: '13px' }}>
              Statut retenu : <strong>{etat(situation.actif)}</strong> ({source})
              {declaration && situation.actif_fichier != null && <> · le fichier dit : {etat(situation.actif_fichier)}</>}
            </div>

            {declaration && (
              <div style={{ gridColumn: '1 / -1', padding: '10px 12px', borderRadius: '6px', border: '1px solid #e5e7eb', fontSize: '13px', display: 'grid', gap: '6px' }}>
                <span><strong>Déclaration en vigueur</strong> : {declaration.libelle}</span>
                {declaration.piece_path && (
                  <button type="button" style={{ ...bouton, justifySelf: 'start' }} onClick={() => void openUploadUrl(buildUploadUrl(declaration.piece_path!))}>
                    <FileText size={14} /> {declaration.piece_nom || 'Pièce enregistrée'}
                  </button>
                )}
                {annulation === null ? (
                  <button type="button" style={{ ...bouton, justifySelf: 'start' }} onClick={() => setAnnulation('')} disabled={enCours}>
                    <Undo2 size={14} /> Annuler la déclaration
                  </button>
                ) : (
                  <div style={{ display: 'grid', gap: '6px' }}>
                    <label style={champ}>
                      Motif de l'annulation
                      <input value={annulation} onChange={event => setAnnulation(event.target.value)} maxLength={2000} autoFocus style={saisie} />
                    </label>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      <button type="button" style={bouton} onClick={() => setAnnulation(null)} disabled={enCours}>Retour</button>
                      <button type="button" style={bouton} onClick={() => void annuler()} disabled={enCours || !annulation.trim()}>
                        <Undo2 size={14} /> {morale ? 'Annuler : la société redevient active' : 'Annuler : le fichier fait de nouveau foi'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            <label style={champ}>
              Déclaration
              <input value={libelleAction} readOnly style={{ ...saisie, background: '#f9fafb' }} />
            </label>
            <label style={champ}>
              Date d'effet
              <input type="date" value={dateEffet} max={aujourdHui()} onChange={event => setDateEffet(event.target.value)} style={saisie} />
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

            <label style={{ ...champ, gridColumn: '1 / -1' }}>
              Référence (facultative)
              <input value={reference} onChange={event => setReference(event.target.value)} maxLength={200} placeholder="Courrier, constat, séance…" style={saisie} />
            </label>
            <label style={{ ...champ, gridColumn: '1 / -1' }}>
              Pièce justificative (facultative)
              <input type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={event => setPiece(event.target.files?.[0] || null)} style={{ fontWeight: 400 }} />
              <span style={{ fontWeight: 400, color: '#6b7280' }}>PDF, JPG ou PNG, 5 Mo au plus</span>
            </label>
            <label style={{ ...champ, gridColumn: '1 / -1' }}>
              Observation (facultative)
              <textarea value={observation} onChange={event => setObservation(event.target.value)} rows={2} maxLength={2000} style={{ ...saisie, resize: 'vertical' }} />
            </label>

            <p style={{ gridColumn: '1 / -1', margin: 0, fontSize: '12px', color: '#4b5563' }}>
              Le statut vaut à partir de l'exercice de la date d'effet et prime sur le fichier. La conclusion ne change pas :
              {morale ? ' la société' : ' le membre'} reste {morale ? 'jugée' : 'jugé'}, et n'est qu'écarté{morale ? 'e' : ''} des comptes « Actifs »
              (tableau de bord, filtres, rapport).
            </p>

            {anciennes.length > 0 && (
              <details style={{ gridColumn: '1 / -1', fontSize: '12px' }}>
                <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Déclarations précédentes ({anciennes.length})</summary>
                <ul style={{ margin: '6px 0 0', paddingLeft: '18px', display: 'grid', gap: '4px' }}>
                  {anciennes.map(item => (
                    <li key={item.id}>
                      {item.libelle}
                      {item.annule_le && <> — annulée le {dateFr(item.annule_le)}{item.motif_annulation ? ` (${item.motif_annulation})` : ''}</>}
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
            {cible ? <Power size={15} /> : <PowerOff size={15} />} {enCours ? 'Enregistrement...' : libelleAction}
          </button>
        </div>
      </div>
    </div>
  )
}
