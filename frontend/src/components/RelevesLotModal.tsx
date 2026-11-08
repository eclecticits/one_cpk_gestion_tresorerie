import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, Mail, MessageCircle, RefreshCw, Send, X } from 'lucide-react'
import {
  CANAUX_RELEVE,
  getTableauRelevesLot,
  lancerTableauRelevesLot,
  LIBELLES_CANAL_RELEVE,
  preparerTableauReleves,
  reprendreTableauRelevesLot,
  type CanalReleve,
  type SelectionReleves,
  type TableauReleveLot,
  type TableauRelevesPreparation,
} from '../api/tableau'
import {
  bouton,
  boutonPrincipal,
  cadreCanaux,
  enteteModale,
  fenetreModale,
  fondModale,
  legendeCanaux,
  listeDetails,
  messageErreur,
  piedModale,
  sousTitreModale,
  texteReleve,
  titreModale,
} from './relevesCommun'

const INTERVALLE_SUIVI_MS = 2000
/** La colonne Action se relit au plus à ce rythme pendant le lot, puis une fois à la fin. */
const INTERVALLE_RAFRAICHISSEMENT_MS = 30000

function EtatLot({ lot }: { lot: TableauReleveLot }) {
  if (lot.statut === 'termine') return <><CheckCircle2 size={16} color="#166534" /> Envoi terminé</>
  if (lot.statut === 'interrompu') {
    return <><AlertTriangle size={16} color="#b45309" /> Envoi interrompu à {lot.traites} sur {lot.total}</>
  }
  return <>Envoi en cours : {lot.traites} sur {lot.total}</>
}

/**
 * Envoi groupé des relevés de situation : ce que donnera l'envoi (qui le
 * reçoit, qui est écarté et pourquoi), puis l'avancement du lot, traité en
 * arrière-plan par le serveur — la fenêtre peut être fermée sans l'arrêter.
 */
