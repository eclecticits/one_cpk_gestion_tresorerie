import { useCallback, useEffect, useMemo, useState } from 'react'
import { Loader2, Mail, MessageCircle, Send, X } from 'lucide-react'
import {
  type CanalEnvoi,
  type DestinataireRapport,
  type DestinatairesRapport,
  envoyerRapport,
  listDestinatairesRapport,
  type ResultatEnvoiRapport,
} from '../../api/envoiRapports'
import { useNotification } from '../../contexts/NotificationContext'
import styles from './EnvoiRapportDialog.module.css'

// Pas d'emoji dans les messages, ni par e-mail ni par WhatsApp : ils sont
// retirés dès la saisie, pour que l'expéditeur voie ce qui partira vraiment
// (le serveur les retire aussi).
const EMOJI = /[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{FE0F}\u{200D}\u{20E3}]/gu
const sansEmoji = (texte: string) => texte.replace(EMOJI, '')

const CANAUX: { key: CanalEnvoi; label: string; aide: string; icone: JSX.Element }[] = [
  { key: 'email', label: 'E-mail', aide: 'Au Bureau, le PDF en pièce jointe', icone: <Mail size={15} /> },
  { key: 'whatsapp', label: 'WhatsApp', aide: 'Aux membres choisis, message et chiffres clés', icone: <MessageCircle size={15} /> },
]

type Props = {
  titre: string
  periode: string
  resume: string[]
  /** Construit le PDF au moment de l'envoi, pas à l'ouverture de la fenêtre. */
  genererPdf: () => Promise<{ blob: Blob; nom: string }>
  onClose: () => void
}

/**
 * Transmet un rapport au Bureau, avec un mot d'accompagnement. L'e-mail part
 * comme celui des réquisitions : un seul message, le Président en « À », le
 * Bureau en « Cc » (Paramètres › Notifications). WhatsApp part aux membres
 * cochés.
 * Ne sait rien du rapport : le titre, la période, les chiffres clés et le PDF
 * lui sont donnés par l'écran qui l'ouvre.
 */
