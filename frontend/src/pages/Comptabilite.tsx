import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  BookOpenCheck,
  CheckCheck,
  Download,
  FileBarChart2,
  FileText,
  Hourglass,
  Inbox,
  Landmark,
  Link2,
  Plus,
  Settings2,
  type LucideIcon,
} from 'lucide-react'
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
import ComptaExportsPanel from '../components/comptabilite/ComptaExportsPanel'
import ComptaBanquesPanel from '../components/comptabilite/ComptaBanquesPanel'
import ComptaLettragePanel from '../components/comptabilite/ComptaLettragePanel'
import ComptaBalanceAgeePanel from '../components/comptabilite/ComptaBalanceAgeePanel'
import EcritureFormModal from '../components/comptabilite/EcritureFormModal'
import EcritureDetailModal from '../components/comptabilite/EcritureDetailModal'
import ValidationLotModal from '../components/comptabilite/ValidationLotModal'
import { useToast } from '../hooks/useToast'
import styles from './Comptabilite.module.css'

const STATUTS = ['BROUILLON', 'VALIDEE', 'CLOTUREE', 'ANNULEE']

type Onglet = 'ecritures' | 'a-comptabiliser' | 'banques' | 'lettrage' | 'balance-agee' | 'exports' | 'etats' | 'etats-financiers' | 'parametrage'

interface OngletDefinition {
  cle: Onglet
  libelle: string
  icon: LucideIcon
  permission?: string
}

interface GroupeOnglets {
  libelle: string
  onglets: OngletDefinition[]
}

const GROUPES_ONGLETS: GroupeOnglets[] = [
  {
    libelle: 'Opérations',
    onglets: [
      { cle: 'ecritures', libelle: 'Écritures', icon: BookOpenCheck },
      { cle: 'a-comptabiliser', libelle: 'À imputer', icon: Inbox },
      { cle: 'banques', libelle: 'Banques', icon: Landmark },
    ],
  },
  {
    libelle: 'Rapprochement',
    onglets: [
      { cle: 'lettrage', libelle: 'Lettrage', icon: Link2 },
      { cle: 'balance-agee', libelle: 'Balance âgée', icon: Hourglass },
    ],
  },
  {
    libelle: 'Restitution',
    onglets: [
      { cle: 'etats', libelle: 'Grand Livre', icon: FileBarChart2 },
      { cle: 'etats-financiers', libelle: 'États financiers', icon: FileText },
      { cle: 'exports', libelle: 'Exports', icon: Download, permission: 'compta.export' },
    ],
  },
  {
    libelle: 'Configuration',
    onglets: [
      { cle: 'parametrage', libelle: 'Paramétrage', icon: Settings2, permission: 'compta.parametrage' },
    ],
  },
]

const ONGLET_KEYS = new Set<Onglet>(GROUPES_ONGLETS.flatMap(groupe => groupe.onglets.map(onglet => onglet.cle)))

function parseOnglet(value: string | null): Onglet {
  return value && ONGLET_KEYS.has(value as Onglet) ? (value as Onglet) : 'ecritures'
}

const SOUS_TITRES: Record<Onglet, string> = {
  ecritures: 'Écritures comptables',
  'a-comptabiliser': 'Opérations incomplètes en attente d’imputation comptable',
  banques: 'Comptes, mouvements et rapprochements bancaires',
  lettrage: 'Rapprochement des comptes de tiers : ce qui reste sans lettre reste dû',
  'balance-agee': 'Reste dû par tiers, rangé par ancienneté',
  exports: 'Exports comptables contrôlés et traçables',
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
  const canExport = hasPermission('compta.export')
  const canEncaisser = hasPermission('encaissements')
  const canDecaisser = hasPermission('sorties_fonds')

  const groupesOnglets = useMemo(
    () => GROUPES_ONGLETS
      .map(groupe => ({
        ...groupe,
        onglets: groupe.onglets.filter(item => !item.permission || hasPermission(item.permission)),
      }))
      .filter(groupe => groupe.onglets.length > 0),
    [hasPermission],
  )
  const ongletsVisibles = useMemo(
    () => new Set(groupesOnglets.flatMap(groupe => groupe.onglets.map(item => item.cle))),
    [groupesOnglets],
  )

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

  useEffect(() => {
    if (permissionsLoading || ongletsVisibles.has(onglet)) return
    setOnglet('ecritures')
    setSearchParams({ tab: 'ecritures' })
  }, [onglet, ongletsVisibles, permissionsLoading, setSearchParams])

  const handleOngletChange = (nextOnglet: Onglet) => {
    setOnglet(nextOnglet)
    // On repart d'une URL propre : un `etat` laissé par l'onglet Grand Livre
    // empêcherait le menu latéral de reconnaître l'onglet suivant.
    setSearchParams({ tab: nextOnglet })
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
      <div className={styles.controlPanel}>
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
                    <CheckCheck size={16} />
                    Valider les brouillons
                  </button>
                )}
                {canSaisir && (
                  <button type="button" className={styles.newEcritureBtn} onClick={() => setShowForm(true)}>
                    <Plus size={16} />
                    Nouvelle écriture
                  </button>
                )}
              </div>
            ) : undefined
          }
        />

        <nav className={styles.tabs} aria-label="Vues de la comptabilité">
          {groupesOnglets.map(groupe => (
            <div key={groupe.libelle} className={styles.tabGroup} role="group" aria-label={groupe.libelle}>
              <span className={styles.tabGroupLabel}>{groupe.libelle}</span>
              <div className={styles.tabGroupItems} role="tablist">
                {groupe.onglets.map(({ cle, libelle, icon: Icon }) => (
                  <button
                    key={cle}
                    type="button"
                    role="tab"
                    aria-selected={onglet === cle}
                    className={`${styles.tab} ${onglet === cle ? styles.tabActive : ''}`}
                    onClick={() => handleOngletChange(cle)}
                  >
                    <Icon size={15} aria-hidden="true" />
                    <span>{libelle}</span>
                    {cle === 'a-comptabiliser' && operationsManuelles.length > 0 && (
                      <b className={styles.tabCount}>{operationsManuelles.length}</b>
                    )}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </nav>
      </div>

      {onglet === 'exports' ? (
        <ComptaExportsPanel canExport={canExport} />
      ) : onglet === 'banques' ? (
        <ComptaBanquesPanel
          canSaisir={canSaisir}
          canValider={canValider}
          canEncaisser={canEncaisser}
          canDecaisser={canDecaisser}
        />
      ) : onglet === 'lettrage' ? (
        <ComptaLettragePanel canLettrer={canSaisir || canValider} />
      ) : onglet === 'balance-agee' ? (
        <ComptaBalanceAgeePanel />
      ) : onglet === 'parametrage' ? (
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
                  <th>Motif de mise en attente</th>
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
                    <td className={styles.libelleCell}>
                      {operation.message_comptabilisation || 'Imputation comptable à compléter.'}
                    </td>
                    <td>
                      <span className={`${styles.badge} ${styles.badgeBrouillon}`}>À imputer</span>
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
