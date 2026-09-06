import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { Download, Eye, Paperclip, Sparkles, X } from 'lucide-react'
import { apiRequest } from '../lib/apiClient'
import { scoreRequisitions } from '../api/ai'
import { useNotification } from '../contexts/NotificationContext'
import { useOrganisationSettings } from '../contexts/OrganisationSettingsContext'
import BudgetDecisionTable from '../components/BudgetDecisionTable'
import { downloadAuthenticatedFile, openAuthenticatedFile } from '../utils/download'
import { toNumber } from '../utils/amount'
import type { Money, Requisition } from '../types'
import styles from './RequisitionDetail.module.css'

const INCLUDE_DETAIL = 'demandeur,validateur,approbateur,examinateur,caissier'

/** Pièce jointe telle que la renvoie /requisitions/{id}/annexes. */
interface Annexe {
  id: string
  filename: string
  file_type?: string | null
  file_size?: number | null
  upload_date?: string | null
}

const formatTaille = (octets?: number | null) => {
  if (!octets || octets <= 0) return null
  if (octets < 1024) return `${octets} o`
  if (octets < 1024 * 1024) return `${(octets / 1024).toFixed(0)} Ko`
  return `${(octets / (1024 * 1024)).toFixed(1)} Mo`
}

const formatCurrency = (amount: Money) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(toNumber(amount))

/** Déplie les formes de réponse de l'API (tableau nu, {items}, {data}). */
const asList = (res: any): any[] =>
  Array.isArray(res) ? res : res?.items ?? res?.data ?? []

/**
 * Fiche complète d'une réquisition, en page à part entière.
 *
 * Elle vivait dans une modale de l'écran Validation : sur une réquisition à
 * plusieurs dizaines de lignes, tout défilait d'un bloc et l'en-tête comme les
 * informations générales sortaient de l'écran. En page, la mise en page tient
 * la hauteur disponible et seules les listes défilent.
 */
