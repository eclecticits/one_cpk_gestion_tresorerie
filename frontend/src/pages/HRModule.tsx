import { FormEvent, Fragment, ReactNode, useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import type { WorkBook } from 'xlsx'
import {
  AlertTriangle,
  BriefcaseBusiness,
  Calendar,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
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
  createAttendancePunch,
  createAttendanceAgentEnrollment,
  createTestDeviceCommand,
  createProbeDeviceCommand,
  downloadAttendanceAgentPackage,
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
  getAttendanceMonthly,
  getAttendanceDeviceStatus,
  getAttendanceAgentReleases,
  getAttendancePunches,
  getHRContracts,
  getHRDashboard,
  getHRDocuments,
  getHREmployees,
  getHRFunctions,
  getHREvaluations,
  getHRLeaves,
  getHRPayrollSettings,
  getHRReferences,
  getHRReport,
  getHRSanctions,
  getHRServices,
  getLeaveBalance,
  getPayrollEntries,
  getPayrollSlips,
  getSalarySlips,
  rejectHRLeave,
  reinstallAttendanceAgent,
  revokeAttendanceAgent,
  submitHRLeave,
  updateHREmployee,
  updateHREvaluation,
  updateHRFunction,
  updateHRPayrollSettings,
  updateHRReference,
  updateHRSanction,
  updateHRService,
  validatePayrollEntry,
  type AttendanceStatut,
  type HRAttendanceDaySummary,
  type HRAttendanceMonthly,
  type HRAttendanceDeviceStatus,
  type HRAttendanceAgentEnrollment,
  type HRAttendanceAgentRelease,
  type HRAttendancePunchJournal,
  type HRContract,
  type HRDashboard,
  type HRDocument,
  type HREmployee,
  type HREvaluation,
  type HRFunction,
  type HRIprBracket,
  type HRLeave,
  type HRLeaveBalance,
  type HRPayrollEntry,
  type HRPayrollSettings,
  type HRReference,
  type HRReport,
  type HRSalarySlip,
  type HRSanction,
  type HRService,
} from '../api/hr'
import { usePermissions } from '../hooks/usePermissions'
import { useNotification } from '../contexts/NotificationContext'
import { useConfirm } from '../contexts/ConfirmContext'
import styles from './HRModule.module.css'

// xlsx / jspdf / jspdf-autotable sont lourds : on les charge dynamiquement au
// moment de l'export, pas au chargement du module HR.
type PdfGeneratorBulletinModule = typeof import('../utils/pdfGeneratorBulletin')
let _pdfGeneratorBulletinModulePromise: Promise<PdfGeneratorBulletinModule> | null = null
function loadPdfGeneratorBulletinModule(): Promise<PdfGeneratorBulletinModule> {
  if (!_pdfGeneratorBulletinModulePromise) _pdfGeneratorBulletinModulePromise = import('../utils/pdfGeneratorBulletin')
  return _pdfGeneratorBulletinModulePromise
}
const generateBulletinPaiePDF: PdfGeneratorBulletinModule['generateBulletinPaiePDF'] = async (...args) => {
  const mod = await loadPdfGeneratorBulletinModule()
  return mod.generateBulletinPaiePDF(...args)
}

type HRView = 'dashboard' | 'employees' | 'contracts' | 'leaves' | 'documents' | 'settings' | 'presences' | 'pointages' | 'pointeuses' | 'paie' | 'bulletins' | 'evaluations' | 'sanctions' | 'rapports' | 'placeholder'

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
  ['var(--odoo-primary)', '#fff'],
  ['var(--odoo-secondary)', '#fff'],
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
  if (pathname.includes('/pointages')) return 'pointages'
  if (pathname.includes('/pointeuses')) return 'pointeuses'
  if (pathname.includes('/presences')) return 'presences'
  if (pathname.includes('/bulletins')) return 'bulletins'
  if (pathname.includes('/paie')) return 'paie'
  if (pathname.includes('/evaluations')) return 'evaluations'
  if (pathname.includes('/sanctions')) return 'sanctions'
  if (pathname.includes('/rapports')) return 'rapports'
  return 'placeholder'
}

