import { FormEvent, Fragment, ReactNode, useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import {
  AlertTriangle,
  BriefcaseBusiness,
  Calendar,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  FileText,
  FolderOpen,
  Grid3X3,
  LayoutList,
  Mail,
  Phone,
  RotateCw,
  Search,
  Send,
  Settings2,
  UserRound,
  UsersRound,
  WalletCards,
  X,
  Eye,
  Edit2,
  MoreVertical,
} from 'lucide-react'
import {
  approveHRLeave,
  archiveHREmployee,
  batchCreateAttendance,
  createHRContract,
  createHRDocument,
  createHREmployee,
  createHRFunction,
  createHRLeave,
  createHRReference,
  createHRService,
  createPayrollEntry,
  createHREvaluation,
  createHRSanction,
  deleteHREvaluation,
  deleteHRSanction,
  generateSalarySlips,
  getAttendances,
  getAttendanceSummary,
  getHRContracts,
  getHRDashboard,
  getHRDocuments,
  getHREmployees,
  getHRFunctions,
  getHREvaluations,
  getHRLeaves,
  getHRReferences,
  getHRReport,
  getHRSanctions,
  getHRServices,
  getLeaveBalance,
  getPayrollEntries,
  getPayrollSlips,
  getSalarySlips,
  rejectHRLeave,
  submitHRLeave,
  updateHREmployee,
  updateHREvaluation,
  updateHRFunction,
  updateHRReference,
  updateHRSanction,
  updateHRService,
  validatePayrollEntry,
  type AttendanceStatut,
  type HRAttendance,
  type HRAttendanceSummary,
  type HRContract,
  type HRDashboard,
  type HRDocument,
  type HREmployee,
  type HREvaluation,
  type HRFunction,
  type HRLeave,
  type HRLeaveBalance,
  type HRPayrollEntry,
  type HRReference,
  type HRReport,
  type HRSalarySlip,
  type HRSanction,
  type HRService,
} from '../api/hr'
import { usePermissions } from '../hooks/usePermissions'
import { useNotification } from '../contexts/NotificationContext'
import styles from './HRModule.module.css'

type HRView = 'dashboard' | 'employees' | 'contracts' | 'leaves' | 'documents' | 'settings' | 'presences' | 'paie' | 'bulletins' | 'evaluations' | 'sanctions' | 'rapports' | 'placeholder'

const STATUS_LABELS: Record<string, string> = {
  actif: 'Actif',
  suspendu: 'Suspendu',
  en_conge: 'En congé',
  sorti: 'Sorti',
  brouillon: 'Brouillon',
  soumis: 'Soumis',
  approuvé: 'Approuvé',
  rejeté: 'Rejeté',
}

const AVATAR_COLORS = [
  ['#714B67', '#fff'],
  ['#00A09D', '#fff'],
  ['#2563eb', '#fff'],
  ['#7c3aed', '#fff'],
  ['#059669', '#fff'],
  ['#d97706', '#fff'],
]

function avatarColors(name: string): [string, string] {
  const i = Math.abs(name.charCodeAt(0) + (name.charCodeAt(1) || 0)) % AVATAR_COLORS.length
  return AVATAR_COLORS[i] as [string, string]
}

function fullName(employee?: HREmployee | null): string {
  if (!employee) return '-'
  return [employee.nom, employee.post_nom, employee.prenom].filter(Boolean).join(' ')
}

function daysUntil(dateStr: string): number {
  return Math.ceil((new Date(dateStr).getTime() - Date.now()) / 86400000)
}

function viewFromPath(pathname: string): HRView {
  if (pathname.includes('/employes') || pathname.includes('/personnel')) return 'employees'
  if (pathname.includes('/contrats')) return 'contracts'
  if (pathname.includes('/conges')) return 'leaves'
  if (pathname.includes('/documents')) return 'documents'
  if (pathname.includes('/configuration') || pathname.includes('/parametres')) return 'settings'
  if (pathname.includes('/vue-ensemble') || pathname.includes('/dashboard')) return 'dashboard'
  if (pathname.includes('/presences')) return 'presences'
  if (pathname.includes('/bulletins')) return 'bulletins'
  if (pathname.includes('/paie')) return 'paie'
  if (pathname.includes('/evaluations')) return 'evaluations'
  if (pathname.includes('/sanctions')) return 'sanctions'
  if (pathname.includes('/rapports')) return 'rapports'
  return 'placeholder'
}

function labelFromPath(pathname: string): string {
  if (pathname.includes('/presences')) return 'Présences'
  if (pathname.includes('/paie') && !pathname.includes('/bulletins')) return 'Préparation de paie'
  if (pathname.includes('/bulletins')) return 'Bulletins de paie'
  if (pathname.includes('/evaluations')) return 'Évaluations'
  if (pathname.includes('/sanctions')) return 'Sanctions'
  if (pathname.includes('/rapports')) return 'Rapports'
  return 'Ressources humaines'
}

// ─── Main module ─────────────────────────────────────────────────────────────

export default function HRModule() {
  const location = useLocation()
  const view = viewFromPath(location.pathname)
  const placeholderTitle = labelFromPath(location.pathname)
  const { hasPermission } = usePermissions()
  const canViewSalary = hasPermission('rh.salaries.view')

  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [serviceFilter, setServiceFilter] = useState('')
  const [formOpen, setFormOpen] = useState(false)
  const [selectedEmployee, setSelectedEmployee] = useState<HREmployee | null>(null)
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards')
  const [leaveViewMode, setLeaveViewMode] = useState<'table' | 'calendar'>('table')

  const [dashboard, setDashboard] = useState<HRDashboard | null>(null)
  const [employees, setEmployees] = useState<HREmployee[]>([])
  const [contracts, setContracts] = useState<HRContract[]>([])
  const [leaves, setLeaves] = useState<HRLeave[]>([])
  const [documents, setDocuments] = useState<HRDocument[]>([])
  const [services, setServices] = useState<HRService[]>([])
  const [functions, setFunctions] = useState<HRFunction[]>([])
  const [references, setReferences] = useState<Record<string, HRReference[]>>({})
  const [attendances, setAttendances] = useState<HRAttendance[]>([])
  const [attendanceSummary, setAttendanceSummary] = useState<HRAttendanceSummary | null>(null)
  const [payrollEntries, setPayrollEntries] = useState<HRPayrollEntry[]>([])
  const [salarySlips, setSalarySlips] = useState<HRSalarySlip[]>([])
  const [evaluations, setEvaluations] = useState<HREvaluation[]>([])
  const [sanctions, setSanctions] = useState<HRSanction[]>([])
  const [report, setReport] = useState<HRReport | null>(null)

  const employeeById = useMemo(() => new Map(employees.map((e) => [e.id, e])), [employees])

  const load = async () => {
    setLoading(true)
    try {
      if (view === 'placeholder') return
      if (view === 'dashboard') {
        const [dash, empRows, ctRows, lvRows] = await Promise.all([
          getHRDashboard(),
          getHREmployees(),
          getHRContracts(),
          getHRLeaves(),
        ])
        setDashboard(dash)
        setEmployees(empRows)
        setContracts(ctRows)
        setLeaves(lvRows)
        return
      }
      if (view === 'settings') {
        const referenceCategories = [
          'departements', 'types-contrats', 'statuts-contrats', 'types-absences',
          'regles-conges', 'jours-feries', 'types-primes', 'types-retenues',
          'devises', 'types-documents',
        ]
        const [serviceRows, functionRows, ...referenceRows] = await Promise.all([
          getHRServices(),
          getHRFunctions(),
          ...referenceCategories.map((c) => getHRReferences(c)),
        ])
        setServices(serviceRows)
        setFunctions(functionRows)
        setReferences(Object.fromEntries(referenceCategories.map((c, i) => [c, referenceRows[i]])))
        return
      }
      if (view === 'presences') {
        const now = new Date()
        const [empRows, attRows, summary] = await Promise.all([
          getHREmployees(),
          getAttendances({ mois: now.getMonth() + 1, annee: now.getFullYear() }),
          getAttendanceSummary({ mois: now.getMonth() + 1, annee: now.getFullYear() }),
        ])
        setEmployees(empRows)
        setAttendances(attRows)
        setAttendanceSummary(summary)
        return
      }
      if (view === 'paie') {
        const now = new Date()
        const entries = await getPayrollEntries({ annee: now.getFullYear() })
        setPayrollEntries(entries)
        return
      }
      if (view === 'bulletins') {
        const now = new Date()
        const [empRows, slips, entries] = await Promise.all([
          getHREmployees(),
          getSalarySlips({ annee: now.getFullYear() }),
          getPayrollEntries({ annee: now.getFullYear() }),
        ])
        setEmployees(empRows)
        setSalarySlips(slips)
        setPayrollEntries(entries)
        return
      }
      if (view === 'evaluations') {
        const [empRows, evalRows] = await Promise.all([getHREmployees(), getHREvaluations()])
        setEmployees(empRows)
        setEvaluations(evalRows)
        return
      }
      if (view === 'sanctions') {
        const [empRows, sanctRows] = await Promise.all([getHREmployees(), getHRSanctions()])
        setEmployees(empRows)
        setSanctions(sanctRows)
        return
      }
      if (view === 'rapports') {
        const [empRows, rpt] = await Promise.all([getHREmployees(), getHRReport()])
        setEmployees(empRows)
        setReport(rpt)
        return
      }
      const [empRows, svcRows, fnRows] = await Promise.all([getHREmployees(), getHRServices(), getHRFunctions()])
      setEmployees(empRows)
      setServices(svcRows)
      setFunctions(fnRows)
      if (view === 'contracts') {
        const [ctRows, typesContrats, statutsContrats] = await Promise.all([
          getHRContracts(),
          getHRReferences('types-contrats'),
          getHRReferences('statuts-contrats'),
        ])
        setContracts(ctRows)
        setReferences((prev) => ({ ...prev, 'types-contrats': typesContrats, 'statuts-contrats': statutsContrats }))
      }
      if (view === 'leaves') {
        const [lvRows, typesAbsences] = await Promise.all([
          getHRLeaves(),
          getHRReferences('types-absences'),
        ])
        setLeaves(lvRows)
        setReferences((prev) => ({ ...prev, 'types-absences': typesAbsences }))
      }
      if (view === 'documents') {
        const [docRows, typesDocs] = await Promise.all([
          getHRDocuments(),
          getHRReferences('types-documents'),
        ])
        setDocuments(docRows)
        setReferences((prev) => ({ ...prev, 'types-documents': typesDocs }))
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [view])

  const titles: Record<HRView, { title: string; action: string; icon: ReactNode }> = {
    dashboard: { title: "Vue d'ensemble", action: '', icon: <UsersRound size={20} /> },
    employees: { title: 'Employés', action: 'Créer un employé', icon: <UserRound size={20} /> },
    contracts: { title: 'Contrats', action: 'Créer un contrat', icon: <BriefcaseBusiness size={20} /> },
    leaves: { title: 'Congés', action: 'Créer une demande', icon: <FileText size={20} /> },
    documents: { title: 'Documents', action: 'Ajouter un document', icon: <FolderOpen size={20} /> },
    settings: { title: 'Configuration RH', action: '', icon: <Settings2 size={20} /> },
    presences: { title: 'Présences', action: 'Saisir présences', icon: <CalendarDays size={20} /> },
    paie: { title: 'Préparation de paie', action: 'Nouveau run de paie', icon: <WalletCards size={20} /> },
    bulletins: { title: 'Bulletins de paie', action: '', icon: <FileText size={20} /> },
    evaluations: { title: 'Évaluations', action: 'Nouvelle évaluation', icon: <FileText size={20} /> },
    sanctions: { title: 'Sanctions', action: 'Enregistrer une sanction', icon: <AlertTriangle size={20} /> },
    rapports: { title: 'Rapports RH', action: '', icon: <Grid3X3 size={20} /> },
    placeholder: { title: placeholderTitle, action: '', icon: <UsersRound size={20} /> },
  }
  const header = titles[view]

  const filteredEmployees = employees.filter((e) => {
    const haystack = `${e.matricule} ${fullName(e)} ${e.service?.libelle || ''} ${e.fonction?.libelle || ''}`.toLowerCase()
    const matchSearch = haystack.includes(search.toLowerCase())
    const matchService = !serviceFilter || String(e.service_id) === serviceFilter
    return matchSearch && matchService
  })

  return (
    <div className={styles.page}>
      {/* ── Control panel ── */}
      <div className={styles.controlPanel}>
        <div className={styles.topRow}>
          <div className={styles.titleGroup}>
            <div className={styles.breadcrumb}>
              <span>Ressources humaines /</span> {header.title}
            </div>
          </div>
          <div className={styles.actionsGroup}>
            <button className={styles.iconButton} onClick={() => void load()} title="Actualiser">
              <RotateCw size={16} className={loading ? styles.spinning : ''} />
            </button>

            {view === 'employees' && (
              <div className={styles.viewToggle}>
                <button
                  className={`${styles.viewToggleBtn} ${viewMode === 'cards' ? styles.viewToggleActive : ''}`}
                  onClick={() => setViewMode('cards')}
                  title="Vue cartes"
                >
                  <Grid3X3 size={15} />
                </button>
                <button
                  className={`${styles.viewToggleBtn} ${viewMode === 'table' ? styles.viewToggleActive : ''}`}
                  onClick={() => setViewMode('table')}
                  title="Vue liste"
                >
                  <LayoutList size={15} />
                </button>
              </div>
            )}

            {view === 'leaves' && (
              <div className={styles.viewToggle}>
                <button
                  className={`${styles.viewToggleBtn} ${leaveViewMode === 'table' ? styles.viewToggleActive : ''}`}
                  onClick={() => setLeaveViewMode('table')}
                  title="Vue liste"
                >
                  <LayoutList size={15} />
                </button>
                <button
                  className={`${styles.viewToggleBtn} ${leaveViewMode === 'calendar' ? styles.viewToggleActive : ''}`}
                  onClick={() => setLeaveViewMode('calendar')}
                  title="Vue calendrier"
                >
                  <Calendar size={15} />
                </button>
              </div>
            )}

            {header.action && (
              <button className={styles.primaryButton} onClick={() => setFormOpen((v) => !v)}>
                {formOpen ? 'Annuler' : header.action}
              </button>
            )}
            {view === 'employees' && selectedEmployee && (
              <button className={styles.secondaryButton} onClick={() => setSelectedEmployee(null)}>
                Vue liste
              </button>
            )}
          </div>
        </div>

        {view !== 'dashboard' && view !== 'placeholder' && view !== 'settings' && (
          <div className={styles.searchRow}>
            <div className={styles.searchGroup}>
              <Search size={16} />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Rechercher..."
              />
            </div>
            {view === 'employees' && services.length > 0 && (
              <select
                className={styles.filterSelect}
                value={serviceFilter}
                onChange={(e) => setServiceFilter(e.target.value)}
              >
                <option value="">Tous les services</option>
                {services.map((s) => (
                  <option key={s.id} value={String(s.id)}>{s.libelle}</option>
                ))}
              </select>
            )}
          </div>
        )}
      </div>

      {/* ── Content ── */}
      <div className={styles.content}>
        {loading ? (
          <div className={styles.emptyState}>
            <RotateCw size={24} className={styles.spinning} />
            <span style={{ marginTop: 12 }}>Chargement...</span>
          </div>
        ) : view === 'dashboard' ? (
          <DashboardView
            dashboard={dashboard}
            canViewSalary={canViewSalary}
            employees={employees}
            contracts={contracts}
            leaves={leaves}
          />
        ) : view === 'employees' ? (
          <>
            {formOpen && (
              <EmployeeForm
                services={services}
                functions={functions}
                onSaved={async () => { setFormOpen(false); await load() }}
              />
            )}
            <EmployeeView
              employees={filteredEmployees}
              selectedEmployee={selectedEmployee}
              onSelect={setSelectedEmployee}
              services={services}
              functions={functions}
              viewMode={viewMode}
              onSaved={load}
            />
          </>
        ) : view === 'contracts' ? (
          <>
            {formOpen && (
              <ContractForm
                employees={employees}
                canViewSalary={canViewSalary}
                typesContrats={references['types-contrats'] || []}
                onSaved={async () => { setFormOpen(false); await load() }}
              />
            )}
            <ContractTable contracts={contracts} employeeById={employeeById} canViewSalary={canViewSalary} />
          </>
        ) : view === 'leaves' ? (
          <>
            {formOpen && (
              <LeaveForm
                employees={employees}
                typesAbsences={references['types-absences'] || []}
                onSaved={async () => { setFormOpen(false); await load() }}
              />
            )}
            {leaveViewMode === 'calendar' ? (
              <LeaveCalendar leaves={leaves} employeeById={employeeById} />
            ) : (
              <LeaveTable leaves={leaves} employeeById={employeeById} onChanged={load} />
            )}
          </>
        ) : view === 'documents' ? (
          <>
            {formOpen && (
              <DocumentForm
                employees={employees}
                typesDocs={references['types-documents'] || []}
                onSaved={async () => { setFormOpen(false); await load() }}
              />
            )}
            <DocumentTable documents={documents} employeeById={employeeById} />
          </>
        ) : view === 'settings' ? (
          <SettingsView services={services} functions={functions} references={references} onSaved={load} />
        ) : view === 'presences' ? (
          <>
            {formOpen && (
              <AttendanceBatchForm employees={employees} onSaved={async () => { setFormOpen(false); await load() }} />
            )}
            <AttendanceView attendances={attendances} employees={employees} summary={attendanceSummary} />
          </>
        ) : view === 'paie' ? (
          <>
            {formOpen && (
              <PayrollEntryForm onSaved={async () => { setFormOpen(false); await load() }} />
            )}
            <PayrollView entries={payrollEntries} employeeById={employeeById} onChanged={load} />
          </>
        ) : view === 'bulletins' ? (
          <SalarySlipsView slips={salarySlips} employeeById={employeeById} payrollEntries={payrollEntries} />
        ) : view === 'evaluations' ? (
          <>
            {formOpen && (
              <EvaluationForm
                employees={employees}
                onSaved={async () => { setFormOpen(false); await load() }}
              />
            )}
            <EvaluationsView
              evaluations={evaluations}
              employeeById={employeeById}
              onChanged={load}
            />
          </>
        ) : view === 'sanctions' ? (
          <>
            {formOpen && (
              <SanctionForm
                employees={employees}
                onSaved={async () => { setFormOpen(false); await load() }}
              />
            )}
            <SanctionsView
              sanctions={sanctions}
              employeeById={employeeById}
              onChanged={load}
            />
          </>
        ) : view === 'rapports' ? (
          <RapportsView report={report} />
        ) : (
          <div className={styles.emptyState}>
            <Clock size={32} style={{ opacity: 0.3, marginBottom: 12 }} />
            <p>Ce sous-menu est en cours de développement.</p>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Dashboard ────────────────────────────────────────────────────────────────

function DashboardView({
  dashboard,
  canViewSalary,
  employees,
  contracts,
  leaves,
}: {
  dashboard: HRDashboard | null
  canViewSalary: boolean
  employees: HREmployee[]
  contracts: HRContract[]
  leaves: HRLeave[]
}) {
  const now = Date.now()
  const in90 = now + 90 * 86400000

  const expiringContracts = contracts.filter((c) => {
    if (!c.date_fin) return false
    const t = new Date(c.date_fin).getTime()
    return t >= now && t <= in90
  }).sort((a, b) => new Date(a.date_fin!).getTime() - new Date(b.date_fin!).getTime())

  const pendingLeaves = leaves.filter((l) => l.statut === 'soumis')

  const byService: Record<string, number> = {}
  for (const e of employees) {
    const svc = e.service?.libelle || 'Non affecté'
    byService[svc] = (byService[svc] || 0) + 1
  }
  const serviceRows = Object.entries(byService).sort((a, b) => b[1] - a[1]).slice(0, 6)
  const maxCount = serviceRows[0]?.[1] || 1

  const kpis = [
    {
      label: 'Employés actifs',
      value: dashboard?.total_agents_actifs ?? 0,
      icon: <UsersRound size={22} />,
      color: '#714B67',
      bg: '#fdf8fc',
    },
    {
      label: 'En congé',
      value: dashboard?.agents_en_conge ?? 0,
      icon: <CalendarDays size={22} />,
      color: '#00A09D',
      bg: '#f0fbfb',
    },
    {
      label: 'Contrats à terme',
      value: dashboard?.contrats_expirant_bientot ?? 0,
      icon: <BriefcaseBusiness size={22} />,
      color: '#d97706',
      bg: '#fffbeb',
    },
    {
      label: 'Congés à valider',
      value: dashboard?.demandes_conge_en_attente ?? 0,
      icon: <Clock size={22} />,
      color: '#2563eb',
      bg: '#eff6ff',
    },
    {
      label: 'Masse salariale',
      value: canViewSalary ? `${dashboard?.masse_salariale_estimee || '0'}` : '••••••',
      icon: <WalletCards size={22} />,
      color: '#059669',
      bg: '#f0fdf4',
    },
  ]

  return (
    <>
      {/* KPI cards */}
      <div className={styles.metricsGrid}>
        {kpis.map((k) => (
          <div key={k.label} className={styles.metricCard} style={{ borderTop: `3px solid ${k.color}` }}>
            <div className={styles.metricCardInner}>
              <div>
                <span className={styles.metricLabel}>{k.label}</span>
                <strong className={styles.metricValue} style={{ color: k.color }}>{k.value}</strong>
              </div>
              <div className={styles.metricIcon} style={{ background: k.bg, color: k.color }}>
                {k.icon}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className={styles.dashGrid}>
        {/* Répartition par service */}
        <section className={styles.section}>
          <h2>Effectifs par service</h2>
          {serviceRows.length === 0 ? (
            <p style={{ color: '#999', textAlign: 'center', padding: '20px' }}>Aucune donnée</p>
          ) : (
            <div className={styles.serviceBarList}>
              {serviceRows.map(([svc, count]) => (
                <div key={svc} className={styles.serviceBarRow}>
                  <span className={styles.serviceBarLabel}>{svc}</span>
                  <div className={styles.serviceBarTrack}>
                    <div
                      className={styles.serviceBarFill}
                      style={{ width: `${(count / maxCount) * 100}%` }}
                    />
                  </div>
                  <span className={styles.serviceBarCount}>{count}</span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Contrats expirant */}
        <section className={styles.section}>
          <h2>
            <AlertTriangle size={16} style={{ verticalAlign: 'middle', marginRight: 6, color: '#d97706' }} />
            Contrats expirant bientôt
          </h2>
          {expiringContracts.length === 0 ? (
            <p style={{ color: '#999', textAlign: 'center', padding: '20px' }}>
              Aucun contrat à terme dans les 90 jours
            </p>
          ) : (
            <div className={styles.alertList}>
              {expiringContracts.slice(0, 6).map((c) => {
                const days = daysUntil(c.date_fin!)
                const urgent = days <= 30
                return (
                  <div key={c.id} className={styles.alertRow}>
                    <div>
                      <div className={styles.alertName}>{c.poste}</div>
                      <div className={styles.alertSub}>{c.type_contrat} · expire le {c.date_fin}</div>
                    </div>
                    <span
                      className={styles.expiryBadge}
                      style={{
                        background: urgent ? '#fee2e2' : '#fff7ed',
                        color: urgent ? '#991b1b' : '#92400e',
                      }}
                    >
                      {days}j
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </section>

        {/* Congés en attente */}
        <section className={styles.section}>
          <h2>
            <Send size={16} style={{ verticalAlign: 'middle', marginRight: 6, color: '#2563eb' }} />
            Demandes en attente
          </h2>
          {pendingLeaves.length === 0 ? (
            <p style={{ color: '#999', textAlign: 'center', padding: '20px' }}>Aucune demande à valider</p>
          ) : (
            <div className={styles.alertList}>
              {pendingLeaves.slice(0, 5).map((l) => (
                <div key={l.id} className={styles.alertRow}>
                  <div>
                    <div className={styles.alertName}>{l.type_absence}</div>
                    <div className={styles.alertSub}>{l.date_debut} → {l.date_fin} · {l.nombre_jours}j</div>
                  </div>
                  <span className={`${styles.badge} ${styles.soumis}`}>soumis</span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Activité récente */}
        <section className={styles.section}>
          <h2>Dernières activités</h2>
          {(dashboard?.derniers_mouvements || []).length === 0 ? (
            <p style={{ color: '#999', textAlign: 'center', padding: '20px' }}>Aucune activité récente</p>
          ) : (
            <div className={styles.alertList}>
              {(dashboard?.derniers_mouvements || []).map((m) => (
                <div key={`${m.label}-${m.date}`} className={styles.activityRow}>
                  <span>{m.label}</span>
                  <time style={{ color: '#888', fontSize: 13 }}>
                    {new Date(m.date).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' })}
                  </time>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </>
  )
}

// ─── Employee list ────────────────────────────────────────────────────────────

function EmployeeView({
  employees,
  selectedEmployee,
  onSelect,
  services,
  functions,
  viewMode,
  onSaved,
}: {
  employees: HREmployee[]
  selectedEmployee: HREmployee | null
  onSelect: (e: HREmployee | null) => void
  services: HRService[]
  functions: HRFunction[]
  viewMode: 'cards' | 'table'
  onSaved: () => Promise<void>
}) {
  return (
    <div className={selectedEmployee ? styles.employeeLayout : undefined}>
      <div className={styles.kanbanContainer}>
        <div className={styles.listMeta}>
          <span className={styles.listCount}>{employees.length} agent{employees.length !== 1 ? 's' : ''}</span>
        </div>
        {viewMode === 'cards' ? (
          <div className={styles.kanbanGrid}>
            {employees.map((e) => (
              <EmployeeCard
                key={e.id}
                employee={e}
                selected={selectedEmployee?.id === e.id}
                onClick={() => onSelect(e)}
              />
            ))}
            {employees.length === 0 && (
              <div className={styles.emptyState} style={{ gridColumn: '1/-1' }}>Aucun employé trouvé</div>
            )}
          </div>
        ) : (
          <EmployeeTable employees={employees} selected={selectedEmployee} onSelect={onSelect} />
        )}
      </div>

      {selectedEmployee && (
        <EmployeeSheet
          employee={selectedEmployee}
          services={services}
          functions={functions}
          onSaved={onSaved}
          onUnselect={() => onSelect(null)}
        />
      )}
    </div>
  )
}

function EmployeeCard({
  employee,
  selected,
  onClick,
}: {
  employee: HREmployee
  selected: boolean
  onClick: () => void
}) {
  const initials = ((employee.prenom?.[0] || '') + (employee.nom[0] || '')).toUpperCase()
  const [bg, fg] = avatarColors(employee.nom)

  return (
    <div
      className={`${styles.employeeCard} ${selected ? styles.selectedCard : ''}`}
      onClick={onClick}
    >
      <div className={styles.avatar} style={{ background: bg, color: fg }}>
        {employee.photo_url ? (
          <img src={employee.photo_url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 4 }} />
        ) : initials}
      </div>
      <div className={styles.cardContent}>
        <div>
          <strong>{fullName(employee)}</strong>
          <small>{employee.fonction?.libelle || 'Poste non défini'}</small>
        </div>
        <div className={styles.cardFooter}>
          {employee.service && (
            <span className={styles.serviceChip}>{employee.service.libelle}</span>
          )}
          <span className={`${styles.badge} ${styles[employee.statut] || ''}`}>
            {STATUS_LABELS[employee.statut] || employee.statut}
          </span>
        </div>
        <div className={styles.cardMeta}>
          <span>{employee.matricule}</span>
          {employee.date_entree && (
            <span>depuis {new Date(employee.date_entree).getFullYear()}</span>
          )}
        </div>
        {(employee.telephone || employee.email) && (
          <div className={styles.cardQuickActions}>
            {employee.telephone && (
              <a
                href={`tel:${employee.telephone}`}
                className={styles.quickAction}
                onClick={(e) => e.stopPropagation()}
                title={employee.telephone}
              >
                <Phone size={13} />
              </a>
            )}
            {employee.email && (
              <a
                href={`mailto:${employee.email}`}
                className={styles.quickAction}
                onClick={(e) => e.stopPropagation()}
                title={employee.email}
              >
                <Mail size={13} />
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function EmployeeTable({
  employees,
  selected,
  onSelect,
}: {
  employees: HREmployee[]
  selected: HREmployee | null
  onSelect: (e: HREmployee) => void
}) {
  return (
    <div className={styles.tableWrap}>
      <table>
        <thead>
          <tr>
            <th>Matricule</th>
            <th>Nom complet</th>
            <th>Service</th>
            <th>Fonction</th>
            <th>Depuis</th>
            <th>Statut</th>
            <th>Contact</th>
          </tr>
        </thead>
        <tbody>
          {employees.map((e) => (
            <tr
              key={e.id}
              onClick={() => onSelect(e)}
              style={{ cursor: 'pointer', background: selected?.id === e.id ? '#fdf8fc' : undefined }}
            >
              <td style={{ fontWeight: 700, fontFamily: 'monospace', color: '#714B67' }}>{e.matricule}</td>
              <td style={{ fontWeight: 600 }}>{fullName(e)}</td>
              <td>{e.service?.libelle || <span style={{ color: '#aaa' }}>—</span>}</td>
              <td>{e.fonction?.libelle || <span style={{ color: '#aaa' }}>—</span>}</td>
              <td style={{ color: '#888', fontSize: 13 }}>{e.date_entree ? new Date(e.date_entree).toLocaleDateString('fr-FR') : '—'}</td>
              <td><span className={`${styles.badge} ${styles[e.statut] || ''}`}>{STATUS_LABELS[e.statut] || e.statut}</span></td>
              <td>
                <div style={{ display: 'flex', gap: 8 }}>
                  {e.telephone && <a href={`tel:${e.telephone}`} onClick={(ev) => ev.stopPropagation()} className={styles.quickAction}><Phone size={14} /></a>}
                  {e.email && <a href={`mailto:${e.email}`} onClick={(ev) => ev.stopPropagation()} className={styles.quickAction}><Mail size={14} /></a>}
                </div>
              </td>
            </tr>
          ))}
          {employees.length === 0 && (
            <tr><td colSpan={7} style={{ textAlign: 'center', padding: 40, color: '#999' }}>Aucun employé trouvé</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ─── Employee sheet ───────────────────────────────────────────────────────────

function EmployeeSheet({
  employee,
  services,
  functions,
  onSaved,
  onUnselect,
}: {
  employee: HREmployee
  services: HRService[]
  functions: HRFunction[]
  onSaved: () => Promise<void>
  onUnselect: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [activeTab, setActiveTab] = useState<'infos' | 'contrats' | 'documents' | 'conges'>('infos')
  const [sheetContracts, setSheetContracts] = useState<HRContract[]>([])
  const [sheetDocuments, setSheetDocuments] = useState<HRDocument[]>([])
  const [sheetLeaveBalance, setSheetLeaveBalance] = useState<HRLeaveBalance[]>([])
  const [sheetLoading, setSheetLoading] = useState(false)

  useEffect(() => {
    setEditing(false)
    setActiveTab('infos')
    setSheetContracts([])
    setSheetDocuments([])
    setSheetLeaveBalance([])
  }, [employee.id])

  useEffect(() => {
    if (activeTab === 'contrats' && sheetContracts.length === 0) {
      setSheetLoading(true)
      getHRContracts({ employee_id: employee.id })
        .then(setSheetContracts)
        .finally(() => setSheetLoading(false))
    }
    if (activeTab === 'documents' && sheetDocuments.length === 0) {
      setSheetLoading(true)
      getHRDocuments({ employee_id: employee.id })
        .then(setSheetDocuments)
        .finally(() => setSheetLoading(false))
    }
    if (activeTab === 'conges' && sheetLeaveBalance.length === 0) {
      setSheetLoading(true)
      getLeaveBalance({ employee_id: employee.id, annee: new Date().getFullYear() })
        .then(setSheetLeaveBalance)
        .finally(() => setSheetLoading(false))
    }
  }, [activeTab, employee.id])

  const initials = ((employee.prenom?.[0] || '') + (employee.nom[0] || '')).toUpperCase()
  const [bg, fg] = avatarColors(employee.nom)

  return (
    <aside className={styles.employeeSheet}>
      <div className={styles.sheetHeader}>
        <div className={styles.sheetAvatar} style={{ background: bg, color: fg }}>
          {employee.photo_url ? (
            <img src={employee.photo_url} alt="" className={styles.sheetPhoto} />
          ) : initials}
        </div>
        <div className={styles.sheetTitle}>
          <div className={styles.sheetTitleRow}>
            <h2>{fullName(employee)}</h2>
            <button className={styles.iconButton} onClick={onUnselect}><X size={18} /></button>
          </div>
          <p>{employee.fonction?.libelle || 'Poste non défini'} · <code style={{ fontSize: 12 }}>{employee.matricule}</code></p>
          <div style={{ marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <span className={`${styles.badge} ${styles[employee.statut] || ''}`}>
              {STATUS_LABELS[employee.statut] || employee.statut}
            </span>
            {employee.service && (
              <span className={styles.serviceChip}>{employee.service.libelle}</span>
            )}
          </div>
        </div>
      </div>

      <div className={styles.sheetBody}>
        {editing ? (
          <EmployeeForm
            employee={employee}
            services={services}
            functions={functions}
            onSaved={async () => { setEditing(false); await onSaved() }}
          />
        ) : (
          <>
            <div className={styles.tabs}>
              {(['infos', 'contrats', 'documents', 'conges'] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={`${styles.tab} ${activeTab === tab ? styles.activeTab : ''}`}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab === 'infos' ? 'Informations' : tab === 'contrats' ? 'Contrats' : tab === 'documents' ? 'Documents' : 'Solde congés'}
                  {tab === 'contrats' && sheetContracts.length > 0 && (
                    <span className={styles.tabBadge}>{sheetContracts.length}</span>
                  )}
                  {tab === 'documents' && sheetDocuments.length > 0 && (
                    <span className={styles.tabBadge}>{sheetDocuments.length}</span>
                  )}
                </button>
              ))}
            </div>

            {activeTab === 'infos' && (
              <dl className={styles.details}>
                <dt>Service</dt><dd>{employee.service?.libelle || '—'}</dd>
                <dt>Téléphone</dt><dd>{employee.telephone || '—'}</dd>
                <dt>Email</dt><dd style={{ wordBreak: 'break-all' }}>{employee.email || '—'}</dd>
                <dt>Sexe</dt><dd>{employee.sexe === 'M' ? 'Masculin' : employee.sexe === 'F' ? 'Féminin' : '—'}</dd>
                <dt>Naissance</dt><dd>{employee.date_naissance || '—'}{employee.lieu_naissance ? ` à ${employee.lieu_naissance}` : ''}</dd>
                <dt>Adresse</dt><dd>{employee.adresse || '—'}</dd>
                <dt>Date d'entrée</dt><dd>{employee.date_entree || '—'}</dd>
                <dt>Urgence</dt><dd>{employee.contact_urgence_nom || '—'}</dd>
                <dt>Tél. urgence</dt><dd>{employee.contact_urgence_telephone || '—'}</dd>
              </dl>
            )}

            {activeTab === 'contrats' && (
              sheetLoading ? (
                <div className={styles.sheetLoading}><RotateCw size={18} className={styles.spinning} /> Chargement...</div>
              ) : sheetContracts.length === 0 ? (
                <div className={styles.sheetEmpty}>Aucun contrat enregistré pour cet employé.</div>
              ) : (
                <div className={styles.sheetCardList}>
                  {sheetContracts.map((c) => {
                    const days = c.date_fin ? daysUntil(c.date_fin) : null
                    const urgent = days !== null && days <= 30
                    const warning = days !== null && days <= 90
                    return (
                      <div key={c.id} className={styles.sheetCard}>
                        <div className={styles.sheetCardRow}>
                          <strong>{c.poste}</strong>
                          <span className={`${styles.badge} ${styles[c.statut] || ''}`}>{STATUS_LABELS[c.statut] || c.statut}</span>
                        </div>
                        <div className={styles.sheetCardMeta}>
                          <span>{c.type_contrat}</span>
                          <span>{c.date_debut}{c.date_fin ? ` → ${c.date_fin}` : ' (indéterminé)'}</span>
                        </div>
                        {days !== null && (
                          <div
                            className={styles.expiryAlert}
                            style={{
                              background: urgent ? '#fee2e2' : warning ? '#fff7ed' : '#f0fdf4',
                              color: urgent ? '#991b1b' : warning ? '#92400e' : '#166534',
                            }}
                          >
                            <AlertTriangle size={13} />
                            Expire dans {days} jour{days > 1 ? 's' : ''}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )
            )}

            {activeTab === 'documents' && (
              sheetLoading ? (
                <div className={styles.sheetLoading}><RotateCw size={18} className={styles.spinning} /> Chargement...</div>
              ) : sheetDocuments.length === 0 ? (
                <div className={styles.sheetEmpty}>Aucun document pour cet employé.</div>
              ) : (
                <div className={styles.sheetCardList}>
                  {sheetDocuments.map((d) => (
                    <a
                      key={d.id}
                      href={d.fichier_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={styles.sheetCard}
                      style={{ textDecoration: 'none', color: 'inherit' }}
                    >
                      <div className={styles.sheetCardRow}>
                        <strong>{d.titre}</strong>
                        <span className={styles.serviceChip}>{d.type_document}</span>
                      </div>
                      <div className={styles.sheetCardMeta}>
                        <span>Ajouté le {new Date(d.date_upload).toLocaleDateString('fr-FR')}</span>
                        <Eye size={14} style={{ color: '#714B67' }} />
                      </div>
                    </a>
                  ))}
                </div>
              )
            )}

            {activeTab === 'conges' && (
              sheetLoading ? (
                <div className={styles.sheetLoading}><RotateCw size={18} className={styles.spinning} /> Chargement...</div>
              ) : sheetLeaveBalance.length === 0 ? (
                <div className={styles.sheetEmpty}>Aucune allocation de congé pour {new Date().getFullYear()}.</div>
              ) : (
                <div className={styles.sheetCardList}>
                  {sheetLeaveBalance.map((b) => {
                    const solde = parseFloat(b.solde)
                    const pct = parseFloat(b.jours_alloues) > 0 ? Math.max(0, Math.min(100, solde / (parseFloat(b.jours_alloues) + parseFloat(b.report_annee_precedente)) * 100)) : 0
                    return (
                      <div key={b.type_absence} className={styles.sheetCard}>
                        <div className={styles.sheetCardRow}>
                          <strong>{b.type_absence}</strong>
                          <span style={{ fontWeight: 700, color: solde < 0 ? '#dc2626' : '#059669' }}>
                            {b.solde} j restants
                          </span>
                        </div>
                        <div style={{ margin: '6px 0', height: 6, background: '#e9ecef', borderRadius: 3, overflow: 'hidden' }}>
                          <div style={{ width: `${pct}%`, height: '100%', background: solde < 0 ? '#dc2626' : '#714B67', borderRadius: 3, transition: 'width 0.3s' }} />
                        </div>
                        <div className={styles.sheetCardMeta}>
                          <span>Alloués: {b.jours_alloues}j{parseFloat(b.report_annee_precedente) > 0 ? ` + ${b.report_annee_precedente}j reportés` : ''}</span>
                          <span>Utilisés: {b.jours_utilises}j</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )
            )}
          </>
        )}
      </div>

      {!editing && (
        <div className={styles.sheetActions}>
          <button className={styles.primaryButton} onClick={() => setEditing(true)}>
            <Edit2 size={14} /> Modifier
          </button>
          <button
            className={styles.secondaryButton}
            onClick={async () => {
              if (confirm('Archiver cet employé ?')) {
                await archiveHREmployee(employee.id)
                await onSaved()
              }
            }}
          >
            Archiver
          </button>
        </div>
      )}
    </aside>
  )
}

// ─── Leave calendar ───────────────────────────────────────────────────────────

const LEAVE_COLORS: Record<string, string> = {
  'congé annuel': '#714B67',
  maladie: '#dc2626',
  mission: '#2563eb',
  permission: '#d97706',
  'absence justifiée': '#059669',
  'absence non justifiée': '#9ca3af',
}

function LeaveCalendar({
  leaves,
  employeeById,
}: {
  leaves: HRLeave[]
  employeeById: Map<number, HREmployee>
}) {
  const [current, setCurrent] = useState(() => {
    const d = new Date()
    return new Date(d.getFullYear(), d.getMonth(), 1)
  })

  const year = current.getFullYear()
  const month = current.getMonth()
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const firstDow = (new Date(year, month, 1).getDay() + 6) % 7 // Monday = 0

  const days = Array.from({ length: daysInMonth }, (_, i) => i + 1)
  const DOW_LABELS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']
  const MONTH_LABELS = ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

  // Which leaves overlap with this month?
  const monthStart = new Date(year, month, 1).getTime()
  const monthEnd = new Date(year, month + 1, 0, 23, 59).getTime()

  const monthLeaves = leaves.filter((l) => {
    const s = new Date(l.date_debut).getTime()
    const e = new Date(l.date_fin).getTime()
    return s <= monthEnd && e >= monthStart && l.statut !== 'rejeté'
  })

  // For each day, collect which leaves are active
  const leavesForDay = (day: number) => {
    const t = new Date(year, month, day).getTime()
    return monthLeaves.filter((l) => {
      const s = new Date(l.date_debut).getTime()
      const e = new Date(l.date_fin).getTime()
      return t >= s && t <= e
    })
  }

  return (
    <div className={styles.section}>
      <div className={styles.calendarHeader}>
        <button className={styles.iconButton} onClick={() => setCurrent(new Date(year, month - 1, 1))}>
          <ChevronLeft size={18} />
        </button>
        <h2 style={{ margin: 0 }}>{MONTH_LABELS[month]} {year}</h2>
        <button className={styles.iconButton} onClick={() => setCurrent(new Date(year, month + 1, 1))}>
          <ChevronRight size={18} />
        </button>
      </div>

      {/* Legend */}
      <div className={styles.calendarLegend}>
        {Object.entries(LEAVE_COLORS).map(([type, color]) => (
          <span key={type} className={styles.legendItem}>
            <span className={styles.legendDot} style={{ background: color }} />
            {type}
          </span>
        ))}
      </div>

      {/* Calendar grid */}
      <div className={styles.calGrid}>
        {DOW_LABELS.map((d) => (
          <div key={d} className={styles.calDowHeader}>{d}</div>
        ))}
        {/* Empty cells before first day */}
        {Array.from({ length: firstDow }, (_, i) => (
          <div key={`empty-${i}`} className={styles.calCell} />
        ))}
        {days.map((day) => {
          const today = new Date()
          const isToday = today.getDate() === day && today.getMonth() === month && today.getFullYear() === year
          const dayLeaves = leavesForDay(day)
          return (
            <div key={day} className={`${styles.calCell} ${isToday ? styles.calToday : ''}`}>
              <span className={styles.calDayNum}>{day}</span>
              <div className={styles.calLeaveSlots}>
                {dayLeaves.slice(0, 2).map((l) => {
                  const emp = employeeById.get(l.employee_id)
                  const color = LEAVE_COLORS[l.type_absence] || '#714B67'
                  return (
                    <div
                      key={l.id}
                      className={styles.calLeaveChip}
                      style={{ background: color }}
                      title={`${fullName(emp)} — ${l.type_absence}`}
                    >
                      {emp ? (emp.prenom?.[0] || emp.nom[0] || '?').toUpperCase() + '.' + emp.nom[0] : '?'}
                    </div>
                  )
                })}
                {dayLeaves.length > 2 && (
                  <div className={styles.calLeaveMore}>+{dayLeaves.length - 2}</div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Stats bar */}
      {monthLeaves.length > 0 && (
        <div className={styles.calStats}>
          <strong>{monthLeaves.length}</strong> absence{monthLeaves.length > 1 ? 's' : ''} ce mois ·{' '}
          {[...new Set(monthLeaves.map((l) => l.employee_id))].length} agent{[...new Set(monthLeaves.map((l) => l.employee_id))].length > 1 ? 's' : ''} concerné{[...new Set(monthLeaves.map((l) => l.employee_id))].length > 1 ? 's' : ''}
        </div>
      )}
    </div>
  )
}

// ─── Leave table ──────────────────────────────────────────────────────────────

function LeaveTable({
  leaves,
  employeeById,
  onChanged,
}: {
  leaves: HRLeave[]
  employeeById: Map<number, HREmployee>
  onChanged: () => Promise<void>
}) {
  const counts = { soumis: 0, approuvé: 0, rejeté: 0, brouillon: 0 }
  for (const l of leaves) {
    if (l.statut in counts) counts[l.statut as keyof typeof counts]++
  }

  return (
    <>
      <div className={styles.leaveSummaryBar}>
        <span className={styles.leaveStat}><span className={`${styles.statDot} ${styles.dotOrange}`} />{counts.soumis} en attente</span>
        <span className={styles.leaveStat}><span className={`${styles.statDot} ${styles.dotGreen}`} />{counts.approuvé} approuvé{counts.approuvé > 1 ? 's' : ''}</span>
        <span className={styles.leaveStat}><span className={`${styles.statDot} ${styles.dotRed}`} />{counts.rejeté} rejeté{counts.rejeté > 1 ? 's' : ''}</span>
        <span className={styles.leaveStat}><span className={`${styles.statDot} ${styles.dotGray}`} />{counts.brouillon} brouillon{counts.brouillon > 1 ? 's' : ''}</span>
      </div>
      <div className={styles.tableWrap}>
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              <th>Type</th>
              <th>Dates</th>
              <th>Jours</th>
              <th>Statut</th>
              <th style={{ textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {leaves.map((item) => (
              <tr key={item.id}>
                <td style={{ fontWeight: 600 }}>{fullName(employeeById.get(item.employee_id))}</td>
                <td>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: LEAVE_COLORS[item.type_absence] || '#714B67', flexShrink: 0 }} />
                    {item.type_absence}
                  </span>
                </td>
                <td style={{ fontSize: 13 }}>{item.date_debut} → {item.date_fin}</td>
                <td><strong>{item.nombre_jours}</strong> j</td>
                <td><span className={`${styles.badge} ${styles[item.statut] || ''}`}>{STATUS_LABELS[item.statut] || item.statut}</span></td>
                <td className={styles.actions} style={{ justifyContent: 'flex-end' }}>
                  {item.statut === 'brouillon' && (
                    <button
                      className={styles.primaryButton}
                      style={{ padding: '4px 10px', fontSize: 12, display: 'flex', alignItems: 'center', gap: 5 }}
                      onClick={async () => { await submitHRLeave(item.id); await onChanged() }}
                    >
                      <Send size={14} /> Soumettre
                    </button>
                  )}
                  {item.statut === 'soumis' && (
                    <>
                      <button
                        className={styles.primaryButton}
                        style={{ padding: '4px 10px', fontSize: 12, background: '#059669', borderColor: '#059669', display: 'flex', alignItems: 'center', gap: 5 }}
                        onClick={async () => { if (confirm('Approuver ?')) { await approveHRLeave(item.id); await onChanged() } }}
                      >
                        <Check size={14} /> Approuver
                      </button>
                      <button
                        className={styles.secondaryButton}
                        style={{ padding: '4px 10px', fontSize: 12, color: '#dc2626', display: 'flex', alignItems: 'center', gap: 5 }}
                        onClick={async () => { if (confirm('Rejeter ?')) { await rejectHRLeave(item.id); await onChanged() } }}
                      >
                        <X size={14} /> Rejeter
                      </button>
                    </>
                  )}
                  <button className={styles.iconButton} title="Détails"><Eye size={16} /></button>
                </td>
              </tr>
            ))}
            {leaves.length === 0 && (
              <tr><td colSpan={6} style={{ textAlign: 'center', padding: 40, color: '#999' }}>Aucune demande de congé</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}

// ─── Contract table ───────────────────────────────────────────────────────────

function ContractTable({
  contracts,
  employeeById,
  canViewSalary,
}: {
  contracts: HRContract[]
  employeeById: Map<number, HREmployee>
  canViewSalary: boolean
}) {
  const expiryCss = (dateStr?: string | null) => {
    if (!dateStr) return null
    const days = daysUntil(dateStr)
    if (days < 0) return { background: '#f3f4f6', color: '#6b7280' } // expiré
    if (days <= 30) return { background: '#fee2e2', color: '#991b1b' }
    if (days <= 90) return { background: '#fff7ed', color: '#92400e' }
    return null
  }

  return (
    <div className={styles.tableWrap}>
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Type</th>
            <th>Poste</th>
            <th>Période</th>
            <th>Expiration</th>
            <th>Statut</th>
            {canViewSalary && <th style={{ textAlign: 'right' }}>Salaire</th>}
            <th style={{ textAlign: 'right' }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {contracts.map((item) => {
            const ec = expiryCss(item.date_fin)
            const days = item.date_fin ? daysUntil(item.date_fin) : null
            return (
              <tr key={item.id}>
                <td style={{ fontWeight: 600 }}>{fullName(employeeById.get(item.employee_id))}</td>
                <td>
                  <span className={styles.badge} style={{ background: '#e9ecef', color: '#495057', border: 'none' }}>
                    {item.type_contrat}
                  </span>
                </td>
                <td>{item.poste}</td>
                <td style={{ fontSize: 13 }}>
                  {item.date_debut}{item.date_fin ? ` → ${item.date_fin}` : ' (Indéterminé)'}
                </td>
                <td>
                  {days !== null ? (
                    <span
                      className={styles.expiryBadge}
                      style={ec || { background: '#f0fdf4', color: '#166534' }}
                    >
                      {days < 0 ? 'Expiré' : `${days}j`}
                    </span>
                  ) : (
                    <span style={{ color: '#aaa', fontSize: 13 }}>—</span>
                  )}
                </td>
                <td>
                  <span className={`${styles.badge} ${styles[item.statut] || ''}`}>
                    {STATUS_LABELS[item.statut] || item.statut}
                  </span>
                </td>
                {canViewSalary && (
                  <td style={{ textAlign: 'right', fontWeight: 600, color: '#714B67' }}>
                    {item.salaire_base} {item.devise}
                  </td>
                )}
                <td className={styles.actions} style={{ justifyContent: 'flex-end' }}>
                  <button className={styles.iconButton} title="Modifier"><Edit2 size={16} /></button>
                  <button className={styles.iconButton} title="Plus"><MoreVertical size={16} /></button>
                </td>
              </tr>
            )
          })}
          {contracts.length === 0 && (
            <tr>
              <td colSpan={canViewSalary ? 8 : 7} style={{ textAlign: 'center', padding: 40, color: '#999' }}>
                Aucun contrat enregistré
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ─── Document table ───────────────────────────────────────────────────────────

function DocumentTable({
  documents,
  employeeById,
}: {
  documents: HRDocument[]
  employeeById: Map<number, HREmployee>
}) {
  return (
    <div className={styles.tableWrap}>
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Type</th>
            <th>Titre</th>
            <th>Date d'ajout</th>
            <th style={{ textAlign: 'right' }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((item) => (
            <tr key={item.id}>
              <td style={{ fontWeight: 600 }}>{fullName(employeeById.get(item.employee_id))}</td>
              <td>
                <span className={styles.badge} style={{ background: '#f8f9fa', color: '#666', border: 'none' }}>
                  {item.type_document}
                </span>
              </td>
              <td>{item.titre}</td>
              <td style={{ color: '#888', fontSize: 13 }}>
                {new Date(item.date_upload).toLocaleDateString('fr-FR')}
              </td>
              <td className={styles.actions} style={{ justifyContent: 'flex-end' }}>
                <a
                  href={item.fichier_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.primaryButton}
                  style={{ padding: '4px 10px', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 5 }}
                >
                  <Eye size={14} /> Voir
                </a>
              </td>
            </tr>
          ))}
          {documents.length === 0 && (
            <tr><td colSpan={5} style={{ textAlign: 'center', padding: 40, color: '#999' }}>Aucun document</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ─── Forms ────────────────────────────────────────────────────────────────────

function EmployeeForm({
  employee,
  services,
  functions,
  onSaved,
}: {
  employee?: HREmployee
  services: HRService[]
  functions: HRFunction[]
  onSaved: () => Promise<void>
}) {
  const [form, setForm] = useState<any>(employee || { statut: 'actif', sexe: 'M' })
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (employee) await updateHREmployee(employee.id, form)
    else await createHREmployee(form)
    await onSaved()
  }
  const set = (k: string, v: any) => setForm((prev: any) => ({ ...prev, [k]: v }))

  return (
    <form className={styles.formPanel} onSubmit={submit}>
      <div style={{ display: 'grid', gap: 15 }}>
        <label className={styles.formLabel}>Identité</label>
        <div style={{ display: 'flex', gap: 10 }}>
          <input required placeholder="Matricule" style={{ width: 120 }} value={form.matricule || ''} onChange={(e) => set('matricule', e.target.value)} />
          <select value={form.sexe || 'M'} style={{ width: 100 }} onChange={(e) => set('sexe', e.target.value)}>
            <option value="M">Masculin</option>
            <option value="F">Féminin</option>
          </select>
        </div>
        <input required placeholder="Nom" value={form.nom || ''} onChange={(e) => set('nom', e.target.value)} />
        <input placeholder="Post-nom" value={form.post_nom || ''} onChange={(e) => set('post_nom', e.target.value)} />
        <input placeholder="Prénom" value={form.prenom || ''} onChange={(e) => set('prenom', e.target.value)} />
        <div style={{ display: 'flex', gap: 10 }}>
          <input type="date" title="Date de naissance" value={form.date_naissance || ''} onChange={(e) => set('date_naissance', e.target.value)} />
          <input placeholder="Lieu de naissance" value={form.lieu_naissance || ''} onChange={(e) => set('lieu_naissance', e.target.value)} />
        </div>
      </div>
      <div style={{ display: 'grid', gap: 15 }}>
        <label className={styles.formLabel}>Affectation & Contact</label>
        <select value={form.service_id || ''} onChange={(e) => set('service_id', e.target.value ? Number(e.target.value) : null)}>
          <option value="">Choisir un service...</option>
          {services.map((s) => <option key={s.id} value={s.id}>{s.libelle}</option>)}
        </select>
        <select value={form.fonction_id || ''} onChange={(e) => set('fonction_id', e.target.value ? Number(e.target.value) : null)}>
          <option value="">Choisir une fonction...</option>
          {functions.map((f) => <option key={f.id} value={f.id}>{f.libelle}</option>)}
        </select>
        <input placeholder="Téléphone" value={form.telephone || ''} onChange={(e) => set('telephone', e.target.value)} />
        <input placeholder="Email" type="email" value={form.email || ''} onChange={(e) => set('email', e.target.value)} />
        <textarea placeholder="Adresse complète" value={form.adresse || ''} style={{ minHeight: 60 }} onChange={(e) => set('adresse', e.target.value)} />
        <div style={{ display: 'flex', gap: 10 }}>
          <input type="date" title="Date d'entrée" value={form.date_entree || ''} onChange={(e) => set('date_entree', e.target.value)} />
          <select value={form.statut || 'actif'} onChange={(e) => set('statut', e.target.value)}>
            <option value="actif">Actif</option>
            <option value="en_conge">En congé</option>
            <option value="suspendu">Suspendu</option>
            <option value="sorti">Sorti</option>
          </select>
        </div>
      </div>
      <div style={{ gridColumn: '1/-1', display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 10 }}>
        <button type="submit" className={styles.primaryButton}>Enregistrer l'employé</button>
      </div>
    </form>
  )
}

function ContractForm({
  employees,
  canViewSalary,
  typesContrats,
  onSaved,
}: {
  employees: HREmployee[]
  canViewSalary: boolean
  typesContrats: HRReference[]
  onSaved: () => Promise<void>
}) {
  const fallbackTypes = ['CDI', 'CDD', 'consultant', 'stagiaire', 'bénévole']
  const [form, setForm] = useState<any>({ type_contrat: typesContrats[0]?.libelle || 'CDI', statut: 'actif', devise: 'USD', salaire_base: 0 })
  const set = (k: string, v: any) => setForm((p: any) => ({ ...p, [k]: v }))
  return (
    <SimpleForm title="Nouveau contrat" onSubmit={async () => {
      const payload = canViewSalary ? form : { ...form, salaire_base: undefined, devise: undefined }
      await createHRContract(payload)
      await onSaved()
    }}>
      <div style={{ display: 'grid', gap: 15 }}>
        <select required onChange={(e) => set('employee_id', Number(e.target.value))}>
          <option value="">Sélectionner un agent...</option>
          {employees.map((e) => <option key={e.id} value={e.id}>{fullName(e)}</option>)}
        </select>
        <select value={form.type_contrat} onChange={(e) => set('type_contrat', e.target.value)}>
          {typesContrats.length > 0
            ? typesContrats.filter((t) => t.is_active !== false).map((t) => <option key={t.id} value={t.libelle}>{t.libelle}</option>)
            : fallbackTypes.map((t) => <option key={t}>{t}</option>)
          }
        </select>
        <input required placeholder="Intitulé du poste" onChange={(e) => set('poste', e.target.value)} />
      </div>
      <div style={{ display: 'grid', gap: 15 }}>
        <input required type="date" title="Date de début" onChange={(e) => set('date_debut', e.target.value)} />
        <input type="date" title="Date de fin" onChange={(e) => set('date_fin', e.target.value || null)} />
        {canViewSalary && (
          <div style={{ display: 'flex', gap: 10 }}>
            <input type="number" placeholder="Salaire" style={{ flex: 1 }} onChange={(e) => set('salaire_base', e.target.value)} />
            <input placeholder="USD" style={{ width: 80 }} value={form.devise} onChange={(e) => set('devise', e.target.value)} />
          </div>
        )}
      </div>
    </SimpleForm>
  )
}

function LeaveForm({ employees, typesAbsences, onSaved }: { employees: HREmployee[]; typesAbsences: HRReference[]; onSaved: () => Promise<void> }) {
  const fallbackTypes = ['congé annuel', 'maladie', 'mission', 'permission', 'absence justifiée', 'absence non justifiée']
  const [form, setForm] = useState<any>({ type_absence: typesAbsences[0]?.libelle || 'congé annuel', statut: 'brouillon' })
  const set = (k: string, v: any) => setForm((p: any) => ({ ...p, [k]: v }))
  return (
    <SimpleForm title="Demande d'absence" onSubmit={async () => { await createHRLeave(form); await onSaved() }}>
      <div style={{ display: 'grid', gap: 15 }}>
        <select required onChange={(e) => set('employee_id', Number(e.target.value))}>
          <option value="">Sélectionner un agent...</option>
          {employees.map((e) => <option key={e.id} value={e.id}>{fullName(e)}</option>)}
        </select>
        <select value={form.type_absence} onChange={(e) => set('type_absence', e.target.value)}>
          {typesAbsences.length > 0
            ? typesAbsences.filter((t) => t.is_active !== false).map((t) => <option key={t.id} value={t.libelle}>{t.libelle}</option>)
            : fallbackTypes.map((t) => <option key={t}>{t}</option>)
          }
        </select>
        <input placeholder="Motif" onChange={(e) => set('motif', e.target.value)} />
      </div>
      <div style={{ display: 'grid', gap: 15 }}>
        <input required type="date" title="Début" onChange={(e) => set('date_debut', e.target.value)} />
        <input required type="date" title="Fin" onChange={(e) => set('date_fin', e.target.value)} />
        <input required type="number" step="0.5" placeholder="Nombre de jours (ex: 2.5)" onChange={(e) => set('nombre_jours', e.target.value)} />
      </div>
    </SimpleForm>
  )
}

function DocumentForm({ employees, typesDocs, onSaved }: { employees: HREmployee[]; typesDocs: HRReference[]; onSaved: () => Promise<void> }) {
  const fallbackTypes = ['CV', 'contrat', 'diplôme', "pièce d'identité", 'photo', "décision d'affectation", 'attestation', 'bulletin de paie', 'autre']
  const [form, setForm] = useState<any>({ type_document: typesDocs[0]?.libelle || 'CV' })
  const set = (k: string, v: any) => setForm((p: any) => ({ ...p, [k]: v }))
  return (
    <SimpleForm title="Ajouter un document" onSubmit={async () => { await createHRDocument(form); await onSaved() }}>
      <div style={{ display: 'grid', gap: 15 }}>
        <select required onChange={(e) => set('employee_id', Number(e.target.value))}>
          <option value="">Sélectionner un agent...</option>
          {employees.map((e) => <option key={e.id} value={e.id}>{fullName(e)}</option>)}
        </select>
        <select value={form.type_document} onChange={(e) => set('type_document', e.target.value)}>
          {typesDocs.length > 0
            ? typesDocs.filter((t) => t.is_active !== false).map((t) => <option key={t.id} value={t.libelle}>{t.libelle}</option>)
            : fallbackTypes.map((t) => <option key={t}>{t}</option>)
          }
        </select>
      </div>
      <div style={{ display: 'grid', gap: 15 }}>
        <input required placeholder="Titre du document" onChange={(e) => set('titre', e.target.value)} />
        <input required placeholder="URL du fichier (https://...)" onChange={(e) => set('fichier_url', e.target.value)} />
      </div>
    </SimpleForm>
  )
}

function SimpleForm({
  children,
  title,
  onSubmit,
}: {
  children: ReactNode
  title: string
  onSubmit: () => Promise<void>
}) {
  return (
    <div className={styles.section} style={{ padding: 0, overflow: 'hidden', marginBottom: 20 }}>
      <div style={{ padding: '12px 20px', background: '#fdf8fc', borderBottom: '1px solid #dee2e6', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0, fontSize: 15, color: '#714B67' }}>{title}</h3>
      </div>
      <form
        className={styles.formPanel}
        style={{ border: 'none', marginBottom: 0 }}
        onSubmit={async (e) => { e.preventDefault(); await onSubmit() }}
      >
        {children}
        <div style={{ gridColumn: '1/-1', display: 'flex', justifyContent: 'flex-end', marginTop: 10 }}>
          <button className={styles.primaryButton}>Enregistrer</button>
        </div>
      </form>
    </div>
  )
}

// ─── Settings ─────────────────────────────────────────────────────────────────

type ConfigItem = {
  key: string
  title: string
  description: string
  count: number
  icon: ReactNode
  actionLabel: string
}

function SettingsView({
  services,
  functions,
  references,
  onSaved,
}: {
  services: HRService[]
  functions: HRFunction[]
  references: Record<string, HRReference[]>
  onSaved: () => Promise<void>
}) {
  const { section: routeSection } = useParams()
  const { showSuccess, showError } = useNotification()
  const section = routeSection || ''
  const [query, setQuery] = useState('')
  const [panelOpen, setPanelOpen] = useState(false)
  const [editing, setEditing] = useState<any | null>(null)
  const [form, setForm] = useState({ code: '', libelle: '', description: '', is_active: true })

  const configGroups: { group: string; icon: ReactNode; items: ConfigItem[] }[] = [
    {
      group: 'Organisation',
      icon: <UsersRound size={18} />,
      items: [
        { key: 'services', title: 'Services', count: services.length, icon: <UsersRound size={20} />, actionLabel: 'Nouveau service', description: 'Gérer les services et unités administratives.' },
        { key: 'fonctions', title: 'Fonctions', count: functions.length, icon: <UserRound size={20} />, actionLabel: 'Nouvelle fonction', description: 'Structurer les intitulés de poste.' },
        { key: 'departements', title: 'Départements', count: references.departements?.length || 0, icon: <UsersRound size={20} />, actionLabel: 'Nouveau département', description: 'Organiser les regroupements internes.' },
      ],
    },
    {
      group: 'Contrats',
      icon: <BriefcaseBusiness size={18} />,
      items: [
        { key: 'types-contrats', title: 'Types de contrats', count: references['types-contrats']?.length || 0, icon: <BriefcaseBusiness size={20} />, actionLabel: 'Nouveau type', description: 'Définir les catégories de contrats.' },
        { key: 'statuts-contrats', title: 'Statuts de contrats', count: references['statuts-contrats']?.length || 0, icon: <BriefcaseBusiness size={20} />, actionLabel: 'Nouveau statut', description: 'Cycle de vie des contrats RH.' },
      ],
    },
    {
      group: 'Temps & absences',
      icon: <CalendarDays size={18} />,
      items: [
        { key: 'types-absences', title: "Types d'absences", count: references['types-absences']?.length || 0, icon: <CalendarDays size={20} />, actionLabel: 'Nouveau type', description: 'Configurer les congés, maladies, missions.' },
        { key: 'regles-conges', title: 'Règles de congés', count: references['regles-conges']?.length || 0, icon: <CalendarDays size={20} />, actionLabel: 'Nouvelle règle', description: 'Règles de calcul et validation des congés.' },
        { key: 'jours-feries', title: 'Jours fériés', count: references['jours-feries']?.length || 0, icon: <CalendarDays size={20} />, actionLabel: 'Nouveau jour férié', description: 'Jours non ouvrés applicables.' },
      ],
    },
    {
      group: 'Paie',
      icon: <WalletCards size={18} />,
      items: [
        { key: 'types-primes', title: 'Types de primes', count: references['types-primes']?.length || 0, icon: <WalletCards size={20} />, actionLabel: 'Nouvelle prime', description: 'Classifier les primes.' },
        { key: 'types-retenues', title: 'Types de retenues', count: references['types-retenues']?.length || 0, icon: <WalletCards size={20} />, actionLabel: 'Nouvelle retenue', description: 'Classifier les retenues.' },
        { key: 'devises', title: 'Devises', count: references.devises?.length || 0, icon: <WalletCards size={20} />, actionLabel: 'Nouvelle devise', description: 'Devises autorisées pour la paie.' },
      ],
    },
    {
      group: 'Documents',
      icon: <FolderOpen size={18} />,
      items: [
        { key: 'types-documents', title: 'Types de documents RH', count: references['types-documents']?.length || 0, icon: <FolderOpen size={20} />, actionLabel: 'Nouveau type', description: 'Catégories du dossier numérique employé.' },
      ],
    },
  ]

  const allItems = configGroups.flatMap((g) => g.items)
  const activeItem = allItems.find((i) => i.key === section) || null

  useEffect(() => { setQuery(''); setPanelOpen(false); setEditing(null) }, [section])

  const activeRows = useMemo(() => {
    if (!activeItem) return []
    if (activeItem.key === 'services') return services.map((s) => ({ ...s, description: '', category: 'services' }))
    if (activeItem.key === 'fonctions') return functions.map((f) => ({ ...f, code: String(f.id), description: '', category: 'fonctions' }))
    return references[activeItem.key] || []
  }, [activeItem, services, functions, references])

  const filteredRows = activeRows.filter((r: any) =>
    `${r.code} ${r.libelle} ${r.description || ''}`.toLowerCase().includes(query.toLowerCase())
  )

  const openPanel = (item?: any) => {
    setEditing(item || null)
    setForm({ code: item?.code || '', libelle: item?.libelle || '', description: item?.description || '', is_active: item?.is_active ?? true })
    setPanelOpen(true)
  }

  const saveConfig = async (e: FormEvent) => {
    e.preventDefault()
    if (!activeItem) return
    try {
      if (activeItem.key === 'services') {
        if (editing) await updateHRService(editing.id, { code: form.code, libelle: form.libelle, is_active: form.is_active })
        else await createHRService({ code: form.code, libelle: form.libelle, is_active: form.is_active })
      } else if (activeItem.key === 'fonctions') {
        if (editing) await updateHRFunction(editing.id, { libelle: form.libelle, is_active: form.is_active })
        else await createHRFunction({ libelle: form.libelle, is_active: form.is_active })
      } else if (editing) {
        await updateHRReference(activeItem.key, editing.id, form)
      } else {
        await createHRReference(activeItem.key, form)
      }
      showSuccess('Configuration enregistrée', 'Le référentiel RH a été mis à jour.')
      await onSaved()
    } catch (err) {
      showError("Échec de l'enregistrement", err instanceof Error ? err.message : 'Impossible de mettre à jour ce référentiel.')
    }
  }

  const toggleConfig = async (item: any) => {
    if (!activeItem) return
    const next = !item.is_active
    try {
      if (activeItem.key === 'services') await updateHRService(item.id, { is_active: next })
      else if (activeItem.key === 'fonctions') await updateHRFunction(item.id, { is_active: next })
      else await updateHRReference(activeItem.key, item.id, { is_active: next })
      showSuccess(next ? 'Élément activé' : 'Élément désactivé', '')
      await onSaved()
    } catch (err) {
      showError('Action impossible', err instanceof Error ? err.message : '')
    }
  }

  if (activeItem) {
    return (
      <div className={styles.configurationPage}>
        <section className={styles.configDetail}>
          <div className={styles.configDetailHeader}>
            <div>
              <Link className={styles.secondaryButton} to="/rh/parametres" style={{ textDecoration: 'none', marginBottom: 15, display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 13 }}>
                ← Retour
              </Link>
              <h2>{activeItem.title}</h2>
              <p style={{ color: '#666', fontSize: 14 }}>{activeItem.description}</p>
            </div>
            <button className={styles.primaryButton} onClick={() => openPanel()}>{activeItem.actionLabel}</button>
          </div>
          <div className={styles.configToolbar}>
            <Search size={16} />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher..." />
          </div>
          {filteredRows.length === 0 ? (
            <div className={styles.emptyState}>Aucun élément configuré.</div>
          ) : (
            <div className={styles.tableWrap}>
              <table>
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Libellé</th>
                    <th>{activeItem.key === 'services' || activeItem.key === 'fonctions' ? 'Statut' : 'Description'}</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRows.map((item: any) => (
                    <tr key={item.id}>
                      <td style={{ fontWeight: 600 }}>{item.code}</td>
                      <td>{item.libelle}</td>
                      {activeItem.key === 'services' || activeItem.key === 'fonctions' ? (
                        <td><span className={`${styles.badge} ${item.is_active ? styles.actif : styles.suspendu}`}>{item.is_active ? 'Actif' : 'Inactif'}</span></td>
                      ) : (
                        <td style={{ color: '#666', fontSize: 13 }}>{item.description || '—'}</td>
                      )}
                      <td className={styles.actions}>
                        <button className={styles.secondaryButton} style={{ padding: '4px 8px', fontSize: 12 }} onClick={() => openPanel(item)}>Modifier</button>
                        <button className={styles.secondaryButton} style={{ padding: '4px 8px', fontSize: 12 }} onClick={() => toggleConfig(item)}>
                          {item.is_active ? 'Désactiver' : 'Activer'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {panelOpen && (
          <div className={styles.sidePanelOverlay} onClick={() => setPanelOpen(false)}>
            <aside className={styles.sidePanel} onClick={(e) => e.stopPropagation()}>
              <div className={styles.sidePanelHeader}>
                <div>
                  <h2 style={{ color: '#714B67', margin: 0 }}>{editing ? 'Modifier' : 'Créer'} {activeItem.title}</h2>
                  <p style={{ color: '#666', fontSize: 13, margin: '4px 0 0' }}>Configuration spécifique au tenant.</p>
                </div>
                <button className={styles.iconButton} onClick={() => setPanelOpen(false)}><X size={18} /></button>
              </div>
              <form className={styles.sidePanelForm} onSubmit={saveConfig}>
                {activeItem.key !== 'fonctions' && (
                  <label className={styles.formLabel}>
                    Code
                    <input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="Ex: R&D, CDI..." />
                  </label>
                )}
                <label className={styles.formLabel}>
                  Libellé
                  <input required value={form.libelle} onChange={(e) => setForm({ ...form, libelle: e.target.value })} placeholder="Ex: Recherche et Développement" />
                </label>
                {activeItem.key !== 'services' && activeItem.key !== 'fonctions' && (
                  <label className={styles.formLabel}>
                    Description
                    <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Détails supplémentaires..." />
                  </label>
                )}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '10px 0' }}>
                  <input type="checkbox" id="is_active" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
                  <label htmlFor="is_active" style={{ cursor: 'pointer', fontSize: 14 }}>Actif</label>
                </div>
                <button className={styles.primaryButton} style={{ width: '100%', marginTop: 10 }}>Enregistrer</button>
              </form>
            </aside>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={styles.configurationPage}>
      <div className={styles.section} style={{ marginBottom: 25 }}>
        <h2 style={{ color: '#714B67', border: 'none', marginBottom: 5 }}>Paramètres du module</h2>
        <p style={{ color: '#666', fontSize: 14, margin: 0 }}>Gérez les référentiels et la structure organisationnelle de votre département RH.</p>
      </div>
      <div className={styles.configGroups}>
        {configGroups.map((group) => (
          <section className={styles.configGroup} key={group.group}>
            <div className={styles.configGroupTitle}>
              <h3 style={{ color: '#714B67', fontWeight: 600, margin: 0, fontSize: 15 }}>{group.group}</h3>
            </div>
            <div className={styles.configCards}>
              {group.items.map((item) => (
                <article className={styles.configCard} key={item.key}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 15 }}>
                    <div style={{ color: '#714B67', background: '#fdf8fc', padding: 10, borderRadius: 4 }}>{item.icon}</div>
                    <div>
                      <h4 style={{ margin: 0, fontSize: 14 }}>{item.title}</h4>
                      <p style={{ margin: 0, fontSize: 12, color: '#666' }}>{item.count} élément{item.count !== 1 ? 's' : ''}</p>
                    </div>
                  </div>
                  <Link className={styles.configureButton} to={`/rh/parametres/${item.key}`}>Configurer</Link>
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}

// ─── Attendance View ──────────────────────────────────────────────────────────

const ATTENDANCE_COLORS: Record<string, string> = {
  present: '#059669',
  absent: '#dc2626',
  demi_journee: '#d97706',
  conge: '#2563eb',
  teletravail: '#7c3aed',
}

const ATTENDANCE_LABELS: Record<string, string> = {
  present: 'Présent',
  absent: 'Absent',
  demi_journee: '½ Journée',
  conge: 'Congé',
  teletravail: 'Télétravail',
}

function AttendanceView({
  attendances,
  employees,
  summary,
}: {
  attendances: HRAttendance[]
  employees: HREmployee[]
  summary: HRAttendanceSummary | null
}) {
  const now = new Date()
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate()
  const days = Array.from({ length: daysInMonth }, (_, i) => i + 1)

  // Build map: employee_id -> day -> statut
  const attMap = new Map<string, string>()
  for (const a of attendances) {
    const day = new Date(a.date_presence).getDate()
    attMap.set(`${a.employee_id}-${day}`, a.statut_presence)
  }

  const activeEmployees = employees.filter((e) => e.statut === 'actif')

  return (
    <>
      {summary && (
        <div className={styles.leaveSummaryBar}>
          <span className={styles.leaveStat}><span className={`${styles.statDot}`} style={{ background: '#059669' }} />{summary.presents} présents</span>
          <span className={styles.leaveStat}><span className={`${styles.statDot}`} style={{ background: '#dc2626' }} />{summary.absents} absents</span>
          <span className={styles.leaveStat}><span className={`${styles.statDot}`} style={{ background: '#d97706' }} />{summary.demi_journees} ½ journées</span>
          <span className={styles.leaveStat}><span className={`${styles.statDot}`} style={{ background: '#2563eb' }} />{summary.conges} en congé</span>
          {summary.taux_presence != null && (
            <span className={styles.leaveStat} style={{ fontWeight: 700, color: '#714B67' }}>
              Taux de présence: {summary.taux_presence.toFixed(1)}%
            </span>
          )}
        </div>
      )}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 12, minWidth: 800 }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: '8px 12px', background: '#fdf8fc', borderBottom: '2px solid #dee2e6', position: 'sticky', left: 0, zIndex: 1 }}>Agent</th>
              {days.map((d) => (
                <th key={d} style={{ padding: '6px 4px', background: '#fdf8fc', borderBottom: '2px solid #dee2e6', textAlign: 'center', minWidth: 28, color: d === now.getDate() ? '#714B67' : undefined, fontWeight: d === now.getDate() ? 700 : 400 }}>
                  {d}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {activeEmployees.map((emp) => (
              <tr key={emp.id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                <td style={{ padding: '6px 12px', fontWeight: 600, background: '#fff', position: 'sticky', left: 0, whiteSpace: 'nowrap' }}>
                  {emp.nom} {emp.prenom || ''}
                </td>
                {days.map((d) => {
                  const statut = attMap.get(`${emp.id}-${d}`)
                  return (
                    <td key={d} style={{ padding: 2, textAlign: 'center' }}>
                      {statut ? (
                        <div
                          title={ATTENDANCE_LABELS[statut] || statut}
                          style={{
                            width: 20,
                            height: 20,
                            borderRadius: 3,
                            background: ATTENDANCE_COLORS[statut] || '#ccc',
                            margin: '0 auto',
                            opacity: 0.85,
                          }}
                        />
                      ) : (
                        <div style={{ width: 20, height: 20, margin: '0 auto' }} />
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
            {activeEmployees.length === 0 && (
              <tr><td colSpan={daysInMonth + 1} style={{ textAlign: 'center', padding: 40, color: '#999' }}>Aucun employé actif</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div style={{ marginTop: 12, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {Object.entries(ATTENDANCE_LABELS).map(([key, label]) => (
          <span key={key} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#555' }}>
            <span style={{ width: 12, height: 12, borderRadius: 2, background: ATTENDANCE_COLORS[key], display: 'inline-block' }} />
            {label}
          </span>
        ))}
      </div>
    </>
  )
}

function AttendanceBatchForm({ employees, onSaved }: { employees: HREmployee[]; onSaved: () => Promise<void> }) {
  const today = new Date().toISOString().split('T')[0]
  const [form, setForm] = useState({ date: today, statut: 'present' as AttendanceStatut, employee_ids: [] as number[] })
  const activeEmployees = employees.filter((e) => e.statut === 'actif')

  const toggleEmp = (id: number) => {
    setForm((prev) => ({
      ...prev,
      employee_ids: prev.employee_ids.includes(id) ? prev.employee_ids.filter((x) => x !== id) : [...prev.employee_ids, id],
    }))
  }

  const selectAll = () => setForm((prev) => ({ ...prev, employee_ids: activeEmployees.map((e) => e.id) }))
  const clearAll = () => setForm((prev) => ({ ...prev, employee_ids: [] }))

  return (
    <div className={styles.section} style={{ padding: 0, overflow: 'hidden', marginBottom: 20 }}>
      <div style={{ padding: '12px 20px', background: '#fdf8fc', borderBottom: '1px solid #dee2e6' }}>
        <h3 style={{ margin: 0, fontSize: 15, color: '#714B67' }}>Saisie de présences</h3>
      </div>
      <form
        className={styles.formPanel}
        style={{ border: 'none', marginBottom: 0 }}
        onSubmit={async (e) => {
          e.preventDefault()
          await batchCreateAttendance(form)
          await onSaved()
        }}
      >
        <div style={{ display: 'grid', gap: 15 }}>
          <div style={{ display: 'flex', gap: 10 }}>
            <input type="date" value={form.date} onChange={(e) => setForm((p) => ({ ...p, date: e.target.value }))} />
            <select value={form.statut} onChange={(e) => setForm((p) => ({ ...p, statut: e.target.value as AttendanceStatut }))}>
              <option value="present">Présent</option>
              <option value="absent">Absent</option>
              <option value="demi_journee">Demi-journée</option>
              <option value="conge">Congé</option>
              <option value="teletravail">Télétravail</option>
            </select>
          </div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
            <button type="button" className={styles.secondaryButton} style={{ fontSize: 12, padding: '4px 10px' }} onClick={selectAll}>Tous</button>
            <button type="button" className={styles.secondaryButton} style={{ fontSize: 12, padding: '4px 10px' }} onClick={clearAll}>Aucun</button>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, maxHeight: 150, overflowY: 'auto' }}>
            {activeEmployees.map((emp) => (
              <label key={emp.id} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 13, cursor: 'pointer', padding: '4px 8px', borderRadius: 4, background: form.employee_ids.includes(emp.id) ? '#fdf8fc' : '#f8f9fa', border: `1px solid ${form.employee_ids.includes(emp.id) ? '#714B67' : '#dee2e6'}` }}>
                <input type="checkbox" checked={form.employee_ids.includes(emp.id)} onChange={() => toggleEmp(emp.id)} style={{ accentColor: '#714B67' }} />
                {emp.nom} {emp.prenom || ''}
              </label>
            ))}
          </div>
        </div>
        <div style={{ gridColumn: '1/-1', display: 'flex', justifyContent: 'flex-end', marginTop: 10 }}>
          <button className={styles.primaryButton} disabled={form.employee_ids.length === 0}>
            Enregistrer ({form.employee_ids.length} agent{form.employee_ids.length !== 1 ? 's' : ''})
          </button>
        </div>
      </form>
    </div>
  )
}

// ─── Payroll View ─────────────────────────────────────────────────────────────

const MONTH_LABELS_SHORT = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Jun', 'Jul', 'Aoû', 'Sep', 'Oct', 'Nov', 'Déc']

function PayrollView({ entries, employeeById, onChanged }: { entries: HRPayrollEntry[]; employeeById: Map<number, HREmployee>; onChanged: () => Promise<void> }) {
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [slips, setSlips] = useState<HRSalarySlip[]>([])
  const [loadingSlips, setLoadingSlips] = useState(false)

  const expandEntry = async (entry: HRPayrollEntry) => {
    if (expandedId === entry.id) { setExpandedId(null); return }
    setExpandedId(entry.id)
    setLoadingSlips(true)
    try {
      const data = await getPayrollSlips(entry.id)
      setSlips(data)
    } finally {
      setLoadingSlips(false)
    }
  }

  return (
    <div className={styles.tableWrap}>
      <table>
        <thead>
          <tr>
            <th>Période</th>
            <th>Bulletins</th>
            <th>Statut</th>
            <th>Note</th>
            <th style={{ textAlign: 'right' }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <Fragment key={entry.id}>
              <tr style={{ cursor: 'pointer' }} onClick={() => void expandEntry(entry)}>
                <td style={{ fontWeight: 700 }}>
                  {MONTH_LABELS_SHORT[entry.mois - 1]} {entry.annee}
                </td>
                <td>{entry.nb_bulletins} bulletin{entry.nb_bulletins !== 1 ? 's' : ''}</td>
                <td><span className={`${styles.badge} ${styles[entry.statut] || ''}`}>{entry.statut}</span></td>
                <td style={{ color: '#888', fontSize: 13 }}>{entry.note || '—'}</td>
                <td className={styles.actions} style={{ justifyContent: 'flex-end' }}>
                  {entry.statut === 'brouillon' && (
                    <>
                      <button
                        className={styles.secondaryButton}
                        style={{ fontSize: 12, padding: '4px 10px' }}
                        onClick={async (e) => { e.stopPropagation(); await generateSalarySlips(entry.id); await onChanged() }}
                      >
                        Générer bulletins
                      </button>
                      <button
                        className={styles.primaryButton}
                        style={{ fontSize: 12, padding: '4px 10px', background: '#059669', borderColor: '#059669' }}
                        onClick={async (e) => { e.stopPropagation(); if (confirm('Valider ce run de paie ?')) { await validatePayrollEntry(entry.id); await onChanged() } }}
                      >
                        Valider
                      </button>
                    </>
                  )}
                  <button className={styles.iconButton} onClick={(e) => { e.stopPropagation(); void expandEntry(entry) }}>
                    <ChevronRight size={16} style={{ transform: expandedId === entry.id ? 'rotate(90deg)' : undefined, transition: 'transform 0.2s' }} />
                  </button>
                </td>
              </tr>
              {expandedId === entry.id && (
                <tr>
                  <td colSpan={5} style={{ padding: 0, background: '#fafafa' }}>
                    {loadingSlips ? (
                      <div style={{ padding: 20, textAlign: 'center', color: '#888' }}><RotateCw size={16} className={styles.spinning} /> Chargement...</div>
                    ) : slips.length === 0 ? (
                      <div style={{ padding: 20, textAlign: 'center', color: '#999' }}>Aucun bulletin. Cliquez sur "Générer bulletins" d'abord.</div>
                    ) : (
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                        <thead>
                          <tr style={{ background: '#f0f0f0' }}>
                            <th style={{ padding: '6px 12px', textAlign: 'left' }}>Agent</th>
                            <th style={{ padding: '6px 12px', textAlign: 'right' }}>Salaire base</th>
                            <th style={{ padding: '6px 12px', textAlign: 'right' }}>Primes</th>
                            <th style={{ padding: '6px 12px', textAlign: 'right' }}>Retenues</th>
                            <th style={{ padding: '6px 12px', textAlign: 'right', fontWeight: 700 }}>Net à payer</th>
                            <th style={{ padding: '6px 12px' }}>Devise</th>
                            <th style={{ padding: '6px 12px' }}>Statut</th>
                          </tr>
                        </thead>
                        <tbody>
                          {slips.map((slip) => (
                            <tr key={slip.id} style={{ borderBottom: '1px solid #eee' }}>
                              <td style={{ padding: '6px 12px', fontWeight: 600 }}>{fullName(employeeById.get(slip.employee_id))}</td>
                              <td style={{ padding: '6px 12px', textAlign: 'right' }}>{slip.salaire_base}</td>
                              <td style={{ padding: '6px 12px', textAlign: 'right', color: '#059669' }}>+{slip.total_primes}</td>
                              <td style={{ padding: '6px 12px', textAlign: 'right', color: '#dc2626' }}>-{slip.total_retenues}</td>
                              <td style={{ padding: '6px 12px', textAlign: 'right', fontWeight: 700, color: '#714B67' }}>{slip.net_a_payer}</td>
                              <td style={{ padding: '6px 12px' }}>{slip.devise}</td>
                              <td style={{ padding: '6px 12px' }}><span className={`${styles.badge} ${styles[slip.statut] || ''}`}>{slip.statut}</span></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
          {entries.length === 0 && (
            <tr><td colSpan={5} style={{ textAlign: 'center', padding: 40, color: '#999' }}>Aucun run de paie. Créez-en un avec le bouton ci-dessus.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function PayrollEntryForm({ onSaved }: { onSaved: () => Promise<void> }) {
  const now = new Date()
  const [form, setForm] = useState({ mois: now.getMonth() + 1, annee: now.getFullYear(), note: '' })
  return (
    <SimpleForm title="Nouveau run de paie" onSubmit={async () => {
      await createPayrollEntry(form)
      await onSaved()
    }}>
      <div style={{ display: 'grid', gap: 15 }}>
        <div style={{ display: 'flex', gap: 10 }}>
          <select value={form.mois} onChange={(e) => setForm((p) => ({ ...p, mois: Number(e.target.value) }))}>
            {MONTH_LABELS_SHORT.map((m, i) => <option key={i + 1} value={i + 1}>{m}</option>)}
          </select>
          <input type="number" value={form.annee} min={2020} max={2099} onChange={(e) => setForm((p) => ({ ...p, annee: Number(e.target.value) }))} style={{ width: 100 }} />
        </div>
        <textarea placeholder="Note (optionnelle)" value={form.note} style={{ minHeight: 60 }} onChange={(e) => setForm((p) => ({ ...p, note: e.target.value }))} />
      </div>
      <div />
    </SimpleForm>
  )
}

// ─── Salary Slips View ────────────────────────────────────────────────────────

const MONTH_LABELS_LONG = ['Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre']

function SalarySlipsView({ slips, employeeById, payrollEntries }: { slips: HRSalarySlip[]; employeeById: Map<number, HREmployee>; payrollEntries: HRPayrollEntry[] }) {
  const entryById = useMemo(() => new Map(payrollEntries.map((e) => [e.id, e])), [payrollEntries])

  return (
    <div className={styles.tableWrap}>
      <table>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Période</th>
            <th style={{ textAlign: 'right' }}>Salaire base</th>
            <th style={{ textAlign: 'right' }}>Primes</th>
            <th style={{ textAlign: 'right' }}>Retenues</th>
            <th style={{ textAlign: 'right', fontWeight: 700 }}>Net à payer</th>
            <th>Devise</th>
            <th>Statut</th>
            <th>PDF</th>
          </tr>
        </thead>
        <tbody>
          {slips.map((slip) => {
            const entry = entryById.get(slip.payroll_entry_id)
            const periode = entry
              ? `${MONTH_LABELS_LONG[entry.mois - 1]} ${entry.annee}`
              : new Date(slip.created_at).toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' })
            return (
            <tr key={slip.id}>
              <td style={{ fontWeight: 600 }}>{fullName(employeeById.get(slip.employee_id))}</td>
              <td style={{ color: '#888', fontSize: 13 }}>
                {periode}
              </td>
              <td style={{ textAlign: 'right' }}>{slip.salaire_base}</td>
              <td style={{ textAlign: 'right', color: '#059669' }}>+{slip.total_primes}</td>
              <td style={{ textAlign: 'right', color: '#dc2626' }}>-{slip.total_retenues}</td>
              <td style={{ textAlign: 'right', fontWeight: 700, color: '#714B67' }}>{slip.net_a_payer}</td>
              <td>{slip.devise}</td>
              <td><span className={`${styles.badge} ${styles[slip.statut] || ''}`}>{slip.statut}</span></td>
              <td>
                {slip.pdf_url ? (
                  <a href={slip.pdf_url} target="_blank" rel="noopener noreferrer" className={styles.quickAction}><Eye size={14} /></a>
                ) : <span style={{ color: '#ccc' }}>—</span>}
              </td>
            </tr>
            )
          })}
          {slips.length === 0 && (
            <tr><td colSpan={9} style={{ textAlign: 'center', padding: 40, color: '#999' }}>Aucun bulletin de paie</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ─── Evaluations View ─────────────────────────────────────────────────────────

const APPRECIATION_COLORS: Record<string, string> = {
  'Excellent': '#059669',
  'Très bien': '#2563eb',
  'Bien': '#7c3aed',
  'Satisfaisant': '#d97706',
  'Insuffisant': '#dc2626',
}

function EvaluationsView({
  evaluations,
  employeeById,
  onChanged,
}: {
  evaluations: HREvaluation[]
  employeeById: Map<number, HREmployee>
  onChanged: () => void
}) {
  const { showNotification } = useNotification()

  const handleDelete = async (id: number) => {
    if (!confirm('Supprimer cette évaluation ?')) return
    try {
      await deleteHREvaluation(id)
      showNotification('success', 'Succès', 'Évaluation supprimée')
      onChanged()
    } catch {
      showNotification('error', 'Erreur', 'Erreur lors de la suppression')
    }
  }

  const handleToggleStatut = async (ev: HREvaluation) => {
    const next = ev.statut === 'brouillon' ? 'finalisé' : 'brouillon'
    try {
      await updateHREvaluation(ev.id, { statut: next })
      showNotification('success', 'Statut mis à jour', next)
      onChanged()
    } catch {
      showNotification('error', 'Erreur', 'Erreur lors de la mise à jour')
    }
  }

  return (
    <div className={styles.tableWrapper}>
      <table className={styles.dataTable}>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Année</th>
            <th>Période</th>
            <th style={{ textAlign: 'right' }}>Note /20</th>
            <th>Appréciation</th>
            <th>Statut</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {evaluations.map((ev) => (
            <tr key={ev.id}>
              <td style={{ fontWeight: 600 }}>{fullName(employeeById.get(ev.employee_id))}</td>
              <td>{ev.annee}</td>
              <td style={{ textTransform: 'capitalize' }}>{ev.periode}</td>
              <td style={{ textAlign: 'right', fontWeight: 700, color: '#714B67' }}>
                {ev.note_globale ? parseFloat(ev.note_globale).toFixed(2) : '—'}
              </td>
              <td>
                {ev.appreciation ? (
                  <span style={{
                    display: 'inline-block', padding: '2px 10px', borderRadius: 12, fontSize: 12,
                    background: APPRECIATION_COLORS[ev.appreciation] ? `${APPRECIATION_COLORS[ev.appreciation]}18` : '#f3f4f6',
                    color: APPRECIATION_COLORS[ev.appreciation] || '#555', fontWeight: 600,
                  }}>
                    {ev.appreciation}
                  </span>
                ) : '—'}
              </td>
              <td><span className={`${styles.badge} ${styles[ev.statut] || ''}`}>{ev.statut}</span></td>
              <td>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className={styles.quickAction} title={ev.statut === 'brouillon' ? 'Finaliser' : 'Repasser en brouillon'} onClick={() => handleToggleStatut(ev)}>
                    <Check size={14} />
                  </button>
                  <button className={styles.quickAction} title="Supprimer" onClick={() => handleDelete(ev.id)} style={{ color: '#dc2626' }}>
                    <X size={14} />
                  </button>
                </div>
              </td>
            </tr>
          ))}
          {evaluations.length === 0 && (
            <tr><td colSpan={7} style={{ textAlign: 'center', padding: 40, color: '#999' }}>Aucune évaluation enregistrée</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function EvaluationForm({
  employees,
  onSaved,
}: {
  employees: HREmployee[]
  onSaved: () => void
}) {
  const now = new Date()
  const [form, setForm] = useState({
    employee_id: employees[0]?.id || 0,
    annee: now.getFullYear(),
    periode: 'annuelle',
    note_globale: '',
    appreciation: '',
    objectifs_atteints: '',
    axes_amelioration: '',
    commentaire: '',
    statut: 'brouillon',
  })

  return (
    <SimpleForm
      title="Nouvelle évaluation"
      onSubmit={async () => {
        await createHREvaluation({
          ...form,
          note_globale: form.note_globale ? (form.note_globale as unknown as number) : undefined,
        } as Partial<HREvaluation>)
        await onSaved()
      }}
    >
      <div style={{ display: 'grid', gap: 14 }}>
        <div>
          <label className={styles.formLabel}>Agent *</label>
          <select value={form.employee_id} onChange={(e) => setForm((p) => ({ ...p, employee_id: Number(e.target.value) }))}>
            {employees.map((e) => <option key={e.id} value={e.id}>{fullName(e)}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <div style={{ flex: 1 }}>
            <label className={styles.formLabel}>Année *</label>
            <input type="number" value={form.annee} min={2020} max={2099} onChange={(e) => setForm((p) => ({ ...p, annee: Number(e.target.value) }))} />
          </div>
          <div style={{ flex: 1 }}>
            <label className={styles.formLabel}>Période</label>
            <select value={form.periode} onChange={(e) => setForm((p) => ({ ...p, periode: e.target.value }))}>
              <option value="annuelle">Annuelle</option>
              <option value="semestrielle">Semestrielle</option>
              <option value="trimestrielle">Trimestrielle</option>
            </select>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <div style={{ flex: 1 }}>
            <label className={styles.formLabel}>Note /20</label>
            <input type="number" value={form.note_globale} min={0} max={20} step={0.25} placeholder="ex: 16.5" onChange={(e) => setForm((p) => ({ ...p, note_globale: e.target.value }))} />
          </div>
          <div style={{ flex: 1 }}>
            <label className={styles.formLabel}>Appréciation</label>
            <select value={form.appreciation} onChange={(e) => setForm((p) => ({ ...p, appreciation: e.target.value }))}>
              <option value="">— Sélectionner —</option>
              <option>Excellent</option>
              <option>Très bien</option>
              <option>Bien</option>
              <option>Satisfaisant</option>
              <option>Insuffisant</option>
            </select>
          </div>
        </div>
        <div>
          <label className={styles.formLabel}>Objectifs atteints</label>
          <textarea value={form.objectifs_atteints} style={{ minHeight: 60 }} onChange={(e) => setForm((p) => ({ ...p, objectifs_atteints: e.target.value }))} />
        </div>
        <div>
          <label className={styles.formLabel}>Axes d'amélioration</label>
          <textarea value={form.axes_amelioration} style={{ minHeight: 60 }} onChange={(e) => setForm((p) => ({ ...p, axes_amelioration: e.target.value }))} />
        </div>
        <div>
          <label className={styles.formLabel}>Commentaire</label>
          <textarea value={form.commentaire} style={{ minHeight: 60 }} onChange={(e) => setForm((p) => ({ ...p, commentaire: e.target.value }))} />
        </div>
        <div>
          <label className={styles.formLabel}>Statut</label>
          <select value={form.statut} onChange={(e) => setForm((p) => ({ ...p, statut: e.target.value }))}>
            <option value="brouillon">Brouillon</option>
            <option value="finalisé">Finalisé</option>
          </select>
        </div>
      </div>
      <div />
    </SimpleForm>
  )
}

// ─── Sanctions View ───────────────────────────────────────────────────────────

const SANCTION_COLORS: Record<string, string> = {
  'Avertissement': '#d97706',
  'Blâme': '#7c3aed',
  'Mise à pied': '#dc2626',
  'Rétrogradation': '#dc2626',
  'Licenciement': '#991b1b',
}

function SanctionsView({
  sanctions,
  employeeById,
  onChanged,
}: {
  sanctions: HRSanction[]
  employeeById: Map<number, HREmployee>
  onChanged: () => void
}) {
  const { showNotification } = useNotification()

  const handleDelete = async (id: number) => {
    if (!confirm('Supprimer cette sanction ?')) return
    try {
      await deleteHRSanction(id)
      showNotification('success', 'Succès', 'Sanction supprimée')
      onChanged()
    } catch {
      showNotification('error', 'Erreur', 'Erreur lors de la suppression')
    }
  }

  const handleToggleStatut = async (s: HRSanction) => {
    const next = s.statut === 'actif' ? 'levé' : 'actif'
    try {
      await updateHRSanction(s.id, { statut: next })
      showNotification('success', 'Statut mis à jour', next)
      onChanged()
    } catch {
      showNotification('error', 'Erreur', 'Erreur lors de la mise à jour')
    }
  }

  return (
    <div className={styles.tableWrapper}>
      <table className={styles.dataTable}>
        <thead>
          <tr>
            <th>Agent</th>
            <th>Type</th>
            <th>Date</th>
            <th>Motif</th>
            <th>Durée (j)</th>
            <th>Statut</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {sanctions.map((s) => (
            <tr key={s.id}>
              <td style={{ fontWeight: 600 }}>{fullName(employeeById.get(s.employee_id))}</td>
              <td>
                <span style={{
                  display: 'inline-block', padding: '2px 10px', borderRadius: 12, fontSize: 12,
                  background: SANCTION_COLORS[s.type_sanction] ? `${SANCTION_COLORS[s.type_sanction]}18` : '#fee2e2',
                  color: SANCTION_COLORS[s.type_sanction] || '#dc2626', fontWeight: 600,
                }}>
                  {s.type_sanction}
                </span>
              </td>
              <td>{new Date(s.date_sanction).toLocaleDateString('fr-FR')}</td>
              <td style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.motif}</td>
              <td style={{ textAlign: 'center' }}>{s.duree_jours ?? '—'}</td>
              <td><span className={`${styles.badge} ${styles[s.statut] || ''}`}>{s.statut}</span></td>
              <td>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className={styles.quickAction} title={s.statut === 'actif' ? 'Lever la sanction' : 'Réactiver'} onClick={() => handleToggleStatut(s)}>
                    <Check size={14} />
                  </button>
                  <button className={styles.quickAction} title="Supprimer" onClick={() => handleDelete(s.id)} style={{ color: '#dc2626' }}>
                    <X size={14} />
                  </button>
                </div>
              </td>
            </tr>
          ))}
          {sanctions.length === 0 && (
            <tr><td colSpan={7} style={{ textAlign: 'center', padding: 40, color: '#999' }}>Aucune sanction enregistrée</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function SanctionForm({
  employees,
  onSaved,
}: {
  employees: HREmployee[]
  onSaved: () => void
}) {
  const today = new Date().toISOString().split('T')[0]
  const [form, setForm] = useState({
    employee_id: employees[0]?.id || 0,
    type_sanction: 'Avertissement',
    date_sanction: today,
    motif: '',
    description: '',
    duree_jours: '',
    statut: 'actif',
  })

  return (
    <SimpleForm
      title="Enregistrer une sanction"
      onSubmit={async () => {
        await createHRSanction({
          ...form,
          duree_jours: form.duree_jours ? Number(form.duree_jours) : undefined,
        } as Partial<HRSanction>)
        await onSaved()
      }}
    >
      <div style={{ display: 'grid', gap: 14 }}>
        <div>
          <label className={styles.formLabel}>Agent *</label>
          <select value={form.employee_id} onChange={(e) => setForm((p) => ({ ...p, employee_id: Number(e.target.value) }))}>
            {employees.map((e) => <option key={e.id} value={e.id}>{fullName(e)}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <div style={{ flex: 1 }}>
            <label className={styles.formLabel}>Type de sanction *</label>
            <select value={form.type_sanction} onChange={(e) => setForm((p) => ({ ...p, type_sanction: e.target.value }))}>
              <option>Avertissement</option>
              <option>Blâme</option>
              <option>Mise à pied</option>
              <option>Rétrogradation</option>
              <option>Licenciement</option>
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <label className={styles.formLabel}>Date de la sanction *</label>
            <input type="date" value={form.date_sanction} onChange={(e) => setForm((p) => ({ ...p, date_sanction: e.target.value }))} />
          </div>
        </div>
        <div>
          <label className={styles.formLabel}>Motif *</label>
          <input type="text" value={form.motif} placeholder="Motif de la sanction" onChange={(e) => setForm((p) => ({ ...p, motif: e.target.value }))} />
        </div>
        <div>
          <label className={styles.formLabel}>Description</label>
          <textarea value={form.description} style={{ minHeight: 60 }} onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))} />
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <div style={{ flex: 1 }}>
            <label className={styles.formLabel}>Durée (jours, si applicable)</label>
            <input type="number" value={form.duree_jours} min={1} placeholder="ex: 3" onChange={(e) => setForm((p) => ({ ...p, duree_jours: e.target.value }))} />
          </div>
          <div style={{ flex: 1 }}>
            <label className={styles.formLabel}>Statut</label>
            <select value={form.statut} onChange={(e) => setForm((p) => ({ ...p, statut: e.target.value }))}>
              <option value="actif">Actif</option>
              <option value="levé">Levé</option>
            </select>
          </div>
        </div>
      </div>
      <div />
    </SimpleForm>
  )
}

// ─── Rapports View ────────────────────────────────────────────────────────────

function RapportsView({ report }: { report: HRReport | null }) {
  if (!report) {
    return (
      <div className={styles.emptyState}>
        <Grid3X3 size={32} style={{ opacity: 0.3, marginBottom: 12 }} />
        <p>Chargement des rapports...</p>
      </div>
    )
  }

  const maxEffectif = Math.max(...report.effectifs_par_service.map((s) => s.total), 1)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 28, padding: '0 0 32px' }}>

      {/* Effectifs par service */}
      <div className={styles.card} style={{ padding: 24 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: '#714B67' }}>Effectifs par service</h3>
        {report.effectifs_par_service.length === 0 ? (
          <p style={{ color: '#999', fontSize: 13 }}>Aucune donnée</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {report.effectifs_par_service.map((svc) => (
              <div key={svc.service}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 13 }}>
                  <span style={{ fontWeight: 600 }}>{svc.service}</span>
                  <span style={{ color: '#888' }}>{svc.actifs} actifs · {svc.en_conge} en congé · {svc.total} total</span>
                </div>
                <div style={{ height: 8, background: '#f3f4f6', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${(svc.total / maxEffectif) * 100}%`, background: '#714B67', borderRadius: 4 }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Présences mensuelles */}
      <div className={styles.card} style={{ padding: 24 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: '#714B67' }}>Présences mensuelles</h3>
        {report.presences.length === 0 ? (
          <p style={{ color: '#999', fontSize: 13 }}>Aucune donnée de présence</p>
        ) : (
          <div className={styles.tableWrapper} style={{ margin: 0 }}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th>Mois</th>
                  <th style={{ textAlign: 'right' }}>Présents</th>
                  <th style={{ textAlign: 'right' }}>Absents</th>
                  <th style={{ textAlign: 'right' }}>½ Journées</th>
                  <th style={{ textAlign: 'right' }}>Congés</th>
                  <th style={{ textAlign: 'right' }}>Taux présence</th>
                </tr>
              </thead>
              <tbody>
                {report.presences.map((p) => (
                  <tr key={`${p.annee}-${p.mois}`}>
                    <td>{MONTH_LABELS_LONG[p.mois - 1]} {p.annee}</td>
                    <td style={{ textAlign: 'right', color: '#059669', fontWeight: 600 }}>{p.presents}</td>
                    <td style={{ textAlign: 'right', color: '#dc2626' }}>{p.absents}</td>
                    <td style={{ textAlign: 'right', color: '#d97706' }}>{p.demi_journees}</td>
                    <td style={{ textAlign: 'right', color: '#2563eb' }}>{p.conges}</td>
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>
                      {p.taux_presence != null ? `${p.taux_presence.toFixed(1)}%` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Masse salariale */}
      <div className={styles.card} style={{ padding: 24 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: '#714B67' }}>Masse salariale</h3>
        {report.masse_salariale.length === 0 ? (
          <p style={{ color: '#999', fontSize: 13 }}>Aucun bulletin validé</p>
        ) : (
          <div className={styles.tableWrapper} style={{ margin: 0 }}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th>Mois</th>
                  <th style={{ textAlign: 'right' }}>Nb Bulletins</th>
                  <th style={{ textAlign: 'right' }}>Total net</th>
                  <th>Devise</th>
                </tr>
              </thead>
              <tbody>
                {report.masse_salariale.map((m) => (
                  <tr key={`${m.annee}-${m.mois}`}>
                    <td>{MONTH_LABELS_LONG[m.mois - 1]} {m.annee}</td>
                    <td style={{ textAlign: 'right' }}>{m.nb_bulletins}</td>
                    <td style={{ textAlign: 'right', fontWeight: 700, color: '#714B67' }}>
                      {parseFloat(m.total_net).toLocaleString('fr-FR', { minimumFractionDigits: 2 })}
                    </td>
                    <td>{m.devise}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Congés par type */}
      <div className={styles.card} style={{ padding: 24 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: '#714B67' }}>Congés par type</h3>
        {report.conges_par_type.length === 0 ? (
          <p style={{ color: '#999', fontSize: 13 }}>Aucune demande de congé</p>
        ) : (
          <div className={styles.tableWrapper} style={{ margin: 0 }}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th>Type</th>
                  <th style={{ textAlign: 'right' }}>Demandes</th>
                  <th style={{ textAlign: 'right' }}>Approuvées</th>
                  <th style={{ textAlign: 'right' }}>En attente</th>
                  <th style={{ textAlign: 'right' }}>Total jours</th>
                </tr>
              </thead>
              <tbody>
                {report.conges_par_type.map((c) => (
                  <tr key={c.type_absence}>
                    <td style={{ fontWeight: 600 }}>{c.type_absence}</td>
                    <td style={{ textAlign: 'right' }}>{c.total_demandes}</td>
                    <td style={{ textAlign: 'right', color: '#059669', fontWeight: 600 }}>{c.approuves}</td>
                    <td style={{ textAlign: 'right', color: '#d97706' }}>{c.en_attente}</td>
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>{parseFloat(c.total_jours).toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
