import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { format } from 'date-fns'
import {
  Ban,
  Banknote,
  FileSpreadsheet,
  Gavel,
  Mail,
  Printer,
  Send,
  X,
} from 'lucide-react'
import {
  ficheNoteDebit,
  mettreEnDemeure,
  relancerParEmail,
  type EvenementNote,
  type FicheNote,
} from '../api/notesDebit'
import { usePermissions } from '../hooks/usePermissions'
import { useToast } from '../hooks/useToast'
import { apiRequest, ApiError } from '../lib/apiClient'
import type { Encaissement } from '../types'
import { generateMiseEnDemeurePDF, generateNotesDebitPDF } from '../utils/pdfNotesDebit'
import PaymentManager from './PaymentManager'
import styles from '../pages/NotesDebitExperts.module.css'

const montant = (valeur: string | number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(Number(valeur) || 0)

const ETAPES: { cle: string; libelle: string }[] = [
  { cle: 'non_paye', libelle: 'Émise' },
  { cle: 'partiel', libelle: 'Partiellement payée' },
  { cle: 'complet', libelle: 'Payée' },
]

const ICONE_EVENEMENT: Record<EvenementNote['type'], JSX.Element> = {
  emission: <Send size={14} aria-hidden />,
  paiement: <Banknote size={14} aria-hidden />,
  paiement_annule: <Ban size={14} aria-hidden />,
  relance: <Mail size={14} aria-hidden />,
  mise_en_demeure: <Gavel size={14} aria-hidden />,
  annulation: <Ban size={14} aria-hidden />,
  journal: <FileSpreadsheet size={14} aria-hidden />,
}

interface Props {
  noteId: string
  onClose: () => void
  /** Un versement, une relance ou une mise en demeure : la liste se met à jour. */
  onChange: () => void
  /** Ouvrir la liste sur les notes de l'import d'où vient celle-ci. */
  onVoirImport?: (imp: { id: string; fichier: string }) => void
}

/**
 * Fiche d'une note de débit, à la manière d'un document Odoo : où elle en est
 * (barre d'état), ce qui lui est arrivé (historique), et ce qu'on peut en faire
 * (encaisser, imprimer, relancer, mettre en demeure).
 */
export default function NoteDebitFiche({ noteId, onClose, onChange, onVoirImport }: Props) {
  const { hasPermission } = usePermissions()
  const { notifySuccess, notifyError } = useToast()
  const peutRecouvrer = hasPermission('encaissements')
  const [fiche, setFiche] = useState<FicheNote | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [occupe, setOccupe] = useState<string | null>(null)
  const [noteEnPaiement, setNoteEnPaiement] = useState<Encaissement | null>(null)
  const [demeureOuverte, setDemeureOuverte] = useState(false)
  const [delai, setDelai] = useState(15)

  const charger = useCallback(async () => {
    try {
      setFiche(await ficheNoteDebit(noteId))
      setErreur(null)
    } catch (err) {
      setErreur(err instanceof ApiError ? err.message : 'Impossible de charger la note de débit.')
    }
  }, [noteId])

  useEffect(() => {
    void charger()
  }, [charger])

  useEffect(() => {
    const echap = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !noteEnPaiement) onClose()
    }
    window.addEventListener('keydown', echap)
    return () => window.removeEventListener('keydown', echap)
  }, [onClose, noteEnPaiement])

  const apresAction = async () => {
    await charger()
    onChange()
  }

  const encaisser = async () => {
    setOccupe('encaisser')
    try {
      setNoteEnPaiement(
        await apiRequest<Encaissement>('GET', `/encaissements/${noteId}`, { params: { include: 'expert_comptable' } }),
      )
    } catch (err) {
      notifyError('Règlement', err instanceof ApiError ? err.message : "Impossible d'ouvrir le règlement.")
    } finally {
      setOccupe(null)
    }
  }

  const relancer = async () => {
    setOccupe('relance')
    try {
      const reponse = await relancerParEmail(noteId)
      notifySuccess('Relance envoyée', reponse?.detail || 'Le membre a été relancé par e-mail.')
      await apresAction()
    } catch (err) {
      notifyError('Relance', err instanceof ApiError ? err.message : "La relance n'a pas pu être envoyée.")
    } finally {
      setOccupe(null)
    }
  }

  const emettreMiseEnDemeure = async () => {
    if (!fiche) return
    setOccupe('demeure')
    try {
      const releve = await mettreEnDemeure(fiche.expert.id, delai)
      await generateMiseEnDemeurePDF(releve)
      setDemeureOuverte(false)
      notifySuccess('Mise en demeure', `Émise pour ${releve.notes.length} note(s), ${montant(releve.total_du)} au total.`)
      await apresAction()
    } catch (err) {
      notifyError('Mise en demeure', err instanceof ApiError ? err.message : "La mise en demeure n'a pas pu être émise.")
    } finally {
      setOccupe(null)
    }
  }

  const imprimer = async () => {
    if (!fiche) return
    setOccupe('imprimer')
    try {
      await generateNotesDebitPDF([fiche], fiche.comptes)
    } finally {
      setOccupe(null)
    }
  }

  const annulee = fiche?.statut_operation === 'ANNULEE'
  const reste = Number(fiche?.reste_du ?? 0)
  const etapeCourante = fiche?.statut_paiement === 'avance' ? 'complet' : fiche?.statut_paiement

  return createPortal(
    <>
      <div className={styles.drawerFond} onClick={onClose} aria-hidden />
      <aside className={styles.drawer} role="dialog" aria-modal="true" aria-label="Note de débit">
        <header className={styles.drawerEntete}>
          <div>
            <span className={styles.muted}>Note de débit</span>
            <h2 className={styles.numero}>{fiche?.numero_recu ?? '…'}</h2>
          </div>
          <button type="button" className={styles.iconeBtn} onClick={onClose} aria-label="Fermer">
            <X size={18} aria-hidden />
          </button>
        </header>

        {erreur && (
          <p className={styles.erreurBloc} role="alert">
            {erreur}
          </p>
        )}

        {fiche && (
          <>
            <div className={styles.barreActions}>
              {peutRecouvrer && reste > 0 && !annulee && (
                <button type="button" className={styles.primaryBtn} onClick={() => void encaisser()} disabled={!!occupe}>
                  <Banknote size={16} aria-hidden /> Encaisser
                </button>
              )}
              <button type="button" className={styles.secondaryBtn} onClick={() => void imprimer()} disabled={!!occupe}>
                <Printer size={16} aria-hidden /> Imprimer
              </button>
              {peutRecouvrer && reste > 0 && !annulee && (
                <>
                  <button type="button" className={styles.secondaryBtn} onClick={() => void relancer()} disabled={!!occupe}>
                    <Mail size={16} aria-hidden /> {occupe === 'relance' ? 'Envoi…' : 'Relancer par e-mail'}
                  </button>
                  <button
                    type="button"
                    className={styles.secondaryBtn}
                    onClick={() => setDemeureOuverte((v) => !v)}
                    aria-expanded={demeureOuverte}
                    disabled={!!occupe}
                  >
                    <Gavel size={16} aria-hidden /> Mise en demeure
                  </button>
                </>
              )}
            </div>

            {demeureOuverte && (
              <div className={styles.demeure}>
                <p>
                  La mise en demeure reprend <strong>toutes les notes non soldées</strong> de {fiche.expert.nom}, pas
                  seulement celle-ci. Elle est inscrite à l'historique de chacune.
                </p>
                <div className={styles.actionsLigne}>
                  <label className={styles.champLigne}>
                    Délai
                    <input
                      type="number"
                      min={1}
                      max={90}
                      value={delai}
                      onChange={(e) => setDelai(Math.max(1, Math.min(90, Number(e.target.value) || 15)))}
                    />
                    jours
                  </label>
                  <button
                    type="button"
                    className={styles.dangerBtn}
                    onClick={() => void emettreMiseEnDemeure()}
                    disabled={!!occupe}
                  >
                    {occupe === 'demeure' ? 'Émission…' : 'Émettre et imprimer'}
                  </button>
                </div>
              </div>
            )}

            {annulee ? (
              <span className={`${styles.badge} ${styles.badgeMuted}`}>Note annulée</span>
            ) : (
              <ol className={styles.statusbar} aria-label="État de la note">
                {ETAPES.map((etape) => (
                  <li
                    key={etape.cle}
                    className={etape.cle === etapeCourante ? styles.statusActif : styles.statusEtape}
                    aria-current={etape.cle === etapeCourante ? 'step' : undefined}
                  >
                    {etape.libelle}
                  </li>
                ))}
              </ol>
            )}

            <div className={styles.smartButtons}>
              <span className={styles.smart}>
                <Banknote size={16} aria-hidden />
                <strong>{fiche.nb_paiements}</strong> versement{fiche.nb_paiements > 1 ? 's' : ''}
              </span>
              <span className={styles.smart}>
                <Mail size={16} aria-hidden />
                <strong>{fiche.relance_count}</strong> relance{fiche.relance_count > 1 ? 's' : ''}
              </span>
              <span className={styles.smart}>
                <Gavel size={16} aria-hidden />
                <strong>{fiche.nb_mises_en_demeure}</strong> mise{fiche.nb_mises_en_demeure > 1 ? 's' : ''} en demeure
              </span>
              {fiche.import && (
                <button
                  type="button"
                  className={styles.smart}
                  onClick={() => fiche.import && onVoirImport?.(fiche.import)}
                  title="Voir les notes de cet import"
                >
                  <FileSpreadsheet size={16} aria-hidden /> {fiche.import.fichier}
                </button>
              )}
            </div>

            <section className={styles.drawerBloc}>
              <div className={styles.membre}>
                <strong>{fiche.expert.nom}</strong>
                <small>
                  {fiche.expert.numero_ordre}
                  {fiche.expert.type_ec === 'SEC' && <span className={`${styles.tag} ${styles.tagSec}`}>SEC</span>}
                  {fiche.expert.province && ` · ${fiche.expert.province}`}
                </small>
                {(fiche.expert.email || fiche.expert.telephone) && (
                  <small>{[fiche.expert.email, fiche.expert.telephone].filter(Boolean).join(' · ')}</small>
                )}
              </div>
              <span className={styles.muted}>
                Émise le {fiche.date_encaissement ? format(new Date(fiche.date_encaissement), 'dd/MM/yyyy') : '—'}
              </span>
            </section>

            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Libellé</th>
                  <th>Poste</th>
                  <th className={styles.num}>Montant</th>
                </tr>
              </thead>
              <tbody>
                {fiche.articles.map((article, i) => (
                  <tr key={`${article.libelle}-${i}`}>
                    <td>
                      {article.libelle}
                      {Number(article.quantite) !== 1 && (
                        <small className={styles.muted}>
                          {' '}
                          ({Number(article.quantite)} × {montant(article.prix_unitaire)})
                        </small>
                      )}
                    </td>
                    <td className={styles.muted}>{article.poste_code ?? '—'}</td>
                    <td className={styles.num}>{montant(article.montant)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={2}>Total</td>
                  <td className={styles.num}>{montant(fiche.montant_total)}</td>
                </tr>
                <tr>
                  <td colSpan={2}>Réglé</td>
                  <td className={styles.num}>{montant(fiche.montant_paye)}</td>
                </tr>
                <tr className={styles.fort}>
                  <td colSpan={2}>Reste à payer</td>
                  <td className={styles.num}>{montant(fiche.reste_du)}</td>
                </tr>
              </tfoot>
            </table>

            <section>
              <h3 className={styles.sousTitre}>Historique</h3>
              <ol className={styles.historique}>
                {fiche.historique.map((evenement, i) => (
                  <li key={`${evenement.date}-${i}`} className={styles[`evt_${evenement.type}`] ?? ''}>
                    <span className={styles.evtIcone}>{ICONE_EVENEMENT[evenement.type]}</span>
                    <div>
                      <div>{evenement.libelle}</div>
                      <small className={styles.muted}>
                        {evenement.date ? format(new Date(evenement.date), 'dd/MM/yyyy HH:mm') : ''}
                        {evenement.auteur ? ` — ${evenement.auteur}` : ''}
                      </small>
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          </>
        )}
      </aside>

      {noteEnPaiement && (
        <PaymentManager
          encaissement={noteEnPaiement}
          onClose={() => setNoteEnPaiement(null)}
          onUpdate={() => void apresAction()}
        />
      )}
    </>,
    document.body,
  )
}
