import { useCallback, useEffect, useMemo, useState } from 'react'
import { format } from 'date-fns'
import { downloadExcel } from '../utils/download'

import { apiRequest, ApiError } from '../lib/apiClient'
import { getBudgetPostes } from '../api/budget'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import { Encaissement, ExpertComptable, ModePatement, TypeClient, TypeOperation } from '../types'
import { getPrintSettings } from '../api/settings'
import { toNumber } from '../utils/amount'

import styles from './Encaissements.module.css'
import PrintReceipt from '../components/PrintReceipt'
import PaymentManager from '../components/PaymentManager'
import NotificationModal from '../components/NotificationModal'
import { generateEncaissementsPDF } from '../utils/pdfGenerator'
import {
  TYPE_CLIENT_LABELS,
  OPERATIONS_PAR_TYPE_CLIENT,
  getOperationLabel,
  getTypeClientLabel,
} from '../utils/encaissementHelpers'
import PageHeader from '../components/PageHeader'

interface Notification {
  type: 'success' | 'error' | 'warning' | 'info'
  title: string
  message: string
  details?: string
}

function buildQuery(params: Record<string, any>) {
  const sp = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return
    sp.set(k, String(v))
  })
  const qs = sp.toString()
  return qs ? `?${qs}` : ''
}