export default function EnvoiRapportDialog({ titre, periode, resume, genererPdf, onClose }: Props) {
  const { showError } = useNotification()
  const [annuaire, setAnnuaire] = useState<DestinatairesRapport | null>(null)
  const destinataires: DestinataireRapport[] | null = annuaire ? annuaire.membres : null
  const [choisis, setChoisis] = useState<Set<number>>(new Set())
  const [bureauSeul, setBureauSeul] = useState(true)
  const [canaux, setCanaux] = useState<Set<CanalEnvoi>>(new Set(['email']))
  const [message, setMessage] = useState('')
  const [envoi, setEnvoi] = useState(false)
  const [resultat, setResultat] = useState<ResultatEnvoiRapport | null>(null)
  const [canauxSoumis, setCanauxSoumis] = useState<Set<CanalEnvoi> | null>(null)

  const demanderFermeture = useCallback(() => {
    if (!envoi) onClose()
  }, [envoi, onClose])

  useEffect(() => {
    listDestinatairesRapport()
      .then((reponse) => {
        setAnnuaire(reponse)
        const liste = reponse.membres
        // Le Bureau est coché d'office ; sans Bureau identifié, la liste entière
        // s'affiche et personne n'est coché.
        const bureau = liste.filter((d) => d.bureau)
        setChoisis(new Set(bureau.map((d) => d.id)))
        if (bureau.length === 0) setBureauSeul(false)
      })
      .catch((error: any) => {
        showError('Envoi du rapport', error?.message || 'Impossible de charger les membres du Bureau.')
        setAnnuaire({ email_to: [], email_cc: [], membres: [] })
      })
  }, [])

  useEffect(() => {
    const fermerAvecEchap = (event: KeyboardEvent) => {
      if (event.key === 'Escape') demanderFermeture()
    }
    window.addEventListener('keydown', fermerAvecEchap)
    return () => window.removeEventListener('keydown', fermerAvecEchap)
  }, [demanderFermeture])

  const visibles = useMemo(
    () => (destinataires || []).filter((d) => !bureauSeul || d.bureau),
    [destinataires, bureauSeul],
  )
  const selection = (destinataires || []).filter((d) => choisis.has(d.id))
  const adressesBureau = annuaire ? annuaire.email_to.length + annuaire.email_cc.length : 0
  const whatsappJoignables = selection.filter((d) => d.whatsapp).length
  const peutEnvoyer = !envoi && canaux.size > 0
    && (!canaux.has('email') || adressesBureau > 0)
    && (!canaux.has('whatsapp') || whatsappJoignables > 0)

  const basculer = <T,>(ensemble: Set<T>, valeur: T) => {
    const suivant = new Set(ensemble)
    if (suivant.has(valeur)) suivant.delete(valeur)
    else suivant.add(valeur)
    return suivant
  }

  const afficherBureauSeulement = (actif: boolean) => {
    setBureauSeul(actif)
    if (actif) {
      const idsBureau = new Set((destinataires || []).filter((d) => d.bureau).map((d) => d.id))
      setChoisis((selectionCourante) => new Set([...selectionCourante].filter((id) => idsBureau.has(id))))
    }
  }

  const envoyer = async () => {
    if (!peutEnvoyer) return
    const voies = new Set(canaux)
    const selectionSoumise = [...selection]
    setCanauxSoumis(voies)
    setEnvoi(true)
    try {
      const pdf = voies.has('email') ? await genererPdf() : undefined
      setResultat(await envoyerRapport({
        titre,
        periode,
        resume,
        message: message.trim(),
        memberIds: voies.has('whatsapp') ? selectionSoumise.flatMap((d) => d.member_ids) : [],
        canaux: [...voies],
        pdf,
      }))
    } catch (error: any) {
      setCanauxSoumis(null)
      showError('Envoi du rapport', error?.message || "Impossible d'envoyer le rapport.")
    } finally {
      setEnvoi(false)
    }
  }

  const canauxResultat = canauxSoumis || canaux

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby="envoi-rapport-titre" onClick={demanderFermeture}>
      <div className={styles.dialog} aria-busy={envoi} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div>
            <h3 id="envoi-rapport-titre">Envoyer au Bureau</h3>
            <p>{titre}{periode ? ` · ${periode}` : ''}</p>
          </div>
          <button type="button" className={styles.iconButton} onClick={demanderFermeture} disabled={envoi} aria-label="Fermer"><X size={18} /></button>
        </div>

        {resultat ? (
          <div className={styles.body}>
            <div className={styles.bilan} role="status" aria-live="polite">
              {canauxResultat.has('email') && <p className={resultat.emails_envoyes > 0 ? styles.bilanSucces : styles.bilanEchec}><Mail size={15} /> {resultat.emails_envoyes > 0 ? `E-mail envoyé au Bureau (${resultat.emails_envoyes} adresse${resultat.emails_envoyes > 1 ? 's' : ''})` : "E-mail non envoyé"}</p>}
              {canauxResultat.has('whatsapp') && <p className={resultat.whatsapp_envoyes > 0 ? styles.bilanSucces : styles.bilanEchec}><MessageCircle size={15} /> {resultat.whatsapp_envoyes} message{resultat.whatsapp_envoyes > 1 ? 's' : ''} WhatsApp envoyé{resultat.whatsapp_envoyes > 1 ? 's' : ''}</p>}
            </div>
            {resultat.echecs.length > 0 && (
              <div className={styles.echecs}>
                <strong>Non transmis</strong>
                <ul>
                  {resultat.echecs.map((e, i) => (
                    <li key={i}><span>{e.nom}</span> · {e.canal === 'email' ? 'E-mail' : 'WhatsApp'} : {e.raison}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className={styles.body}>
            <fieldset className={styles.canaux}>
              <legend>Envoyer par</legend>
              {CANAUX.map((c) => (
                <label key={c.key} className={`${styles.canal} ${canaux.has(c.key) ? styles.canalActif : ''}`}>
                  <input type="checkbox" checked={canaux.has(c.key)} disabled={envoi} onChange={() => setCanaux((s) => basculer(s, c.key))} />
                  {c.icone}
                  <span>
                    <strong>{c.label}</strong>
                    <small>{c.aide}</small>
                  </span>
                </label>
              ))}
            </fieldset>

            {canaux.has('email') && (
              <div className={styles.section}>
                <div className={styles.sectionHeader}><span>E-mail au Bureau</span></div>
                {annuaire === null ? (
                  <div className={styles.vide}><Loader2 size={16} className={styles.spin} /> Chargement…</div>
                ) : adressesBureau === 0 ? (
                  <p className={styles.avertissement}>Aucune adresse du Bureau : renseignez l’e-mail du Président et les copies dans Paramètres › Notifications.</p>
                ) : (
                  <dl className={styles.adresses}>
                    <dt>À</dt>
                    <dd>{annuaire.email_to.join(', ')}</dd>
                    {annuaire.email_cc.length > 0 && (
                      <>
                        <dt>Cc</dt>
                        <dd>{annuaire.email_cc.join(', ')}</dd>
                      </>
                    )}
                  </dl>
                )}
              </div>
            )}

            {canaux.has('whatsapp') && (
            <div className={styles.section}>
              <div className={styles.sectionHeader}>
                <span>Destinataires WhatsApp <small>{selection.length} choisi{selection.length > 1 ? 's' : ''}</small></span>
                <label className={styles.inline}>
                  <input type="checkbox" checked={bureauSeul} disabled={envoi} onChange={(e) => afficherBureauSeulement(e.target.checked)} />
                  Bureau seulement
                </label>
              </div>
              {destinataires === null ? (
                <div className={styles.vide}><Loader2 size={16} className={styles.spin} /> Chargement…</div>
              ) : visibles.length === 0 ? (
                <div className={styles.vide}>Aucun membre enregistré. Les membres se gèrent dans Administration › Gestion des unités organisationnelles.</div>
              ) : (
                <ul className={styles.liste}>
                  {visibles.map((d) => (
                    <li key={d.id}>
                      <label className={styles.personne}>
                        <input type="checkbox" checked={choisis.has(d.id)} disabled={envoi} onChange={() => setChoisis((s) => basculer(s, d.id))} />
                        <span className={styles.identite}>
                          <strong>{d.nom}</strong>
                          <small>{[d.fonction, d.services.join(', ')].filter(Boolean).join(' · ')}</small>
                        </span>
                        <span className={d.whatsapp ? styles.oui : styles.non} title={d.whatsapp ? 'Joignable par WhatsApp' : 'Pas de numéro, ou notifications WhatsApp non acceptées'}>
                          <MessageCircle size={13} />
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
              {selection.length > whatsappJoignables && (
                <p className={styles.avertissement}>
                  {selection.length - whatsappJoignables} membre{selection.length - whatsappJoignables > 1 ? 's' : ''} sans WhatsApp (pas de numéro, ou notifications non acceptées) : ils ne recevront pas le message.
                </p>
              )}
            </div>
            )}

            <label className={styles.section}>
              <span className={styles.sectionHeader}><span>Message</span></span>
              <textarea
                rows={4}
                maxLength={2000}
                disabled={envoi}
                placeholder="Ex. Pour examen lors de la prochaine réunion du Bureau."
                value={message}
                onChange={(e) => setMessage(sansEmoji(e.target.value))}
              />
              <span className={styles.aideRow}>
                <small className={styles.aide}>Le rapport, sa période et ses chiffres clés sont ajoutés automatiquement à la suite.</small>
                <small className={styles.compteur}>{message.length}/2000</small>
              </span>
            </label>
          </div>
        )}

        <div className={styles.footer}>
          {resultat ? (
            <button type="button" className={styles.primaryButton} onClick={demanderFermeture}>Fermer</button>
          ) : (
            <>
              <button type="button" className={styles.secondaryButton} onClick={demanderFermeture} disabled={envoi}>Annuler</button>
              <button type="button" className={styles.primaryButton} onClick={() => void envoyer()} disabled={!peutEnvoyer}>
                {envoi ? <Loader2 size={15} className={styles.spin} /> : <Send size={15} />} Envoyer
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
