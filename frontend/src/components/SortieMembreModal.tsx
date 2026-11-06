import { useState } from 'react'
import { FileText, Save, Undo2, X } from 'lucide-react'
import {
  annulerSortieMembre,
  declarerSortieMembre,
  LIBELLES_SITUATION_SORTIE,
  type SituationSortie,
  type TableauSortie,
} from '../api/tableau'
import { buildUploadUrl, openUploadUrl } from '../utils/uploads'

/** Le membre de la ligne de la base : assez pour le désigner, et sa sortie s'il en a une. */
export interface MembreSortie {
  numero_ordre: string | null
  nom: string
  categorie: string
  sortie?: TableauSortie | null
}

const SITUATIONS_PHYSIQUE: SituationSortie[] = ['DECEDE', 'DEMISSIONNAIRE', 'RADIE', 'OMIS']
const MOTIFS = [
  ['DISSOLUTION', 'Dissolution-liquidation'],
  ['FUSION', 'Fusion-absorption'],
  ['RADIATION', 'Radiation'],
] as const

const champ: React.CSSProperties = { display: 'grid', gap: '5px', fontSize: '12px', fontWeight: 600 }
const saisie: React.CSSProperties = { padding: '8px 10px', border: '1px solid #c9ccd2', borderRadius: '5px', fontWeight: 400 }
const bouton: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '8px 12px',
  border: '1px solid #c9ccd2', borderRadius: '5px', background: '#fff', cursor: 'pointer', fontSize: '13px',
}

const aujourdHui = () => new Date().toISOString().slice(0, 10)

/**
 * Déclare la sortie du Tableau d'un membre : décès, démission, radiation,
 * omission, ou cessation d'une société. Le membre garde sa catégorie.
 */
