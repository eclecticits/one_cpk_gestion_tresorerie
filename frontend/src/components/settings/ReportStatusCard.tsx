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
  /** Variable d'environnement qui active ce rapport, nommée quand il est désactivé. */
  variableActivation: string
}

function formatDate(value: string | null) {
  return value ? ` ${new Date(value).toLocaleString('fr-FR')}` : ' —'
}

// Carte de statut d'un rapport planifié (hebdomadaire ou mensuel).
// « Inactif » recouvrait deux pannes sans rapport : un rapport qu'aucune
// configuration n'a activé, et un planificateur activé qui ne tourne pas. La
// première se règle dans le .env, la seconde en redémarrant le service.
function etatPlanificateur(status: WeeklyReportStatus | MonthlyReportStatus, variableActivation: string) {
  if (!status.enabled) {
    return {
      classe: styles.badgeInactive,
      libelle: 'Désactivé dans la configuration',
      explication: (
        <>
          Aucun envoi automatique : mettez{' '}
          <code className={styles.inlineCode}>{variableActivation}=true</code> dans le fichier{' '}
          <code className={styles.inlineCode}>.env</code> du serveur, puis redémarrez le backend.
        </>
      ),
    }
  }
  if (status.host === 'exports-worker') {
    // L'API ne voit pas l'ordonnanceur du worker : ni « Actif » ni « Arrêté ».
    return {
      classe: styles.badgeActive,
      libelle: 'Porté par le worker',
      explication: (
        <>
          Les envois partent du conteneur <code className={styles.inlineCode}>exports-worker</code> : il doit
          être en marche pour que le rapport parte.
        </>
      ),
    }
  }
  if (status.running) {
    return { classe: styles.badgeActive, libelle: 'Actif', explication: null }
  }
  return {
    classe: styles.badgeWarning,
    libelle: 'Arrêté',
    explication: (
      <>
        Le rapport est activé, mais le planificateur ne tourne pas dans le serveur : redémarrez le backend, puis
        consultez son journal au démarrage s'il reste arrêté.
      </>
    ),
  }
}

export default function ReportStatusCard({ status, loading, running, onRefresh, onRun, hint, variableActivation }: ReportStatusCardProps) {
  const etat = status ? etatPlanificateur(status, variableActivation) : null
  return (
    <div className={styles.weeklyCard}>
      <div className={styles.weeklyStatusRow}>
        <div>
          <div className={styles.weeklyLabel}>Statut du planificateur</div>
          <div className={styles.weeklyMeta}>
            {loading && 'Chargement...'}
            {!loading && status && (
              <>
                <span className={etat?.classe}>{etat?.libelle}</span>
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
      {etat?.explication && <div className={styles.weeklyWarning}>{etat.explication}</div>}
      {status && status.last_status === 'failed' && (
        <div className={styles.weeklyWarning}>
          Dernier envoi en échec. {status.last_error || 'Vérifiez la configuration SMTP.'}
        </div>
      )}
      <div className={styles.weeklyHint}>{hint}</div>
    </div>
  )
}
