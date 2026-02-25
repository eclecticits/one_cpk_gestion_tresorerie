import { Edit2, PenTool, Trash2 } from 'lucide-react'
import type { CommissionMember } from '../../types'
import styles from './MemberCard.module.css'

type Props = {
  member: CommissionMember
  serviceBadges?: string[]
  onEdit?: () => void
  onDelete?: () => void
  onToggleSigner?: () => void
}

const roleLabels: Record<CommissionMember['role_type'], string> = {
  PRESIDENT: 'Président',
  DELEGUE: 'Délégué',
  MEMBRE: 'Membre',
  ASSISTANT: 'Assistant',
}

export default function MemberCard({ member, serviceBadges, onEdit, onDelete, onToggleSigner }: Props) {
  const roleLabel = roleLabels[member.role_type] || 'Membre'
  const roleClass =
    member.role_type === 'PRESIDENT'
      ? styles.rolePresident
      : member.role_type === 'DELEGUE'
      ? styles.roleDelegate
      : member.role_type === 'ASSISTANT'
      ? styles.roleAssistant
      : styles.roleMember

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.matricule}>{member.matricule || 'N/A'}</span>
        <div className={styles.actions}>
          {onEdit && (
            <button type="button" onClick={onEdit} className={styles.iconBtn} aria-label="Modifier">
              <Edit2 size={14} />
            </button>
          )}
          {onDelete && (
            <button type="button" onClick={onDelete} className={styles.iconBtnDanger} aria-label="Retirer">
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>

      <div className={styles.identity}>
        <h4 className={styles.name}>{member.full_name || 'Sans nom'}</h4>
        <p className={styles.email}>{member.email || 'Email non renseigné'}</p>
      </div>

      {serviceBadges && serviceBadges.length > 0 && (
        <div className={styles.services}>
          {serviceBadges.map((service) => (
            <span key={service} className={styles.serviceBadge}>
              {service}
            </span>
          ))}
        </div>
      )}

      <div className={styles.badges}>
        <span className={`${styles.roleBadge} ${roleClass}`}>{roleLabel}</span>
        <button
          type="button"
          className={`${styles.signerBadge} ${member.is_signer ? styles.signerActive : styles.signerInactive}`}
          onClick={onToggleSigner}
          disabled={!onToggleSigner}
        >
          <PenTool size={10} />
          {member.is_signer ? 'Signataire' : 'Non signataire'}
        </button>
      </div>
    </div>
  )
}
