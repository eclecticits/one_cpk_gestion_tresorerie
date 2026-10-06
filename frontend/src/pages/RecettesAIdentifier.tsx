import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { ResponsiveModal } from '../components/ResponsiveModal'
import { listComptesBancaires } from '../api/banques'
import { HORS_BUDGET_STATUS_LABELS } from '../api/mouvementsHorsBudget'
import {
  TRANCHE_LABELS,
  createRecetteAIdentifier,
  listRecettesAIdentifier,
  pistesIdentification,
  reglerNoteDepuisRecette,
  type PisteIdentification,
  type RecetteAIdentifier,
  type TotauxRecettesAIdentifier,
  type TrancheAnciennete,
} from '../api/recettesAIdentifier'
import type { CompteBancaire } from '../types/banque'
import { toNumber } from '../utils/amount'
import { usePermissions } from '../hooks/usePermissions'
import styles from './RecettesAIdentifier.module.css'

/**
 * Versements reçus en banque dont on ne sait pas encore qui a payé.
 *
 * L'argent est là : il a crédité la banque à la saisie et attend au compte
 * d'attente. L'écran répond à deux questions — combien attend, depuis quand —
 * et permet de reclasser chaque versement une fois le payeur retrouvé.
 */

/** Au-delà, un versement non identifié devient une anomalie à traiter. */
const SEUIL_ALERTE_JOURS = 60

const formatMontant = (valeur: unknown, devise: string) =>
  new Intl.NumberFormat('fr-FR', {
    style: 'currency',
    currency: devise === 'CDF' ? 'CDF' : 'USD',
  }).format(toNumber(valeur as any) || 0)

const formatDate = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString('fr-FR') : '—')

const aujourdhui = () => new Date().toISOString().slice(0, 10)

type Filtre = 'ouvertes' | 'toutes'

const RAISON_LABELS: Record<PisteIdentification['raison'], string> = {
  recherche: 'Recherche',
  montant: 'Même montant',
  nom: 'Nom du libellé',
}

