import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowDownToLine, ArrowRightLeft, ArrowUpFromLine, Check, CheckCheck, FileUp, Landmark, RefreshCw, Undo2, X } from 'lucide-react'
import { listComptesBancaires } from '../../api/banques'
import {
  deciderComptaRapprochement,
  getComptaMappings,
  getComptaMouvementsBancaires,
  getComptaReleveBancaire,
  getComptaRelevesBancaires,
  importComptaReleveBancaire,
} from '../../api/comptabilite'
import type { ComptaPropositionRapprochement, ComptaReleveLigne } from '../../types/comptabilite'
import { toNumber } from '../../utils/amount'
import { useToast } from '../../hooks/useToast'
import styles from './ComptaBanquesPanel.module.css'

function isoDate(value: Date): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function montant(value: string | number | null | undefined, devise: string): string {
  return `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(toNumber(value ?? 0))} ${devise}`
}

function jour(value: string): string {
  const [annee, mois, j] = value.slice(0, 10).split('-')
  return annee && mois && j ? `${j}/${mois}/${annee}` : value
}

const STATUTS_LIGNE: Record<ComptaReleveLigne['statut_rapprochement'], string> = {
  NON_RAPPROCHE: 'Sans correspondance',
  PROPOSE: 'Proposé',
  INCERTAIN: 'À vérifier',
  RAPPROCHE: 'Rapproché',
  IGNORE: 'Ignoré',
}

const OPERATIONS: Record<string, string> = {
  ENCAISSEMENT: 'Encaissement',
  VERSEMENT: 'Versement',
  SORTIE: 'Sortie',
  TRANSFERT: 'Transfert',
}

function libelleProposition(item: ComptaPropositionRapprochement): string {
  const score = Math.round(toNumber(item.score))
  const type = OPERATIONS[item.operation_type] ?? item.operation_type
  return `${score} % · ${type} · ${jour(item.date_operation)} · ${item.reference || item.libelle}`
}

type FiltreLignes = 'A_TRAITER' | 'RAPPROCHE' | 'IGNORE' | 'DOUBLON' | 'TOUT'

const FILTRES: { cle: FiltreLignes; libelle: string }[] = [
  { cle: 'A_TRAITER', libelle: 'À traiter' },
  { cle: 'RAPPROCHE', libelle: 'Rapprochées' },
  { cle: 'IGNORE', libelle: 'Ignorées' },
  { cle: 'DOUBLON', libelle: 'Doublons' },
  { cle: 'TOUT', libelle: 'Toutes' },
]

function filtreDe(ligne: ComptaReleveLigne): Exclude<FiltreLignes, 'TOUT'> {
  if (ligne.est_doublon) return 'DOUBLON'
  if (ligne.statut_rapprochement === 'RAPPROCHE') return 'RAPPROCHE'
  if (ligne.statut_rapprochement === 'IGNORE') return 'IGNORE'
  return 'A_TRAITER'
}

function propositionKey(item: ComptaPropositionRapprochement): string {
  return `${item.operation_type}|${item.operation_id}`
}

interface Props {
  canSaisir: boolean
  canValider: boolean
  canEncaisser: boolean
  canDecaisser: boolean
}

