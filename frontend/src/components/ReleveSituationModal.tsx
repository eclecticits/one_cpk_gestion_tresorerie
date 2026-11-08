import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, Mail, MessageCircle, Send, X, XCircle, type LucideIcon } from 'lucide-react'
import {
  CANAUX_RELEVE,
  envoyerTableauReleve,
  getTableauReleveApercu,
  LIBELLES_CANAL_RELEVE,
  type CanalReleve,
  type StatutEnvoiReleve,
  type TableauReleveApercu,
  type TableauReleveResultat,
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

/** Le membre de la ligne de la base : assez pour retrouver son relevé. */
export interface MembreReleve {
  numero_ordre: string
  nom: string
}

const dateFr = (valeur: string) => new Date(valeur).toLocaleDateString('fr-FR')

const PRESENTATION_STATUT: Record<StatutEnvoiReleve, { couleur: string; Icone: LucideIcon }> = {
  envoye: { couleur: '#166534', Icone: CheckCircle2 },
  echec: { couleur: '#991b1b', Icone: XCircle },
  deja_envoye: { couleur: '#92400e', Icone: AlertTriangle },
  ignore: { couleur: '#92400e', Icone: AlertTriangle },
}

/**
 * Aperçu puis envoi du relevé de situation d'un membre : le texte exact qui
 * partira, ses destinataires, et ce qui a déjà été envoyé.
 */
export default function ReleveSituationModal({
  membre,
  exercice,
  onClose,
  onSent,
}: {
  membre: MembreReleve
  exercice?: string
  onClose: () => void
  onSent: () => void
}) {
  const [apercu, setApercu] = useState<TableauReleveApercu | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [canaux, setCanaux] = useState<Record<CanalReleve, boolean>>({ email: false, whatsapp: false })
  const [renvoyer, setRenvoyer] = useState(false)
  const [enCours, setEnCours] = useState(false)
  const [resultat, setResultat] = useState<TableauReleveResultat | null>(null)

  useEffect(() => {
    let actif = true
    getTableauReleveApercu(membre.numero_ordre, exercice)
      .then(donnees => {
        if (!actif) return
        setApercu(donnees)
        setCanaux({
          email: donnees.emails.length > 0 && donnees.email_actif,
          whatsapp: !!donnees.telephone && donnees.whatsapp_actif,
        })
      })
      .catch((error: unknown) => actif && setErreur(messageErreur(error, "Le relevé n'a pas pu être préparé.")))
    return () => { actif = false }
  }, [membre.numero_ordre, exercice])

  const chargement = !apercu && !erreur
  const raisonIndisponible = (canal: CanalReleve): string | null => {
    if (!apercu) return null
    if (canal === 'email') {
      if (!apercu.emails.length) return "Pas d'adresse e-mail au dossier"
      if (!apercu.email_actif) return "L'envoi d'e-mails n'est pas configuré"
    } else {
      if (!apercu.telephone) return 'Pas de numéro de téléphone exploitable'
      if (!apercu.whatsapp_actif) return 'Le canal WhatsApp est désactivé'
    }
    return null
  }

  const choisis = CANAUX_RELEVE.filter(canal => canaux[canal] && !raisonIndisponible(canal))
  const dejaPartout = choisis.length > 0 && choisis.every(canal => apercu?.deja_envoye[canal])
  const peutEnvoyer = choisis.length > 0 && !(dejaPartout && !renvoyer) && !enCours

  const envoyer = async () => {
    if (!apercu || !choisis.length) return
    setEnCours(true)
    setErreur(null)
    try {
      const reponse = await envoyerTableauReleve({
        numero_ordre: membre.numero_ordre, exercice: apercu.exercice, canaux: choisis, renvoyer,
      })
      setResultat(reponse)
      if (reponse.resultats.some(r => r.statut === 'envoye')) onSent()
    } catch (error: unknown) {
      setErreur(messageErreur(error, "Le relevé n'a pas pu être envoyé."))
    } finally {
      setEnCours(false)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="tableau-releve-title"
      style={fondModale}
      onMouseDown={event => { if (event.target === event.currentTarget && !enCours) onClose() }}
    >
      <div style={fenetreModale}>
        <div style={enteteModale}>
          <div>
            <h2 id="tableau-releve-title" style={titreModale}>Envoyer sa situation</h2>
            <p style={sousTitreModale}>
              {membre.nom} · {membre.numero_ordre}
              {apercu?.fonction_bureau && ` · ${apercu.fonction_bureau} au Bureau`}
            </p>
          </div>
          <button type="button" style={bouton} onClick={onClose} disabled={enCours} title="Fermer" aria-label="Fermer">
            <X size={16} />
          </button>
        </div>

        <div style={{ padding: '16px', display: 'grid', gap: '14px' }}>
          {chargement && <p style={{ margin: 0, color: '#6b7280', fontSize: '13px' }}>Préparation du relevé…</p>}

          {apercu && !apercu.envoyable && (
            <div style={{ display: 'flex', gap: '8px', padding: '10px 12px', borderRadius: '6px', background: '#fffbeb', border: '1px solid #fde68a', color: '#92400e', fontSize: '13px' }}>
              <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '1px' }} />
              <span>{apercu.raison}</span>
            </div>
          )}

          {apercu?.envoyable && (
            <>
              <div>
                <div style={{ fontSize: '12px', fontWeight: 600, color: '#374151', marginBottom: '6px' }}>Objet : {apercu.sujet}</div>
                <pre style={texteReleve}>
                  {apercu.corps}
                </pre>
              </div>

              <fieldset style={cadreCanaux}>
                <legend style={legendeCanaux}>Envoyer par</legend>
                {CANAUX_RELEVE.map(canal => {
                  const indisponible = raisonIndisponible(canal)
                  const deja = apercu.deja_envoye[canal]
                  const destinataire = canal === 'email' ? apercu.emails.join(', ') : apercu.telephone
                  return (
                    <label key={canal} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: indisponible ? '#9ca3af' : undefined }}>
                      <input
                        type="checkbox"
                        checked={canaux[canal] && !indisponible}
                        disabled={!!indisponible || enCours}
                        onChange={event => setCanaux(valeur => ({ ...valeur, [canal]: event.target.checked }))}
                      />
                      {canal === 'email' ? <Mail size={14} /> : <MessageCircle size={14} />}
                      <span style={{ fontWeight: 600 }}>{LIBELLES_CANAL_RELEVE[canal]}</span>
                      <span style={{ color: '#6b7280' }}>{indisponible || destinataire}</span>
                      {deja && <span style={{ color: '#b45309', fontSize: '12px' }}>déjà envoyé le {dateFr(deja)}</span>}
                    </label>
                  )
                })}
              </fieldset>

              {choisis.some(canal => apercu.deja_envoye[canal]) && (
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px' }}>
                  <input type="checkbox" checked={renvoyer} onChange={event => setRenvoyer(event.target.checked)} disabled={enCours} />
                  La situation n'a pas changé depuis le dernier envoi : renvoyer quand même
                </label>
              )}
            </>
          )}

          {resultat && (
            <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'grid', gap: '6px', fontSize: '13px' }}>
              {resultat.resultats.map(r => {
                const { couleur, Icone } = PRESENTATION_STATUT[r.statut]
                return (
                  <li key={r.canal} style={{ display: 'flex', alignItems: 'center', gap: '6px', color: couleur }}>
                    <Icone size={15} />
                    <strong>{LIBELLES_CANAL_RELEVE[r.canal]}</strong>
                    <span>{r.statut === 'envoye' ? `envoyé à ${r.destinataire}` : r.message}</span>
                  </li>
                )
              })}
            </ul>
          )}

          {erreur && <p style={{ margin: 0, color: '#991b1b', fontSize: '13px' }}>{erreur}</p>}

          {apercu && apercu.historique.length > 0 && (
            <details style={{ fontSize: '13px' }}>
              <summary style={{ cursor: 'pointer', color: '#374151' }}>Envois précédents ({apercu.historique.length})</summary>
              <ul style={listeDetails}>
                {apercu.historique.map((envoi, index) => (
                  <li key={index}>
                    {dateFr(envoi.date)} · {LIBELLES_CANAL_RELEVE[envoi.canal]} · {envoi.destinataire} ·{' '}
                    <span style={{ color: envoi.statut === 'envoye' ? '#166534' : '#991b1b' }}>
                      {envoi.statut === 'envoye' ? 'envoyé' : `échec${envoi.erreur ? ` : ${envoi.erreur}` : ''}`}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>

        <div style={piedModale}>
          <button type="button" style={bouton} onClick={onClose} disabled={enCours}>{resultat ? 'Fermer' : 'Annuler'}</button>
          {apercu?.envoyable && !resultat && (
            <button
              type="button"
              style={{ ...boutonPrincipal, opacity: peutEnvoyer ? 1 : 0.55 }}
              onClick={envoyer}
              disabled={!peutEnvoyer}
            >
              <Send size={14} /> {enCours ? 'Envoi…' : 'Envoyer'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