function labelFromPath(pathname: string): string {
  if (pathname.includes('/pointages')) return 'Journal des pointages'
  if (pathname.includes('/pointeuses')) return 'Pointeuses'
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
  const [attendanceMonthly, setAttendanceMonthly] = useState<HRAttendanceMonthly | null>(null)
  const [attendanceMonth, setAttendanceMonth] = useState(() => {
    const now = new Date()
    return { mois: now.getMonth() + 1, annee: now.getFullYear() }
  })
  const [punchJournal, setPunchJournal] = useState<HRAttendancePunchJournal | null>(null)
  const [attendanceDevices, setAttendanceDevices] = useState<HRAttendanceDeviceStatus[]>([])
  const [payrollEntries, setPayrollEntries] = useState<HRPayrollEntry[]>([])
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
        const [empRows, monthly] = await Promise.all([
          getHREmployees(),
          getAttendanceMonthly(attendanceMonth),
        ])
        setEmployees(empRows)
        setAttendanceMonthly(monthly)
        return
      }
      if (view === 'pointages') {
        const today = new Date().toISOString().split('T')[0]
        const [empRows, servicesRows, journal] = await Promise.all([
          getHREmployees(),
          getHRServices(),
          getAttendancePunches({ date_from: today, date_to: today, limit: 25, offset: 0 }),
        ])
        setEmployees(empRows)
        setServices(servicesRows)
        setPunchJournal(journal)
        return
      }
      if (view === 'pointeuses') {
        setAttendanceDevices(await getAttendanceDeviceStatus())
        return
      }
      if (view === 'paie') {
        const now = new Date()
        const entries = await getPayrollEntries({ annee: now.getFullYear() })
        setPayrollEntries(entries)
        return
      }
      if (view === 'bulletins') {
        const empRows = await getHREmployees()
        setEmployees(empRows)
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

  useEffect(() => { void load() }, [view, attendanceMonth.mois, attendanceMonth.annee])

  const titles: Record<HRView, { title: string; action: string; icon: ReactNode }> = {
    dashboard: { title: "Vue d'ensemble", action: '', icon: <UsersRound size={20} /> },
    employees: { title: 'Employés', action: 'Créer un employé', icon: <UserRound size={20} /> },
    contracts: { title: 'Contrats', action: 'Créer un contrat', icon: <BriefcaseBusiness size={20} /> },
    leaves: { title: 'Congés', action: 'Créer une demande', icon: <FileText size={20} /> },
    documents: { title: 'Documents', action: 'Ajouter un document', icon: <FolderOpen size={20} /> },
    settings: { title: 'Configuration RH', action: '', icon: <Settings2 size={20} /> },
    presences: { title: 'Présences', action: 'Saisir présences', icon: <CalendarDays size={20} /> },
    pointages: { title: 'Journal des pointages', action: '', icon: <Clock size={20} /> },
    pointeuses: { title: 'Pointeuses', action: '', icon: <Clock size={20} /> },
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
            <AttendanceView
              monthly={attendanceMonthly}
              employees={employees}
              currentMonth={attendanceMonth}
              onMonthChange={setAttendanceMonth}
            />
          </>
        ) : view === 'pointages' ? (
          <>
            <AttendancePunchJournalView
              employees={employees}
              services={services}
              initialJournal={punchJournal}
              onChanged={load}
            />
          </>
        ) : view === 'pointeuses' ? (
          <AttendanceDevicesView devices={attendanceDevices} onRefresh={load} />
        ) : view === 'paie' ? (
          <>
            {formOpen && (
              <PayrollEntryForm onSaved={async () => { setFormOpen(false); await load() }} />
            )}
            <PayrollView entries={payrollEntries} employeeById={employeeById} onChanged={load} />
          </>
        ) : view === 'bulletins' ? (
          <SalarySlipsView employeeById={employeeById} />
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
      color: 'var(--odoo-primary)',
      bg: 'color-mix(in srgb, var(--odoo-primary) 8%, white)',
    },
    {
      label: 'En congé',
      value: dashboard?.agents_en_conge ?? 0,
      icon: <CalendarDays size={22} />,
      color: 'var(--odoo-secondary)',
      bg: 'color-mix(in srgb, var(--odoo-secondary) 8%, white)',
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
              style={{ cursor: 'pointer', background: selected?.id === e.id ? 'color-mix(in srgb, var(--odoo-primary) 8%, white)' : undefined }}
            >
              <td style={{ fontWeight: 700, fontFamily: 'monospace', color: 'var(--odoo-primary)' }}>{e.matricule}</td>
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
                        <Eye size={14} style={{ color: 'var(--odoo-primary)' }} />
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
                          <div style={{ width: `${pct}%`, height: '100%', background: solde < 0 ? '#dc2626' : 'var(--odoo-primary)', borderRadius: 3, transition: 'width 0.3s' }} />
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
  'congé annuel': 'var(--odoo-primary)',
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
                  const color = LEAVE_COLORS[l.type_absence] || 'var(--odoo-primary)'
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
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: LEAVE_COLORS[item.type_absence] || 'var(--odoo-primary)', flexShrink: 0 }} />
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
                  <td style={{ textAlign: 'right', fontWeight: 600, color: 'var(--odoo-primary)' }}>
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
      <div style={{ padding: '12px 20px', background: 'color-mix(in srgb, var(--odoo-primary) 8%, white)', borderBottom: '1px solid #dee2e6', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0, fontSize: 15, color: 'var(--odoo-primary)' }}>{title}</h3>
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
  const [payrollIsDefault, setPayrollIsDefault] = useState<boolean | null>(null)

  useEffect(() => {
    getHRPayrollSettings().then((s) => setPayrollIsDefault(s.is_default)).catch(() => {})
  }, [])

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
        { key: 'ipr-cnss', title: 'Barème IPR / CNSS', count: 0, icon: <WalletCards size={20} />, actionLabel: '', description: 'Tranches, plancher/plafond IPR et taux CNSS utilisés pour générer les bulletins.' },
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
    return references[activeItem.key] || []
  }, [activeItem, references])

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
      if (editing) {
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
      await updateHRReference(activeItem.key, item.id, { is_active: next })
      showSuccess(next ? 'Élément activé' : 'Élément désactivé', '')
      await onSaved()
    } catch (err) {
      showError('Action impossible', err instanceof Error ? err.message : '')
    }
  }

  if (activeItem?.key === 'ipr-cnss') {
    return (
      <div className={styles.configurationPage}>
        <Link className={styles.secondaryButton} to="/rh/parametres" style={{ textDecoration: 'none', marginBottom: 15, display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 13 }}>
          ← Retour
        </Link>
        <PayrollSettingsPanel />
      </div>
    )
  }

  if (activeItem?.key === 'services') {
    return (
      <div className={styles.configurationPage}>
        <Link className={styles.secondaryButton} to="/rh/parametres" style={{ textDecoration: 'none', marginBottom: 15, display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 13 }}>
          ← Retour
        </Link>
        <ServicesConfigPanel onSaved={onSaved} />
      </div>
    )
  }

  if (activeItem?.key === 'fonctions') {
    return (
      <div className={styles.configurationPage}>
        <Link className={styles.secondaryButton} to="/rh/parametres" style={{ textDecoration: 'none', marginBottom: 15, display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 13 }}>
          ← Retour
        </Link>
        <FunctionsConfigPanel onSaved={onSaved} />
      </div>
    )
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
                    <th>Description</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRows.map((item: any) => (
                    <tr key={item.id}>
                      <td style={{ fontWeight: 600 }}>{item.code}</td>
                      <td>{item.libelle}</td>
                      <td style={{ color: '#666', fontSize: 13 }}>{item.description || '—'}</td>
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
                  <h2 style={{ color: 'var(--odoo-primary)', margin: 0 }}>{editing ? 'Modifier' : 'Créer'} {activeItem.title}</h2>
                  <p style={{ color: '#666', fontSize: 13, margin: '4px 0 0' }}>Configuration spécifique au tenant.</p>
                </div>
                <button className={styles.iconButton} onClick={() => setPanelOpen(false)}><X size={18} /></button>
              </div>
              <form className={styles.sidePanelForm} onSubmit={saveConfig}>
                <label className={styles.formLabel}>
                  Code
                  <input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="Ex: R&D, CDI..." />
                </label>
                <label className={styles.formLabel}>
                  Libellé
                  <input required value={form.libelle} onChange={(e) => setForm({ ...form, libelle: e.target.value })} placeholder="Ex: Recherche et Développement" />
                </label>
                <label className={styles.formLabel}>
                  Description
                  <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Détails supplémentaires..." />
                </label>
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

  const catalogQuery = query.trim().toLowerCase()
  const filteredConfigGroups = catalogQuery
    ? configGroups
        .map((group) => ({
          ...group,
          items: group.items.filter((item) =>
            `${group.group} ${item.title} ${item.description}`.toLowerCase().includes(catalogQuery)
          ),
        }))
        .filter((group) => group.items.length > 0)
    : configGroups

  return (
    <div className={styles.configurationPage}>
      <div className={styles.section} style={{ marginBottom: 25 }}>
        <h2 style={{ color: 'var(--odoo-primary)', border: 'none', marginBottom: 5 }}>Paramètres du module</h2>
        <p style={{ color: '#666', fontSize: 14, margin: 0 }}>Gérez les référentiels et la structure organisationnelle de votre département RH.</p>
      </div>
      <div className={styles.configToolbar} style={{ marginBottom: 20 }}>
        <Search size={16} />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher un paramètre..." />
      </div>
      {filteredConfigGroups.length === 0 ? (
        <div className={styles.emptyState}>Aucun paramètre trouvé.</div>
      ) : (
        <div className={styles.configGroups}>
          {filteredConfigGroups.map((group) => (
            <section className={styles.configGroup} key={group.group}>
              <div className={styles.configGroupTitle}>
                <h3 style={{ color: 'var(--odoo-primary)', fontWeight: 600, margin: 0, fontSize: 15 }}>{group.group}</h3>
              </div>
              <div className={styles.configCards}>
                {group.items.map((item) => (
                  <article className={styles.configCard} key={item.key}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 15 }}>
                      <div style={{ color: 'var(--odoo-primary)', background: 'color-mix(in srgb, var(--odoo-primary) 8%, white)', padding: 10, borderRadius: 4 }}>{item.icon}</div>
                      <div>
                        <h4 style={{ margin: 0, fontSize: 14 }}>{item.title}</h4>
                        {item.key === 'ipr-cnss' ? (
                          payrollIsDefault === null ? (
                            <p style={{ margin: '4px 0 0', fontSize: 12, color: '#666' }}>Configuration</p>
                          ) : (
                            <span className={`${styles.badge} ${payrollIsDefault ? styles.en_conge : styles.actif}`} style={{ marginTop: 4 }}>
                              {payrollIsDefault ? 'Valeurs par défaut' : 'Personnalisé'}
                            </span>
                          )
                        ) : item.count === 0 ? (
                          <span className={`${styles.badge} ${styles.en_conge}`} style={{ marginTop: 4 }}>Non configuré</span>
                        ) : (
                          <p style={{ margin: '4px 0 0', fontSize: 12, color: '#666' }}>{item.count} élément{item.count !== 1 ? 's' : ''}</p>
                        )}
                      </div>
                    </div>
                    <Link className={styles.configureButton} to={`/rh/parametres/${item.key}`}>Configurer</Link>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Payroll settings (IPR / CNSS) ─────────────────────────────────────────────

type BracketRow = { lower: string; upper: string; rate: string }

function PayrollSettingsPanel() {
  const { showSuccess, showError } = useNotification()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [isDefault, setIsDefault] = useState(true)
  const [deviseBareme, setDeviseBareme] = useState('CDF')
  const [iprPlancher, setIprPlancher] = useState('0')
  const [iprPlafondTaux, setIprPlafondTaux] = useState('30')
  const [cnssTaux, setCnssTaux] = useState('5')
  const [brackets, setBrackets] = useState<BracketRow[]>([])

  const load = async () => {
    setLoading(true)
    try {
      const s = await getHRPayrollSettings()
      setIsDefault(s.is_default)
      setDeviseBareme(s.devise_bareme)
      setIprPlancher(s.ipr_plancher)
      setIprPlafondTaux(String(Number(s.ipr_plafond_taux) * 100))
      setCnssTaux(String(Number(s.cnss_taux_salarie) * 100))
      setBrackets(s.ipr_brackets.map((b) => ({
        lower: b.lower,
        upper: b.upper ?? '',
        rate: String(Number(b.rate) * 100),
      })))
    } catch (err) {
      showError('Chargement impossible', err instanceof Error ? err.message : "Impossible de charger les paramètres de paie.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const updateBracket = (index: number, field: keyof BracketRow, value: string) => {
    setBrackets((prev) => prev.map((b, i) => (i === index ? { ...b, [field]: value } : b)))
  }

  const addBracket = () => {
    const last = brackets[brackets.length - 1]
    setBrackets((prev) => [...prev, { lower: last?.upper || '0', upper: '', rate: '0' }])
  }

  const removeBracket = (index: number) => {
    setBrackets((prev) => prev.filter((_, i) => i !== index))
  }

  const save = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      const payload: HRPayrollSettings = {
        devise_bareme: deviseBareme,
        ipr_plancher: iprPlancher,
        ipr_plafond_taux: String(Number(iprPlafondTaux) / 100),
        cnss_taux_salarie: String(Number(cnssTaux) / 100),
        is_default: false,
        ipr_brackets: brackets.map((b, i): HRIprBracket => ({
          lower: b.lower,
          upper: i === brackets.length - 1 ? null : (b.upper || null),
          rate: String(Number(b.rate) / 100),
        })),
      }
      await updateHRPayrollSettings(payload)
      showSuccess('Paramètres enregistrés', 'Le barème IPR/CNSS a été mis à jour pour les prochains bulletins générés.')
      await load()
    } catch (err) {
      showError("Échec de l'enregistrement", err instanceof Error ? err.message : 'Vérifiez que les tranches sont contiguës et sans trou.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className={styles.emptyState}>Chargement...</div>

  return (
    <section className={styles.configDetail}>
      <div className={styles.configDetailHeader}>
        <div>
          <h2>Barème IPR / CNSS</h2>
          <p style={{ color: '#666', fontSize: 14 }}>
            Utilisé par « Générer les bulletins » pour calculer les retenues. Les bulletins déjà générés ne sont pas recalculés.
          </p>
          {isDefault && (
            <p style={{ color: '#d97706', fontSize: 13, marginTop: 6 }}>
              Aucune personnalisation enregistrée — valeurs par défaut (RDC) actuellement utilisées.
            </p>
          )}
        </div>
      </div>

      <form onSubmit={save} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
          <label className={styles.formLabel}>
            Devise du barème
            <input value={deviseBareme} maxLength={3} onChange={(e) => setDeviseBareme(e.target.value.toUpperCase())} style={{ width: 80 }} />
          </label>
          <label className={styles.formLabel}>
            Plancher IPR (montant min./mois, dans la devise du barème)
            <input type="number" step="0.01" value={iprPlancher} onChange={(e) => setIprPlancher(e.target.value)} />
          </label>
          <label className={styles.formLabel}>
            Plafond IPR (% du revenu imposable)
            <input type="number" step="0.01" value={iprPlafondTaux} onChange={(e) => setIprPlafondTaux(e.target.value)} />
          </label>
          <label className={styles.formLabel}>
            Taux CNSS salarié (%)
            <input type="number" step="0.01" value={cnssTaux} onChange={(e) => setCnssTaux(e.target.value)} />
          </label>
        </div>

        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <h4 style={{ margin: 0 }}>Tranches IPR (mensuelles, en {deviseBareme})</h4>
            <button type="button" className={styles.secondaryButton} onClick={addBracket}>+ Ajouter une tranche</button>
          </div>
          <div className={styles.tableWrap}>
            <table>
              <thead>
                <tr>
                  <th>Borne basse</th>
                  <th>Borne haute</th>
                  <th>Taux (%)</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {brackets.map((b, i) => {
                  const isLast = i === brackets.length - 1
                  return (
                    <tr key={i}>
                      <td><input type="number" step="0.01" value={b.lower} onChange={(e) => updateBracket(i, 'lower', e.target.value)} /></td>
                      <td>
                        {isLast ? (
                          <span style={{ color: '#999' }}>Illimité</span>
                        ) : (
                          <input type="number" step="0.01" value={b.upper} onChange={(e) => updateBracket(i, 'upper', e.target.value)} />
                        )}
                      </td>
                      <td><input type="number" step="0.01" value={b.rate} onChange={(e) => updateBracket(i, 'rate', e.target.value)} /></td>
                      <td>
                        {brackets.length > 1 && (
                          <button type="button" className={styles.iconButton} onClick={() => removeBracket(i)}><X size={14} /></button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        <button className={styles.primaryButton} type="submit" disabled={saving} style={{ alignSelf: 'flex-start' }}>
          {saving ? 'Enregistrement...' : 'Enregistrer'}
        </button>
      </form>
    </section>
  )
}

// ─── Services (RH) ──────────────────────────────────────────────────────────

function formatPersonName(person?: { nom: string; post_nom?: string | null; prenom?: string | null } | null): string {
  if (!person) return '—'
  return [person.nom, person.post_nom, person.prenom].filter(Boolean).join(' ')
}

function collectDescendantServiceIds(services: HRService[], rootId: number): Set<number> {
  const byParent = new Map<number, number[]>()
  services.forEach((s) => {
    if (s.parent_id != null) {
      byParent.set(s.parent_id, [...(byParent.get(s.parent_id) || []), s.id])
    }
  })
  const result = new Set<number>()
  const stack = [rootId]
  while (stack.length) {
    const current = stack.pop() as number
    for (const childId of byParent.get(current) || []) {
      if (!result.has(childId)) {
        result.add(childId)
        stack.push(childId)
      }
    }
  }
  return result
}

type ServiceForm = {
  code: string
  libelle: string
  description: string
  responsable_id: string
  parent_id: string
  is_active: boolean
}

const EMPTY_SERVICE_FORM: ServiceForm = { code: '', libelle: '', description: '', responsable_id: '', parent_id: '', is_active: true }

function ServicesConfigPanel({ onSaved }: { onSaved: () => Promise<void> }) {
  const { showSuccess, showError } = useNotification()
  const confirm = useConfirm()
  const [services, setServices] = useState<HRService[]>([])
  const [employees, setEmployees] = useState<HREmployee[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [panelOpen, setPanelOpen] = useState(false)
  const [editing, setEditing] = useState<HRService | null>(null)
  const [form, setForm] = useState<ServiceForm>(EMPTY_SERVICE_FORM)

  const load = async () => {
    setLoading(true)
    try {
      const [svcRows, empRows] = await Promise.all([getHRServices(), getHREmployees()])
      setServices(svcRows)
      setEmployees(empRows)
    } catch (err) {
      showError('Chargement impossible', err instanceof Error ? err.message : 'Impossible de charger les services.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const filteredServices = services.filter((s) =>
    `${s.code} ${s.libelle} ${s.description || ''}`.toLowerCase().includes(query.toLowerCase())
  )

  const excludedParentIds = useMemo(() => {
    if (!editing) return new Set<number>()
    const descendants = collectDescendantServiceIds(services, editing.id)
    descendants.add(editing.id)
    return descendants
  }, [services, editing])

  const parentOptions = services.filter((s) => !excludedParentIds.has(s.id))

  const openPanel = (item?: HRService) => {
    setEditing(item || null)
    setForm({
      code: item?.code || '',
      libelle: item?.libelle || '',
      description: item?.description || '',
      responsable_id: item?.responsable_id != null ? String(item.responsable_id) : '',
      parent_id: item?.parent_id != null ? String(item.parent_id) : '',
      is_active: item?.is_active ?? true,
    })
    setPanelOpen(true)
  }

  const saveConfig = async (e: FormEvent) => {
    e.preventDefault()
    const code = form.code.trim()
    const duplicate = services.some(
      (s) => s.code.trim().toLowerCase() === code.toLowerCase() && s.id !== editing?.id
    )
    if (duplicate) {
      showError('Code déjà utilisé', `Un autre service utilise déjà le code "${code}".`)
      return
    }
    const payload = {
      code,
      libelle: form.libelle.trim(),
      description: form.description.trim() || null,
      responsable_id: form.responsable_id ? Number(form.responsable_id) : null,
      parent_id: form.parent_id ? Number(form.parent_id) : null,
      is_active: form.is_active,
    }
    try {
      if (editing) await updateHRService(editing.id, payload)
      else await createHRService(payload)
      showSuccess('Service enregistré', 'Le service a été mis à jour.')
      setPanelOpen(false)
      await load()
      await onSaved()
    } catch (err) {
      showError("Échec de l'enregistrement", err instanceof Error ? err.message : 'Impossible d’enregistrer ce service.')
    }
  }

  const toggleActive = async (service: HRService) => {
    const next = !service.is_active
    if (!next) {
      const confirmed = await confirm({
        title: 'Désactiver ce service ?',
        description: `${service.code} — ${service.libelle}`,
        confirmText: 'Désactiver',
        variant: 'danger',
      })
      if (!confirmed) return
    }
    try {
      await updateHRService(service.id, { is_active: next })
      showSuccess(next ? 'Service activé' : 'Service désactivé', '')
      await load()
      await onSaved()
    } catch (err) {
      showError('Action impossible', err instanceof Error ? err.message : '')
    }
  }

  if (loading) return <div className={styles.emptyState}>Chargement...</div>

  return (
    <section className={styles.configDetail}>
      <div className={styles.configDetailHeader}>
        <div>
          <h2>Services</h2>
          <p style={{ color: '#666', fontSize: 14 }}>Gérer les services, leur responsable et la hiérarchie organisationnelle.</p>
        </div>
        <button className={styles.primaryButton} onClick={() => openPanel()}>Nouveau service</button>
      </div>
      <div className={styles.configToolbar}>
        <Search size={16} />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher..." />
      </div>
      {filteredServices.length === 0 ? (
        <div className={styles.emptyState}>Aucun service configuré.</div>
      ) : (
        <div className={styles.tableWrap}>
          <table>
            <thead>
              <tr>
                <th>Code</th>
                <th>Libellé</th>
                <th>Responsable</th>
                <th>Parent</th>
                <th>Employés</th>
                <th>Statut</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredServices.map((s) => (
                <tr key={s.id}>
                  <td style={{ fontWeight: 600 }}>{s.code}</td>
                  <td>{s.libelle}</td>
                  <td>{formatPersonName(s.responsable)}</td>
                  <td>{s.parent?.libelle || '—'}</td>
                  <td>{s.employees_count ?? 0}</td>
                  <td><span className={`${styles.badge} ${s.is_active ? styles.actif : styles.suspendu}`}>{s.is_active ? 'Actif' : 'Inactif'}</span></td>
                  <td className={styles.actions}>
                    <button className={styles.secondaryButton} style={{ padding: '4px 8px', fontSize: 12 }} onClick={() => openPanel(s)}>Modifier</button>
                    <button className={styles.secondaryButton} style={{ padding: '4px 8px', fontSize: 12 }} onClick={() => toggleActive(s)}>
                      {s.is_active ? 'Désactiver' : 'Activer'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {panelOpen && (
        <div className={styles.sidePanelOverlay} onClick={() => setPanelOpen(false)}>
          <aside className={styles.sidePanel} onClick={(e) => e.stopPropagation()}>
            <div className={styles.sidePanelHeader}>
              <div>
                <h2 style={{ color: 'var(--odoo-primary)', margin: 0 }}>{editing ? 'Modifier' : 'Créer'} un service</h2>
                <p style={{ color: '#666', fontSize: 13, margin: '4px 0 0' }}>Configuration spécifique au tenant.</p>
              </div>
              <button className={styles.iconButton} onClick={() => setPanelOpen(false)}><X size={18} /></button>
            </div>
            <form className={styles.sidePanelForm} onSubmit={saveConfig}>
              <label className={styles.formLabel}>
                Code
                <input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="Ex: RH, FIN..." />
              </label>
              <label className={styles.formLabel}>
                Libellé
                <input required value={form.libelle} onChange={(e) => setForm({ ...form, libelle: e.target.value })} placeholder="Ex: Ressources Humaines" />
              </label>
              <label className={styles.formLabel}>
                Description
                <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Rôle du service..." />
              </label>
              <label className={styles.formLabel}>
                Responsable
                <select value={form.responsable_id} onChange={(e) => setForm({ ...form, responsable_id: e.target.value })}>
                  <option value="">Aucun</option>
                  {employees.map((e) => (
                    <option key={e.id} value={e.id}>{fullName(e)}</option>
                  ))}
                </select>
              </label>
              <label className={styles.formLabel}>
                Service parent
                <select value={form.parent_id} onChange={(e) => setForm({ ...form, parent_id: e.target.value })}>
                  <option value="">Aucun (service racine)</option>
                  {parentOptions.map((s) => (
                    <option key={s.id} value={s.id}>{s.libelle}</option>
                  ))}
                </select>
              </label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '10px 0' }}>
                <input type="checkbox" id="service_is_active" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
                <label htmlFor="service_is_active" style={{ cursor: 'pointer', fontSize: 14 }}>Actif</label>
              </div>
              <button className={styles.primaryButton} style={{ width: '100%', marginTop: 10 }}>Enregistrer</button>
            </form>
          </aside>
        </div>
      )}
    </section>
  )
}

// ─── Fonctions (RH) ─────────────────────────────────────────────────────────

const NIVEAU_HIERARCHIQUE_OPTIONS = ['Cadre de direction', 'Cadre', 'Agent de maîtrise', 'Employé', 'Ouvrier']

type FunctionForm = {
  code: string
  libelle: string
  description: string
  niveau_hierarchique: string
  is_active: boolean
}

const EMPTY_FUNCTION_FORM: FunctionForm = { code: '', libelle: '', description: '', niveau_hierarchique: '', is_active: true }

function FunctionsConfigPanel({ onSaved }: { onSaved: () => Promise<void> }) {
  const { showSuccess, showError } = useNotification()
  const confirm = useConfirm()
  const [functions, setFunctions] = useState<HRFunction[]>([])
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [panelOpen, setPanelOpen] = useState(false)
  const [editing, setEditing] = useState<HRFunction | null>(null)
  const [form, setForm] = useState<FunctionForm>(EMPTY_FUNCTION_FORM)

  const load = async () => {
    setLoading(true)
    try {
      const rows = await getHRFunctions()
      setFunctions(rows)
    } catch (err) {
      showError('Chargement impossible', err instanceof Error ? err.message : 'Impossible de charger les fonctions.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const filteredFunctions = functions.filter((f) =>
    `${f.code} ${f.libelle} ${f.description || ''}`.toLowerCase().includes(query.toLowerCase())
  )

  const openPanel = (item?: HRFunction) => {
    setEditing(item || null)
    setForm({
      code: item?.code || '',
      libelle: item?.libelle || '',
      description: item?.description || '',
      niveau_hierarchique: item?.niveau_hierarchique || '',
      is_active: item?.is_active ?? true,
    })
    setPanelOpen(true)
  }

  const saveConfig = async (e: FormEvent) => {
    e.preventDefault()
    const code = form.code.trim()
    const libelle = form.libelle.trim()
    const duplicate = functions.some(
      (f) =>
        f.id !== editing?.id &&
        (f.code.trim().toLowerCase() === code.toLowerCase() || f.libelle.trim().toLowerCase() === libelle.toLowerCase())
    )
    if (duplicate) {
      showError('Code ou libellé déjà utilisé', `Une autre fonction utilise déjà ce code ou ce libellé.`)
      return
    }
    const payload = {
      code,
      libelle,
      description: form.description.trim() || null,
      niveau_hierarchique: form.niveau_hierarchique || null,
      is_active: form.is_active,
    }
    try {
      if (editing) await updateHRFunction(editing.id, payload)
      else await createHRFunction(payload)
      showSuccess('Fonction enregistrée', 'La fonction a été mise à jour.')
      setPanelOpen(false)
      await load()
      await onSaved()
    } catch (err) {
      showError("Échec de l'enregistrement", err instanceof Error ? err.message : 'Impossible d’enregistrer cette fonction.')
    }
  }

  const toggleActive = async (fn: HRFunction) => {
    const next = !fn.is_active
    if (!next) {
      const confirmed = await confirm({
        title: 'Désactiver cette fonction ?',
        description: `${fn.code} — ${fn.libelle}`,
        confirmText: 'Désactiver',
        variant: 'danger',
      })
      if (!confirmed) return
    }
    try {
      await updateHRFunction(fn.id, { is_active: next })
      showSuccess(next ? 'Fonction activée' : 'Fonction désactivée', '')
      await load()
      await onSaved()
    } catch (err) {
      showError('Action impossible', err instanceof Error ? err.message : '')
    }
  }

  if (loading) return <div className={styles.emptyState}>Chargement...</div>

  return (
    <section className={styles.configDetail}>
      <div className={styles.configDetailHeader}>
        <div>
          <h2>Fonctions</h2>
          <p style={{ color: '#666', fontSize: 14 }}>Structurer les intitulés de poste et leur niveau hiérarchique.</p>
        </div>
        <button className={styles.primaryButton} onClick={() => openPanel()}>Nouvelle fonction</button>
      </div>
      <div className={styles.configToolbar}>
        <Search size={16} />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher..." />
      </div>
      {filteredFunctions.length === 0 ? (
        <div className={styles.emptyState}>Aucune fonction configurée.</div>
      ) : (
        <div className={styles.tableWrap}>
          <table>
            <thead>
              <tr>
                <th>Code</th>
                <th>Libellé</th>
                <th>Niveau hiérarchique</th>
                <th>Employés</th>
                <th>Statut</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredFunctions.map((f) => (
                <tr key={f.id}>
                  <td style={{ fontWeight: 600 }}>{f.code}</td>
                  <td>{f.libelle}</td>
                  <td>{f.niveau_hierarchique || '—'}</td>
                  <td>{f.employees_count ?? 0}</td>
                  <td><span className={`${styles.badge} ${f.is_active ? styles.actif : styles.suspendu}`}>{f.is_active ? 'Actif' : 'Inactif'}</span></td>
                  <td className={styles.actions}>
                    <button className={styles.secondaryButton} style={{ padding: '4px 8px', fontSize: 12 }} onClick={() => openPanel(f)}>Modifier</button>
                    <button className={styles.secondaryButton} style={{ padding: '4px 8px', fontSize: 12 }} onClick={() => toggleActive(f)}>
                      {f.is_active ? 'Désactiver' : 'Activer'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {panelOpen && (
        <div className={styles.sidePanelOverlay} onClick={() => setPanelOpen(false)}>
          <aside className={styles.sidePanel} onClick={(e) => e.stopPropagation()}>
            <div className={styles.sidePanelHeader}>
              <div>
                <h2 style={{ color: 'var(--odoo-primary)', margin: 0 }}>{editing ? 'Modifier' : 'Créer'} une fonction</h2>
                <p style={{ color: '#666', fontSize: 13, margin: '4px 0 0' }}>Configuration spécifique au tenant.</p>
              </div>
              <button className={styles.iconButton} onClick={() => setPanelOpen(false)}><X size={18} /></button>
            </div>
            <form className={styles.sidePanelForm} onSubmit={saveConfig}>
              <label className={styles.formLabel}>
                Code
                <input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} placeholder="Ex: DEV, RH-MGR..." />
              </label>
              <label className={styles.formLabel}>
                Libellé
                <input required value={form.libelle} onChange={(e) => setForm({ ...form, libelle: e.target.value })} placeholder="Ex: Développeur" />
              </label>
              <label className={styles.formLabel}>
                Description
                <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="Rôle du poste..." />
              </label>
              <label className={styles.formLabel}>
                Niveau hiérarchique
                <select value={form.niveau_hierarchique} onChange={(e) => setForm({ ...form, niveau_hierarchique: e.target.value })}>
                  <option value="">Non défini</option>
                  {NIVEAU_HIERARCHIQUE_OPTIONS.map((n) => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              </label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '10px 0' }}>
                <input type="checkbox" id="function_is_active" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
                <label htmlFor="function_is_active" style={{ cursor: 'pointer', fontSize: 14 }}>Actif</label>
              </div>
              <button className={styles.primaryButton} style={{ width: '100%', marginTop: 10 }}>Enregistrer</button>
            </form>
          </aside>
        </div>
      )}
    </section>
  )
}

// ─── Attendance View ──────────────────────────────────────────────────────────

const ATTENDANCE_COLORS: Record<string, string> = {
  present: '#059669',
  absent: '#dc2626',
  demi_journee: '#d97706',
  conge: '#2563eb',
  teletravail: '#7c3aed',
  non_ouvrable: '#cbd5e1',
}

const ATTENDANCE_LABELS: Record<string, string> = {
  present: 'Présent',
  absent: 'Absent',
  demi_journee: '½ Journée',
  conge: 'Congé',
  teletravail: 'Télétravail',
  non_ouvrable: 'Non ouvrable',
}

function AttendanceView({
  monthly,
  employees,
  currentMonth,
  onMonthChange,
}: {
  monthly: HRAttendanceMonthly | null
  employees: HREmployee[]
  currentMonth: { mois: number; annee: number }
  onMonthChange: (value: { mois: number; annee: number }) => void
}) {
  const [selectedDay, setSelectedDay] = useState<HRAttendanceDaySummary | null>(null)
  const daysInMonth = monthly?.days_in_month || new Date(currentMonth.annee, currentMonth.mois, 0).getDate()
  const days = Array.from({ length: daysInMonth }, (_, i) => i + 1)
  const monthLabel = new Intl.DateTimeFormat('fr-FR', { month: 'long', year: 'numeric' }).format(new Date(currentMonth.annee, currentMonth.mois - 1, 1))
  const today = new Date()
  const activeEmployees = employees.filter((e) => e.statut === 'actif')
  const rowsByEmployee = new Map(monthly?.employees.map((row) => [row.employee_id, row]) || [])

  const moveMonth = (delta: number) => {
    const next = new Date(currentMonth.annee, currentMonth.mois - 1 + delta, 1)
    onMonthChange({ mois: next.getMonth() + 1, annee: next.getFullYear() })
  }

  const goToday = () => onMonthChange({ mois: today.getMonth() + 1, annee: today.getFullYear() })

  const exportExcel = async () => {
    if (!monthly) return
    const XLSX = await import('xlsx')
    const summaryRows = monthly.employees.map((row) => ({
      Matricule: row.employee_matricule || '',
      Employé: row.employee_name,
      Service: row.service_name || '',
      'Jours ouvrables': row.working_days,
      'Jours présents': row.present_days,
      'Jours absents': row.absent_days,
      'Demi-journées': row.half_days,
      Congés: row.leave_days,
      Télétravail: row.remote_days,
      'Nombre de retards': row.late_count,
      'Heures travaillées': minutesToHours(row.worked_minutes),
      'Heures supplémentaires': minutesToHours(row.overtime_minutes),
      Anomalies: row.anomaly_count,
    }))
    const detailRows = monthly.employees.flatMap((row) => row.days.map((day) => ({
      Date: new Date(day.date),
      Matricule: row.employee_matricule || '',
      Employé: row.employee_name,
      Service: row.service_name || '',
      'Première entrée': day.first_in_time || '',
      'Dernière sortie': day.last_out_time || '',
      'Temps travaillé': minutesToHours(day.worked_minutes),
      'Temps de pause': minutesToHours(day.pause_minutes),
      Retard: minutesToHours(day.late_minutes),
      'Heures supplémentaires': minutesToHours(day.overtime_minutes),
      Statut: ATTENDANCE_LABELS[day.status] || day.status,
      Anomalie: day.anomalies.join('; '),
      Source: [...new Set(day.punches.map((p) => p.source))].join(', '),
    })))
    const rawRows = monthly.employees.flatMap((row) => row.days.flatMap((day) => day.punches.map((p) => ({
      Date: new Date(day.date),
      Heure: p.time,
      Matricule: row.employee_matricule || '',
      Employé: row.employee_name,
      "Type événement": p.event_type === 'IN' ? 'Entrée' : 'Sortie',
      Source: p.source,
      Device: p.device_id || '',
      Référence: p.external_reference || '',
    }))))
    const workbook = XLSX.utils.book_new()
    appendSheet(XLSX, workbook, 'Synthèse mensuelle', summaryRows)
    appendSheet(XLSX, workbook, 'Détail journalier', detailRows)
    appendSheet(XLSX, workbook, 'Pointages bruts', rawRows)
    XLSX.writeFile(workbook, `presences_ONEC_${currentMonth.annee}-${String(currentMonth.mois).padStart(2, '0')}.xlsx`)
  }

  return (
    <>
      <div className={styles.leaveSummaryBar} style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button type="button" className={styles.secondaryButton} onClick={() => moveMonth(-1)}><ChevronLeft size={16} /></button>
          <strong style={{ minWidth: 150, textTransform: 'capitalize', textAlign: 'center' }}>{monthLabel}</strong>
          <button type="button" className={styles.secondaryButton} onClick={() => moveMonth(1)}><ChevronRight size={16} /></button>
          <button type="button" className={styles.secondaryButton} onClick={goToday}>Aujourd'hui</button>
        </div>
        <button type="button" className={styles.primaryButton} onClick={exportExcel} disabled={!monthly}>
          <Download size={16} /> Exporter Excel
        </button>
      </div>
      {monthly && (
        <div className={styles.leaveSummaryBar}>
          <span className={styles.leaveStat}><span className={styles.statDot} style={{ background: '#059669' }} />Présents: {monthly.totals.presents || 0}</span>
          <span className={styles.leaveStat}><span className={styles.statDot} style={{ background: '#dc2626' }} />Absents: {monthly.totals.absents || 0}</span>
          <span className={styles.leaveStat}><span className={styles.statDot} style={{ background: '#f59e0b' }} />Retards: {monthly.totals.lates || 0}</span>
          <span className={styles.leaveStat}><span className={styles.statDot} style={{ background: '#2563eb' }} />Congés: {monthly.totals.leaves || 0}</span>
          <span className={styles.leaveStat}><span className={styles.statDot} style={{ background: '#991b1b' }} />Anomalies: {monthly.totals.anomalies || 0}</span>
        </div>
      )}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 12, minWidth: Math.max(900, daysInMonth * 32 + 240) }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: '8px 12px', background: 'color-mix(in srgb, var(--odoo-primary) 8%, white)', borderBottom: '2px solid #dee2e6', position: 'sticky', left: 0, zIndex: 1 }}>Agent</th>
              {days.map((d) => (
                <th key={d} style={{ padding: '6px 4px', background: 'color-mix(in srgb, var(--odoo-primary) 8%, white)', borderBottom: '2px solid #dee2e6', textAlign: 'center', minWidth: 28, color: d === today.getDate() ? 'var(--odoo-primary)' : undefined, fontWeight: d === today.getDate() ? 700 : 400 }}>
                  {d}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {activeEmployees.map((emp) => {
              const row = rowsByEmployee.get(emp.id)
              return (
                <tr key={emp.id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                  <td style={{ padding: '6px 12px', fontWeight: 600, background: '#fff', position: 'sticky', left: 0, whiteSpace: 'nowrap', zIndex: 1 }}>
                    {emp.nom} {emp.prenom || ''}
                  </td>
                  {days.map((d) => {
                  const day = row?.days[d - 1]
                  const statut = day?.status
                  return (
                    <td key={d} style={{ padding: 2, textAlign: 'center' }}>
                      {statut && statut !== 'non_ouvrable' ? (
                        <button
                          type="button"
                          title={ATTENDANCE_LABELS[statut] || statut}
                          onClick={() => day && setSelectedDay(day)}
                          style={{
                            position: 'relative',
                            width: 20,
                            height: 20,
                            borderRadius: 3,
                            background: ATTENDANCE_COLORS[statut] || '#ccc',
                            margin: '0 auto',
                            opacity: 0.85,
                            border: 'none',
                            cursor: 'pointer',
                          }}
                        >
                          {day?.has_late && <span style={{ position: 'absolute', right: -3, top: -3, width: 7, height: 7, borderRadius: 999, background: '#f59e0b', border: '1px solid #fff' }} />}
                          {day?.has_anomaly && <span style={{ position: 'absolute', left: -3, bottom: -3, width: 7, height: 7, borderRadius: 999, background: '#991b1b', border: '1px solid #fff' }} />}
                        </button>
                      ) : (
                        <div style={{ width: 20, height: 20, margin: '0 auto', background: statut === 'non_ouvrable' ? '#f1f5f9' : 'transparent', borderRadius: 3 }} />
                      )}
                    </td>
                  )
                })}
                </tr>
              )
            })}
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
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#555' }}>
          <span style={{ width: 8, height: 8, borderRadius: 999, background: '#f59e0b', display: 'inline-block' }} />Retard
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#555' }}>
          <span style={{ width: 8, height: 8, borderRadius: 999, background: '#991b1b', display: 'inline-block' }} />Anomalie
        </span>
      </div>
      {selectedDay && (
        <AttendanceDayModal day={selectedDay} onClose={() => setSelectedDay(null)} />
      )}
    </>
  )
}

function minutesToHours(minutes: number): string {
  const safe = Math.max(0, minutes || 0)
  return `${String(Math.floor(safe / 60)).padStart(2, '0')}h${String(safe % 60).padStart(2, '0')}`
}

function appendSheet(xlsx: typeof import('xlsx'), workbook: WorkBook, name: string, rows: Record<string, unknown>[]) {
  const sheet = xlsx.utils.json_to_sheet(rows.length ? rows : [{}])
  const headers = Object.keys(rows[0] || {})
  sheet['!cols'] = headers.map((header) => ({ wch: Math.max(12, Math.min(32, header.length + 4)) }))
  sheet['!autofilter'] = { ref: sheet['!ref'] || 'A1:A1' }
  sheet['!freeze'] = { xSplit: 0, ySplit: 1 }
  xlsx.utils.book_append_sheet(workbook, sheet, name)
}

function AttendanceDayModal({ day, onClose }: { day: HRAttendanceDaySummary; onClose: () => void }) {
  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalPanel} style={{ maxWidth: 620 }} onClick={(event) => event.stopPropagation()}>
        <div className={styles.modalHeader}>
          <div>
            <h3>{day.employee_name}</h3>
            <p>{new Intl.DateTimeFormat('fr-FR', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' }).format(new Date(day.date))}</p>
          </div>
          <button type="button" className={styles.iconButton} onClick={onClose}><X size={18} /></button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12 }}>
          {[
            ['Première entrée', day.first_in_time || '—'],
            ['Dernière sortie', day.last_out_time || '—'],
            ['Temps travaillé', day.worked_duration || '00h00'],
            ['Pause', day.pause_duration || '00h00'],
            ['Retard', day.late_duration || '—'],
            ['Heures supplémentaires', day.overtime_duration || '00h00'],
            ['Statut', ATTENDANCE_LABELS[day.status] || day.status],
            ['Anomalie', day.anomalies.length ? day.anomalies.join(', ') : 'Aucune'],
          ].map(([label, value]) => (
            <div key={label} style={{ padding: 12, border: '1px solid #e2e8f0', borderRadius: 8, background: '#fff' }}>
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>{label}</div>
              <strong style={{ fontSize: 14, color: '#0f172a' }}>{value}</strong>
            </div>
          ))}
        </div>
        <h4 style={{ margin: '18px 0 10px' }}>Historique des pointages</h4>
        <div style={{ display: 'grid', gap: 8 }}>
          {day.punches.length === 0 ? (
            <p style={{ color: '#64748b' }}>Aucun pointage brut enregistré.</p>
          ) : day.punches.map((punch) => (
            <div key={punch.id} style={{ display: 'grid', gridTemplateColumns: '70px 1fr 120px', gap: 10, padding: '8px 10px', borderRadius: 8, background: '#f8fafc' }}>
              <strong>{punch.time}</strong>
              <span>{punch.event_type === 'IN' ? 'Entrée' : 'Sortie'}</span>
              <span style={{ color: '#64748b' }}>{punch.source}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function AttendancePunchJournalView({
  employees,
  services,
  initialJournal,
  onChanged,
}: {
  employees: HREmployee[]
  services: HRService[]
  initialJournal: HRAttendancePunchJournal | null
  onChanged: () => Promise<void>
}) {
  const { hasPermission } = usePermissions()
  const canCorrect = hasPermission('rh.attendance.correct')
  const today = new Date().toISOString().split('T')[0]
  const [journal, setJournal] = useState(initialJournal)
  const [loadingJournal, setLoadingJournal] = useState(false)
  const [manualOpen, setManualOpen] = useState(false)
  const [pageSize, setPageSize] = useState(25)
  const [filters, setFilters] = useState({ date_from: today, date_to: today, employee_id: '', service_id: '', source: '', situation: '', search: '' })
  const [manual, setManual] = useState({ employee_id: '', date: today, time: '08:00', event_type: 'IN' as 'IN' | 'OUT', notes: '' })

  useEffect(() => setJournal(initialJournal), [initialJournal])

  const loadJournal = async (offset = 0, limitOverride = pageSize) => {
    setLoadingJournal(true)
    try {
      const data = await getAttendancePunches({
        date_from: filters.date_from || undefined,
        date_to: filters.date_to || undefined,
        employee_id: filters.employee_id ? Number(filters.employee_id) : undefined,
        service_id: filters.service_id ? Number(filters.service_id) : undefined,
        source: filters.source || undefined,
        search: filters.search || undefined,
        limit: limitOverride,
        offset,
      })
      setJournal(data)
    } finally {
      setLoadingJournal(false)
    }
  }

  const submitManual = async (event: FormEvent) => {
    event.preventDefault()
    await createAttendancePunch({
      employee_id: Number(manual.employee_id),
      punched_at: new Date(`${manual.date}T${manual.time}`).toISOString(),
      event_type: manual.event_type,
      source: 'MANUAL',
      notes: manual.notes || undefined,
    })
    setManualOpen(false)
    await loadJournal(0)
    await onChanged()
  }

  const resetFilters = () => {
    const next = { date_from: today, date_to: today, employee_id: '', service_id: '', source: '', situation: '', search: '' }
    setFilters(next)
    void getAttendancePunches({ date_from: today, date_to: today, limit: pageSize, offset: 0 }).then(setJournal)
  }

  const sourceLabels: Record<string, string> = {
    DEVICE: 'Pointeuse',
    MANUAL: 'Manuel',
    EXCEL_IMPORT: 'Import Excel',
    BIOMETRIC: 'Biométrique',
    RFID: 'RFID',
    QR_CODE: 'QR Code',
    MOBILE: 'Mobile',
    API: 'API',
  }
  const sourceOptions = ['DEVICE', 'MANUAL', 'EXCEL_IMPORT', 'BIOMETRIC', 'RFID', 'QR_CODE', 'MOBILE', 'API']
  const eventLabel = (value: 'IN' | 'OUT') => value === 'IN' ? 'Entrée' : 'Sortie'
  const sourceLabel = (value: string) => sourceLabels[value] || value
  const situationForPunch = (punch: { event_type: 'IN' | 'OUT'; punched_at: string; notes?: string | null }) => {
    const note = (punch.notes || '').toLowerCase()
    if (note.includes('anomal')) return 'Anomalie'
    if (note.includes('retard')) return 'Retard'
    const date = new Date(punch.punched_at)
    if (punch.event_type === 'IN' && (date.getHours() > 8 || (date.getHours() === 8 && date.getMinutes() > 15))) return 'Retard'
    return 'Normal'
  }
  const filteredItems = (journal?.items || []).filter((punch) => {
    if (!filters.situation) return true
    return situationForPunch(punch).toLowerCase() === filters.situation
  })
  const summary = {
    pointages: journal?.total || 0,
    presents: new Set((journal?.items || []).filter((p) => p.event_type === 'IN').map((p) => p.employee_id)).size,
    retards: (journal?.items || []).filter((p) => situationForPunch(p) === 'Retard').length,
    anomalies: (journal?.items || []).filter((p) => situationForPunch(p) === 'Anomalie').length,
  }
  const firstRow = journal ? Math.min(journal.total, journal.offset + 1) : 0
  const lastRow = journal ? Math.min(journal.total, journal.offset + journal.limit) : 0
  const currentPage = journal ? Math.floor(journal.offset / journal.limit) + 1 : 1
  const totalPages = journal ? Math.max(1, Math.ceil(journal.total / journal.limit)) : 1
  const exportJournal = async () => {
    const [XLSX, data] = await Promise.all([
      import('xlsx'),
      getAttendancePunches({
        date_from: filters.date_from || undefined,
        date_to: filters.date_to || undefined,
        employee_id: filters.employee_id ? Number(filters.employee_id) : undefined,
        service_id: filters.service_id ? Number(filters.service_id) : undefined,
        source: filters.source || undefined,
        search: filters.search || undefined,
        limit: 200,
        offset: 0,
      }),
    ])
    const rows = data.items
      .filter((punch) => !filters.situation || situationForPunch(punch).toLowerCase() === filters.situation)
      .map((punch) => ({
        'Date/Heure': new Date(punch.punched_at),
        Employé: punch.employee_name,
        Matricule: punch.employee_matricule || '',
        Service: punch.service_name || '',
        Événement: eventLabel(punch.event_type),
        Source: sourceLabel(punch.source),
        Situation: situationForPunch(punch),
        Observation: punch.notes || '',
      }))
    const workbook = XLSX.utils.book_new()
    appendSheet(XLSX, workbook, 'Journal des pointages', rows)
    XLSX.writeFile(workbook, `journal_pointages_ONEC_${filters.date_from || today}_${filters.date_to || today}.xlsx`)
  }

  return (
    <div className={styles.punchJournal}>
      <div className={styles.punchToolbar}>
        <div className={styles.punchToolbarTop}>
          <button type="button" className={styles.secondaryButton} onClick={resetFilters}>Aujourd'hui</button>
          <label className={styles.compactField}><span>Du</span><input type="date" value={filters.date_from} onChange={(e) => setFilters((p) => ({ ...p, date_from: e.target.value }))} /></label>
          <label className={styles.compactField}><span>Au</span><input type="date" value={filters.date_to} onChange={(e) => setFilters((p) => ({ ...p, date_to: e.target.value }))} /></label>
          <div className={styles.punchToolbarActions}>
            <button type="button" className={styles.secondaryButton} onClick={() => setManualOpen(true)}>+ Ajouter un pointage</button>
            <button type="button" className={styles.primaryButton} onClick={exportJournal}><Download size={16} /> Exporter Excel</button>
          </div>
        </div>
        <div className={styles.punchFilters}>
          <select value={filters.employee_id} onChange={(e) => setFilters((p) => ({ ...p, employee_id: e.target.value }))}>
            <option value="">Employé</option>
            {employees.map((emp) => <option key={emp.id} value={emp.id}>{fullName(emp)}</option>)}
          </select>
          <select value={filters.service_id} onChange={(e) => setFilters((p) => ({ ...p, service_id: e.target.value }))}>
            <option value="">Service</option>
            {services.map((svc) => <option key={svc.id} value={svc.id}>{svc.libelle}</option>)}
          </select>
          <select value={filters.source} onChange={(e) => setFilters((p) => ({ ...p, source: e.target.value }))}>
            <option value="">Toutes les sources</option>
            {sourceOptions.map((source) => <option key={source} value={source}>{sourceLabel(source)}</option>)}
          </select>
          <select value={filters.situation} onChange={(e) => setFilters((p) => ({ ...p, situation: e.target.value }))}>
            <option value="">Toutes les situations</option>
            <option value="normal">Normal</option>
            <option value="retard">Retard</option>
            <option value="anomalie">Anomalie</option>
          </select>
          <input placeholder="Rechercher un employé..." value={filters.search} onChange={(e) => setFilters((p) => ({ ...p, search: e.target.value }))} />
          <button type="button" className={styles.primaryButton} onClick={() => loadJournal(0)}><Search size={16} /> Filtrer</button>
        </div>
      </div>
      <div className={styles.punchSummary}>
        <strong>Aujourd'hui</strong>
        <span>{summary.pointages} pointages</span>
        <span>{summary.presents} présents</span>
        <span>{summary.retards} retards</span>
        <span>{summary.anomalies} anomalie{summary.anomalies > 1 ? 's' : ''}</span>
      </div>
      <div className={styles.section} style={{ overflowX: 'auto', padding: 0 }}>
        {loadingJournal && <div className={styles.punchLoading}>Chargement du journal...</div>}
        <table className={styles.dataTable}>
          <thead><tr><th>Date/Heure</th><th>Employé</th><th>Service</th><th>Événement</th><th>Source</th><th>Situation</th><th>Actions</th></tr></thead>
          <tbody>
            {filteredItems.map((punch) => {
              const situation = situationForPunch(punch)
              return (
              <tr key={punch.id}>
                <td>{new Date(punch.punched_at).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</td>
                <td>{punch.employee_name}</td>
                <td>{punch.service_name || '—'}</td>
                <td><span className={`${styles.punchBadge} ${punch.event_type === 'IN' ? styles.punchBadgeIn : styles.punchBadgeOut}`}>{eventLabel(punch.event_type)}</span></td>
                <td>{sourceLabel(punch.source)}</td>
                <td><span className={`${styles.punchBadge} ${situation === 'Retard' ? styles.punchBadgeLate : situation === 'Anomalie' ? styles.punchBadgeAnomaly : ''}`}>{situation}</span></td>
                <td><button type="button" className={styles.linkButton}>Voir</button>{canCorrect && <button type="button" className={styles.linkButton}>Corriger</button>}</td>
              </tr>
              )
            })}
            {(!journal || filteredItems.length === 0) && (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: 28 }}>
                  <div style={{ color: '#64748b', marginBottom: 10 }}>Aucun pointage trouvé pour cette période.</div>
                  <button type="button" className={styles.secondaryButton} onClick={resetFilters}>Réinitialiser les filtres</button>
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {journal && (
          <div className={styles.punchPagination}>
            <span>{journal.total === 0 ? '0' : `${firstRow}-${lastRow}`} sur {journal.total} pointages</span>
            <select value={pageSize} onChange={(e) => { const next = Number(e.target.value); setPageSize(next); void loadJournal(0, next) }}>
              <option value={25}>25 par page</option>
              <option value={50}>50 par page</option>
              <option value={100}>100 par page</option>
            </select>
            <button type="button" className={styles.secondaryButton} disabled={journal.offset === 0} onClick={() => loadJournal(Math.max(0, journal.offset - journal.limit))}>Précédent</button>
            {Array.from({ length: Math.min(4, totalPages) }, (_, index) => index + 1).map((page) => (
              <button key={page} type="button" className={page === currentPage ? styles.primaryButton : styles.secondaryButton} onClick={() => loadJournal((page - 1) * journal.limit)}>{page}</button>
            ))}
            <button type="button" className={styles.secondaryButton} disabled={journal.offset + journal.limit >= journal.total} onClick={() => loadJournal(journal.offset + journal.limit)}>Suivant</button>
          </div>
        )}
      </div>
      {manualOpen && (
        <div className={styles.modalOverlay} onClick={() => setManualOpen(false)}>
          <form className={styles.modalPanel} style={{ maxWidth: 520 }} onSubmit={submitManual} onClick={(event) => event.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div>
                <h3>Ajouter un pointage</h3>
                <p>Source enregistrée automatiquement : Manuel</p>
              </div>
              <button type="button" className={styles.iconButton} onClick={() => setManualOpen(false)}><X size={18} /></button>
            </div>
            <div style={{ display: 'grid', gap: 12 }}>
              <label className={styles.compactField}><span>Employé</span><select required value={manual.employee_id} onChange={(e) => setManual((p) => ({ ...p, employee_id: e.target.value }))}>
                <option value="">Sélectionner</option>
                {employees.filter((e) => e.statut === 'actif').map((emp) => <option key={emp.id} value={emp.id}>{fullName(emp)}</option>)}
              </select></label>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <label className={styles.compactField}><span>Date</span><input type="date" required value={manual.date} onChange={(e) => setManual((p) => ({ ...p, date: e.target.value }))} /></label>
                <label className={styles.compactField}><span>Heure</span><input type="time" required value={manual.time} onChange={(e) => setManual((p) => ({ ...p, time: e.target.value }))} /></label>
              </div>
              <label className={styles.compactField}><span>Type</span><select value={manual.event_type} onChange={(e) => setManual((p) => ({ ...p, event_type: e.target.value as 'IN' | 'OUT' }))}>
                <option value="IN">Entrée</option>
                <option value="OUT">Sortie</option>
              </select></label>
              <label className={styles.compactField}><span>Observation</span><input value={manual.notes} onChange={(e) => setManual((p) => ({ ...p, notes: e.target.value }))} /></label>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 18 }}>
              <button type="button" className={styles.secondaryButton} onClick={() => setManualOpen(false)}>Annuler</button>
              <button className={styles.primaryButton}>Enregistrer</button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}

function AttendanceDevicesView({ devices, onRefresh }: { devices: HRAttendanceDeviceStatus[]; onRefresh: () => Promise<void> }) {
  const [form, setForm] = useState({
    agent_name: 'ONEC Attendance Agent',
    site: '',
    api_base_url: '',
    device_code: '',
    device_name: '',
    provider: 'hikvision',
    model: 'DS-K1A8603MF-B',
    local_host: '',
    local_port: 80,
  })
  const [creating, setCreating] = useState(false)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [releases, setReleases] = useState<HRAttendanceAgentRelease[]>([])
  const [enrollment, setEnrollment] = useState<HRAttendanceAgentEnrollment | null>(null)
  const statusLabel: Record<string, string> = {
    ONLINE: 'En ligne',
    OFFLINE: 'Hors ligne',
    AGENT_OFFLINE: 'Agent hors ligne',
    SYNC_ERROR: 'Erreur de synchronisation',
    DEVICE_OFFLINE: 'Pointeuse hors ligne',
    DEVICE_REACHABLE: 'Pointeuse joignable',
    AUTH_REQUIRED: 'Authentification requise',
    AUTH_FAILED: 'Authentification échouée',
    DEVICE_ONLINE: 'Pointeuse en ligne',
    ISAPI_AVAILABLE: 'ISAPI disponible',
    ISAPI_UNAVAILABLE: 'ISAPI indisponible',
    TEST_FAILED: 'Test échoué',
    UNKNOWN: 'Inconnu',
  }
  const fmt = (value?: string | null) => value ? new Date(value).toLocaleString('fr-FR') : '—'
  useEffect(() => {
    void getAttendanceAgentReleases().then(setReleases).catch(() => setReleases([]))
  }, [])
  const latestRelease = (platform: 'windows' | 'linux') => releases.find((release) => release.platform === platform && release.architecture === 'x64')
  const submitEnrollment = async (event: FormEvent) => {
    event.preventDefault()
    setCreating(true)
    try {
      const created = await createAttendanceAgentEnrollment({
        ...form,
        local_port: Number(form.local_port) || 80,
        expires_in_minutes: 60,
      })
      setEnrollment(created)
      await onRefresh()
    } finally {
      setCreating(false)
    }
  }
  const downloadPackage = async (device: HRAttendanceDeviceStatus, platform: 'windows' | 'linux') => {
    const release = latestRelease(platform)
    if (!release || !device.agent_id || !form.api_base_url) return
    await downloadAttendanceAgentPackage(release.id, {
      agent_id: device.agent_id,
      platform,
      architecture: 'x64',
      api_base_url: form.api_base_url,
      expires_in_minutes: 60,
    })
  }
  const testDevice = async (device: HRAttendanceDeviceStatus) => {
    setTestingId(device.id)
    try {
      await createTestDeviceCommand(device.id)
      window.setTimeout(() => { void onRefresh().finally(() => setTestingId(null)) }, 2500)
    } catch (error) {
      setTestingId(null)
      throw error
    }
  }
  const probeDevice = async (device: HRAttendanceDeviceStatus) => {
    setTestingId(device.id)
    try {
      await createProbeDeviceCommand(device.id)
      window.setTimeout(() => { void onRefresh().finally(() => setTestingId(null)) }, 3500)
    } catch (error) {
      setTestingId(null)
      throw error
    }
  }
  const diagnostic = (device: HRAttendanceDeviceStatus) => {
    const result = device.last_test_result || {}
    const boolLabel = (value: unknown, yes = 'OK', no = 'Échec') => value === true ? yes : value === false ? no : 'Non vérifié'
    const authLabel = () => {
      if (result.authentication_ok === true) return 'OK'
      if (result.authentication_required === true) return 'Requise'
      if (device.last_error) return 'Échec'
      return 'Non vérifiée'
    }
    const isapiLabel = () => result.isapi_supported === true ? 'Disponible' : result.isapi_supported === false ? 'Indisponible' : 'Non vérifié'
    return [
      ['Agent', device.agent_online ? 'Connecté' : 'Hors ligne'],
      ['Réseau TCP', boolLabel(result.tcp_reachable, 'OK', 'Hors ligne')],
      ['HTTP', result.http_reachable === true ? `OK${result.http_status ? ` ${result.http_status}` : ''}` : result.https_reachable === true ? `HTTPS OK${result.https_status ? ` ${result.https_status}` : ''}` : 'Non vérifié'],
      ['Authentification', authLabel()],
      ['ISAPI', isapiLabel()],
      ['Modèle détecté', String(result.detected_model || result.configured_model || 'Non vérifié')],
      ['Firmware', String(result.firmware_version || 'Non vérifié')],
    ]
  }
  const revokeAgent = async (agentId?: number | null) => {
    if (!agentId) return
    await revokeAttendanceAgent(agentId)
    await onRefresh()
  }
  const reinstallAgent = async (device: HRAttendanceDeviceStatus) => {
    if (!device.agent_id || !form.api_base_url) return
    const result = await reinstallAttendanceAgent(device.agent_id, {
      agent_id: device.agent_id,
      platform: 'windows',
      architecture: 'x64',
      api_base_url: form.api_base_url,
      expires_in_minutes: 60,
    })
    setEnrollment(result.enrollment)
    await onRefresh()
  }
  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <form className={styles.section} onSubmit={submitEnrollment}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', marginBottom: 14 }}>
          <div>
            <h3 style={{ margin: 0, color: 'var(--odoo-primary)' }}>Ajouter une pointeuse</h3>
            <p style={{ margin: '4px 0 0', color: '#64748b', fontSize: 13 }}>Prépare un enrollment temporaire pour un agent universel Windows/Linux.</p>
          </div>
          <button type="submit" className={styles.primaryButton} disabled={creating}>
            <Download size={16} /> {creating ? 'Création...' : 'Créer enrollment'}
          </button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 12 }}>
          <label className={styles.compactField}><span>Agent</span><input required value={form.agent_name} onChange={(e) => setForm((p) => ({ ...p, agent_name: e.target.value }))} /></label>
          <label className={styles.compactField}><span>Site</span><input value={form.site} onChange={(e) => setForm((p) => ({ ...p, site: e.target.value }))} /></label>
          <label className={styles.compactField}><span>URL ONEC Smart</span><input required placeholder="http://192.168.1.20:8000" value={form.api_base_url} onChange={(e) => setForm((p) => ({ ...p, api_base_url: e.target.value }))} /></label>
          <label className={styles.compactField}><span>Code pointeuse</span><input required value={form.device_code} onChange={(e) => setForm((p) => ({ ...p, device_code: e.target.value }))} /></label>
          <label className={styles.compactField}><span>Nom pointeuse</span><input required value={form.device_name} onChange={(e) => setForm((p) => ({ ...p, device_name: e.target.value }))} /></label>
          <label className={styles.compactField}><span>Provider</span><select value={form.provider} onChange={(e) => setForm((p) => ({ ...p, provider: e.target.value }))}><option value="hikvision">Hikvision</option><option value="mock">Mock</option></select></label>
          <label className={styles.compactField}><span>Modèle cible</span><input value={form.model} onChange={(e) => setForm((p) => ({ ...p, model: e.target.value }))} /></label>
          <label className={styles.compactField}><span>IP locale pointeuse</span><input required placeholder="192.168.1.150" value={form.local_host} onChange={(e) => setForm((p) => ({ ...p, local_host: e.target.value }))} /></label>
          <label className={styles.compactField}><span>Port local</span><input required type="number" min={1} max={65535} value={form.local_port} onChange={(e) => setForm((p) => ({ ...p, local_port: Number(e.target.value) }))} /></label>
        </div>
        {enrollment && (
          <div style={{ marginTop: 14, display: 'grid', gap: 8, padding: 12, border: '1px solid #bbf7d0', background: '#f0fdf4', borderRadius: 6, fontSize: 13 }}>
            <strong>Enrollment prêt jusqu'au {fmt(enrollment.expires_at)}</strong>
            <div>Agent ID : <code>{enrollment.agent_id}</code></div>
            <div>URL : <code>{enrollment.enrollment_url}</code></div>
            <div>Token temporaire : <code>{enrollment.enrollment_token}</code></div>
            <div>API agent : <code>{enrollment.api_base_url}</code></div>
          </div>
        )}
      </form>
      <div className={styles.leaveSummaryBar} style={{ justifyContent: 'space-between' }}>
        <span>Agents connectés : {devices.filter((d) => d.agent_online).length}</span>
        <span>Pointeuses en ligne : {devices.filter((d) => d.device_online).length}</span>
        <span>En attente : {devices.reduce((sum, d) => sum + d.pending_count, 0)}</span>
        <span>Erreurs : {devices.reduce((sum, d) => sum + d.error_count, 0)}</span>
        <span>Windows x64 : {latestRelease('windows') ? 'Disponible' : 'Indisponible'}</span>
        <span>Linux x64 : {latestRelease('linux') ? 'Disponible' : 'Indisponible'}</span>
        <button type="button" className={styles.secondaryButton} onClick={() => void onRefresh()}><RotateCw size={16} /> Actualiser</button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 }}>
        {devices.map((device) => (
          <div key={device.device_id} className={styles.section}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start' }}>
              <div>
                <h3 style={{ margin: 0, color: 'var(--odoo-primary)' }}>{device.name}</h3>
                <p style={{ margin: '4px 0 0', color: '#64748b' }}>{device.site || 'Site non renseigné'} · {device.provider}</p>
              </div>
              <span className={`${styles.punchBadge} ${device.status === 'ONLINE' ? styles.punchBadgeIn : device.status === 'SYNC_ERROR' ? styles.punchBadgeAnomaly : ''}`}>
                {statusLabel[device.status] || device.status}
              </span>
            </div>
            <div style={{ display: 'grid', gap: 8, marginTop: 14, fontSize: 13 }}>
              {diagnostic(device).map(([label, value]) => (
                <div key={label}>{label} : <strong>{value}</strong></div>
              ))}
              <div>Dernier contact : <strong>{fmt(device.last_seen_at)}</strong></div>
              <div>Dernière synchronisation : <strong>{fmt(device.last_sync_at)}</strong></div>
              <div>Dernier test : <strong>{fmt(device.last_test_at)}</strong></div>
              <div>Latence : <strong>{device.last_test_latency_ms != null ? `${device.last_test_latency_ms} ms` : '—'}</strong></div>
              <div>Pointages aujourd'hui : <strong>{device.today_punch_count}</strong></div>
              <div>En attente : <strong>{device.pending_count}</strong></div>
              <div>Erreurs : <strong>{device.error_count}</strong></div>
              {device.last_error && <div style={{ color: '#b91c1c' }}>Dernière erreur : {device.last_error}</div>}
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
              <button type="button" className={styles.secondaryButton} disabled={testingId === device.id} onClick={() => void testDevice(device)}>
                {testingId === device.id ? 'Test en cours...' : 'Tester la connexion'}
              </button>
              <button type="button" className={styles.secondaryButton} disabled={testingId === device.id} onClick={() => void probeDevice(device)}>
                {testingId === device.id ? 'Probe en cours...' : 'Probe lecture seule'}
              </button>
              <button type="button" className={styles.secondaryButton} disabled={!latestRelease('windows') || !device.agent_id || !form.api_base_url} onClick={() => void downloadPackage(device, 'windows')}>Télécharger Windows</button>
              <button type="button" className={styles.secondaryButton} disabled={!latestRelease('linux') || !device.agent_id || !form.api_base_url} onClick={() => void downloadPackage(device, 'linux')}>Télécharger Linux</button>
              <button type="button" className={styles.secondaryButton} disabled={!device.agent_id} onClick={() => void reinstallAgent(device)}>Réinstaller</button>
              <button type="button" className={styles.secondaryButton} disabled={!device.agent_id} onClick={() => void revokeAgent(device.agent_id)}>Révoquer</button>
              <button type="button" className={styles.secondaryButton}>Synchroniser</button>
              <button type="button" className={styles.secondaryButton}>Voir les logs</button>
            </div>
          </div>
        ))}
        {devices.length === 0 && (
          <div className={styles.section} style={{ color: '#64748b' }}>
            Aucune pointeuse enregistrée. Configurez un agent local puis envoyez un heartbeat pour créer ou rattacher les appareils.
          </div>
        )}
      </div>
    </div>
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
      <div style={{ padding: '12px 20px', background: 'color-mix(in srgb, var(--odoo-primary) 8%, white)', borderBottom: '1px solid #dee2e6' }}>
        <h3 style={{ margin: 0, fontSize: 15, color: 'var(--odoo-primary)' }}>Saisie de présences</h3>
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
              <label key={emp.id} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 13, cursor: 'pointer', padding: '4px 8px', borderRadius: 4, background: form.employee_ids.includes(emp.id) ? 'color-mix(in srgb, var(--odoo-primary) 8%, white)' : '#f8f9fa', border: `1px solid ${form.employee_ids.includes(emp.id) ? 'var(--odoo-primary)' : '#dee2e6'}` }}>
                <input type="checkbox" checked={form.employee_ids.includes(emp.id)} onChange={() => toggleEmp(emp.id)} style={{ accentColor: 'var(--odoo-primary)' }} />
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
                              <td style={{ padding: '6px 12px', textAlign: 'right', fontWeight: 700, color: 'var(--odoo-primary)' }}>{slip.net_a_payer}</td>
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

function SalarySlipsView({ employeeById }: { employeeById: Map<number, HREmployee> }) {
  const { showError } = useNotification()
  const currentYear = new Date().getFullYear()
  const yearOptions = useMemo(() => Array.from({ length: 5 }, (_, i) => currentYear - i), [currentYear])
  const [year, setYear] = useState(currentYear)
  const [query, setQuery] = useState('')
  const [slips, setSlips] = useState<HRSalarySlip[]>([])
  const [payrollEntries, setPayrollEntries] = useState<HRPayrollEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([getSalarySlips({ annee: year }), getPayrollEntries({ annee: year })])
      .then(([slipRows, entryRows]) => {
        if (cancelled) return
        setSlips(slipRows)
        setPayrollEntries(entryRows)
      })
      .catch((err) => {
        if (!cancelled) showError('Chargement impossible', err instanceof Error ? err.message : 'Impossible de charger les bulletins.')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [year])

  const entryById = useMemo(() => new Map(payrollEntries.map((e) => [e.id, e])), [payrollEntries])

  const filteredSlips = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return slips
    return slips.filter((slip) => fullName(employeeById.get(slip.employee_id)).toLowerCase().includes(q))
  }, [slips, query, employeeById])

  const periodeLabel = (slip: HRSalarySlip) => {
    const entry = entryById.get(slip.payroll_entry_id)
    return entry
      ? `${MONTH_LABELS_LONG[entry.mois - 1]} ${entry.annee}`
      : new Date(slip.created_at).toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' })
  }

  const totalsByDevise = useMemo(() => {
    const totals = new Map<string, { count: number; net: number; ipr: number; cnss: number; primes: number; retenues: number }>()
    filteredSlips.forEach((slip) => {
      const t = totals.get(slip.devise) || { count: 0, net: 0, ipr: 0, cnss: 0, primes: 0, retenues: 0 }
      t.count += 1
      t.net += Number(slip.net_a_payer) || 0
      t.ipr += Number(slip.ipr) || 0
      t.cnss += Number(slip.cnss_salarie) || 0
      t.primes += Number(slip.total_primes) || 0
      t.retenues += Number(slip.total_retenues) || 0
      totals.set(slip.devise, t)
    })
    return totals
  }, [filteredSlips])

  const fmt = (n: number) => n.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

  const exportToExcel = async () => {
    const XLSX = await import('xlsx')
    const rows = filteredSlips.map((slip) => ({
      'Agent': fullName(employeeById.get(slip.employee_id)),
      'Période': periodeLabel(slip),
      'Salaire base': Number(slip.salaire_base),
      'Primes': Number(slip.total_primes),
      'IPR': Number(slip.ipr),
      'CNSS': Number(slip.cnss_salarie),
      'Total retenues': Number(slip.total_retenues),
      'Net à payer': Number(slip.net_a_payer),
      'Devise': slip.devise,
      'Statut': slip.statut,
    }))
    totalsByDevise.forEach((t, devise) => {
      rows.push({
        'Agent': '', 'Période': `TOTAL ${devise}`,
        'Salaire base': 0, 'Primes': t.primes, 'IPR': t.ipr, 'CNSS': t.cnss,
        'Total retenues': t.retenues, 'Net à payer': t.net, 'Devise': devise, 'Statut': `${t.count} bulletin${t.count !== 1 ? 's' : ''}`,
      })
    })
    const ws = XLSX.utils.json_to_sheet(rows)
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, 'Bulletins')
    XLSX.writeFile(wb, `bulletins_paie_${year}.xlsx`)
  }

  const exportToPDF = async () => {
    const [{ default: jsPDF }, { default: autoTable }] = await Promise.all([
      import('jspdf'),
      import('jspdf-autotable'),
    ])
    const doc = new jsPDF({ orientation: 'landscape' })
    doc.setFontSize(16)
    doc.text(`Bulletins de paie - ${year}`, 14, 18)
    doc.setFontSize(10)
    doc.setTextColor(90)
    doc.text(`Rapport généré le : ${new Date().toLocaleDateString('fr-FR')}`, 14, 26)

    const body = filteredSlips.map((slip) => [
      fullName(employeeById.get(slip.employee_id)),
      periodeLabel(slip),
      slip.salaire_base,
      `+${slip.total_primes}`,
      `-${slip.ipr}`,
      `-${slip.cnss_salarie}`,
      `-${slip.total_retenues}`,
      slip.net_a_payer,
      slip.devise,
      slip.statut,
    ])

    autoTable(doc, {
      startY: 32,
      head: [['Agent', 'Période', 'Salaire base', 'Primes', 'IPR', 'CNSS', 'Total retenues', 'Net à payer', 'Devise', 'Statut']],
      body,
      headStyles: { fillColor: [113, 75, 103], textColor: [255, 255, 255], fontStyle: 'bold' },
      alternateRowStyles: { fillColor: [248, 250, 252] },
      margin: { top: 30, left: 12, right: 12 },
      styles: { fontSize: 8, cellPadding: 3 },
    })

    let y = (doc as any).lastAutoTable.finalY + 10
    doc.setFontSize(10)
    doc.setTextColor(0)
    totalsByDevise.forEach((t, devise) => {
      doc.text(
        `Total ${devise} (${t.count} bulletin${t.count !== 1 ? 's' : ''}) — Net à payer : ${fmt(t.net)} · IPR : ${fmt(t.ipr)} · CNSS : ${fmt(t.cnss)}`,
        14,
        y
      )
      y += 6
    })

    doc.save(`bulletins_paie_${year}.pdf`)
  }

  return (
    <div>
      <div className={styles.configToolbar} style={{ marginBottom: 15, borderRadius: 6, border: '1px solid var(--odoo-border)' }}>
        <select
          value={year}
          onChange={(e) => setYear(Number(e.target.value))}
          style={{ border: '1px solid var(--odoo-border)', borderRadius: 4, padding: '5px 10px', fontSize: 14 }}
        >
          {yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <Search size={16} />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Rechercher un agent..." />
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button type="button" className={styles.secondaryButton} onClick={exportToExcel} disabled={filteredSlips.length === 0} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <Download size={14} /> Excel
          </button>
          <button type="button" className={styles.secondaryButton} onClick={exportToPDF} disabled={filteredSlips.length === 0} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <Download size={14} /> PDF
          </button>
        </div>
      </div>
      {!loading && filteredSlips.length > 0 && (
        <div className={styles.leaveSummaryBar}>
          <span className={styles.leaveStat}>{filteredSlips.length} bulletin{filteredSlips.length !== 1 ? 's' : ''}</span>
          {Array.from(totalsByDevise.entries()).map(([devise, t]) => (
            <Fragment key={devise}>
              <span className={styles.leaveStat} style={{ fontWeight: 700, color: 'var(--odoo-primary)' }}>Net {devise} : {fmt(t.net)}</span>
              <span className={styles.leaveStat} style={{ color: '#dc2626' }}>IPR : {fmt(t.ipr)}</span>
              <span className={styles.leaveStat} style={{ color: '#dc2626' }}>CNSS : {fmt(t.cnss)}</span>
            </Fragment>
          ))}
        </div>
      )}
      <div className={styles.tableWrap}>
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              <th>Période</th>
              <th style={{ textAlign: 'right' }}>Salaire base</th>
              <th style={{ textAlign: 'right' }}>Primes</th>
              <th style={{ textAlign: 'right' }}>IPR</th>
              <th style={{ textAlign: 'right' }}>CNSS</th>
              <th style={{ textAlign: 'right' }}>Total retenues</th>
              <th style={{ textAlign: 'right', fontWeight: 700 }}>Net à payer</th>
              <th>Devise</th>
              <th>Statut</th>
              <th>Bulletin</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={11} style={{ textAlign: 'center', padding: 40, color: '#999' }}>Chargement...</td></tr>
            ) : (
              <>
                {filteredSlips.map((slip) => {
                  const employee = employeeById.get(slip.employee_id)
                  const name = fullName(employee)
                  const initials = ((employee?.prenom?.[0] || '') + (employee?.nom?.[0] || '')).toUpperCase()
                  const [avatarBg, avatarFg] = avatarColors(employee?.nom || name)
                  return (
                  <tr key={slip.id}>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div className={styles.avatar} style={{ width: 28, height: 28, borderRadius: 14, fontSize: 12, background: avatarBg, color: avatarFg }}>
                          {initials || '?'}
                        </div>
                        <span style={{ fontWeight: 600 }}>{name}</span>
                      </div>
                    </td>
                    <td style={{ color: '#888', fontSize: 13 }}>
                      {periodeLabel(slip)}
                    </td>
                    <td style={{ textAlign: 'right' }}>{fmt(Number(slip.salaire_base))}</td>
                    <td style={{ textAlign: 'right', color: '#059669' }}>+{fmt(Number(slip.total_primes))}</td>
                    <td style={{ textAlign: 'right', color: '#dc2626' }}>-{fmt(Number(slip.ipr))}</td>
                    <td style={{ textAlign: 'right', color: '#dc2626' }}>-{fmt(Number(slip.cnss_salarie))}</td>
                    <td style={{ textAlign: 'right', color: '#dc2626' }}>-{fmt(Number(slip.total_retenues))}</td>
                    <td style={{ textAlign: 'right', fontWeight: 700, color: 'var(--odoo-primary)' }}>{fmt(Number(slip.net_a_payer))}</td>
                    <td>{slip.devise}</td>
                    <td><span className={`${styles.badge} ${styles[slip.statut] || ''}`}>{slip.statut}</span></td>
                    <td>
                      <button
                        type="button"
                        className={styles.quickAction}
                        title="Générer le bulletin PDF"
                        onClick={() => generateBulletinPaiePDF(slip, employeeById.get(slip.employee_id), periodeLabel(slip))}
                      >
                        <FileText size={14} />
                      </button>
                    </td>
                  </tr>
                  )
                })}
                {filteredSlips.length === 0 && (
                  <tr><td colSpan={11} style={{ textAlign: 'center', padding: 40, color: '#999' }}>Aucun bulletin de paie pour {year}{query ? ' correspondant à la recherche' : ''}.</td></tr>
                )}
              </>
            )}
          </tbody>
        </table>
      </div>
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
              <td style={{ textAlign: 'right', fontWeight: 700, color: 'var(--odoo-primary)' }}>
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
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: 'var(--odoo-primary)' }}>Effectifs par service</h3>
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
                  <div style={{ height: '100%', width: `${(svc.total / maxEffectif) * 100}%`, background: 'var(--odoo-primary)', borderRadius: 4 }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Présences mensuelles */}
      <div className={styles.card} style={{ padding: 24 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: 'var(--odoo-primary)' }}>Présences mensuelles</h3>
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
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: 'var(--odoo-primary)' }}>Masse salariale</h3>
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
                    <td style={{ textAlign: 'right', fontWeight: 700, color: 'var(--odoo-primary)' }}>
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
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 700, color: 'var(--odoo-primary)' }}>Congés par type</h3>
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