export default function RequisitionDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const { showError } = useNotification()
  const { settings: orgSettings } = useOrganisationSettings()
  const aiEnabled = Boolean(orgSettings?.is_ai_enabled)

  // Le clic depuis la liste passe la réquisition déjà chargée : la fiche
  // s'affiche sans attendre. Au rechargement direct de l'URL, on la relit.
  const requisitionFromList = (location.state as { requisition?: Requisition } | null)?.requisition
  const [requisition, setRequisition] = useState<Requisition | null>(
    requisitionFromList && String(requisitionFromList.id) === String(id) ? requisitionFromList : null
  )
  const [lignes, setLignes] = useState<any[]>([])
  const [chargementFiche, setChargementFiche] = useState(!requisition)
  const [chargementLignes, setChargementLignes] = useState(true)
  const [introuvable, setIntrouvable] = useState(false)
  const [aiScore, setAiScore] = useState<any>(null)
  const [annexes, setAnnexes] = useState<Annexe[]>([])
  const [chargementAnnexes, setChargementAnnexes] = useState(true)

  const fermer = useCallback(() => {
    if (window.history.length > 1) {
      navigate(-1)
      return
    }
    navigate('/validation')
  }, [navigate])

  // Fermeture au clavier : une page de consultation se quitte à l'Échap.
  useEffect(() => {
    const surTouche = (event: KeyboardEvent) => {
      if (event.key === 'Escape') fermer()
    }
    window.addEventListener('keydown', surTouche)
    return () => window.removeEventListener('keydown', surTouche)
  }, [fermer])

  useEffect(() => {
    if (!id) return
    if (requisition && String(requisition.id) === String(id)) {
      setChargementFiche(false)
      return
    }
    let annule = false
    const charger = async () => {
      setChargementFiche(true)
      try {
        const res = await apiRequest('GET', '/requisitions', {
          params: { id, include: INCLUDE_DETAIL, limit: 1 },
        })
        if (annule) return
        const trouvee = asList(res)[0]
        if (!trouvee) {
          setIntrouvable(true)
          return
        }
        setRequisition(trouvee as Requisition)
      } catch (error: any) {
        if (annule) return
        setIntrouvable(true)
        showError('Erreur', error?.message || 'Impossible de charger cette réquisition.')
      } finally {
        if (!annule) setChargementFiche(false)
      }
    }
    charger()
    return () => { annule = true }
    // `requisition` est volontairement hors dépendances : la relecture ne doit
    // être déclenchée que par un changement d'identifiant dans l'URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  useEffect(() => {
    if (!id) return
    let annule = false
    const charger = async () => {
      setChargementLignes(true)
      try {
        const res = await apiRequest('GET', '/lignes-requisition', {
          params: { requisition_id: id },
        })
        if (!annule) setLignes(asList(res))
      } catch (error: any) {
        if (annule) return
        showError('Erreur', error?.message || 'Impossible de charger les lignes de dépense.')
      } finally {
        if (!annule) setChargementLignes(false)
      }
    }
    charger()
    return () => { annule = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  useEffect(() => {
    if (!id) return
    let annule = false
    const charger = async () => {
      setChargementAnnexes(true)
      try {
        const res = await apiRequest('GET', `/requisitions/${id}/annexes`)
        if (!annule) setAnnexes(asList(res) as Annexe[])
      } catch (error) {
        // Une réquisition sans pièce jointe n'est pas une anomalie : on ne
        // dérange pas l'utilisateur avec une notification pour autant.
        console.error('Error loading annexes:', error)
        if (!annule) setAnnexes([])
      } finally {
        if (!annule) setChargementAnnexes(false)
      }
    }
    charger()
    return () => { annule = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  useEffect(() => {
    if (!aiEnabled || !id) return
    let annule = false
    const charger = async () => {
      try {
        const res = await scoreRequisitions({ requisition_ids: [String(id)] })
        if (!annule && res?.length) setAiScore(res[0])
      } catch (error) {
        console.error('Error loading AI score:', error)
      }
    }
    charger()
    return () => { annule = true }
  }, [id, aiEnabled])

  const validations = useMemo(() => {
    if (!requisition) return { rejetee: false, autorisee: false, approuvee: false }
    const statut = String((requisition as any).status ?? (requisition as any).statut ?? '').toUpperCase()
    return {
      rejetee: statut === 'REJETEE',
      autorisee: statut === 'AUTORISEE' || statut === 'APPROUVEE' || statut === 'PAYEE',
      approuvee: statut === 'APPROUVEE' || statut === 'PAYEE',
    }
  }, [requisition])

  const nomComplet = (personne: any) =>
    `${personne?.prenom || ''} ${personne?.nom || ''}`.trim() || 'N/A'

  const ouvrirAnnexe = async (annexe: Annexe) => {
    try {
      await openAuthenticatedFile(`/requisitions/annexe/${annexe.id}`)
    } catch (error: any) {
      showError('Pièce jointe', error?.message || "Impossible d'ouvrir la pièce jointe.")
    }
  }

  const telechargerAnnexe = async (annexe: Annexe) => {
    try {
      await downloadAuthenticatedFile(`/requisitions/annexe/${annexe.id}`, annexe.filename)
    } catch (error: any) {
      showError('Pièce jointe', error?.message || 'Impossible de télécharger la pièce jointe.')
    }
  }

  if (chargementFiche) {
    return <div className={styles.state}>Chargement de la réquisition…</div>
  }

  if (introuvable || !requisition) {
    return (
      <div className={styles.state}>
        <p>Cette réquisition est introuvable ou hors de votre périmètre.</p>
        <button type="button" onClick={() => navigate('/validation')}>Retour à la validation</button>
      </div>
    )
  }

  const risk = aiScore?.risk_score ?? null
  const reasons = Array.isArray(aiScore?.reasons) ? aiScore.reasons : []
  const reasonText = reasons.length > 0 ? reasons.join(' ') : ''
  const progressClass =
    risk !== null && risk >= 71
      ? styles.aiProgressHigh
      : risk !== null && risk >= 41
      ? styles.aiProgressMedium
      : styles.aiProgressLow

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headerText}>
          <span className={styles.eyebrow}>Réquisition</span>
          <h1>{requisition.numero_requisition}</h1>
        </div>
        <div className={styles.headerActions}>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={fermer}
            aria-label="Fermer la fiche"
            title="Fermer (Échap)"
          >
            <X size={17} aria-hidden="true" />
            Fermer
          </button>
        </div>
      </header>

      <div className={styles.body}>
        <section className={`${styles.section} ${styles.areaInfos}`}>
          <h2>Informations générales</h2>
          <div className={styles.grid}>
            {validations.rejetee && requisition.validateur && (
              <div className={styles.item}>
                <label>Rejeté par</label>
                <p>{nomComplet(requisition.validateur)}</p>
              </div>
            )}
            {!validations.rejetee && validations.autorisee && requisition.validateur && (
              <div className={styles.item}>
                <label>Validateur technique</label>
                <p>{nomComplet(requisition.validateur)}</p>
              </div>
            )}
            {!validations.rejetee && validations.approuvee && requisition.approbateur && (
              <div className={styles.item}>
                <label>Validation 2/2</label>
                <p>{nomComplet(requisition.approbateur)}</p>
              </div>
            )}
            <div className={styles.item}>
              <label>Numéro</label>
              <p><strong>{requisition.numero_requisition}</strong></p>
            </div>
            <div className={styles.item}>
              <label>Objet</label>
              <p>{requisition.objet}</p>
            </div>
            <div className={styles.item}>
              <label>Demandeur</label>
              <p>{requisition.demandeur ? nomComplet(requisition.demandeur) : 'N/A'}</p>
            </div>
            <div className={styles.item}>
              <label>Montant total</label>
              <p><strong className={styles.amount}>{formatCurrency(requisition.montant_total)}</strong></p>
            </div>
          </div>
        </section>

        {aiEnabled && (
          <section className={`${styles.section} ${styles.areaIa}`}>
            <h2>Analyse de conformité IA</h2>
            {!aiScore ? (
              <p className={styles.aiHint}>Analyse IA en cours…</p>
            ) : (
              <div className={styles.aiPanel}>
                <div className={styles.aiPanelHeader}>
                  <span className={styles.aiPanelTitle}>Score global</span>
                  <span className={styles.aiPanelScore}>
                    <Sparkles size={12} style={{ verticalAlign: 'text-bottom', marginRight: 4 }} />
                    {risk}/100
                  </span>
                </div>
                <div className={styles.aiProgressTrack}>
                  <div className={`${styles.aiProgressFill} ${progressClass}`} style={{ width: `${risk}%` }} />
                </div>
                <div className={styles.aiPanelMeta}>
                  <span>Échantillon : {aiScore.sample_size ?? 0}</span>
                  {aiScore.z_score !== null && aiScore.z_score !== undefined && (
                    <span>Écart : {Math.abs(Number(aiScore.z_score)).toFixed(1)} σ</span>
                  )}
                  {aiScore.duplicate_candidates > 0 && (
                    <span>Doublons potentiels : {aiScore.duplicate_candidates}</span>
                  )}
                </div>
                <div className={styles.aiPanelBody}>
                  <p>{aiScore.explanation}</p>
                  {reasonText && <p className={styles.aiPanelReasons}>{reasonText}</p>}
                </div>
              </div>
            )}
          </section>
        )}

        <section className={`${styles.section} ${styles.areaLignes}`}>
          <h2>Lignes de dépense</h2>
          {chargementLignes ? (
            <p className={styles.aiHint}>Chargement…</p>
          ) : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Poste budgétaire</th>
                    <th>Description</th>
                    <th className={styles.numCell}>Montant</th>
                  </tr>
                </thead>
                <tbody>
                  {lignes.map((ligne) => (
                    <tr key={ligne.id || `${ligne.rubrique}-${ligne.libelle}`}>
                      <td>{ligne.rubrique || '-'}</td>
                      <td>{ligne.libelle || ligne.description || '-'}</td>
                      <td className={styles.numCell}><strong>{formatCurrency(ligne.montant_total || 0)}</strong></td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={2} className={styles.numCell} style={{ fontWeight: 600 }}>Total général</td>
                    <td className={styles.numCell}>
                      <strong className={styles.amount}>{formatCurrency(requisition.montant_total)}</strong>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </section>

        <section className={`${styles.section} ${styles.areaReperes}`}>
          <h2>Repères budgétaires</h2>
          <BudgetDecisionTable lines={lignes} requestedAmount={requisition.montant_total} />
        </section>

        <section className={`${styles.section} ${styles.areaPieces}`}>
          <h2>Pièces jointes</h2>
          {chargementAnnexes ? (
            <p className={styles.aiHint}>Chargement…</p>
          ) : annexes.length === 0 ? (
            <p className={styles.aiHint}>Aucune pièce jointe sur cette réquisition.</p>
          ) : (
            <ul className={styles.annexeList}>
              {annexes.map((annexe) => {
                const taille = formatTaille(annexe.file_size)
                return (
                  <li key={annexe.id} className={styles.annexeItem}>
                    <Paperclip size={15} className={styles.annexeIcon} aria-hidden="true" />
                    <div className={styles.annexeText}>
                      <span className={styles.annexeName} title={annexe.filename}>{annexe.filename}</span>
                      {taille && <span className={styles.annexeMeta}>{taille}</span>}
                    </div>
                    <div className={styles.annexeActions}>
                      <button
                        type="button"
                        className={styles.annexeBtn}
                        onClick={() => ouvrirAnnexe(annexe)}
                        title="Ouvrir la pièce jointe"
                        aria-label={`Ouvrir ${annexe.filename}`}
                      >
                        <Eye size={15} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className={styles.annexeBtn}
                        onClick={() => telechargerAnnexe(annexe)}
                        title="Télécharger la pièce jointe"
                        aria-label={`Télécharger ${annexe.filename}`}
                      >
                        <Download size={15} aria-hidden="true" />
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
