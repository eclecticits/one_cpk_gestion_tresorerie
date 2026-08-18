import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { CheckCheck, Plus } from 'lucide-react'
import {
  getComptaComptes,
  getComptaEcritures,
  getComptaExercices,
  getComptaJournaux,
  getComptaOperationsAComptabiliser,
  getComptaStatut,
  setupComptabilite,
} from '../api/comptabilite'
import { usePermissions } from '../hooks/usePermissions'
import { toNumber } from '../utils/amount'
import type { ComptaEcriture, TypeReferentiel } from '../types/comptabilite'
import PageHeader from '../components/PageHeader'
import ComptaSetupScreen from '../components/comptabilite/ComptaSetupScreen'
import ComptaEtatsPanel from '../components/comptabilite/ComptaEtatsPanel'
import ComptaEtatsFinanciersPanel from '../components/comptabilite/ComptaEtatsFinanciersPanel'
import ComptaMappingsPanel from '../components/comptabilite/ComptaMappingsPanel'
import EcritureFormModal from '../components/comptabilite/EcritureFormModal'
import EcritureDetailModal from '../components/comptabilite/EcritureDetailModal'
import ValidationLotModal from '../components/comptabilite/ValidationLotModal'
import { useToast } from '../hooks/useToast'
import styles from './Comptabilite.module.css'

const STATUTS = ['BROUILLON', 'VALIDEE', 'CLOTUREE', 'ANNULEE']

type Onglet = 'ecritures' | 'a-comptabiliser' | 'etats' | 'etats-financiers' | 'parametrage'

const ONGLETS: [Onglet, string][] = [
  ['ecritures', 'Écritures'],
  ['a-comptabiliser', 'À comptabiliser'],
  ['etats', 'Grand Livre'],
  ['etats-financiers', 'États financiers'],
  ['parametrage', 'Paramétrage'],
]

const ONGLET_KEYS = new Set<Onglet>(ONGLETS.map(([cle]) => cle))

function parseOnglet(value: string | null): Onglet {
  return value && ONGLET_KEYS.has(value as Onglet) ? (value as Onglet) : 'ecritures'
}

const SOUS_TITRES: Record<Onglet, string> = {
  ecritures: 'Écritures comptables',
  'a-comptabiliser': 'Opérations en attente de comptabilisation manuelle',
  etats: 'Grand Livre, Journal et Balance',
  'etats-financiers': 'Bilan, Résultat, SIG et clôture',
  parametrage: 'Paramétrage comptable',
}

function formatMontant(value: number): string {
  return new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)
}

function badgeClass(statut: string): string {
  switch (statut) {
    case 'VALIDEE':
      return styles.badgeValidee
    case 'CLOTUREE':
      return styles.badgeCloturee
    case 'ANNULEE':
      return styles.badgeAnnulee
    default:
      return styles.badgeBrouillon
  }
}

