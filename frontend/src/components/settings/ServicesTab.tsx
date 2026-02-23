import { useMemo, useState } from 'react'
import { Building2, Mail, ShieldCheck, UserPlus, Users2 } from 'lucide-react'
import type { Service, User } from '../../types'
import AssignResponsableModal from '../modals/AssignResponsableModal'
import styles from './ServicesTab.module.css'

type Props = {
  services: Service[]
  users: User[]
  onAssign: (serviceId: number, userId: string | null) => Promise<void>
}

export default function ServicesTab({ services, users, onAssign }: Props) {
  const [selectedService, setSelectedService] = useState<Service | null>(null)

  const sortedServices = useMemo(() => {
    return [...services].sort((a, b) => a.code.localeCompare(b.code))
  }, [services])

  return (
    <div>
      <div className={styles.header}>
        <h2>Services & Commissions</h2>
        <p>Assignez un responsable et suivez l’organisation des commissions.</p>
      </div>

      <div className={styles.grid}>
        {sortedServices.map((service) => {
          const responsable = service.responsable
          const label = responsable
            ? `${responsable.prenom || ''} ${responsable.nom || ''}`.trim() || responsable.email || 'Responsable'
            : ''
          return (
            <div key={service.id} className={styles.card}>
              <div className={styles.cardHeader}>
                <div className={styles.icon}>
                  <Building2 size={22} />
                </div>
                <span className={styles.badge}>ID {service.code}</span>
              </div>
              <div className={styles.title}>{service.libelle}</div>

              <div className={styles.responsable}>
                <p className={styles.badge} style={{ marginBottom: 8 }}>
                  Responsable
                </p>
                {responsable ? (
                  <div className={styles.responsableInfo}>
                    <div className={styles.responsableAvatar}>{label ? label[0] : '?'}</div>
                    <div>
                      <div className={styles.responsableName}>{label}</div>
                      {responsable.email && (
                        <div className={styles.responsableEmail}>
                          <Mail size={12} /> {responsable.email}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className={styles.responsableEmpty}>
                    <Users2 size={18} />
                    Aucun responsable assigné
                  </div>
                )}
              </div>

              <div className={styles.actions}>
                <button
                  type="button"
                  className={styles.primaryBtn}
                  onClick={() => setSelectedService(service)}
                >
                  <UserPlus size={16} /> {responsable ? 'Changer' : 'Assigner'}
                </button>
                <button type="button" className={styles.ghostBtn} title="Accès & rubriques">
                  <ShieldCheck size={18} />
                </button>
              </div>
            </div>
          )
        })}
        {sortedServices.length === 0 && (
          <div className={styles.responsableEmpty}>Aucun service disponible.</div>
        )}
      </div>

      {selectedService && (
        <AssignResponsableModal
          service={selectedService}
          users={users}
          onClose={() => setSelectedService(null)}
          onConfirm={async (serviceId, userId) => {
            await onAssign(serviceId, userId)
            setSelectedService(null)
          }}
        />
      )}
    </div>
  )
}