export default function RecettesAIdentifier() {
  const { hasPermission } = usePermissions()
  const peutSaisir = hasPermission('encaissements')
  const peutIdentifier = hasPermission('treso.encaissements.identifier')

  const [filtre, setFiltre] = useState<Filtre>('ouvertes')
  const [recettes, setRecettes] = useState<RecetteAIdentifier[]>([])
  const [totaux, setTotaux] = useState<TotauxRecettesAIdentifier[]>([])
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [saisieOuverte, setSaisieOuverte] = useState(false)
  const [aRegler, setARegler] = useState<RecetteAIdentifier | null>(null)

  const charger = useCallback(async () => {
    setChargement(true)
    setErreur(null)
    try {
      const res = await listRecettesAIdentifier(filtre)
      setRecettes(res.items)
      setTotaux(res.totaux)
    } catch (e: any) {
      setErreur(e?.message || 'Impossible de charger les recettes à identifier.')
      setRecettes([])
      setTotaux([])
    } finally {
      setChargement(false)
    }
  }, [filtre])

  useEffect(() => {
    charger()
  }, [charger])

  const enAlerte = useMemo(
    () => recettes.filter((r) => toNumber(r.reste) > 0 && r.age_jours > SEUIL_ALERTE_JOURS).length,
    [recettes],
  )

  const apresAction = (texte: string) => {
    setMessage(texte)
    charger()
  }

  return (
    <div className={styles.page}>
      <PageHeader
        title="Recettes à identifier"
        subtitle="Versements reçus en banque sans payeur connu : déjà en trésorerie, en attente au compte d'attente, hors budget jusqu'à leur identification."
        actions={
          <div className={styles.headerActions}>
            {peutSaisir && (
              <button type="button" className={styles.primaryBtn} onClick={() => setSaisieOuverte(true)}>
                Saisir un versement
              </button>
            )}
            <button
              type="button"
              className={styles.iconBtn}
              onClick={charger}
              disabled={chargement}
              aria-label={chargement ? 'Actualisation en cours' : 'Rafraîchir les recettes à identifier'}
              title="Rafraîchir"
            >
              <RefreshCw size={16} aria-hidden="true" />
            </button>
          </div>
        }
      />

      <section className={styles.summary} aria-label="Montants en attente d'identification" aria-live="polite">
        {totaux.length === 0 ? (
          <div className={styles.summaryCard}>
            <span className={styles.summaryLabel}>En attente</span>
            <strong className={styles.summaryValue}>Aucun montant</strong>
          </div>
        ) : (
          totaux.map((t) => (
            <div key={t.devise} className={styles.summaryCard}>
              <span className={styles.summaryLabel}>En attente ({t.devise})</span>
              <strong className={styles.summaryValue}>{formatMontant(t.total, t.devise)}</strong>
              <div className={styles.tranches}>
                {(Object.keys(TRANCHE_LABELS) as TrancheAnciennete[]).map((tranche) => (
                  <span key={tranche} className={styles.tranche} data-tranche={tranche}>
                    {TRANCHE_LABELS[tranche]} : {formatMontant(t.par_tranche[tranche], t.devise)}
                  </span>
                ))}
              </div>
            </div>
          ))
        )}
        <div className={`${styles.summaryCard} ${enAlerte > 0 ? styles.summaryAlerte : ''}`}>
          <span className={styles.summaryLabel}>Plus de {SEUIL_ALERTE_JOURS} jours</span>
          <strong className={styles.summaryValue}>{enAlerte}</strong>
        </div>
      </section>

      <div className={styles.filters} role="group" aria-label="Filtrer les recettes à identifier">
        {([
          ['ouvertes', 'À identifier'],
          ['toutes', 'Toutes'],
        ] as [Filtre, string][]).map(([valeur, label]) => (
          <button
            key={valeur}
            type="button"
            aria-pressed={filtre === valeur}
            className={`${styles.filterBtn} ${filtre === valeur ? styles.filterBtnActive : ''}`}
            onClick={() => setFiltre(valeur)}
          >
            {label}
          </button>
        ))}
      </div>

      {erreur && <div className={styles.error} role="alert">{erreur}</div>}
      {message && (
        <div className={styles.success} role="status">
          {message}
          <button type="button" className={styles.linkBtn} onClick={() => setMessage(null)}>
            Fermer
          </button>
        </div>
      )}

      <div className={styles.tableWrap} aria-busy={chargement}>
        <table className={styles.table}>
          <caption className={styles.srOnly}>Versements reçus en banque en attente d'identification</caption>
          <thead>
            <tr>
              <th>Date de valeur</th>
              <th>Libellé bancaire</th>
              <th>Reçu</th>
              <th>Identifié</th>
              <th>Reste</th>
              <th>Ancienneté</th>
              <th>Statut</th>
              <th><span className={styles.srOnly}>Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {chargement ? (
              <tr>
                <td colSpan={8} className={styles.empty}>Chargement…</td>
              </tr>
            ) : recettes.length === 0 ? (
              <tr>
                <td colSpan={8} className={styles.empty}>
                  {filtre === 'ouvertes' ? 'Aucun versement en attente d\'identification.' : 'Aucune recette à identifier.'}
                </td>
              </tr>
            ) : (
              recettes.map((r) => {
                const reste = toNumber(r.reste)
                const ouverte = reste > 0 && r.statut_operation === 'ACTIVE'
                return (
                  <tr key={r.id} className={ouverte && r.age_jours > SEUIL_ALERTE_JOURS ? styles.rowAlerte : undefined}>
                    <td data-label="Date de valeur">
                      <strong>{formatDate(r.date_valeur)}</strong>
                      <div className={styles.sub}>{r.numero}</div>
                    </td>
                    <td data-label="Libellé bancaire">
                      <div className={styles.libelle}>{r.libelle}</div>
                      <div className={styles.sub}>
                        {[r.reference && `Réf. ${r.reference}`, r.compte_bancaire].filter(Boolean).join(' · ')}
                      </div>
                      {r.identifications.length > 0 && (
                        <ul className={styles.identifications}>
                          {r.identifications.map((i) => (
                            <li key={i.versement_id}>
                              {formatMontant(i.montant, r.devise)} → {i.numero_recu || '—'}
                              {i.client ? ` · ${i.client}` : ''}
                              {i.identifie_le ? ` · le ${formatDate(i.identifie_le)}` : ''}
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td data-label="Reçu">{formatMontant(r.montant_initial, r.devise)}</td>
                    <td data-label="Identifié">{formatMontant(r.montant_identifie, r.devise)}</td>
                    <td data-label="Reste">
                      <strong className={reste > 0 ? styles.resteDu : styles.resteNul}>
                        {formatMontant(r.reste, r.devise)}
                      </strong>
                    </td>
                    <td data-label="Ancienneté">
                      <span className={styles.tranche} data-tranche={r.tranche}>
                        {r.age_jours} j
                      </span>
                    </td>
                    <td data-label="Statut">
                      <span className={styles.statut} data-statut={r.statut_operation === 'ANNULEE' ? 'ANNULE' : r.statut}>
                        {r.statut_operation === 'ANNULEE'
                          ? 'Annulée'
                          : r.statut
                            ? HORS_BUDGET_STATUS_LABELS[r.statut]
                            : '—'}
                      </span>
                    </td>
                    <td data-label="Actions">
                      {ouverte && peutIdentifier && (
                        <div className={styles.actions}>
                          <Link to={`/encaissements/nouveau?identifier=${r.id}`} className={styles.primaryLink}>
                            Nouvelle recette
                          </Link>
                          <button type="button" className={styles.secondaryBtn} onClick={() => setARegler(r)}>
                            Régler une note
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {saisieOuverte && (
        <SaisieVersement
          onClose={() => setSaisieOuverte(false)}
          onSuccess={(numero) => {
            setSaisieOuverte(false)
            apresAction(`Versement ${numero} enregistré : la banque est créditée, le payeur reste à identifier.`)
          }}
        />
      )}

      {aRegler && (
        <ReglerNote
          recette={aRegler}
          onClose={() => setARegler(null)}
          onSuccess={(numero) => {
            setARegler(null)
            apresAction(`Note ${numero || ''} réglée depuis le versement ${aRegler.numero || ''}.`)
          }}
        />
      )}
    </div>
  )
}

function SaisieVersement({ onClose, onSuccess }: { onClose: () => void; onSuccess: (numero: string) => void }) {
  const [comptes, setComptes] = useState<CompteBancaire[]>([])
  const [compteId, setCompteId] = useState('')
  const [dateValeur, setDateValeur] = useState(aujourdhui())
  const [montant, setMontant] = useState('')
  const [libelle, setLibelle] = useState('')
  const [reference, setReference] = useState('')
  const [mode, setMode] = useState<'virement' | 'cheque' | 'mobile_money' | 'card'>('virement')
  const [envoi, setEnvoi] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    listComptesBancaires({ active: true, account_type: 'BANK' })
      .then((liste) => {
        setComptes(liste)
        const principal = liste.find((c) => c.is_principal) || liste[0]
        if (principal) setCompteId(String(principal.id))
      })
      .catch(() => setErreur('Impossible de charger les comptes bancaires.'))
  }, [])

  const compte = comptes.find((c) => String(c.id) === compteId)

  const enregistrer = async () => {
    const valeur = Number(montant.replace(',', '.'))
    if (!compte) return setErreur('Choisissez le compte bancaire crédité.')
    if (!(valeur > 0)) return setErreur('Le montant doit être positif.')
    if (!libelle.trim()) return setErreur('Recopiez le libellé du relevé bancaire.')
    setEnvoi(true)
    setErreur(null)
    try {
      const res = await createRecetteAIdentifier({
        compte_bancaire_id: compte.id,
        montant: valeur,
        date_valeur: dateValeur,
        libelle: libelle.trim(),
        reference: reference.trim() || null,
        mode_paiement: mode,
      })
      onSuccess(res.numero)
    } catch (e: any) {
      setErreur(e?.message || "Le versement n'a pas pu être enregistré.")
    } finally {
      setEnvoi(false)
    }
  }

  return (
    <ResponsiveModal
      isOpen
      onClose={onClose}
      title="Saisir un versement à identifier"
      size="md"
      footer={
        <div className={styles.modalFooter}>
          <button type="button" className={styles.secondaryBtn} onClick={onClose} disabled={envoi}>
            Annuler
          </button>
          <button type="button" className={styles.primaryBtn} onClick={enregistrer} disabled={envoi}>
            {envoi ? 'Enregistrement…' : 'Enregistrer'}
          </button>
        </div>
      }
    >
      <div className={styles.form}>
        <p className={styles.hint}>
          La banque est créditée tout de suite, sans toucher au budget. Aucun reçu n'est émis : il le sera quand le
          payeur sera identifié.
        </p>
        <label className={styles.field}>
          <span>Compte bancaire crédité</span>
          <select value={compteId} onChange={(e) => setCompteId(e.target.value)}>
            {comptes.length === 0 && <option value="">Aucun compte bancaire actif</option>}
            {comptes.map((c) => (
              <option key={c.id} value={c.id}>
                {c.intitule} — {c.numero_compte} ({c.devise})
              </option>
            ))}
          </select>
        </label>
        <div className={styles.fieldRow}>
          <label className={styles.field}>
            <span>Date de valeur</span>
            <input type="date" value={dateValeur} max={aujourdhui()} onChange={(e) => setDateValeur(e.target.value)} />
          </label>
          <label className={styles.field}>
            <span>Montant{compte ? ` (${compte.devise})` : ''}</span>
            <input inputMode="decimal" value={montant} onChange={(e) => setMontant(e.target.value)} placeholder="0,00" />
          </label>
        </div>
        <label className={styles.field}>
          <span>Libellé du relevé bancaire</span>
          <textarea
            rows={2}
            value={libelle}
            onChange={(e) => setLibelle(e.target.value)}
            placeholder="Recopié tel quel, ex. VIR RECU DE …"
          />
        </label>
        <div className={styles.fieldRow}>
          <label className={styles.field}>
            <span>Référence bancaire</span>
            <input value={reference} onChange={(e) => setReference(e.target.value)} />
          </label>
          <label className={styles.field}>
            <span>Mode</span>
            <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
              <option value="virement">Virement</option>
              <option value="cheque">Chèque</option>
              <option value="mobile_money">Mobile money</option>
              <option value="card">Carte</option>
            </select>
          </label>
        </div>
        {erreur && <div className={styles.error} role="alert">{erreur}</div>}
      </div>
    </ResponsiveModal>
  )
}

function ReglerNote({
  recette,
  onClose,
  onSuccess,
}: {
  recette: RecetteAIdentifier
  onClose: () => void
  onSuccess: (numero?: string | null) => void
}) {
  const [recherche, setRecherche] = useState('')
  const [pistes, setPistes] = useState<PisteIdentification[]>([])
  const [chargement, setChargement] = useState(true)
  const [choisie, setChoisie] = useState<PisteIdentification | null>(null)
  const [montant, setMontant] = useState('')
  const [envoi, setEnvoi] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const reste = toNumber(recette.reste)

  useEffect(() => {
    let annule = false
    setChargement(true)
    const minuteur = window.setTimeout(() => {
      pistesIdentification(recette.id, recherche)
        .then((liste) => !annule && setPistes(liste))
        .catch((e: any) => !annule && setErreur(e?.message || 'Recherche impossible.'))
        .finally(() => !annule && setChargement(false))
    }, recherche ? 300 : 0)
    return () => {
      annule = true
      window.clearTimeout(minuteur)
    }
  }, [recette.id, recherche])

  const choisir = (piste: PisteIdentification) => {
    setChoisie(piste)
    setMontant(String(Math.min(reste, toNumber(piste.reste_du))))
  }

  const regler = async () => {
    if (!choisie) return
    const valeur = Number(montant.replace(',', '.'))
    if (!(valeur > 0)) return setErreur('Le montant doit être positif.')
    if (valeur > reste + 0.01) return setErreur('Le montant dépasse le reste à identifier.')
    if (valeur > toNumber(choisie.reste_du) + 0.01) return setErreur('Le montant dépasse le reste dû de la note.')
    setEnvoi(true)
    setErreur(null)
    try {
      const res = await reglerNoteDepuisRecette(recette.id, choisie.encaissement_id, valeur)
      onSuccess(res.numero_recu)
    } catch (e: any) {
      setErreur(e?.message || "La note n'a pas pu être réglée.")
    } finally {
      setEnvoi(false)
    }
  }

  return (
    <ResponsiveModal
      isOpen
      onClose={onClose}
      title={`Régler une note avec ${recette.numero || 'ce versement'}`}
      size="lg"
      footer={
        <div className={styles.modalFooter}>
          <button type="button" className={styles.secondaryBtn} onClick={onClose} disabled={envoi}>
            Annuler
          </button>
          <button type="button" className={styles.primaryBtn} onClick={regler} disabled={envoi || !choisie}>
            {envoi ? 'Règlement…' : 'Régler la note'}
          </button>
        </div>
      }
    >
      <div className={styles.form}>
        <p className={styles.hint}>
          « {recette.libelle} » — reste à identifier : <strong>{formatMontant(recette.reste, recette.devise)}</strong>.
          La note est réglée sans nouveau mouvement en banque : le versement y est déjà.
        </p>
        <label className={styles.field}>
          <span>Rechercher une note (numéro, client, expert)</span>
          <input
            value={recherche}
            onChange={(e) => {
              setRecherche(e.target.value)
              setChoisie(null)
            }}
            placeholder="Sans recherche : notes du même montant ou au nom présent dans le libellé"
          />
        </label>
        <div className={styles.pistes} aria-busy={chargement}>
          {chargement ? (
            <div className={styles.empty}>Recherche…</div>
          ) : pistes.length === 0 ? (
            <div className={styles.empty}>Aucune note impayée ne correspond.</div>
          ) : (
            pistes.map((p) => (
              <button
                key={p.encaissement_id}
                type="button"
                className={`${styles.piste} ${choisie?.encaissement_id === p.encaissement_id ? styles.pisteChoisie : ''}`}
                onClick={() => choisir(p)}
                aria-pressed={choisie?.encaissement_id === p.encaissement_id}
              >
                <span className={styles.pisteTitre}>
                  {p.numero_recu || p.numero_note_externe || '—'} · {p.client || '—'}
                </span>
                <span className={styles.sub}>
                  {p.libelle} · {formatDate(p.date)} · reste dû {formatMontant(p.reste_du, p.devise)}
                </span>
                <span className={styles.raison}>{RAISON_LABELS[p.raison]}</span>
              </button>
            ))
          )}
        </div>
        {choisie && (
          <label className={styles.field}>
            <span>Montant appliqué à la note ({recette.devise})</span>
            <input inputMode="decimal" value={montant} onChange={(e) => setMontant(e.target.value)} />
          </label>
        )}
        {erreur && <div className={styles.error} role="alert">{erreur}</div>}
      </div>
    </ResponsiveModal>
  )
}
