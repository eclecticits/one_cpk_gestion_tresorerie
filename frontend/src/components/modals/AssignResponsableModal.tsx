import { useMemo, useState } from 'react'
import { Mail, Search, UserCheck, X } from 'lucide-react'
import styles from './AssignResponsableModal.module.css'
import type { Service, User } from '../../types'

type Props = {
  service: Service
  users: User[]
  onConfirm: (serviceId: number, userId: string | null) => void
  onClose: () => void
}

export default function AssignResponsableModal({ service, users, onConfirm, onClose }: Props) {
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedUserId, setSelectedUserId] = useState<string | null>(
    service.responsable?.id || service.responsable_id || null
  )

  const filteredUsers = useMemo(() => {
    const term = searchTerm.trim().toLowerCase()
    if (!term) return users
    return users.filter((u) => {
      const name = `${u.prenom || ''} ${u.nom || ''}`.toLowerCase()
      return name.includes(term) || (u.email || '').toLowerCase().includes(term)
    })
  }, [searchTerm, users])

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <div className={styles.header}>
          <div className={styles.headerTitle}>
            <h3>Assigner un responsable</h3>
            <p>{service.code} · {service.libelle}</p>
          </div>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Fermer">
            <X size={18} />
          </button>
        </div>
        <div className={styles.body}>
          <div className={styles.search}>
            <Search size={16} className={styles.searchIcon} />
            <input
              type="text"
              placeholder="Rechercher un utilisateur..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>

          <div className={styles.list}>
            {filteredUsers.map((u) => {
              const label = `${u.prenom || ''} ${u.nom || ''}`.trim() || u.email
              const active = selectedUserId === u.id
              return (
                <button
                  key={u.id}
                  type="button"
                  className={`${styles.userOption} ${active ? styles.userOptionActive : ''}`}
                  onClick={() => setSelectedUserId(u.id)}
                >
                  <div className={styles.userInfo}>
                    <div className={styles.avatar}>{(label || '?')[0]}</div>
                    <div>
                      <div className={styles.userName}>{label}</div>
                      <div className={styles.userMeta}>
                        <Mail size={12} />
                        <span>{u.email}</span>
                      </div>
                    </div>
                  </div>
                  {active && <UserCheck size={18} color="#4f46e5" />}
                </button>
              )
            })}
          </div>

          <div className={styles.actions}>
            <button type="button" className={styles.btnSecondary} onClick={onClose}>
              Annuler
            </button>
            <button
              type="button"
              className={styles.btnPrimary}
              onClick={() => onConfirm(service.id, selectedUserId)}
              disabled={!selectedUserId}
            >
              Confirmer
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
