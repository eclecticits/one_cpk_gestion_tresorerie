import { useEffect, useState } from 'react'
import { format } from 'date-fns'
import { Send, X } from 'lucide-react'
import {
  envoyerConvocation,
  listDestinatairesConvocation,
  type ConvocationDestinataire,
  type RemboursementTransportBrouillon,
} from '../api/remboursementsTransport'
import styles from './ConvocationReunionModal.module.css'

type Ligne = ConvocationDestinataire & { inclus: boolean }

type Props = {
  brouillon: RemboursementTransportBrouillon
  onClose: () => void
  onEnvoyee: (contenu: Record<string, any>, message: string, type: 'success' | 'warning') => void
}

const SOURCES: Record<string, string> = {
  convocation: 'déjà convoqué',
  expert: 'fiche expert',
  membre: 'membre du service',
}

export default function ConvocationReunionModal({ brouillon, onClose, onEnvoyee }: Props) {
  const [lignes, setLignes] = useState<Ligne[] | null>(null)
  const [message, setMessage] = useState('')
  const [envoi, setEnvoi] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const precedente = brouillon.contenu?.convocation

  useEffect(() => {
    let actif = true
    listDestinatairesConvocation(brouillon.id)
      .then((res) => {
        if (actif) setLignes((res || []).map((d) => ({ ...d, email: d.email || '', inclus: Boolean(d.email) })))
      })
      .catch((e: any) => actif && setErreur(e?.message || 'Chargement des participants impossible.'))
    return () => {
      actif = false
    }
  }, [brouillon.id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !envoi && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [envoi, onClose])

  const maj = (index: number, patch: Partial<Ligne>) =>
    setLignes((prev) => (prev ? prev.map((l, i) => (i === index ? { ...l, ...patch } : l)) : prev))

  const choisis = (lignes || []).filter((l) => l.inclus && String(l.email || '').trim())
  const sansAdresse = (lignes || []).filter((l) => l.inclus && !String(l.email || '').trim()).length

  const envoyer = async () => {
    if (!choisis.length) return
    setEnvoi(true)
    setErreur(null)
    try {
      const res = await envoyerConvocation(
        brouillon.id,
        choisis.map(({ nom, titre_fonction, email }) => ({ nom, titre_fonction, email: String(email).trim() })),
        message,
      )
      if (res.echecs.length) {
        onEnvoyee(
          res.contenu,
          `${res.envoyes} convocation(s) envoyée(s) ; échec pour ${res.echecs.map((e) => e.email).join(', ')}.`,
          'warning',
        )
      } else {
        onEnvoyee(res.contenu, `${res.envoyes} convocation(s) envoyée(s) avec l’invitation agenda.`, 'success')
      }
      onClose()
    } catch (e: any) {
      setErreur(e?.message || 'Envoi impossible.')
    } finally {
      setEnvoi(false)
    }
  }

  return (
    <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && !envoi && onClose()}>
      <div className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="convocation-titre">
        <header className={styles.header}>
          <div>
            <h2 id="convocation-titre">Convoquer les participants</h2>
            {precedente?.envoyee_le && (
              <p className={styles.sub}>
                Dernier envoi le {format(new Date(precedente.envoyee_le), "dd/MM/yyyy 'à' HH:mm")}
                {precedente.envoyee_par ? ` par ${precedente.envoyee_par}` : ''}. Un renvoi met à jour l’agenda des destinataires.
              </p>
            )}
          </div>
          <button type="button" className={styles.close} onClick={onClose} disabled={envoi} aria-label="Fermer">
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        <div className={styles.body}>
          {lignes === null && !erreur && <p className={styles.sub}>Chargement…</p>}
          {lignes && lignes.length === 0 && (
            <p className={styles.sub}>Aucun participant dans ce brouillon : ajoutez-les d’abord dans le formulaire.</p>
          )}
          {lignes && lignes.length > 0 && (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col" className={styles.check} aria-label="Convoquer" />
                    <th scope="col">Participant</th>
                    <th scope="col">Adresse e-mail</th>
                  </tr>
                </thead>
                <tbody>
                  {lignes.map((l, i) => (
                    <tr key={`${l.nom}-${i}`}>
                      <td className={styles.check}>
                        <input
                          type="checkbox"
                          checked={l.inclus}
                          onChange={(e) => maj(i, { inclus: e.target.checked })}
                          aria-label={`Convoquer ${l.nom}`}
                        />
                      </td>
                      <td>
                        <strong>{l.nom}</strong>
                        {l.titre_fonction ? <div className={styles.sub}>{l.titre_fonction}</div> : null}
                      </td>
                      <td>
                        <input
                          type="email"
                          className={styles.input}
                          value={l.email || ''}
                          placeholder="adresse@exemple.org"
                          onChange={(e) => maj(i, { email: e.target.value, inclus: Boolean(e.target.value.trim()) || l.inclus })}
                          aria-label={`Adresse e-mail de ${l.nom}`}
                        />
                        {l.source && l.email ? <div className={styles.sub}>{SOURCES[l.source]}</div> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <label className={styles.label} htmlFor="convocation-message">
            Message ajouté à la convocation (facultatif)
          </label>
          <textarea
            id="convocation-message"
            className={styles.textarea}
            rows={3}
            maxLength={4000}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Ex. : Merci de vous munir des documents transmis la semaine dernière."
          />
          <p className={styles.sub}>
            Chaque participant reçoit un message séparé, avec la date, le lieu, l’ordre du jour (les travaux du formulaire)
            et une invitation à ajouter à son agenda.
          </p>
          {sansAdresse > 0 && (
            <p className={styles.warn}>{sansAdresse} participant(s) coché(s) sans adresse : ils ne seront pas convoqués.</p>
          )}
          {erreur && <p className={styles.error} role="alert">{erreur}</p>}
        </div>

        <footer className={styles.footer}>
          <button type="button" className={styles.secondary} onClick={onClose} disabled={envoi}>
            Annuler
          </button>
          <button type="button" className={styles.primary} onClick={envoyer} disabled={envoi || !choisis.length}>
            <Send size={15} aria-hidden="true" /> {envoi ? 'Envoi…' : `Envoyer (${choisis.length})`}
          </button>
        </footer>
      </div>
    </div>
  )
}
