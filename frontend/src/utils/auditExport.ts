import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'

type AuditLike = {
  created_at: string
  action: string
  entity_type?: string | null
  entity_id?: string | null
  user_id?: string | null
  old_value?: any
  new_value?: any
}

type ExportOptions = {
  title?: string
  userLabelMap?: Map<string, string>
}

const ACTION_LABELS: Record<string, string> = {
  ROLE_PERMISSIONS_UPDATED: 'Mise à jour des permissions',
  ROLE_CREATED: 'Création d’un rôle',
  ROLE_UPDATED: 'Modification d’un rôle',
  ROLE_DELETED: 'Suppression d’un rôle',
  USER_CREATED: 'Création d’utilisateur',
  USER_UPDATED: 'Modification d’utilisateur',
  USER_DELETED: 'Suppression d’utilisateur',
  USER_PASSWORD_RESET: 'Réinitialisation du mot de passe',
  USER_STATUS_TOGGLED: 'Changement du statut utilisateur',
  REQUISITION_CREATED: 'Création de réquisition',
  REQUISITION_UPDATED: 'Modification de réquisition',
  REQUISITION_DELETED: 'Suppression de réquisition',
  SERVICE_CREATED: 'Création de service',
  SERVICE_UPDATED: 'Modification de service',
  SERVICE_DELETED: 'Suppression de service',
  SETTINGS_UPDATED: 'Mise à jour des paramètres',
}

const humanize = (value: string) =>
  value
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^./, (c) => c.toUpperCase())

const formatValue = (value: any) => {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

const getChangedFields = (oldValue: any, newValue: any) => {
  const oldObj = typeof oldValue === 'object' && oldValue ? oldValue : {}
  const newObj = typeof newValue === 'object' && newValue ? newValue : {}
  const keys = new Set([...Object.keys(oldObj), ...Object.keys(newObj)])
  const changed: string[] = []
  keys.forEach((key) => {
    const before = (oldObj as any)[key]
    const after = (newObj as any)[key]
    if (JSON.stringify(before) !== JSON.stringify(after)) {
      changed.push(humanize(key))
    }
  })
  return changed
}

const buildDetails = (log: AuditLike) => {
  const changed = getChangedFields(log.old_value, log.new_value)
  if (changed.length > 0) {
    return `Champs modifiés: ${changed.join(', ')}`
  }
  if (log.new_value) return `Après: ${formatValue(log.new_value)}`
  if (log.old_value) return `Avant: ${formatValue(log.old_value)}`
  return '—'
}

export const exportAuditToPDF = (logs: AuditLike[], options: ExportOptions = {}) => {
  const doc = new jsPDF({ orientation: 'landscape' })
  const title = options.title || "ONEC-CPK : Journal d'audit"

  doc.setFontSize(16)
  doc.text(title, 14, 18)
  doc.setFontSize(10)
  doc.setTextColor(90)
  doc.text(`Rapport généré le : ${format(new Date(), 'dd/MM/yyyy HH:mm')}`, 14, 26)

  const rows = logs.map((log) => {
    const userLabel =
      (log.user_id && options.userLabelMap?.get(log.user_id)) ||
      log.user_id ||
      '—'
    const actionLabel = ACTION_LABELS[log.action] || humanize(log.action || '')
    const cible = log.entity_type
      ? `${humanize(log.entity_type)}${log.entity_id ? ` #${log.entity_id}` : ''}`
      : log.entity_id
        ? `#${log.entity_id}`
        : '—'
    return [
      format(new Date(log.created_at), 'dd/MM/yyyy HH:mm'),
      userLabel,
      actionLabel,
      cible,
      buildDetails(log),
    ]
  })

  autoTable(doc, {
    startY: 34,
    head: [['Date', 'Utilisateur', 'Action', 'Cible', 'Détails']],
    body: rows,
    headStyles: { fillColor: [30, 41, 59], textColor: [255, 255, 255], fontStyle: 'bold' },
    alternateRowStyles: { fillColor: [248, 250, 252] },
    margin: { top: 30, left: 12, right: 12 },
    styles: { fontSize: 9, cellPadding: 3 },
    columnStyles: {
      0: { cellWidth: 36 },
      1: { cellWidth: 45 },
      2: { cellWidth: 45 },
      3: { cellWidth: 45 },
      4: { cellWidth: 90 },
    },
  })

  doc.save(`Audit_Log_ONEC_${format(new Date(), 'yyyyMMdd')}.pdf`)
}
