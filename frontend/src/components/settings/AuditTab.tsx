import { useEffect, useMemo, useState } from 'react'
import { DownloadCloud, Edit3, FileUp, Filter, History, Search, Trash2, UserPlus } from 'lucide-react'
import { getAuditLogs, getAuditUsers, type AuditLog, type AuditUser } from '../../api/auditLogs'
// jsPDF est lourd : chargement dynamique au moment de l'export.
type AuditExportModule = typeof import('../../utils/auditExport')
let _auditExportModulePromise: Promise<AuditExportModule> | null = null
function loadAuditExportModule(): Promise<AuditExportModule> {
  if (!_auditExportModulePromise) _auditExportModulePromise = import('../../utils/auditExport')
  return _auditExportModulePromise
}
const exportAuditToPDF: AuditExportModule['exportAuditToPDF'] = async (...args) => {
  const mod = await loadAuditExportModule()
  return mod.exportAuditToPDF(...args)
}
import styles from './AuditTab.module.css'

type FilterType = 'ALL' | 'CREATE' | 'UPDATE' | 'DELETE' | 'IMPORT'

const getTypeFromAction = (action: string): FilterType => {
  const upper = action.toUpperCase()
  if (upper.includes('DELETE') || upper.includes('REMOVE')) return 'DELETE'
  if (upper.includes('UPDATE') || upper.includes('EDIT')) return 'UPDATE'
  if (upper.includes('IMPORT')) return 'IMPORT'
  if (upper.includes('CREATE') || upper.includes('ADD')) return 'CREATE'
  return 'ALL'
}

const getBadge = (type: FilterType) => {
  switch (type) {
    case 'DELETE':
      return { label: 'Suppression', className: styles.eventDelete, icon: <Trash2 size={12} /> }
    case 'UPDATE':
      return { label: 'Modification', className: styles.eventUpdate, icon: <Edit3 size={12} /> }
    case 'CREATE':
      return { label: 'Création', className: styles.eventCreate, icon: <UserPlus size={12} /> }
    case 'IMPORT':
      return { label: 'Importation', className: styles.eventImport, icon: <FileUp size={12} /> }
    default:
      return { label: 'Action', className: styles.eventDefault, icon: <History size={12} /> }
  }
}

const initials = (label: string) => {
  const parts = label.trim().split(' ')
  return (parts[0]?.[0] || '') + (parts[1]?.[0] || '')
}

export default function AuditTab() {
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [users, setUsers] = useState<AuditUser[]>([])
  const [filter, setFilter] = useState<FilterType>('ALL')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const [logsRes, usersRes] = await Promise.all([
          getAuditLogs({ limit: 200, offset: 0 }),
          getAuditUsers(),
        ])
        if (!cancelled) {
          setLogs(Array.isArray(logsRes) ? logsRes : [])
          setUsers(Array.isArray(usersRes) ? usersRes : [])
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const userMap = useMemo(() => {
    const map = new Map<string, string>()
    users.forEach((u) => {
      map.set(u.id, u.label || u.email || u.id)
    })
    return map
  }, [users])

  const filteredLogs = useMemo(() => {
    const term = query.trim().toLowerCase()
    return logs.filter((log) => {
      const type = getTypeFromAction(log.action)
      if (filter !== 'ALL' && type !== filter) return false
      if (!term) return true
      const label = userMap.get(log.user_id || '') || ''
      return (
        label.toLowerCase().includes(term) ||
        (log.action || '').toLowerCase().includes(term) ||
        (log.entity_type || '').toLowerCase().includes(term) ||
        (log.entity_id || '').toLowerCase().includes(term)
      )
    })
  }, [logs, filter, query, userMap])

  return (
    <div className={styles.wrapper}>
      <div className={styles.filters}>
        <div className={styles.filterGroup}>
          <Filter size={16} />
          <span className={styles.filterLabel}>Filtrer par</span>
          {(['ALL', 'CREATE', 'UPDATE', 'DELETE', 'IMPORT'] as FilterType[]).map((type) => (
            <button
              key={type}
              type="button"
              className={`${styles.filterBtn} ${filter === type ? styles.filterBtnActive : ''}`}
              onClick={() => setFilter(type)}
            >
              {type === 'ALL' ? 'Toutes' : type}
            </button>
          ))}
        </div>
        <div className={styles.search}>
          <Search size={14} className={styles.searchIcon} />
          <input
            type="text"
            placeholder="Rechercher un utilisateur..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <button
          type="button"
          className={styles.exportBtn}
          onClick={() => exportAuditToPDF(filteredLogs, { userLabelMap: userMap })}
          disabled={loading || filteredLogs.length === 0}
        >
          <DownloadCloud size={16} /> Export PDF
        </button>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Date & Heure</th>
              <th>Utilisateur</th>
              <th>Événement</th>
              <th>Cible</th>
            </tr>
          </thead>
          <tbody>
            {filteredLogs.map((log) => {
              const type = getTypeFromAction(log.action)
              const badge = getBadge(type)
              const label = userMap.get(log.user_id || '') || log.user_id || '—'
              return (
                <tr key={log.id}>
                  <td>{new Date(log.created_at).toLocaleString('fr-FR')}</td>
                  <td>
                    <div className={styles.userCell}>
                      <div className={styles.userAvatar}>{initials(label)}</div>
                      <span>{label}</span>
                    </div>
                  </td>
                  <td>
                    <span className={`${styles.eventBadge} ${badge.className}`}>
                      {badge.icon} {badge.label}
                    </span>
                  </td>
                  <td>
                    {(log.entity_type || 'N/A')}{log.entity_id ? ` • ${log.entity_id}` : ''}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {!loading && filteredLogs.length === 0 && (
          <div className={styles.emptyState}>Aucune activité enregistrée.</div>
        )}
        {loading && <div className={styles.emptyState}>Chargement…</div>}
      </div>
    </div>
  )
}