export default function SortieMembreModal({
  membre,
  onClose,
  onSaved,
}: {
  membre: MembreSortie
  onClose: () => void
  onSaved: () => void
}) {
  const morale = membre.categorie === 'Société' || membre.categorie === 'SEC'
  const existante = membre.sortie || null
  const [situation, setSituation] = useState<SituationSortie>(existante?.situation ?? (morale ? 'CESSE' : 'DECEDE'))
  const [dateEffet, setDateEffet] = useState(existante?.date_effet ?? '')
  const [lieu, setLieu] = useState(existante?.lieu_deces ?? '')
  const [motif, setMotif] = useState<string>(existante?.motif_cessation ?? '')
  const [absorbante, setAbsorbante] = useState(existante?.societe_absorbante ?? '')
  const [reference, setReference] = useState(existante?.reference_decision ?? '')
  const [observation, setObservation] = useState(existante?.observation ?? '')
  const [piece, setPiece] = useState<File | null>(null)
  const [enCours, setEnCours] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)

  const manque = (() => {
    if (!membre.numero_ordre) return "Ce membre n'a pas de N° d'ordre : corrigez-le d'abord."
    if (!dateEffet) return 'Indiquez la date.'
    if (dateEffet > aujourdHui()) return 'La date ne peut pas être dans le futur.'
    if (situation === 'DECEDE' && !lieu.trim()) return 'Indiquez le lieu du décès.'
    if ((situation === 'RADIE' || situation === 'OMIS') && !reference.trim()) return 'Indiquez la référence de la décision.'
    if (situation === 'CESSE' && !motif) return 'Choisissez le motif.'
    if (situation === 'CESSE' && motif === 'FUSION' && !absorbante.trim()) return 'Indiquez la société absorbante.'
    return null
  })()

  const enregistrer = async () => {
    if (manque || !membre.numero_ordre) return
    setEnCours(true)
    setErreur(null)
    try {
      await declarerSortieMembre({
        numero_ordre: membre.numero_ordre,
        nom: membre.nom,
        categorie: membre.categorie,
        situation,
        date_effet: dateEffet,
        lieu_deces: situation === 'DECEDE' ? lieu : undefined,
        motif_cessation: situation === 'CESSE' ? motif : undefined,
        societe_absorbante: situation === 'CESSE' && motif === 'FUSION' ? absorbante : undefined,
        reference_decision: situation === 'RADIE' || situation === 'OMIS' ? reference : undefined,
        observation,
        piece,
      })
      onSaved()
    } catch (error: any) {
      setErreur(error?.message || "La sortie n'a pas pu être enregistrée.")
    } finally {
      setEnCours(false)
    }
  }

  const reintegrer = async () => {
    if (!existante) return
    if (!window.confirm(`Réintégrer ${membre.nom} au Tableau ? La sortie déclarée sera supprimée.`)) return
    setEnCours(true)
    setErreur(null)
    try {
      await annulerSortieMembre(existante.id)
      onSaved()
    } catch (error: any) {
      setErreur(error?.message || "La sortie n'a pas pu être annulée.")
    } finally {
      setEnCours(false)
    }
  }

  const libelleDate = situation === 'DECEDE' ? 'Date du décès'
    : situation === 'CESSE' ? 'Date de cessation'
      : situation === 'DEMISSIONNAIRE' ? "Date d'effet de la démission"
        : 'Date de la décision'

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="tableau-sortie-title"
      style={{ position: 'fixed', inset: 0, zIndex: 80, background: 'rgba(17, 24, 39, 0.45)', display: 'grid', placeItems: 'center', padding: '16px' }}
      onMouseDown={event => { if (event.target === event.currentTarget && !enCours) onClose() }}
    >
      <div style={{ width: 'min(560px, 100%)', maxHeight: '90vh', overflowY: 'auto', background: '#fff', borderRadius: '8px', border: '1px solid #d8dadd', boxShadow: '0 20px 50px rgba(0,0,0,.22)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', padding: '16px 16px 0' }}>
          <div>
            <h2 id="tableau-sortie-title" style={{ margin: 0, fontSize: '17px' }}>Sortie du Tableau</h2>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#6b7280' }}>
              {membre.nom} · {membre.numero_ordre || "sans N° d'ordre"} · {membre.categorie}
            </p>
          </div>
          <button type="button" style={bouton} onClick={onClose} disabled={enCours} title="Fermer" aria-label="Fermer">
            <X size={16} />
          </button>
        </div>

        <div style={{ padding: '16px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
          <label style={champ}>
            Situation
            {morale ? (
              <input value={LIBELLES_SITUATION_SORTIE.CESSE} readOnly style={{ ...saisie, background: '#f9fafb' }} />
            ) : (
              <select value={situation} onChange={event => setSituation(event.target.value as SituationSortie)} style={saisie}>
                {SITUATIONS_PHYSIQUE.map(code => <option key={code} value={code}>{LIBELLES_SITUATION_SORTIE[code]}</option>)}
              </select>
            )}
          </label>
          <label style={champ}>
            {libelleDate}
            <input type="date" value={dateEffet} max={aujourdHui()} onChange={event => setDateEffet(event.target.value)} style={saisie} />
          </label>

          {situation === 'DECEDE' && (
            <label style={{ ...champ, gridColumn: '1 / -1' }}>
              Lieu du décès
              <input value={lieu} onChange={event => setLieu(event.target.value)} maxLength={200} placeholder="Ville, pays" style={saisie} />
            </label>
          )}

          {(situation === 'RADIE' || situation === 'OMIS') && (
            <label style={{ ...champ, gridColumn: '1 / -1' }}>
              Référence de la décision
              <input value={reference} onChange={event => setReference(event.target.value)} maxLength={200} placeholder="N° et date de la décision" style={saisie} />
            </label>
          )}

          {situation === 'CESSE' && (
            <>
              <label style={champ}>
                Motif
                <select value={motif} onChange={event => setMotif(event.target.value)} style={saisie}>
                  <option value="">Choisir…</option>
                  {MOTIFS.map(([code, libelle]) => <option key={code} value={code}>{libelle}</option>)}
                </select>
              </label>
              {motif === 'FUSION' && (
                <label style={champ}>
                  Société absorbante
                  <input value={absorbante} onChange={event => setAbsorbante(event.target.value)} maxLength={300} style={saisie} />
                </label>
              )}
            </>
          )}

          <label style={{ ...champ, gridColumn: '1 / -1' }}>
            Pièce justificative (facultative)
            <input
              type="file"
              accept=".pdf,.jpg,.jpeg,.png"
              onChange={event => setPiece(event.target.files?.[0] || null)}
              style={{ fontWeight: 400 }}
            />
            <span style={{ fontWeight: 400, color: '#6b7280' }}>
              {situation === 'DECEDE' ? 'Acte de décès ou faire-part' : situation === 'CESSE' ? 'PV de dissolution, extrait RCCM…' : 'Lettre ou décision'} · PDF, JPG ou PNG, 5 Mo au plus
            </span>
            {existante?.piece_path && !piece && (
              <button
                type="button"
                style={{ ...bouton, justifySelf: 'start', fontWeight: 400 }}
                onClick={() => void openUploadUrl(buildUploadUrl(existante.piece_path!))}
              >
                <FileText size={14} /> {existante.piece_nom || 'Pièce enregistrée'}
              </button>
            )}
          </label>

          <label style={{ ...champ, gridColumn: '1 / -1' }}>
            Observation (facultative)
            <textarea value={observation} onChange={event => setObservation(event.target.value)} rows={2} maxLength={2000} style={{ ...saisie, resize: 'vertical' }} />
          </label>

          <p style={{ gridColumn: '1 / -1', margin: 0, fontSize: '12px', color: '#4b5563' }}>
            Le membre garde sa catégorie mais n'est plus jugé à partir de l'exercice de cette date.
            Sa cotisation n'est plus due après la date ; les arriérés antérieurs restent visibles.
          </p>
          {erreur && <p role="alert" style={{ gridColumn: '1 / -1', margin: 0, color: '#991b1b', fontSize: '13px' }}>{erreur}</p>}
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', padding: '0 16px 16px', flexWrap: 'wrap' }}>
          <div>
            {existante && (
              <button type="button" style={bouton} onClick={() => void reintegrer()} disabled={enCours}>
                <Undo2 size={15} /> Réintégrer au Tableau
              </button>
            )}
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            {manque && <span style={{ fontSize: '12px', color: '#6b7280' }}>{manque}</span>}
            <button type="button" style={bouton} onClick={onClose} disabled={enCours}>Annuler</button>
            <button
              type="button"
              disabled={enCours || !!manque}
              onClick={() => void enregistrer()}
              style={{ ...bouton, background: 'var(--tenant-primary, #1f6b5c)', color: '#fff', borderColor: 'var(--tenant-primary, #1f6b5c)', opacity: enCours || manque ? 0.6 : 1 }}
            >
              <Save size={15} /> {enCours ? 'Enregistrement...' : 'Enregistrer'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