export default function Comptabilite() {
  const { hasPermission, loading: permissionsLoading } = usePermissions()
  const { notifyError, notifySuccess } = useToast()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()

  const canSaisir = hasPermission('compta.saisie')
  const canValider = hasPermission('compta.validation')
  const canParametrer = hasPermission('compta.parametrage')
  const canCloturer = hasPermission('compta.cloture')

  const [setupSubmitting, setSetupSubmitting] = useState(false)
  const [setupError, setSetupError] = useState<string | null>(null)
  const [onglet, setOnglet] = useState<Onglet>(() => parseOnglet(searchParams.get('tab')))

  const [filterStatut, setFilterStatut] = useState('')
  const [filterJournal, setFilterJournal] = useState('')
  const [filterExercice, setFilterExercice] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 20

  const [showForm, setShowForm] = useState(false)
  const [selectedEcriture, setSelectedEcriture] = useState<ComptaEcriture | null>(null)
  const [showValidationLot, setShowValidationLot] = useState(false)

  const statutQuery = useQuery({
    queryKey: ['compta-statut'],
    queryFn: getComptaStatut,
  })

  const provisionne = statutQuery.data?.provisionne ?? false

  const referentielQuery = useQuery({
    queryKey: ['compta-referentiel'],
    queryFn: async () => {
      const [comptes, journaux, exercices] = await Promise.all([
        getComptaComptes(),
        getComptaJournaux(),
        getComptaExercices(),
      ])
      return { comptes, journaux, exercices }
    },
    enabled: provisionne,
    // Référentiel comptable (plan de comptes, journaux, exercices) : change
    // rarement en session, on évite un refetch à chaque montage de l'écran.
    staleTime: 5 * 60_000,
  })

  const comptes = referentielQuery.data?.comptes ?? []
  const journaux = referentielQuery.data?.journaux ?? []
  const exercices = referentielQuery.data?.exercices ?? []

  const ecrituresQueryKey = [
    'compta-ecritures',
    filterStatut,
    filterJournal,
    filterExercice,
    page,
    pageSize,
  ] as const

  const ecrituresQuery = useQuery({
    queryKey: ecrituresQueryKey,
    queryFn: () =>
      getComptaEcritures({
        statut: filterStatut || undefined,
        journal_id: filterJournal ? Number(filterJournal) : undefined,
        exercice_id: filterExercice ? Number(filterExercice) : undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      }),
    enabled: provisionne,
  })

  const ecritures = ecrituresQuery.data?.items ?? []
  const totalCount = ecrituresQuery.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))

  const operationsManuellesQuery = useQuery({
    queryKey: ['compta-operations-a-comptabiliser'],
    queryFn: () => getComptaOperationsAComptabiliser({ limit: 200, offset: 0 }),
    enabled: provisionne && onglet === 'a-comptabiliser',
  })
  const operationsManuelles = operationsManuellesQuery.data?.items ?? []

  const journalLabel = useMemo(() => {
    const map = new Map<number, string>()
    journaux.forEach(j => map.set(j.id, j.code))
    return (id: number) => map.get(id) ?? String(id)
  }, [journaux])

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['compta-statut'] })
    queryClient.invalidateQueries({ queryKey: ['compta-referentiel'] })
    queryClient.invalidateQueries({ queryKey: ['compta-ecritures'] })
    queryClient.invalidateQueries({ queryKey: ['compta-operations-a-comptabiliser'] })
  }

  const handleSetup = async (input: {
    type_referentiel: TypeReferentiel
    exercice_date_debut: string
    exercice_date_fin: string
  }) => {
    setSetupSubmitting(true)
    setSetupError(null)
    try {
      await setupComptabilite(input)
      invalidateAll()
      notifySuccess('Comptabilité activée', 'Le plan de comptes et les journaux ont été créés.')
    } catch (err: any) {
      setSetupError(err?.message || "Impossible d'activer la comptabilité.")
    } finally {
      setSetupSubmitting(false)
    }
  }

  const handleCreated = (ecriture: ComptaEcriture) => {
    setShowForm(false)
    queryClient.invalidateQueries({ queryKey: ['compta-ecritures'] })
    notifySuccess('Écriture enregistrée', 'Elle est en brouillon — validez-la pour lui attribuer un numéro.')
    setSelectedEcriture(ecriture)
  }

  const handleUpdated = (ecriture: ComptaEcriture) => {
    setSelectedEcriture(ecriture)
    queryClient.invalidateQueries({ queryKey: ['compta-ecritures'] })
    if (ecriture.statut === 'VALIDEE') {
      notifySuccess('Écriture validée', `Numéro attribué : ${ecriture.numero}`)
    } else if (ecriture.statut === 'ANNULEE') {
      notifySuccess('Écriture contre-passée', 'Une écriture inverse a été créée en brouillon.')
    }
  }

  useEffect(() => {
    if (statutQuery.isError) {
      notifyError('Erreur', 'Impossible de charger le statut du module Comptabilité.')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statutQuery.isError])

  useEffect(() => {
    const nextOnglet = parseOnglet(searchParams.get('tab'))
    setOnglet(prev => (prev === nextOnglet ? prev : nextOnglet))
  }, [searchParams])

  const handleOngletChange = (nextOnglet: Onglet) => {
    setOnglet(nextOnglet)
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('tab', nextOnglet)
    setSearchParams(nextParams)
  }

  if (permissionsLoading || statutQuery.isLoading) {
    return <div className={styles.loadingScreen}>Chargement…</div>
  }

  if (!provisionne) {
    return (
      <div className={styles.container}>
        <PageHeader title="Comptabilité" subtitle="Comptabilité générale en partie double" />
        <ComptaSetupScreen
          canConfigure={canParametrer}
          submitting={setupSubmitting}
          errorMessage={setupError}
          onSubmit={handleSetup}
        />
      </div>
    )
  }

  return (
    <div className={styles.container}>
      <PageHeader
        title="Comptabilité"
        subtitle={SOUS_TITRES[onglet]}
        actions={
          onglet === 'ecritures' || onglet === 'a-comptabiliser' ? (
            <div className={styles.toolbar}>
              {onglet === 'ecritures' && canValider && (
                <button
                  type="button"
                  className={styles.validerLotBtn}
                  onClick={() => setShowValidationLot(true)}
                >
                  <CheckCheck size={16} style={{ verticalAlign: '-3px', marginRight: '4px' }} />
                  Valider les brouillons
                </button>
              )}
              {canSaisir && (
                <button type="button" className={styles.newEcritureBtn} onClick={() => setShowForm(true)}>
                  <Plus size={16} style={{ verticalAlign: '-3px', marginRight: '4px' }} />
                  Nouvelle écriture
                </button>
              )}
            </div>
          ) : undefined
        }
      />

      <div className={styles.tabs} role="tablist">
        {ONGLETS.map(([cle, libelle]) => (
          <button
            key={cle}
            type="button"
            role="tab"
            aria-selected={onglet === cle}
            className={`${styles.tab} ${onglet === cle ? styles.tabActive : ''}`}
            onClick={() => handleOngletChange(cle)}
          >
            {libelle}
          </button>
        ))}
      </div>

      {onglet === 'parametrage' ? (
        <ComptaMappingsPanel comptes={comptes} canParametrer={canParametrer} />
      ) : onglet === 'etats-financiers' ? (
        <ComptaEtatsFinanciersPanel exercices={exercices} canCloturer={canCloturer} />
      ) : onglet === 'etats' ? (
        <ComptaEtatsPanel
          comptes={comptes}
          journaux={journaux}
          exercices={exercices}
          canValider={canValider}
        />
      ) : onglet === 'a-comptabiliser' ? (
        <div className={styles.tableWrap}>
          {operationsManuellesQuery.isLoading ? (
            <div className={styles.loadingState}>Chargement des opérations…</div>
          ) : operationsManuelles.length === 0 ? (
            <div className={styles.emptyState}>Aucune opération en attente de comptabilisation manuelle.</div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Référence</th>
                  <th>Date</th>
                  <th>Libellé</th>
                  <th>Poste budgétaire</th>
                  <th style={{ textAlign: 'right' }}>Montant</th>
                  <th>Statut</th>
                </tr>
              </thead>
              <tbody>
                {operationsManuelles.map(operation => (
                  <tr key={`${operation.type_operation}-${operation.id}`}>
                    <td>{operation.type_operation === 'encaissement' ? 'Encaissement' : 'Sortie de fonds'}</td>
                    <td className={styles.numeroCell}>{operation.reference || '-'}</td>
                    <td>{operation.date_operation ? operation.date_operation.slice(0, 10) : '-'}</td>
                    <td className={styles.libelleCell}>{operation.libelle}</td>
                    <td className={styles.libelleCell}>
                      {operation.budget_poste_code
                        ? `${operation.budget_poste_code} - ${operation.budget_poste_libelle || ''}`
                        : operation.budget_poste_libelle || '-'}
                    </td>
                    <td className={styles.amountCell}>
                      {formatMontant(toNumber(operation.montant))} {operation.devise}
                    </td>
                    <td>
                      <span className={`${styles.badge} ${styles.badgeBrouillon}`}>À saisir</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : (
        <>
      <div className={styles.filtersBar}>
        <div className={styles.filterField}>
          <label htmlFor="compta-filter-statut">Statut</label>
          <select
            id="compta-filter-statut"
            value={filterStatut}
            onChange={e => {
              setFilterStatut(e.target.value)
              setPage(1)
            }}
          >
            <option value="">Tous</option>
            {STATUTS.map(s => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.filterField}>
          <label htmlFor="compta-filter-journal">Journal</label>
          <select
            id="compta-filter-journal"
            value={filterJournal}
            onChange={e => {
              setFilterJournal(e.target.value)
              setPage(1)
            }}
          >
            <option value="">Tous</option>
            {journaux.map(j => (
              <option key={j.id} value={j.id}>
                {j.code} — {j.libelle}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.filterField}>
          <label htmlFor="compta-filter-exercice">Exercice</label>
          <select
            id="compta-filter-exercice"
            value={filterExercice}
            onChange={e => {
              setFilterExercice(e.target.value)
              setPage(1)
            }}
          >
            <option value="">Tous</option>
            {exercices.map(ex => (
              <option key={ex.id} value={ex.id}>
                {ex.code}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.resultCount}>
          {totalCount} écriture{totalCount > 1 ? 's' : ''}
        </div>
      </div>

      <div className={styles.tableWrap}>
        {ecrituresQuery.isLoading ? (
          <div className={styles.loadingState}>Chargement des écritures…</div>
        ) : ecritures.length === 0 ? (
          <div className={styles.emptyState}>
            Aucune écriture{filterStatut || filterJournal || filterExercice ? ' pour ces filtres' : ''}.
          </div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Numéro</th>
                <th>Date</th>
                <th>Journal</th>
                <th>Libellé</th>
                <th style={{ textAlign: 'right' }}>Montant</th>
                <th>Statut</th>
              </tr>
            </thead>
            <tbody>
              {ecritures.map(ec => {
                const total = ec.lignes.reduce((sum, l) => sum + toNumber(l.debit), 0)
                return (
                  <tr key={ec.id} className={styles.row} onClick={() => setSelectedEcriture(ec)}>
                    <td className={styles.numeroCell}>{ec.numero || '(brouillon)'}</td>
                    <td>{ec.date_ecriture}</td>
                    <td>{journalLabel(ec.journal_id)}</td>
                    <td className={styles.libelleCell}>{ec.libelle}</td>
                    <td className={styles.amountCell}>
                      {formatMontant(total)} {ec.devise}
                    </td>
                    <td>
                      <span className={`${styles.badge} ${badgeClass(ec.statut)}`}>{ec.statut}</span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {totalCount > 0 && (
        <div className={styles.pagination}>
          <button
            type="button"
            className={styles.pageBtn}
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
          >
            ← Précédent
          </button>
          <span className={styles.pageInfo}>
            Page {page} / {totalPages}
          </span>
          <button
            type="button"
            className={styles.pageBtn}
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
          >
            Suivant →
          </button>
        </div>
      )}
        </>
      )}

      {showForm && (
        <EcritureFormModal
          journaux={journaux}
          exercices={exercices}
          comptes={comptes}
          onClose={() => setShowForm(false)}
          onCreated={handleCreated}
        />
      )}

      {showValidationLot && (
        <ValidationLotModal
          exerciceId={filterExercice ? Number(filterExercice) : undefined}
          journalId={filterJournal ? Number(filterJournal) : undefined}
          exercices={exercices}
          journaux={journaux}
          onClose={() => setShowValidationLot(false)}
          onValide={result => {
            setShowValidationLot(false)
            queryClient.invalidateQueries({ queryKey: ['compta-ecritures'] })
            queryClient.invalidateQueries({ queryKey: ['compta-balance'] })
            queryClient.invalidateQueries({ queryKey: ['compta-etat'] })
            queryClient.invalidateQueries({ queryKey: ['compta-controle-bilan'] })
            notifySuccess(
              `${result.validees} écriture(s) validée(s)`,
              result.echecs.length > 0
                ? `${result.echecs.length} écriture(s) sont restées au brouillon — corrigez-les puis relancez.`
                : 'Elles entrent désormais dans le Grand Livre et les états financiers.'
            )
          }}
        />
      )}

      {selectedEcriture && (
        <EcritureDetailModal
          ecriture={selectedEcriture}
          journaux={journaux}
          exercices={exercices}
          canValidate={canValider}
          onClose={() => setSelectedEcriture(null)}
          onUpdated={handleUpdated}
        />
      )}
    </div>
  )
}
