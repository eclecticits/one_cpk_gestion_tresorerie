import styles from './DeactivateExpertModal.module.css'
import { ExpertComptable } from '../types'

interface DeactivateExpertModalProps {
  isOpen: boolean
  expert: ExpertComptable | null
  onConfirm: () => void
  onCancel: () => void
  isReactivate?: boolean
}

export default function DeactivateExpertModal({
  isOpen,
  expert,
  onConfirm,
  onCancel,
  isReactivate = false,
}: DeactivateExpertModalProps) {
  if (!isOpen || !expert) return null

  return (
    <div className={styles.overlay} onClick={onCancel}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.iconWrapper}>
          <span className={isReactivate ? styles.iconSuccess : styles.iconDanger}>
            {isReactivate ? '✓' : '⚠'}
          </span>
        </div>

        <div className={styles.content}>
          <h2 className={styles.title}>
            {isReactivate ? 'Réactiver cet expert-comptable ?' : 'Désactiver cet expert-comptable ?'}
          </h2>
          <p className={styles.subtitle}>
            {isReactivate
              ? 'Il pourra à nouveau effectuer de nouvelles opérations et sera visible dans les listes actives.'
              : 'Il ne pourra plus effectuer de nouvelles opérations, mais ses données restent conservées.'}
          </p>

          <div className={styles.expertInfo}>
            <div className={styles.expertNumber}>{expert.numero_ordre}</div>
            <div className={styles.expertName}>{expert.nom_denomination}</div>
          </div>

          {isReactivate ? (
            <div className={styles.section}>
              <div className={styles.sectionHeader}>
                <span className={styles.checkIcon}>✓</span>
                <h3>Effets de la réactivation</h3>
              </div>
              <ul className={styles.list}>
                <li>Pourra être sélectionné pour de nouvelles réquisitions</li>
                <li>Pourra recevoir de nouveaux encaissements</li>
                <li>Apparaîtra dans toutes les listes d'experts actifs</li>
                <li>Toutes ses données historiques restent accessibles</li>
              </ul>
            </div>
          ) : (
            <>
              <div className={styles.section}>
                <div className={styles.sectionHeader}>
                  <span className={styles.crossIcon}>✕</span>
                  <h3>Effets immédiats</h3>
                </div>
                <p className={styles.sectionSubtitle}>Ne pourra plus être sélectionné pour :</p>
                <ul className={styles.list}>
                  <li>Nouvelles réquisitions</li>
                  <li>Nouveaux encaissements</li>
                  <li>Nouvelles opérations</li>
                </ul>
              </div>

              <div className={styles.section}>
                <div className={styles.sectionHeader}>
                  <span className={styles.checkIcon}>✓</span>
                  <h3>Données conservées</h3>
                </div>
                <ul className={styles.list}>
                  <li>Toutes les données historiques</li>
                  <li>Les opérations déjà enregistrées</li>
                  <li>Réactivation possible à tout moment</li>
                </ul>
              </div>

              <div className={styles.note}>
                <span className={styles.infoIcon}>ℹ</span>
                <span>Cette action est réversible à tout moment.</span>
              </div>
            </>
          )}
        </div>

        <div className={styles.actions}>
          <button
            type="button"
            onClick={onCancel}
            className={styles.cancelBtn}
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={isReactivate ? styles.confirmBtn : styles.dangerBtn}
          >
            {isReactivate ? 'Réactiver' : 'Désactiver'}
          </button>
        </div>
      </div>
    </div>
  )
}
