import type { ReactNode } from 'react'
import type { MonthlyReportStatus, WeeklyReportStatus } from '../../api/admin'
import styles from '../../pages/Settings.module.css'

type ReportStatusCardProps = {
  status: WeeklyReportStatus | MonthlyReportStatus | null
  loading: boolean
  running: boolean
  onRefresh: () => void
  onRun: () => void
  hint: ReactNode
}

function formatDate(value: string | null) {
  return value ? ` ${new Date(value).toLocaleString('fr-FR')}` : ' —'
}

// Carte de statut d'un rapport planifié (hebdomadaire ou mensuel).
export default function ReportStatusCard({ status, loading, running, onRefresh, onRun, hint }: ReportStatusCardProps) {
  return (
    <div className={styles.weeklyCard}>
      <div className={styles.weeklyStatusRow}>
        <div>
          <div className={styles.weeklyLabel}>Statut du planificateur</div>
          <div className={styles.weeklyMeta}>
            {loading && 'Chargement...'}
            {!loading && status && (
              <>
                {status.enabled && status.host === 'exports-worker' ? (
                  // L'API ne voit pas l'ordonnanceur du worker : ni « Actif » ni « Inactif ».
                  <span className={styles.badgeActive}>Porté par le worker</span>
                ) : (
                  <span className={status.enabled && status.running ? styles.badgeActive : styles.badgeInactive}>
                    {status.enabled && status.running ? 'Actif' : 'Inactif'}
                  </span>
                )}
                <span>Fuseau : {status.timezone}</span>
                <span>Prochaine exécution :{formatDate(status.next_run)}</span>
                <span>Dernier envoi :{formatDate(status.last_sent_at)}</span>
                <span>Dernier succès :{formatDate(status.last_success_at)}</span>
                <span>Dernier échec :{formatDate(status.last_failure_at)}</span>
              </>
            )}
            {!loading && !status && 'Statut indisponible.'}
          </div>
        </div>
        <div className={styles.weeklyActions}>
          <button type="button" className={styles.secondaryBtn} onClick={onRefresh} disabled={loading}>
            {loading ? 'Actualisation...' : 'Actualiser'}
          </button>
          <button type="button" className={styles.primaryBtn} onClick={onRun} disabled={running}>
            {running ? 'Envoi...' : 'Envoyer maintenant'}
          </button>
        </div>
      </div>
      {status && status.last_status === 'failed' && (
        <div className={styles.weeklyWarning}>
          Dernier envoi en échec. {status.last_error || 'Vérifiez la configuration SMTP.'}
        </div>
      )}
      <div className={styles.weeklyHint}>{hint}</div>
    </div>
  )
}