export default function ComptaBanquesPanel({ canSaisir, canValider, canEncaisser, canDecaisser }: Props) {
  // Mêmes droits que le serveur : saisie ou validation comptable.
  const canImporter = canSaisir || canValider
  const now = new Date()
  const [dateDebut, setDateDebut] = useState(isoDate(new Date(now.getFullYear(), now.getMonth(), 1)))
  const [dateFin, setDateFin] = useState(isoDate(now))
  const [compteId, setCompteId] = useState<number | null>(null)
  const [releveId, setReleveId] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [savingLineId, setSavingLineId] = useState<string | null>(null)
  const [selection, setSelection] = useState<Record<string, string>>({})
  const [filtreLignes, setFiltreLignes] = useState<FiltreLignes>('A_TRAITER')
  const [confirmationLot, setConfirmationLot] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()
  const { notifyError, notifySuccess } = useToast()

  const comptesQuery = useQuery({
    queryKey: ['compta-banques-comptes'],
    queryFn: () => listComptesBancaires({ active: true, account_type: 'BANK' }),
    staleTime: 5 * 60_000,
  })
  const mappingsQuery = useQuery({
    queryKey: ['compta-mappings-banques'],
    queryFn: () => getComptaMappings(),
    staleTime: 5 * 60_000,
  })
  const comptes = comptesQuery.data ?? []

  useEffect(() => {
    if (compteId === null && comptes.length > 0) setCompteId(comptes[0].id)
  }, [compteId, comptes])

  const compte = comptes.find(item => item.id === compteId)
  const mapping = mappingsQuery.data?.comptes_bancaires.find(item => item.compte_bancaire_id === compteId)
  const devise = compte?.devise ?? 'USD'

  const mouvementsQuery = useQuery({
    queryKey: ['compta-banque-mouvements', compteId, devise, dateDebut, dateFin],
    queryFn: () => getComptaMouvementsBancaires({
      compte_bancaire_id: Number(compteId),
      devise,
      date_debut: dateDebut,
      date_fin: dateFin,
    }),
    enabled: compteId !== null && Boolean(dateDebut && dateFin),
  })
  const relevesQuery = useQuery({
    queryKey: ['compta-releves', compteId],
    queryFn: () => getComptaRelevesBancaires(Number(compteId)),
    enabled: compteId !== null,
  })
  const releveQuery = useQuery({
    queryKey: ['compta-releve', releveId],
    queryFn: () => getComptaReleveBancaire(String(releveId)),
    enabled: Boolean(releveId),
  })
  const journal = mouvementsQuery.data
  const releve = releveQuery.data

  const compteParFiltre = useMemo(() => {
    const compte: Record<FiltreLignes, number> = { A_TRAITER: 0, RAPPROCHE: 0, IGNORE: 0, DOUBLON: 0, TOUT: 0 }
    for (const ligne of releve?.lignes ?? []) {
      compte[filtreDe(ligne)] += 1
      compte.TOUT += 1
    }
    return compte
  }, [releve])
  const lignesAffichees = useMemo(
    () => (releve?.lignes ?? []).filter(ligne => filtreLignes === 'TOUT' || filtreDe(ligne) === filtreLignes),
    [releve, filtreLignes]
  )
  // « Sûres » = statut PROPOSE côté serveur : score d'au moins 90 et aucune
  // autre opération à moins de 5 points. Les INCERTAIN restent à la main.
  const propositionsSures = useMemo(
    () => (releve?.lignes ?? []).filter(
      ligne => !ligne.est_doublon && ligne.statut_rapprochement === 'PROPOSE' && ligne.propositions.length > 0
    ),
    [releve]
  )

  const compteLabel = useMemo(() => {
    if (!compte) return 'Compte bancaire'
    return `${compte.banque?.nom || 'Banque'} — ${compte.intitule}`
  }, [compte])

  const importer = async () => {
    if (!file || compteId === null) return
    setUploading(true)
    try {
      const imported = await importComptaReleveBancaire(compteId, file)
      setReleveId(imported.id)
      setFile(null)
      if (inputRef.current) inputRef.current.value = ''
      await queryClient.invalidateQueries({ queryKey: ['compta-releves', compteId] })
      queryClient.setQueryData(['compta-releve', imported.id], imported)
      notifySuccess('Relevé importé', `${imported.nombre_lignes} ligne(s), ${imported.nombre_doublons} doublon(s) détecté(s).`)
    } catch (error: any) {
      notifyError('Import refusé', error?.message || 'Le relevé ne peut pas être lu.')
    } finally {
      setUploading(false)
    }
  }

  const choixPour = (ligne: ComptaReleveLigne): ComptaPropositionRapprochement | undefined => {
    const key = selection[ligne.id]
    return ligne.propositions.find(item => propositionKey(item) === key) ?? ligne.propositions[0]
  }

  const decider = async (ligne: ComptaReleveLigne, decision: 'RAPPROCHER' | 'IGNORER' | 'ANNULER') => {
    const choix = choixPour(ligne)
    if (decision === 'RAPPROCHER' && !choix) {
      notifyError('Aucune proposition', 'Cette ligne ne dispose pas de mouvement à confirmer.')
      return
    }
    setSavingLineId(ligne.id)
    try {
      await deciderComptaRapprochement(ligne.id, {
        decision,
        operation_type: choix?.operation_type,
        operation_id: choix?.operation_id,
      })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['compta-releve', releveId] }),
        queryClient.invalidateQueries({ queryKey: ['compta-releves', compteId] }),
        queryClient.invalidateQueries({ queryKey: ['compta-banque-mouvements', compteId] }),
      ])
      const titres = { RAPPROCHER: 'Rapprochement confirmé', IGNORER: 'Ligne ignorée', ANNULER: 'Décision annulée' }
      notifySuccess(titres[decision], ligne.libelle)
    } catch (error: any) {
      notifyError('Décision impossible', error?.message || 'Le rapprochement n’a pas été enregistré.')
    } finally {
      setSavingLineId(null)
    }
  }

  const confirmerPropositionsSures = async () => {
    setConfirmationLot(false)
    setSavingLineId('lot')
    let confirmees = 0
    const refus: string[] = []
    for (const ligne of propositionsSures) {
      const choix = ligne.propositions[0]
      try {
        await deciderComptaRapprochement(ligne.id, {
          decision: 'RAPPROCHER',
          operation_type: choix.operation_type,
          operation_id: choix.operation_id,
        })
        confirmees += 1
      } catch (error: any) {
        refus.push(`ligne ${ligne.numero_ligne} : ${error?.message || 'refusée'}`)
      }
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['compta-releve', releveId] }),
      queryClient.invalidateQueries({ queryKey: ['compta-releves', compteId] }),
      queryClient.invalidateQueries({ queryKey: ['compta-banque-mouvements', compteId] }),
    ])
    setSavingLineId(null)
    if (refus.length === 0) {
      notifySuccess('Propositions confirmées', `${confirmees} ligne(s) rapprochée(s).`)
    } else {
      notifyError(
        `${confirmees} confirmée(s), ${refus.length} refusée(s)`,
        refus.slice(0, 3).join(' · ') + (refus.length > 3 ? ' …' : '')
      )
    }
  }

  return (
    <div className={styles.stack}>
      <section className={styles.panel}>
        <div className={styles.heading}>
          <div><span className={styles.eyebrow}>Trésorerie bancaire</span><h3>Comptes et mouvements</h3><p>Chaque devise reste séparée ; aucune conversion n’est appliquée ici.</p></div>
          <div className={styles.quickActions}>
            {canEncaisser && <Link to="/encaissements/nouveau"><ArrowDownToLine size={15} /> Encaissement</Link>}
            {canDecaisser && <Link to="/sorties-fonds/nouvelle"><ArrowUpFromLine size={15} /> Décaissement / frais</Link>}
            {canDecaisser && <Link to="/sorties-fonds/nouvelle?type_sortie=versement_banque"><ArrowRightLeft size={15} /> Virement interne</Link>}
          </div>
        </div>

        <div className={styles.filters}>
          <label>Compte bancaire<select value={compteId ?? ''} onChange={event => {
            setCompteId(event.target.value ? Number(event.target.value) : null)
            setReleveId(null)
          }}><option value="">Sélectionner…</option>{comptes.map(item => <option key={item.id} value={item.id}>{item.banque?.nom || 'Banque'} — {item.intitule} ({item.devise})</option>)}</select></label>
          <label>Du<input type="date" value={dateDebut} onChange={event => setDateDebut(event.target.value)} /></label>
          <label>Au<input type="date" value={dateFin} onChange={event => setDateFin(event.target.value)} /></label>
          <button type="button" className={styles.refresh} onClick={() => mouvementsQuery.refetch()} disabled={!compteId || mouvementsQuery.isFetching}><RefreshCw size={15} /> Actualiser</button>
        </div>

        {compte && <div className={`${styles.accountCard} ${mapping?.compte_id ? styles.accountReady : styles.accountMissing}`}>
          <Landmark size={20} /><div><strong>{compteLabel}</strong><span>{compte.numero_compte || 'N° non renseigné'} · {devise} · Compte comptable : {mapping?.compte_numero ? `${mapping.compte_numero} — ${mapping.compte_libelle}` : 'À paramétrer'}</span></div>
        </div>}

        {journal ? <>
          <div className={styles.metrics}>
            <div><span>Solde initial</span><strong>{montant(journal.solde_initial, devise)}</strong></div>
            <div className={styles.in}><span>Encaissements</span><strong>{montant(journal.total_entrees, devise)}</strong></div>
            <div className={styles.out}><span>Décaissements</span><strong>{montant(journal.total_sorties, devise)}</strong></div>
            <div><span>Solde final</span><strong>{montant(journal.solde_final, devise)}</strong></div>
          </div>
          <div className={styles.tableWrap}><table><thead><tr><th>Date</th><th>Type</th><th>Référence</th><th>Tiers</th><th>Libellé</th><th>Débit</th><th>Crédit</th><th>Solde</th><th>Pointé</th></tr></thead><tbody>
            {journal.lignes.map((ligne, index) => <tr key={`${ligne.transaction_type}-${ligne.transaction_id}-${index}`}><td>{jour(ligne.date)}</td><td>{ligne.type_operation || ligne.transaction_type || '—'}</td><td className={styles.mono}>{ligne.reference || '—'}</td><td>{ligne.tiers || '—'}</td><td>{ligne.libelle || '—'}</td><td className={styles.amount}>{toNumber(ligne.sortie) ? montant(ligne.sortie, devise) : '—'}</td><td className={styles.amount}>{toNumber(ligne.entree) ? montant(ligne.entree, devise) : '—'}</td><td className={styles.amount}>{montant(ligne.solde, devise)}</td><td><span className={`${styles.badge} ${ligne.is_reconciled ? styles.ok : styles.wait}`}>{ligne.is_reconciled ? 'Oui' : 'Non'}</span></td></tr>)}
          </tbody></table>{journal.lignes.length === 0 && <div className={styles.empty}>Aucun mouvement sur cette période.</div>}</div>
        </> : <div className={styles.empty}>{mouvementsQuery.isLoading ? 'Chargement des mouvements…' : 'Sélectionnez un compte bancaire.'}</div>}
      </section>

      <section className={styles.panel}>
        <div className={styles.heading}><div><span className={styles.eyebrow}>Rapprochement bancaire</span><h3>Importer un relevé CSV ou Excel</h3><p>Les correspondances sont proposées ; une validation humaine reste obligatoire.</p></div></div>
        <div className={styles.importBar}>
          <input ref={inputRef} type="file" accept=".csv,.xlsx" onChange={event => setFile(event.target.files?.[0] ?? null)} disabled={!canImporter || compteId === null} />
          <button type="button" className={styles.primary} onClick={importer} disabled={!canImporter || !file || compteId === null || uploading}><FileUp size={16} /> {uploading ? 'Analyse…' : 'Importer le relevé'}</button>
        </div>
        {!canImporter && <p className={styles.notice}>La permission de saisie ou de validation comptable est requise pour importer un relevé.</p>}

        <div className={styles.imports}>
          {(relevesQuery.data ?? []).map(item => <button type="button" key={item.id} className={releveId === item.id ? styles.importActive : ''} onClick={() => setReleveId(item.id)}><strong>{item.nom_fichier}</strong><span>{new Date(item.created_at).toLocaleString('fr-FR')} · {item.nombre_lignes} lignes · {item.nombre_rapprochees}/{item.nombre_lignes - item.nombre_doublons} rapprochée(s) · {item.nombre_doublons} doublon(s)</span></button>)}
          {!relevesQuery.isLoading && (relevesQuery.data?.length ?? 0) === 0 && <div className={styles.empty}>Aucun relevé importé pour ce compte.</div>}
        </div>

        {releve && <div className={styles.statement}>
          <div className={styles.statementTitle}>
            <strong>{releve.nom_fichier}</strong>
            <span>
              {releve.nombre_rapprochees}/{releve.nombre_lignes - releve.nombre_doublons} rapprochée(s) ·{' '}
              {releve.nombre_doublons} doublon(s)
            </span>
          </div>
          <div className={styles.statementBar}>
            <div className={styles.filtresLignes} role="group" aria-label="Filtrer les lignes du relevé">
              {FILTRES.map(({ cle, libelle }) => (
                <button
                  key={cle}
                  type="button"
                  aria-pressed={filtreLignes === cle}
                  className={filtreLignes === cle ? styles.filtreActif : ''}
                  onClick={() => setFiltreLignes(cle)}
                >
                  {libelle} <span>{compteParFiltre[cle]}</span>
                </button>
              ))}
            </div>
            {canValider && propositionsSures.length > 0 && (
              confirmationLot ? (
                <div className={styles.confirmationLot} role="alert">
                  <span>
                    Confirmer {propositionsSures.length} rapprochement(s) ? Chaque ligne sera tracée à votre nom.
                  </span>
                  <button type="button" className={styles.primary} onClick={confirmerPropositionsSures}>
                    Confirmer
                  </button>
                  <button type="button" className={styles.refresh} onClick={() => setConfirmationLot(false)}>
                    Annuler
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className={styles.primary}
                  disabled={savingLineId !== null}
                  onClick={() => setConfirmationLot(true)}
                >
                  <CheckCheck size={15} />
                  {savingLineId === 'lot'
                    ? 'Confirmation…'
                    : `Confirmer les ${propositionsSures.length} propositions sûres`}
                </button>
              )
            )}
          </div>
          <div className={styles.tableWrap}><table><thead><tr><th>Ligne</th><th>Date</th><th>Référence / tiers</th><th>Libellé</th><th>Débit</th><th>Crédit</th><th>Statut</th><th>Proposition à valider</th><th>Action</th></tr></thead><tbody>
            {lignesAffichees.map(ligne => {
              const choix = choixPour(ligne)
              const decidee = ['RAPPROCHE', 'IGNORE'].includes(ligne.statut_rapprochement)
              const decidable = !ligne.est_doublon && !decidee
              const enCours = savingLineId === ligne.id || savingLineId === 'lot'
              const badge = ligne.est_doublon
                ? styles.duplicate
                : ligne.statut_rapprochement === 'RAPPROCHE'
                  ? styles.ok
                  : styles.wait
              return (
                <tr key={ligne.id}>
                  <td>{ligne.numero_ligne}</td>
                  <td>
                    {jour(ligne.date_operation)}
                    {ligne.date_valeur ? <small>Valeur {jour(ligne.date_valeur)}</small> : null}
                  </td>
                  <td>
                    <span className={styles.mono}>{ligne.reference || '—'}</span>
                    <small>{ligne.tiers || ''}</small>
                  </td>
                  <td>{ligne.libelle}</td>
                  <td className={styles.amount}>{toNumber(ligne.debit) ? montant(ligne.debit, devise) : '—'}</td>
                  <td className={styles.amount}>{toNumber(ligne.credit) ? montant(ligne.credit, devise) : '—'}</td>
                  <td>
                    <span className={`${styles.badge} ${badge}`}>
                      {ligne.est_doublon ? 'Doublon' : STATUTS_LIGNE[ligne.statut_rapprochement]}
                    </span>
                  </td>
                  <td>
                    {decidable && ligne.propositions.length > 0 ? (
                      <select
                        value={propositionKey(choix!)}
                        onChange={event => setSelection(current => ({ ...current, [ligne.id]: event.target.value }))}
                      >
                        {ligne.propositions.map(item => (
                          <option key={propositionKey(item)} value={propositionKey(item)}>
                            {libelleProposition(item)}
                          </option>
                        ))}
                      </select>
                    ) : ligne.statut_rapprochement === 'RAPPROCHE' && ligne.operation_type ? (
                      OPERATIONS[ligne.operation_type] ?? ligne.operation_type
                    ) : decidable ? (
                      'Aucune'
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>
                    {canValider && decidable ? (
                      <div className={styles.lineActions}>
                        <button
                          type="button"
                          title="Confirmer"
                          aria-label="Confirmer le rapprochement"
                          disabled={!choix || enCours}
                          onClick={() => decider(ligne, 'RAPPROCHER')}
                        >
                          <Check size={15} />
                        </button>
                        <button
                          type="button"
                          title="Ignorer"
                          aria-label="Ignorer la ligne"
                          disabled={enCours}
                          onClick={() => decider(ligne, 'IGNORER')}
                        >
                          <X size={15} />
                        </button>
                      </div>
                    ) : canValider && decidee && !ligne.est_doublon ? (
                      <div className={styles.lineActions}>
                        <button
                          type="button"
                          title="Annuler la décision"
                          aria-label="Annuler la décision"
                          disabled={enCours}
                          onClick={() => decider(ligne, 'ANNULER')}
                        >
                          <Undo2 size={15} />
                        </button>
                      </div>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody></table>
            {lignesAffichees.length === 0 && (
              <div className={styles.empty}>
                {filtreLignes === 'A_TRAITER' ? 'Toutes les lignes de ce relevé ont été traitées.' : 'Aucune ligne dans ce filtre.'}
              </div>
            )}
          </div>
          {!canValider && <p className={styles.notice}>La permission de validation comptable est requise pour confirmer un rapprochement.</p>}
        </div>}
        {releveQuery.isLoading && <div className={styles.empty}>Chargement du relevé…</div>}
      </section>
    </div>
  )
}
