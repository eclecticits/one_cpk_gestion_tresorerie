import { useEffect, useMemo, useState } from 'react'
import { getAuditLogs, getAuditActions, getAuditUsers, AuditLog, AuditLogFilters, AuditUser } from '../api/auditLogs'
import { ApiError, API_BASE_URL, getAccessToken } from '../lib/apiClient'
import { useToast } from '../hooks/useToast'
import styles from './AuditLogs.module.css'

const DEFAULT_LIMIT = 200

const formatDate = (value: string) => {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('fr-FR')
}

const formatJson = (value: any) => {
  if (!value) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

  const downloadCsv = (rows: AuditLog[]) => {
    if (!rows.length) return
    const headers = [
      'id',
      'created_at',
      'action',
      'entity_type',
      'entity_id',
      'user_id',
      'ip_address',
      'old_value',
      'new_value',
    ]
  const escape = (value: any) => {
    const str = value === null || value === undefined ? '' : String(value)
    return `"${str.replace(/"/g, '""')}"`
  }
  const lines = [
    headers.join(','),
    ...rows.map((row) =>
      [
        row.id,
        row.created_at,
        row.action,
        row.entity_type || '',
        row.entity_id || '',
        row.user_id || '',
        row.ip_address || '',
        formatJson(row.old_value),
        formatJson(row.new_value),
      ]
        .map(escape)
        .join(',')
    ),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `audit_logs_${new Date().toISOString().slice(0, 10)}.csv`
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export default function AuditLogs() {
  const { notifyError } = useToast()
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [actions, setActions] = useState<string[]>([])
  const [users, setUsers] = useState<AuditUser[]>([])
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [filters, setFilters] = useState<AuditLogFilters>({
    action: '',
    user_id: '',
    target_table: '',
    target_id: '',
    date_debut: '',
    date_fin: '',
    limit: DEFAULT_LIMIT,
    offset: 0,
  })
  const [appliedFilters, setAppliedFilters] = useState<AuditLogFilters>(filters)

  const activeFiltersLabel = useMemo(() => {
    const parts: string[] = []
    if (appliedFilters.action) parts.push(`Action: ${appliedFilters.action}`)
    if (appliedFilters.user_id) parts.push(`Utilisateur: ${appliedFilters.user_id}`)
    if (appliedFilters.target_table) parts.push(`Type: ${appliedFilters.target_table}`)
    if (appliedFilters.target_id) parts.push(`Cible: ${appliedFilters.target_id}`)
    if (appliedFilters.date_debut) parts.push(`Du: ${appliedFilters.date_debut}`)
    if (appliedFilters.date_fin) parts.push(`Au: ${appliedFilters.date_fin}`)
    return parts.join(' · ')
  }, [appliedFilters])

  const userLabelMap = useMemo(() => {
    const map = new Map<string, string>()
    users.forEach((u) => {
      map.set(u.id, u.label || u.email || u.id)
    })
    return map
  }, [users])

  useEffect(() => {
    const fetchLogs = async () => {
      setLoading(true)
      try {
        const data = await getAuditLogs(appliedFilters)
        setLogs(data || [])
      } catch (error) {
        const detail =
          error instanceof ApiError
            ? error.payload?.detail || `HTTP ${error.status}`
            : 'Erreur inconnue'
        notifyError('Chargement impossible', detail)
        setLogs([])
      } finally {
        setLoading(false)
      }
    }

    fetchLogs()
  }, [appliedFilters, notifyError])

  useEffect(() => {
    const fetchActions = async () => {
      try {
        const data = await getAuditActions()
        setActions(data || [])
      } catch (error) {
        console.error('Erreur chargement actions audit:', error)
      }
    }
    fetchActions()
  }, [])

  useEffect(() => {
    const fetchUsers = async () => {
      try {
        const data = await getAuditUsers()
        setUsers(data || [])
      } catch (error) {
        console.error('Erreur chargement utilisateurs audit:', error)
      }
    }
    fetchUsers()
  }, [])

  const handleApply = () => {
    setAppliedFilters({ ...filters, limit: DEFAULT_LIMIT, offset: 0 })
  }

  const handleReset = () => {
    const reset: AuditLogFilters = {
      action: '',
      user_id: '',
      target_table: '',
      target_id: '',
      date_debut: '',
      date_fin: '',
      limit: DEFAULT_LIMIT,
      offset: 0,
    }
    setFilters(reset)
    setAppliedFilters(reset)
  }

  const handleServerExport = async () => {
    setExporting(true)
    try {
      const params = new URLSearchParams()
      Object.entries(appliedFilters).forEach(([key, value]) => {
        if (value === undefined || value === null || value === '') return
        params.set(key, String(value))
      })
      const token = getAccessToken()
      const url = `${API_BASE_URL}/audit-logs/export?${params.toString()}`
      const resp = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!resp.ok) {
        const message = await resp.text()
        throw new Error(message || `HTTP ${resp.status}`)
      }
      const blob = await resp.blob()
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = `audit_logs_${new Date().toISOString().slice(0, 10)}.csv`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(link.href)
    } catch (error) {
      notifyError('Export impossible', error instanceof Error ? error.message : 'Erreur inconnue')
    } finally {
      setExporting(false)
    }
  }

  const handleServerExportXlsx = async () => {
    setExporting(true)
    try {
      const params = new URLSearchParams()
      Object.entries(appliedFilters).forEach(([key, value]) => {
        if (value === undefined || value === null || value === '') return
        params.set(key, String(value))
      })
      const token = getAccessToken()
      const url = `${API_BASE_URL}/audit-logs/export-xlsx?${params.toString()}`
      const resp = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!resp.ok) {
        const message = await resp.text()
        throw new Error(message || `HTTP ${resp.status}`)
      }
      const blob = await resp.blob()
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = `audit_logs_${new Date().toISOString().slice(0, 10)}.xlsx`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(link.href)
    } catch (error) {
      notifyError('Export impossible', error instanceof Error ? error.message : 'Erreur inconnue')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1>Audit système</h1>
        <p>Historique des actions sensibles (RBAC, validations, sorties de fonds, etc.).</p>
      </header>

      <section className={styles.filters}>
        <div className={styles.field}>
          <label>Action</label>
          <select
            value={filters.action || ''}
            onChange={(e) => setFilters((prev) => ({ ...prev, action: e.target.value }))}
          >
            <option value="">Toutes</option>
            {actions.map((action) => (
              <option key={action} value={action}>
                {action}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.field}>
          <label>Utilisateur (ID)</label>
          <select
            value={filters.user_id || ''}
            onChange={(e) => setFilters((prev) => ({ ...prev, user_id: e.target.value }))}
          >
            <option value="">Tous</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.label}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.field}>
          <label>Type</label>
          <input
            value={filters.target_table || ''}
            onChange={(e) => setFilters((prev) => ({ ...prev, target_table: e.target.value }))}
            placeholder="ex: requisitions"
          />
        </div>
        <div className={styles.field}>
          <label>ID cible</label>
          <input
            value={filters.target_id || ''}
            onChange={(e) => setFilters((prev) => ({ ...prev, target_id: e.target.value }))}
            placeholder="UUID ou id"
          />
        </div>
        <div className={styles.field}>
          <label>Date début</label>
          <input
            type="date"
            value={filters.date_debut || ''}
            onChange={(e) => setFilters((prev) => ({ ...prev, date_debut: e.target.value }))}
          />
        </div>
        <div className={styles.field}>
          <label>Date fin</label>
          <input
            type="date"
            value={filters.date_fin || ''}
            onChange={(e) => setFilters((prev) => ({ ...prev, date_fin: e.target.value }))}
          />
        </div>
        <div className={styles.actions}>
          <button type="button" onClick={handleApply} disabled={loading}>
            {loading ? 'Chargement...' : 'Appliquer'}
          </button>
          <button type="button" className={styles.secondary} onClick={handleReset} disabled={loading}>
            Réinitialiser
          </button>
          <button
            type="button"
            className={styles.secondary}
            onClick={() => downloadCsv(logs)}
            disabled={loading || logs.length === 0}
          >
            Export CSV
          </button>
          <button
            type="button"
            className={styles.secondary}
            onClick={handleServerExport}
            disabled={loading || exporting}
          >
            {exporting ? 'Export...' : 'Export CSV (serveur)'}
          </button>
          <button
            type="button"
            className={styles.secondary}
            onClick={handleServerExportXlsx}
            disabled={loading || exporting}
          >
            {exporting ? 'Export...' : 'Export XLSX (serveur)'}
          </button>
        </div>
      </section>

      {activeFiltersLabel && (
        <div className={styles.activeFilters}>
          <span>Filtres:</span>
          <strong>{activeFiltersLabel}</strong>
        </div>
      )}

      <section className={styles.tableWrapper}>
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Action</th>
              <th>Type</th>
              <th>Cible</th>
              <th>Utilisateur</th>
              <th>IP</th>
              <th>Détails</th>
            </tr>
          </thead>
          <tbody>
            {!loading && logs.length === 0 && (
              <tr>
                <td colSpan={7} className={styles.emptyCell}>
                  Aucun événement trouvé.
                </td>
              </tr>
            )}
            {logs.map((log) => (
              <tr key={log.id}>
                <td>{formatDate(log.created_at)}</td>
                <td className={styles.actionCell}>{log.action}</td>
                <td>{log.entity_type || '-'}</td>
                <td>{log.entity_id || '-'}</td>
                <td>{(log.user_id && userLabelMap.get(log.user_id)) || log.user_id || '-'}</td>
                <td>{log.ip_address || '-'}</td>
                <td>
                  <details className={styles.details}>
                    <summary>Voir</summary>
                    <div>
                      <div className={styles.detailBlock}>
                        <span>Avant</span>
                        <pre>{formatJson(log.old_value) || '-'}</pre>
                      </div>
                      <div className={styles.detailBlock}>
                        <span>Après</span>
                        <pre>{formatJson(log.new_value) || '-'}</pre>
                      </div>
                    </div>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