export default function RelevesLotModal({
  selection,
  libelleSelection,
  onClose,
  onProgress,
}: {
  selection: Omit<SelectionReleves, 'canaux' | 'renvoyer'>
  libelleSelection: string
  onClose: () => void
  /** Appelé quand des relevés sont partis : la colonne Action se met à jour. */
  onProgress: () => void
}) {
  const [canaux, setCanaux] = useState<Record<CanalReleve, boolean>>({ email: true, whatsapp: true })
  const [renvoyer, setRenvoyer] = useState(false)
  const [preparation, setPreparation] = useState<TableauRelevesPreparation | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [lot, setLot] = useState<TableauReleveLot | null>(null)
  const [lancement, setLancement] = useState(false)
  const [voirExemple, setVoirExemple] = useState(false)
  const dernierEnvoye = useRef(0)
  const dernierRafraichissement = useRef(0)

  // Le résumé tient compte des canaux : « déjà envoyé » se juge canal par canal.
  const canauxDemandes = CANAUX_RELEVE.filter(canal => canaux[canal])
  useEffect(() => {
    let actif = true
    setErreur(null)
    preparerTableauReleves({ ...selection, canaux: ['email', 'whatsapp'] })
      .then(donnees => {
        if (!actif) return
        setPreparation(donnees)
        setCanaux(valeur => ({
          email: valeur.email && donnees.email_actif,
          whatsapp: valeur.whatsapp && donnees.whatsapp_actif,
        }))
      })
      .catch((error: unknown) => actif && setErreur(messageErreur(error, "L'envoi groupé n'a pas pu être préparé.")))
    return () => { actif = false }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- la sélection est figée à l'ouverture
  }, [])

  // Suivi du lot tant qu'il avance.
  useEffect(() => {
    if (!lot || lot.statut !== 'en_cours') return
    const minuteur = window.setTimeout(() => {
      getTableauRelevesLot(lot.id)
        .then(suivant => {
          setLot(suivant)
          // Chaque relecture de la colonne Action recharge tous les envois de
          // l'exercice : espacée pendant le lot, faite une fois à la fin.
          const fini = suivant.statut !== 'en_cours'
          const espace = Date.now() - dernierRafraichissement.current >= INTERVALLE_RAFRAICHISSEMENT_MS
          if (fini || (suivant.envoyes !== dernierEnvoye.current && espace)) {
            dernierEnvoye.current = suivant.envoyes
            dernierRafraichissement.current = Date.now()
            onProgress()
          }
        })
        // Relecture manquée : une copie du lot relance le minuteur.
        .catch(() => setLot(valeur => (valeur ? { ...valeur } : valeur)))
    }, INTERVALLE_SUIVI_MS)
    return () => window.clearTimeout(minuteur)
  }, [lot, onProgress])

  const raisonIndisponible = (canal: CanalReleve): string | null => {
    if (!preparation) return null
    if (canal === 'email' && !preparation.email_actif) return "L'envoi d'e-mails n'est pas configuré"
    if (canal === 'whatsapp' && !preparation.whatsapp_actif) return 'Le canal WhatsApp est désactivé'
    return null
  }
  const choisis = canauxDemandes.filter(canal => !raisonIndisponible(canal))
  const trop = !!preparation && preparation.envoyables > preparation.max
  const peutLancer = !!preparation && preparation.envoyables > 0 && choisis.length > 0 && !trop && !lancement
  const chargement = !preparation && !erreur
  const dejaEnvoye = choisis.some(canal => preparation?.par_canal[canal]?.deja_envoye)

  const lancer = async () => {
    if (!peutLancer || !preparation) return
    const message = `Envoyer sa situation à ${preparation.envoyables} membre(s) par ${choisis.map(c => LIBELLES_CANAL_RELEVE[c]).join(' et ')} ?`
    if (!window.confirm(message)) return
    setLancement(true)
    setErreur(null)
    try {
      setLot(await lancerTableauRelevesLot({ ...selection, exercice: preparation.exercice, canaux: choisis, renvoyer }))
    } catch (error: unknown) {
      setErreur(messageErreur(error, "L'envoi groupé n'a pas pu être lancé."))
    } finally {
      setLancement(false)
    }
  }

  const reprendre = async () => {
    if (!lot) return
    setErreur(null)
    try {
      setLot(await reprendreTableauRelevesLot(lot.id))
    } catch (error: unknown) {
      setErreur(messageErreur(error, "L'envoi n'a pas pu être repris."))
    }
  }

  const pourcentage = lot && lot.total ? Math.round((lot.traites / lot.total) * 100) : 0
  const compteurs = preparation
    ? [
        { libelle: 'Sélectionnés', valeur: preparation.total, couleur: '#374151' },
        { libelle: 'Recevront leur situation', valeur: preparation.envoyables, couleur: '#0f7b62' },
        { libelle: 'dont en règle', valeur: preparation.en_regle, couleur: '#166534' },
        { libelle: 'dont non en règle', valeur: preparation.non_en_regle, couleur: '#991b1b' },
      ]
    : []

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="tableau-releves-lot-title"
      style={fondModale}
      onMouseDown={event => { if (event.target === event.currentTarget && !lancement) onClose() }}
    >
      <div style={fenetreModale}>
        <div style={enteteModale}>
          <div>
            <h2 id="tableau-releves-lot-title" style={titreModale}>Envoyer leur situation</h2>
            <p style={sousTitreModale}>{libelleSelection}</p>
          </div>
          <button type="button" style={bouton} onClick={onClose} disabled={lancement} title="Fermer" aria-label="Fermer">
            <X size={16} />
          </button>
        </div>

        <div style={{ padding: '16px', display: 'grid', gap: '14px', fontSize: '13px' }}>
          {chargement && <p style={{ margin: 0, color: '#6b7280' }}>Lecture de la sélection…</p>}

          {preparation && !lot && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '8px' }}>
                {compteurs.map(({ libelle, valeur, couleur }) => (
                  <div key={libelle} style={{ border: '1px solid #e5e7eb', borderRadius: '6px', padding: '8px 10px' }}>
                    <div style={{ fontSize: '20px', fontWeight: 700, color: couleur }}>{valeur}</div>
                    <div style={{ color: '#6b7280', fontSize: '12px' }}>{libelle}</div>
                  </div>
                ))}
              </div>

              {preparation.bloques.length > 0 && (
                <div style={{ padding: '10px 12px', borderRadius: '6px', background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600, marginBottom: '4px' }}>
                    <AlertTriangle size={15} /> Écartés de l'envoi : {preparation.total - preparation.envoyables}
                  </div>
                  <ul style={{ margin: 0, paddingLeft: '20px' }}>
                    {preparation.bloques.map(b => <li key={b.code}>{b.libelle} : {b.nombre}</li>)}
                  </ul>
                </div>
              )}

              {trop && (
                <p style={{ margin: 0, color: '#991b1b' }}>
                  Un envoi groupé compte {preparation.max} membres au plus : affinez le filtre.
                </p>
              )}

              <fieldset style={cadreCanaux}>
                <legend style={legendeCanaux}>Envoyer par</legend>
                {CANAUX_RELEVE.map(canal => {
                  const indisponible = raisonIndisponible(canal)
                  const detail = preparation.par_canal[canal]
                  const dejaRecu = detail?.deja_envoye ? ` · ${detail.deja_envoye} déjà reçu cette situation` : ''
                  return (
                    <label key={canal} style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', color: indisponible ? '#9ca3af' : undefined }}>
                      <input
                        type="checkbox"
                        checked={canaux[canal] && !indisponible}
                        disabled={!!indisponible}
                        onChange={event => setCanaux(valeur => ({ ...valeur, [canal]: event.target.checked }))}
                      />
                      {canal === 'email' ? <Mail size={14} /> : <MessageCircle size={14} />}
                      <span style={{ fontWeight: 600 }}>{LIBELLES_CANAL_RELEVE[canal]}</span>
                      <span style={{ color: '#6b7280' }}>
                        {indisponible || `${detail?.joignables ?? 0} joignable(s)${dejaRecu}`}
                      </span>
                    </label>
                  )
                })}
              </fieldset>

              {dejaEnvoye && (
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <input type="checkbox" checked={renvoyer} onChange={event => setRenvoyer(event.target.checked)} />
                  Renvoyer aussi à ceux qui ont déjà reçu la même situation
                </label>
              )}

              {preparation.exemple && (
                <div>
                  <button type="button" style={{ ...bouton, padding: '4px 8px', fontSize: '12px' }} onClick={() => setVoirExemple(v => !v)}>
                    {voirExemple ? "Masquer l'exemple" : `Voir un exemple (${preparation.exemple.nom})`}
                  </button>
                  {voirExemple && (
                    <pre style={{ ...texteReleve, margin: '8px 0 0' }}>
                      {`Objet : ${preparation.exemple.sujet}\n\n${preparation.exemple.corps}`}
                    </pre>
                  )}
                </div>
              )}
            </>
          )}

          {lot && (
            <div style={{ display: 'grid', gap: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
                <EtatLot lot={lot} />
              </div>
              <div style={{ height: '8px', borderRadius: '4px', background: '#e5e7eb', overflow: 'hidden' }} role="progressbar" aria-valuenow={pourcentage} aria-valuemin={0} aria-valuemax={100}>
                <div style={{ width: `${pourcentage}%`, height: '100%', background: lot.statut === 'interrompu' ? '#d97706' : '#0f7b62', transition: 'width .4s' }} />
              </div>
              <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', color: '#374151' }}>
                <span style={{ color: '#166534' }}>Envoyés : {lot.envoyes}</span>
                {lot.echecs > 0 && <span style={{ color: '#991b1b' }}>Échecs : {lot.echecs}</span>}
                {lot.deja_envoyes > 0 && <span>Déjà reçu : {lot.deja_envoyes}</span>}
                {lot.ignores > 0 && <span>Non joignables : {lot.ignores}</span>}
              </div>
              {lot.statut === 'en_cours' && (
                <p style={{ margin: 0, color: '#6b7280', fontSize: '12px' }}>
                  Vous pouvez fermer cette fenêtre : l'envoi se poursuit sur le serveur.
                </p>
              )}
              {lot.erreurs.length > 0 && (
                <details>
                  <summary style={{ cursor: 'pointer', color: '#991b1b' }}>Détail des échecs ({lot.erreurs.length})</summary>
                  <ul style={listeDetails}>
                    {lot.erreurs.map((e, index) => (
                      <li key={index}>{e.nom} ({e.numero_ordre}) · {LIBELLES_CANAL_RELEVE[e.canal]} · {e.erreur || 'échec'}</li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}

          {erreur && <p style={{ margin: 0, color: '#991b1b' }}>{erreur}</p>}
        </div>

        <div style={piedModale}>
          <button type="button" style={bouton} onClick={onClose} disabled={lancement}>{lot ? 'Fermer' : 'Annuler'}</button>
          {lot?.statut === 'interrompu' && (
            <button type="button" style={boutonPrincipal} onClick={reprendre}>
              <RefreshCw size={14} /> Reprendre
            </button>
          )}
          {!lot && preparation && (
            <button
              type="button"
              style={{ ...boutonPrincipal, opacity: peutLancer ? 1 : 0.55 }}
              onClick={lancer}
              disabled={!peutLancer}
            >
              <Send size={14} /> {lancement ? 'Lancement…' : `Envoyer à ${preparation.envoyables} membre(s)`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