export default function Encaissements() {
  const { user } = useAuth()
  const { hasPermission, loading: permissionsLoading } = usePermissions()

  const [showForm, setShowForm] = useState(false)
  const [encaissements, setEncaissements] = useState<Encaissement[]>([])
  const [budgetLines, setBudgetPostes] = useState<any[]>([])
  const [experts, setExperts] = useState<ExpertComptable[]>([])
  const [loading, setLoading] = useState(true)
  const [pageSize, setPageSize] = useState(50)
  const [page, setPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)
  const [summaryTotals, setSummaryTotals] = useState({ totalFacture: 0, totalPaye: 0 })

  const [searchEC, setSearchEC] = useState('')
  const [filteredExperts, setFilteredExperts] = useState<ExpertComptable[]>([])

  const [printingEncaissement, setPrintingEncaissement] = useState<Encaissement | null>(null)
  const [managingPayment, setManagingPayment] = useState<Encaissement | null>(null)

  const [notification, setNotification] = useState<Notification | null>(null)

  const [dateDebut, setDateDebut] = useState('')
  const [dateFin, setDateFin] = useState('')
  const [filterStatut, setFilterStatut] = useState<string>('')
  const [filterNumeroRecu, setFilterNumeroRecu] = useState('')
  const [filterClient, setFilterClient] = useState('')
  const [filterType, setFilterType] = useState<string>('')
  const [tauxChange, setTauxChange] = useState<number>(1)
  const [budgetSearch, setBudgetSearch] = useState('')
  const [showBudgetDropdown, setShowBudgetDropdown] = useState(false)
  const [expandedBudgetIds, setExpandedBudgetIds] = useState<Set<number>>(() => new Set())

  const [formData, setFormData] = useState({
    type_client: 'expert_comptable' as TypeClient,
    expert_comptable_id: '',
    client_nom: '',
    type_operation: 'cotisation_annuelle' as TypeOperation,
    description: '',
    devise_perception: 'USD',
    montant: '',
    montant_paye: '',
    mode_paiement: 'cash' as ModePatement,
    reference: '',
    notes_paiement: '',
    date_encaissement: format(new Date(), 'yyyy-MM-dd'),
    budget_poste_id: '',
  })

  const formatCurrency = (amount: string | number | null | undefined) => {
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(toNumber(amount))
  }

  const getMontantPayeUSD = () => {
    const raw = toNumber(formData.montant_paye || 0)
    if (formData.devise_perception === 'CDF') {
      return tauxChange > 0 ? raw / tauxChange : 0
    }
    return raw
  }

  const loadData = useCallback(async () => {
    try {
      setLoading(true)

      const encPath =
        '/encaissements' + buildQuery({
          include: 'expert_comptable',
          date_debut: dateDebut,
          date_fin: dateFin,
          statut_paiement: filterStatut,
          numero_recu: filterNumeroRecu,
          client: filterClient,
          type_operation: filterType,
          order: 'date_encaissement.desc',
          limit: pageSize,
          offset: (page - 1) * pageSize,
          include_summary: true,
        })
      const expPath = '/experts-comptables' + buildQuery({ active: true, limit: 200, offset: 0 })

      const [encRes, expRes, budgetRes] = await Promise.all([
        apiRequest<any>('GET', encPath),
        apiRequest<ExpertComptable[]>('GET', expPath),
        getBudgetPostes({ type: 'RECETTE', active: true }),
      ])

      const encItems = Array.isArray(encRes) ? encRes : (encRes?.items ?? [])
      setEncaissements(encItems)
      setTotalCount(
        typeof encRes?.total === 'number' ? encRes.total : Array.isArray(encItems) ? encItems.length : 0
      )
      if (encRes?.total_montant_facture !== undefined || encRes?.total_montant_paye !== undefined) {
        setSummaryTotals({
          totalFacture: toNumber(encRes.total_montant_facture ?? 0),
          totalPaye: toNumber(encRes.total_montant_paye ?? 0),
        })
      } else {
        const fallbackTotalFacture = (encItems as Encaissement[]).reduce(
          (sum, e) => sum + toNumber(e.montant_total || e.montant || 0),
          0
        )
        const fallbackTotalPaye = (encItems as Encaissement[]).reduce(
          (sum, e) => sum + toNumber(e.montant_paye || 0),
          0
        )
        setSummaryTotals({ totalFacture: fallbackTotalFacture, totalPaye: fallbackTotalPaye })
      }
      setExperts(Array.isArray(expRes) ? expRes : [])
      const items = budgetRes?.postes ?? []
      setBudgetPostes(items)
    } catch (error) {
      console.error('Error loading data:', error)
      let details = 'Vérifie la connexion au backend / API_BASE_URL.'
      if (error instanceof ApiError) {
        const payloadDetail = (error.payload as any)?.detail
        if (typeof payloadDetail === 'string') {
          details = payloadDetail
        } else if (Array.isArray(payloadDetail)) {
          details = payloadDetail.map((d) => d?.msg || d?.message || String(d)).join(' | ')
        } else if (error.message) {
          details = error.message
        }
        if (error.payload) {
          const payloadStr = JSON.stringify(error.payload)
          if (payloadStr && payloadStr !== '{}' && !details.includes(payloadStr)) {
            details = `${details} | ${payloadStr}`
          }
        }
      } else if (error && typeof (error as any).message === 'string') {
        details = (error as any).message
      } else {
        details = String(error)
      }
      setNotification({
        type: 'error',
        title: 'Erreur de chargement',
        message: 'Impossible de charger les données.',
        details,
      })
    } finally {
      setLoading(false)
    }
  }, [
    dateDebut,
    dateFin,
    filterStatut,
    filterNumeroRecu,
    filterClient,
    filterType,
    pageSize,
    page,
  ])

  useEffect(() => {
    loadData()
  }, [loadData])

  useEffect(() => {
    const loadSettings = async () => {
      try {
        const settings = await getPrintSettings()
        const rate = Number(settings.exchange_rate || 1)
        setTauxChange(rate > 0 ? rate : 1)
      } catch {
        setTauxChange(1)
      }
    }
    loadSettings()
  }, [])

  useEffect(() => {
    setPage(1)
  }, [dateDebut, dateFin, filterStatut, filterNumeroRecu, filterClient, filterType, pageSize])

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize))
  const safePage = Math.min(page, totalPages)

  const budgetTree = useMemo(() => {
    const nodes = new Map<number, any>()
    const roots: any[] = []

    budgetLines.forEach((line: any) => {
      nodes.set(line.id, { ...line, children: [] })
    })

    budgetLines.forEach((line: any) => {
      const node = nodes.get(line.id)
      if (line.parent_id && nodes.has(line.parent_id)) {
        nodes.get(line.parent_id).children.push(node)
      } else {
        roots.push(node)
      }
    })

    const sortNodes = (list: any[]) => {
      list.sort((a, b) => String(a.code || '').localeCompare(String(b.code || '')))
      list.forEach((item) => sortNodes(item.children))
    }
    sortNodes(roots)
    return roots
  }, [budgetLines])

  const filteredBudgetTree = useMemo(() => {
    const query = budgetSearch.trim().toLowerCase()
    if (!query) return budgetTree

    const matches = (node: any) => {
      const code = String(node.code || '').toLowerCase()
      const libelle = String(node.libelle || '').toLowerCase()
      return code.includes(query) || libelle.includes(query)
    }

    const filterNodes = (nodes: any[]): any[] => {
      return nodes
        .map((node) => {
          const children = filterNodes(node.children || [])
          if (matches(node) || children.length > 0) {
            return { ...node, children }
          }
          return null
        })
        .filter(Boolean)
    }

    return filterNodes(budgetTree)
  }, [budgetTree, budgetSearch])

  const selectBudgetPoste = (line: any) => {
    if ((line.children?.length || 0) > 0) return
    setFormData((prev) => ({ ...prev, budget_poste_id: String(line.id) }))
    setBudgetSearch(`${line.code} - ${line.libelle}`)
    setShowBudgetDropdown(false)
  }

  const toggleBudgetNode = (id: number) => {
    setExpandedBudgetIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const forceExpandBudgetTree = budgetSearch.trim().length > 0

  const BudgetDropdownNode = ({
    node,
    depth,
    expandedIds,
    onToggle,
    onSelect,
  }: {
    node: any
    depth: number
    expandedIds: Set<number>
    onToggle: (id: number) => void
    onSelect: (line: any) => void
  }) => {
    const hasChildren = (node.children || []).length > 0
    const isExpanded = forceExpandBudgetTree || expandedIds.has(node.id)
    return (
      <>
        <div
          className={`${styles.dropdownItem} ${hasChildren ? styles.parentItem : ''}`}
          style={{ paddingLeft: `${10 + depth * 16}px` }}
          onClick={() => {
            if (hasChildren) {
              onToggle(node.id)
            } else {
              onSelect(node)
            }
          }}
        >
          {hasChildren && (
            <span className={`${styles.treeToggle} ${isExpanded ? styles.treeToggleOpen : ''}`} />
          )}
          <strong>{node.code}</strong> - {node.libelle}
          {hasChildren && <span className={styles.parentBadge}>Parent</span>}
        </div>
        {hasChildren && isExpanded && node.children.map((child: any) => (
          <BudgetDropdownNode
            key={child.id}
            node={child}
            depth={depth + 1}
            expandedIds={expandedIds}
            onToggle={onToggle}
            onSelect={onSelect}
          />
        ))}
      </>
    )
  }

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages)
    }
  }, [page, totalPages])

  useEffect(() => {
    if (!searchEC) {
      setFilteredExperts([])
      return
    }
    const q = searchEC.toLowerCase()
    const filtered = experts.filter(
      (e) => e.numero_ordre.toLowerCase().includes(q) || e.nom_denomination.toLowerCase().includes(q)
    )
    setFilteredExperts(filtered)
  }, [searchEC, experts])

  const selectExpert = (expert: ExpertComptable) => {
    setFormData((prev) => ({ ...prev, expert_comptable_id: expert.id, client_nom: '' }))
    setSearchEC(`${expert.numero_ordre} - ${expert.nom_denomination}`)
    setFilteredExperts([])
  }

  const filteredEncaissements = useMemo(() => encaissements, [encaissements])

  const totalEncaissements = useMemo(() => summaryTotals.totalPaye, [summaryTotals.totalPaye])

  const totalMontantFacture = useMemo(() => summaryTotals.totalFacture, [summaryTotals.totalFacture])

  const totalResteAPayer = useMemo(() => totalMontantFacture - totalEncaissements, [totalMontantFacture, totalEncaissements])

  const resetFilters = useCallback(() => {
    setDateDebut('')
    setDateFin('')
    setFilterStatut('')
    setFilterNumeroRecu('')
    setFilterClient('')
    setFilterType('')
    setPage(1)
  }, [])

  const hasActiveFilters = dateDebut || dateFin || filterStatut || filterNumeroRecu || filterClient || filterType

  const exportToExcel = useCallback(async () => {
    try {
      const suffix = `${dateDebut || 'debut'}_${dateFin || 'fin'}`
      await downloadExcel('/exports/encaissements', {
        date_debut: dateDebut,
        date_fin: dateFin,
        statut_paiement: filterStatut,
        numero_recu: filterNumeroRecu,
        client: filterClient,
        type_operation: filterType,
      }, `encaissements_${suffix}.xlsx`)
    } catch (error) {
      console.error('Error exporting encaissements:', error)
      setNotification({
        type: 'error',
        title: "Erreur d'export",
        message: "Impossible d'exporter les encaissements.",
      })
    }
  }, [
    dateDebut,
    dateFin,
    filterStatut,
    filterNumeroRecu,
    filterClient,
    filterType,
    totalEncaissements,
    totalMontantFacture,
    totalResteAPayer,
  ])

  const exportToPDF = useCallback(async () => {
    const exportPath =
      '/encaissements' +
      buildQuery({
        include: 'expert_comptable',
        date_debut: dateDebut,
        date_fin: dateFin,
        statut_paiement: filterStatut,
        numero_recu: filterNumeroRecu,
        client: filterClient,
        type_operation: filterType,
        order: 'date_encaissement.desc',
        limit: 5000,
        offset: 0,
      })
    const exportRes = await apiRequest<Encaissement[]>('GET', exportPath)
    const exportItems = Array.isArray(exportRes) ? exportRes : (exportRes as any)?.items ?? []

    const dataForPDF = exportItems.map((enc: Encaissement) => ({
      ...enc,
      client: enc.expert_comptable
        ? `${enc.expert_comptable.numero_ordre} - ${enc.expert_comptable.nom_denomination}`
        : enc.client_nom || '',
      rubrique:
        enc.type_operation === 'formation' ? 'Formation' : enc.type_operation === 'livre' ? 'Livre' : 'Autre',
    }))

    const start = dateDebut || format(new Date(), 'yyyy-MM-dd')
    const end = dateFin || format(new Date(), 'yyyy-MM-dd')

    await generateEncaissementsPDF(dataForPDF as any, start, end, `${user?.prenom || ''} ${user?.nom || ''}`.trim())
  }, [dateDebut, dateFin, filterStatut, filterNumeroRecu, filterClient, filterType, user])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (formData.type_client === 'expert_comptable' && !formData.expert_comptable_id) {
      setNotification({
        type: 'warning',
        title: 'Expert-comptable non sélectionné',
        message: "Veuillez sélectionner un expert-comptable depuis la liste déroulante.",
        details: "Utilisez la recherche (numéro d'ordre ou nom) puis cliquez sur le bon résultat.",
      })
      return
    }

    if (formData.type_client !== 'expert_comptable' && !formData.client_nom.trim()) {
      setNotification({
        type: 'warning',
        title: 'Nom du client requis',
        message: "Veuillez saisir le nom complet du client / banque / partenaire / organisation.",
      })
      return
    }

    if (!formData.montant || !formData.montant_paye) {
      setNotification({
        type: 'warning',
        title: 'Montants requis',
        message: "Veuillez saisir le montant et le montant payé.",
      })
      return
    }

    const devise = formData.devise_perception === 'CDF' ? 'CDF' : 'USD'
    const montantTotal = parseFloat(formData.montant)
    const montantPayeInput = parseFloat(formData.montant_paye)
    const montantPaye = devise === 'CDF'
      ? (tauxChange > 0 ? montantPayeInput / tauxChange : 0)
      : montantPayeInput
    const montantPercu = devise === 'CDF' ? montantPayeInput : montantPayeInput

    if (!Number.isFinite(montantTotal) || montantTotal <= 0) {
      setNotification({ type: 'error', title: 'Montant invalide', message: 'Le montant total doit être > 0.' })
      return
    }

    if (!Number.isFinite(montantPaye) || montantPaye <= 0) {
      setNotification({ type: 'error', title: 'Montant payé invalide', message: 'Le montant payé doit être > 0.' })
      return
    }

    if (!formData.budget_poste_id) {
      setNotification({ type: 'error', title: 'Poste requis', message: 'Veuillez sélectionner un poste.' })
      return
    }

    if (montantPaye > montantTotal) {
      setNotification({
        type: 'error',
        title: 'Montant invalide',
        message: 'Le montant payé ne peut pas être supérieur au montant total.',
        details: `Montant total : ${formatCurrency(montantTotal)}\nMontant payé : ${formatCurrency(montantPaye)}`,
      })
      return
    }

    try {
      const numeroData = await apiRequest<string>('POST', '/encaissements/generate-numero-recu')
      if (!numeroData) {
        setNotification({
          type: 'error',
          title: 'Erreur de génération',
          message: 'Impossible de générer le numéro de reçu.',
          details: 'Veuillez réessayer ou contacter le support si le problème persiste.',
        })
        return
      }

      const statutPaiement = montantPaye >= montantTotal ? 'complet' : montantPaye > 0 ? 'partiel' : 'non_paye'

      const created = await apiRequest<any>('POST', '/encaissements', {
        numero_recu: numeroData,
        type_client: formData.type_client,
        expert_comptable_id: formData.type_client === 'expert_comptable' ? formData.expert_comptable_id : null,
        client_nom: formData.type_client !== 'expert_comptable' ? formData.client_nom.trim() : null,
        type_operation: formData.type_operation,
        description: formData.description || null,
        montant: montantTotal,
        montant_total: montantTotal,
        montant_paye: montantPaye,
        montant_percu: montantPercu,
        devise_perception: devise,
        taux_change_applique: devise === 'CDF' ? tauxChange : 1,
        budget_poste_id: Number(formData.budget_poste_id),
        statut_paiement: statutPaiement,
        mode_paiement: formData.mode_paiement,
        reference: formData.reference || null,
        date_encaissement: formData.date_encaissement,
        created_by: user?.id,
      })

      // On accepte soit un objet, soit un tableau (selon backend)
      const encCreated = Array.isArray(created) ? created[0] : created

      if (encCreated?.id) {
        try {
          await apiRequest('POST', '/payment-history', {
            encaissement_id: encCreated.id,
            montant: montantPaye,
            mode_paiement: formData.mode_paiement,
            reference: formData.reference || null,
            notes: formData.notes_paiement || null,
            created_by: user?.id,
          })
        } catch (err) {
          console.error('Error creating payment history:', err)
        }
      }

      setShowForm(false)
      setFormData({
        type_client: 'expert_comptable',
        expert_comptable_id: '',
        client_nom: '',
        type_operation: 'cotisation_annuelle',
        description: '',
        devise_perception: 'USD',
        montant: '',
        montant_paye: '',
        mode_paiement: 'cash',
        reference: '',
        notes_paiement: '',
        date_encaissement: format(new Date(), 'yyyy-MM-dd'),
        budget_poste_id: '',
      })
      setSearchEC('')
      setFilteredExperts([])

      await loadData()
      window.dispatchEvent(new Event('dashboard-refresh'))

      const statutMessage =
        statutPaiement === 'complet'
          ? 'Payé en totalité'
          : `Paiement partiel - Reste à payer : ${formatCurrency(montantTotal - montantPaye)}`

      setNotification({
        type: 'success',
        title: 'Encaissement créé avec succès',
        message: `Le reçu ${numeroData} a été enregistré dans le système.`,
        details: `Statut : ${statutMessage}\nMontant total : ${formatCurrency(montantTotal)}\nMontant payé : ${formatCurrency(
          montantPaye
        )}`,
      })
    } catch (error: any) {
      console.error('Error creating encaissement:', error)
      setNotification({
        type: 'error',
        title: "Erreur d'enregistrement",
        message: error?.message || 'Une erreur inconnue est survenue.',
        details: 'Vérifie le backend et les données envoyées.',
      })
    }
  }

  if (loading || permissionsLoading) {
    return (
      <div className={styles.loading}>
        <div className={styles.skeletonGrid}>
          {Array.from({ length: 4 }).map((_, idx) => (
            <div key={`enc-skel-${idx}`} className={styles.skeletonCard}>
              <div className={styles.skeletonLine} />
              <div className={styles.skeletonLineShort} />
              <div className={styles.skeletonLine} />
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className={styles.container}>
      <PageHeader
        title="Encaissements"
        subtitle="Enregistrement des paiements et recettes"
        actions={
          hasPermission('encaissements') && (
            <button onClick={() => setShowForm(true)} className={styles.primaryBtn}>
              + Nouvel encaissement
            </button>
          )
        }
      />

      {totalCount > 0 && (
        <div className={styles.pagination}>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={safePage === 1}
          >
            ← Précédent
          </button>
          <span className={styles.pageInfo}>
            Page {safePage} / {totalPages}
          </span>
          <button
            className={styles.pageBtn}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={safePage === totalPages}
          >
            Suivant →
          </button>
        </div>
      )}

      <div className={styles.filtersSection}>
        <h3>Filtres</h3>

        <div className={styles.filterGrid}>
          <div className={styles.filterField}>
            <label>Date début</label>
            <input type="date" value={dateDebut} onChange={(e) => setDateDebut(e.target.value)} />
          </div>

          <div className={styles.filterField}>
            <label>Date fin</label>
            <input type="date" value={dateFin} onChange={(e) => setDateFin(e.target.value)} />
          </div>

          <div className={styles.filterField}>
            <label>Statut</label>
            <select value={filterStatut} onChange={(e) => setFilterStatut(e.target.value)}>
              <option value="">Tous les statuts</option>
              <option value="complet">Payé</option>
              <option value="partiel">Paiement partiel</option>
              <option value="non_paye">Non payé</option>
              <option value="avance">Avance</option>
            </select>
          </div>

          <div className={styles.filterField}>
            <label>N° Reçu</label>
            <input
              type="text"
              value={filterNumeroRecu}
              onChange={(e) => setFilterNumeroRecu(e.target.value)}
              placeholder="ONEC-CPK-2026-01..."
            />
          </div>

          <div className={styles.filterField}>
            <label>Client</label>
            <input
              type="text"
              value={filterClient}
              onChange={(e) => setFilterClient(e.target.value)}
              placeholder="Nom ou numéro d'ordre"
            />
          </div>

          <div className={styles.filterField}>
            <label>Type</label>
            <select value={filterType} onChange={(e) => setFilterType(e.target.value)}>
              <option value="">Tous les types</option>
              <option value="formation">Formation</option>
              <option value="livre">Livre</option>
              <option value="autre">Autre</option>
            </select>
          </div>
        </div>

      <div className={styles.filterActions}>
          <div className={styles.pageSize}>
            <label>Affichage</label>
            <select
              value={String(pageSize)}
              onChange={(e) => setPageSize(Number(e.target.value))}
            >
              <option value="20">20 / page</option>
              <option value="50">50 / page</option>
              <option value="100">100 / page</option>
            </select>
          </div>
          {hasActiveFilters && (
            <button onClick={resetFilters} className={styles.resetBtn}>
              Réinitialiser les filtres
            </button>
          )}
          {totalCount > 0 && (
            <>
              <button onClick={exportToExcel} className={styles.excelBtn}>
                Exporter Excel
              </button>
              <button onClick={exportToPDF} className={styles.pdfBtn}>
                Exporter PDF
              </button>
            </>
          )}
        </div>

        {hasActiveFilters && (
          <div className={styles.filterSummary}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
                gap: '16px',
                marginBottom: '12px',
              }}
            >
              <div>
                <div style={{ fontSize: '13px', color: '#6b7280', marginBottom: '4px' }}>Montant total facturé</div>
                <div style={{ fontSize: '20px', fontWeight: 700, color: '#1f2937' }}>
                  {formatCurrency(totalMontantFacture)}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '13px', color: '#6b7280', marginBottom: '4px' }}>
                  Montant encaissé (dans la caisse)
                </div>
                <div style={{ fontSize: '20px', fontWeight: 700, color: '#16a34a' }}>
                  {formatCurrency(totalEncaissements)}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '13px', color: '#6b7280', marginBottom: '4px' }}>Reste à payer</div>
                <div style={{ fontSize: '20px', fontWeight: 700, color: totalResteAPayer > 0 ? '#f59e0b' : '#6b7280' }}>
                  {formatCurrency(totalResteAPayer)}
                </div>
              </div>
            </div>

            <div className={styles.summaryCount}>
              {filteredEncaissements.length} opération{filteredEncaissements.length > 1 ? 's' : ''}
            </div>
          </div>
        )}
      </div>

      {showForm && (
        <div className={styles.modal}>
          <div className={styles.modalContent}>
            <div className={styles.modalHeader}>
              <h2>Nouvel encaissement</h2>
              <button onClick={() => setShowForm(false)} className={styles.closeBtn}>
                ×
              </button>
            </div>

            <form onSubmit={handleSubmit} className={styles.form}>
              <div className={styles.field}>
                <label>Type de client *</label>
                <select
                  value={formData.type_client}
                  onChange={(e) => {
                    const newType = e.target.value as TypeClient
                    const availableOperations = OPERATIONS_PAR_TYPE_CLIENT[newType]
                    const defaultOperation = availableOperations[0]?.value || 'autre_encaissement'

                    setFormData((prev) => ({
                      ...prev,
                      type_client: newType,
                      expert_comptable_id: '',
                      client_nom: '',
                      type_operation: defaultOperation as TypeOperation,
                    }))
                    setSearchEC('')
                    setFilteredExperts([])
                  }}
                >
                  {Object.entries(TYPE_CLIENT_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>

              {formData.type_client === 'expert_comptable' ? (
                <div className={styles.field}>
                  <label>Expert-Comptable *</label>
                  <div style={{ position: 'relative' }}>
                    <input
                      type="text"
                      value={searchEC}
                      onChange={(e) => setSearchEC(e.target.value)}
                      placeholder="Rechercher par numéro d'ordre ou nom"
                      style={{
                        borderColor: formData.expert_comptable_id ? '#10b981' : undefined,
                        paddingRight: formData.expert_comptable_id ? '40px' : undefined,
                      }}
                    />
                    {formData.expert_comptable_id && (
                      <span
                        style={{
                          position: 'absolute',
                          right: '12px',
                          top: '50%',
                          transform: 'translateY(-50%)',
                          color: '#10b981',
                          fontSize: '20px',
                          fontWeight: 'bold',
                        }}
                      >
                        ✓
                      </span>
                    )}
                  </div>

                  {filteredExperts.length > 0 && (
                    <div className={styles.dropdown}>
                      {filteredExperts.slice(0, 10).map((expert) => (
                        <div
                          key={expert.id}
                          onClick={() => selectExpert(expert)}
                          className={styles.dropdownItem}
                        >
                          <strong>{expert.numero_ordre}</strong> - {expert.nom_denomination}
                        </div>
                      ))}
                    </div>
                  )}

                  {!formData.expert_comptable_id && searchEC && filteredExperts.length === 0 && (
                    <small style={{ color: '#f59e0b', fontSize: '13px' }}>
                      Aucun expert trouvé. Veuillez vérifier le numéro ou le nom.
                    </small>
                  )}
                </div>
              ) : (
                <div className={styles.field}>
                  <label>
                    {formData.type_client === 'banque_institution'
                      ? 'Nom de la banque / institution *'
                      : formData.type_client === 'partenaire'
                      ? 'Nom du partenaire *'
                      : formData.type_client === 'organisation'
                      ? "Nom de l'organisation *"
                      : 'Nom du client *'}
                  </label>
                  <input
                    type="text"
                    value={formData.client_nom}
                    onChange={(e) => setFormData((prev) => ({ ...prev, client_nom: e.target.value }))}
                    placeholder={
                      formData.type_client === 'banque_institution'
                        ? 'Ex: Rawbank, BCDC, Equity Bank'
                        : formData.type_client === 'partenaire'
                        ? 'Nom du partenaire'
                        : formData.type_client === 'organisation'
                        ? "Nom de l'organisation"
                        : 'Nom complet du client'
                    }
                    required
                  />
                </div>
              )}

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Type d'opération *</label>
                  <select
                    value={formData.type_operation}
                    onChange={(e) => setFormData((prev) => ({ ...prev, type_operation: e.target.value as TypeOperation }))}
                    required
                  >
                    {OPERATIONS_PAR_TYPE_CLIENT[formData.type_client].map((op) => (
                      <option key={op.value} value={op.value}>
                        {op.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className={styles.field}>
                  <label>Poste budgétaire (recette) *</label>
                  <div style={{ position: 'relative' }}>
                    <input
                      type="text"
                      value={budgetSearch}
                      onChange={(e) => {
                        setBudgetSearch(e.target.value)
                        setFormData((prev) => ({ ...prev, budget_poste_id: '' }))
                        setShowBudgetDropdown(true)
                      }}
                      onFocus={() => setShowBudgetDropdown(true)}
                      onBlur={() => {
                        setTimeout(() => setShowBudgetDropdown(false), 120)
                      }}
                      placeholder="Rechercher par code ou libellé"
                    />
                    {showBudgetDropdown && filteredBudgetTree.length > 0 && (
                      <div
                        className={styles.dropdown}
                        onMouseDown={(event) => event.preventDefault()}
                      >
                        {filteredBudgetTree.map((node: any) => (
                          <BudgetDropdownNode
                            key={node.id}
                            node={node}
                            depth={0}
                            expandedIds={expandedBudgetIds}
                            onToggle={toggleBudgetNode}
                            onSelect={selectBudgetPoste}
                          />
                        ))}
                      </div>
                    )}
                    {showBudgetDropdown && filteredBudgetTree.length === 0 && (
                      <div
                        className={styles.dropdown}
                        onMouseDown={(event) => event.preventDefault()}
                      >
                        <div className={styles.dropdownItem}>
                          Aucun poste trouvé.
                        </div>
                      </div>
                    )}
                  </div>
                  <input type="hidden" value={formData.budget_poste_id} required />
                </div>

                <div className={styles.field}>
                  <label>Montant comptable (USD) *</label>
                  <input
                    type="number"
                    step="0.01"
                    value={formData.montant}
                    onChange={(e) => setFormData((prev) => ({ ...prev, montant: e.target.value }))}
                    placeholder="0.00"
                    required
                  />
                </div>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Devise de perception *</label>
                  <select
                    value={formData.devise_perception}
                    onChange={(e) => {
                      const devise = e.target.value
                      setFormData((prev) => ({
                        ...prev,
                        devise_perception: devise,
                      }))
                    }}
                  >
                    <option value="USD">USD</option>
                    <option value="CDF">CDF</option>
                  </select>
                </div>
                <div className={styles.field}>
                  <label>Montant dû (USD)</label>
                  <input
                    type="text"
                    value={formatCurrency(
                      Math.max(0, toNumber(formData.montant || 0) - getMontantPayeUSD())
                    )}
                    disabled
                  />
                  <div className={`${styles.inlineNote} ${styles.inlineNoteEmphasis}`}>
                    Calculé automatiquement : Montant comptable − Montant payé.
                  </div>
                  {formData.devise_perception === 'CDF' && (
                    <div className={styles.inlineNote}>
                      Taux: {tauxChange.toFixed(2)}
                    </div>
                  )}
                </div>
              </div>

              <div className={styles.field}>
                <label>Description</label>
                <textarea
                  value={formData.description}
                  onChange={(e) => setFormData((prev) => ({ ...prev, description: e.target.value }))}
                  rows={3}
                  placeholder="Description optionnelle de l'encaissement"
                />
              </div>

              <div className={styles.field}>
                <label>Date</label>
                <input
                  type="date"
                  value={formData.date_encaissement}
                  onChange={(e) => setFormData((prev) => ({ ...prev, date_encaissement: e.target.value }))}
                />
              </div>

              <div className={styles.paymentSection}>
                <h3>Informations de paiement (obligatoire)</h3>
                <p>Tout encaissement doit être accompagné d'un paiement.</p>
              </div>

              <div className={styles.fieldRow}>
                <div className={styles.field}>
                  <label>Montant payé ({formData.devise_perception}) *</label>
                  <input
                    type="number"
                    step="0.01"
                    value={formData.montant_paye}
                    onChange={(e) => setFormData((prev) => ({ ...prev, montant_paye: e.target.value }))}
                    placeholder="Montant encaissé"
                    required
                  />
                  {formData.montant && formData.montant_paye && (
                    <div
                      style={{
                        marginTop: '6px',
                        fontSize: '12px',
                        color:
                          getMontantPayeUSD() >= parseFloat(formData.montant) ? '#16a34a' : '#f59e0b',
                        fontWeight: 500,
                      }}
                    >
                      {getMontantPayeUSD() >= parseFloat(formData.montant)
                        ? '✓ Paiement complet'
                        : `⚠ Paiement partiel - Reste: ${formatCurrency(
                            parseFloat(formData.montant) - getMontantPayeUSD()
                          )}`}
                    </div>
                  )}
                  {formData.devise_perception === 'CDF' && (
                    <div className={styles.inlineNote}>
                      Équiv. USD: {formatCurrency(getMontantPayeUSD())}
                    </div>
                  )}
                </div>

                <div className={styles.field}>
                  <label>Mode de paiement *</label>
                  <select
                    value={formData.mode_paiement}
                    onChange={(e) => {
                      const newMode = e.target.value as ModePatement
                      setFormData((prev) => ({
                        ...prev,
                        mode_paiement: newMode,
                        reference: newMode === 'cash' ? '' : prev.reference,
                      }))
                    }}
                    required
                  >
                    <option value="cash">Cash (espèces)</option>
                    <option value="mobile_money">Mobile Money</option>
                    <option value="virement">Opération bancaire</option>
                  </select>
                </div>
              </div>

              {(formData.mode_paiement === 'mobile_money' || formData.mode_paiement === 'virement') && (
                <div className={styles.field}>
                  <label>Référence de la transaction *</label>
                  <input
                    type="text"
                    value={formData.reference}
                    onChange={(e) => setFormData((prev) => ({ ...prev, reference: e.target.value }))}
                    placeholder="Numéro de transaction ou référence"
                    required
                  />
                </div>
              )}

              <div className={styles.field}>
                <label>Notes sur le paiement (optionnel)</label>
                <textarea
                  value={formData.notes_paiement}
                  onChange={(e) => setFormData((prev) => ({ ...prev, notes_paiement: e.target.value }))}
                  rows={2}
                  placeholder="Ex: Payé par M. Dupont, paiement en plusieurs fois..."
                />
              </div>

              <div className={styles.formActions}>
                <button type="button" onClick={() => setShowForm(false)} className={styles.secondaryBtn}>
                  Annuler
                </button>
                <button type="submit" className={styles.primaryBtn}>
                  Enregistrer l'encaissement et le paiement
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      <div className={styles.tableContainer}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>N° Reçu</th>
              <th>Date</th>
              <th>Type client</th>
              <th>Client</th>
              <th>Type d'opération</th>
              <th>Description</th>
              <th>Montant total</th>
              <th>Payé</th>
              <th>Statut</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredEncaissements.length === 0 ? (
              <tr>
                <td colSpan={10} style={{ textAlign: 'center', padding: '30px', color: '#9ca3af' }}>
                  {hasActiveFilters ? 'Aucun encaissement trouvé avec ces filtres' : 'Aucun encaissement enregistré'}
                </td>
              </tr>
            ) : (
              filteredEncaissements.map((enc) => (
                <tr key={enc.id}>
                  <td>
                    <strong>{enc.numero_recu}</strong>
                  </td>
                  <td>{format(new Date(enc.date_encaissement), 'dd/MM/yyyy')}</td>
                  <td>
                    <span
                      className={styles.badge}
                      style={{
                        background:
                          enc.type_client === 'expert_comptable'
                            ? '#dbeafe'
                            : enc.type_client === 'banque_institution'
                            ? '#d1fae5'
                            : enc.type_client === 'partenaire'
                            ? '#fef3c7'
                            : '#f3f4f6',
                        color:
                          enc.type_client === 'expert_comptable'
                            ? '#1e40af'
                            : enc.type_client === 'banque_institution'
                            ? '#065f46'
                            : enc.type_client === 'partenaire'
                            ? '#92400e'
                            : '#374151',
                      }}
                    >
                      {getTypeClientLabel(enc.type_client)}
                    </span>
                  </td>
                  <td>
                    {enc.expert_comptable ? (
                      <div className={styles.ecInfo}>
                        <div className={styles.ecNumero}>{enc.expert_comptable.numero_ordre}</div>
                        <div className={styles.ecNom}>{enc.expert_comptable.nom_denomination}</div>
                      </div>
                    ) : (
                      <div className={styles.ecNom}>{enc.client_nom}</div>
                    )}
                  </td>
                  <td>
                    <span className={styles.badge}>{getOperationLabel(enc.type_operation)}</span>
                  </td>
                  <td>{enc.description}</td>
                  <td>
                    <strong>{formatCurrency(enc.montant_total || enc.montant || 0)}</strong>
                    {enc.devise_perception === 'CDF' && (
                      <div className={styles.inlineNote}>
                        Perçu: {formatCurrency(enc.montant_percu)} CDF · Taux: {toNumber(enc.taux_change_applique).toFixed(2)}
                      </div>
                    )}
                  </td>
                  <td>
                    <div>
                      <div style={{ fontWeight: 600, color: '#16a34a' }}>{formatCurrency(enc.montant_paye || 0)}</div>
                      {enc.statut_paiement === 'partiel' && (
                        <div style={{ fontSize: '11px', color: '#f59e0b', marginTop: '2px' }}>
                          Reste:{' '}
                          {formatCurrency(
                            toNumber(enc.montant_total || enc.montant || 0) - toNumber(enc.montant_paye || 0)
                          )}
                        </div>
                      )}
                    </div>
                  </td>
                  <td>
                    <span className={styles.statutBadge} data-statut={enc.statut_paiement || 'complet'}>
                      {enc.statut_paiement === 'non_paye'
                        ? 'Non payé'
                        : enc.statut_paiement === 'partiel'
                        ? 'Partiel'
                        : enc.statut_paiement === 'avance'
                        ? 'Avance'
                        : 'Payé'}
                    </span>
                  </td>
                  <td>
                    <div className={styles.actionBtns}>
                      <button
                        onClick={() => setManagingPayment(enc)}
                        className={styles.paymentBtn}
                        title="Gérer les paiements"
                      >
                        💰
                      </button>
                      <button
                        onClick={() => setPrintingEncaissement(enc)}
                        className={styles.printBtn}
                        title="Imprimer le reçu"
                      >
                        🖨️ Imprimer
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className={styles.mobileCards}>
        {filteredEncaissements.length === 0 ? (
          <div className={styles.emptyCards}>
            {hasActiveFilters ? 'Aucun encaissement trouvé avec ces filtres' : 'Aucun encaissement enregistré'}
          </div>
        ) : (
          filteredEncaissements.map((enc) => (
            <div
              key={`card-${enc.id}`}
              className={styles.card}
              data-statut={enc.statut_paiement || 'complet'}
              role="button"
              tabIndex={0}
              onClick={() => setManagingPayment(enc)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  setManagingPayment(enc)
                }
              }}
            >
              <div className={styles.cardHeader}>
                <div>
                  <div className={styles.cardTitle}>{enc.numero_recu}</div>
                  <div className={styles.cardSub}>{format(new Date(enc.date_encaissement), 'dd/MM/yyyy')}</div>
                </div>
                <div className={styles.cardHeaderActions}>
                  <span className={styles.statutBadge} data-statut={enc.statut_paiement || 'complet'}>
                    {enc.statut_paiement === 'non_paye'
                      ? 'Non payé'
                      : enc.statut_paiement === 'partiel'
                      ? 'Partiel'
                      : enc.statut_paiement === 'avance'
                      ? 'Avance'
                      : 'Payé'}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setManagingPayment(enc)
                    }}
                    className={styles.cardIconBtn}
                    title="Voir détails"
                  >
                    👁️
                  </button>
                </div>
              </div>

              <div className={styles.cardBody}>
                <div className={styles.cardAmountMain}>
                  {formatCurrency(enc.montant_total || enc.montant || 0)}
                </div>
                <div className={styles.cardGrid}>
                  <div>
                    <div className={styles.cardLabel}>Client</div>
                    <div className={styles.cardValue}>
                      {enc.expert_comptable
                        ? `${enc.expert_comptable.nom_denomination} (${enc.expert_comptable.numero_ordre})`
                        : enc.client_nom || 'N/A'}
                    </div>
                  </div>
                  <div>
                    <div className={styles.cardLabel}>Type</div>
                    <div className={styles.cardValue}>{getTypeClientLabel(enc.type_client)}</div>
                  </div>
                  <div>
                    <div className={styles.cardLabel}>Opération</div>
                    <div className={styles.cardValue}>{getOperationLabel(enc.type_operation)}</div>
                  </div>
                  <div>
                    <div className={styles.cardLabel}>Payé</div>
                    <div className={styles.cardValueStrong}>
                      {formatCurrency(enc.montant_paye || 0)}
                    </div>
                  </div>
                </div>
                {enc.devise_perception === 'CDF' && (
                  <div className={styles.cardNote}>
                    Perçu: {formatCurrency(enc.montant_percu)} CDF · Taux: {toNumber(enc.taux_change_applique).toFixed(2)}
                  </div>
                )}
                {enc.statut_paiement === 'partiel' && (
                  <div className={styles.cardNoteWarn}>
                    Reste: {formatCurrency(toNumber(enc.montant_total || enc.montant || 0) - toNumber(enc.montant_paye || 0))}
                  </div>
                )}
                {enc.description && (
                  <div className={styles.cardNote}>
                    {enc.description}
                  </div>
                )}
              </div>

              <div className={styles.cardActions}>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    setManagingPayment(enc)
                  }}
                  className={styles.paymentBtn}
                  title="Gérer les paiements"
                >
                  💰 Paiements
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    setPrintingEncaissement(enc)
                  }}
                  className={styles.printBtn}
                  title="Imprimer le reçu"
                >
                  🖨️ Imprimer
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {printingEncaissement && (
        <PrintReceipt
          encaissement={printingEncaissement}
          autoPrint={true}
          onClose={() => setPrintingEncaissement(null)}
        />
      )}

      {managingPayment && (
        <PaymentManager encaissement={managingPayment} onClose={() => setManagingPayment(null)} onUpdate={loadData} />
      )}

      {notification && (
        <NotificationModal
          type={notification.type}
          title={notification.title}
          message={notification.message}
          details={notification.details}
          onClose={() => setNotification(null)}
          autoClose={notification.type === 'success'}
        />
      )}
    </div>
  )
}
