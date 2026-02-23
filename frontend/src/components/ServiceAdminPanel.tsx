import { useEffect, useState } from 'react'
import { createService, getServices, updateService } from '../api/services'
import type { Service } from '../types'
import styles from './ServiceAdminPanel.module.css'

export default function ServiceAdminPanel({ onUpdated }: { onUpdated?: () => void | Promise<void> }) {
  const [services, setServices] = useState<Service[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [createCode, setCreateCode] = useState('')
  const [createLibelle, setCreateLibelle] = useState('')
  const [createLoading, setCreateLoading] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editCode, setEditCode] = useState('')
  const [editLibelle, setEditLibelle] = useState('')
  const [editLoading, setEditLoading] = useState(false)

  const loadServices = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await getServices()
      setServices(Array.isArray(response) ? response : [])
    } catch (err: any) {
      setError(err?.message || 'Erreur de chargement des services.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadServices()
  }, [])

  const handleUpdated = async () => {
    await loadServices()
    if (onUpdated) {
      await onUpdated()
    }
  }

  return (
    <section className={styles.manage}>
      <div className={styles.manageHeader}>
        <h2>Administration des services</h2>
        <span>Ajouter, modifier ou activer/désactiver les commissions.</span>
      </div>

      {error && <div className={styles.stateError}>{error}</div>}
      {loading && <div className={styles.state}>Chargement...</div>}

      {!loading && (
        <>
          <div className={styles.manageForm}>
            <input
              type="text"
              placeholder="Code (ex: FORCO)"
              value={createCode}
              onChange={(e) => setCreateCode(e.target.value)}
            />
            <input
              type="text"
              placeholder="Libellé"
              value={createLibelle}
              onChange={(e) => setCreateLibelle(e.target.value)}
            />
            <button
              type="button"
              disabled={createLoading || !createCode.trim() || !createLibelle.trim()}
              onClick={async () => {
                try {
                  setCreateLoading(true)
                  await createService({ code: createCode, libelle: createLibelle, is_active: true })
                  setCreateCode('')
                  setCreateLibelle('')
                  await handleUpdated()
                } catch (err: any) {
                  setError(err?.message || 'Création impossible.')
                } finally {
                  setCreateLoading(false)
                }
              }}
            >
              {createLoading ? 'Création…' : 'Ajouter'}
            </button>
          </div>

          <div className={styles.manageList}>
            {services.map((service) => (
              <div key={service.id} className={styles.manageRow}>
                {editingId === service.id ? (
                  <>
                    <input
                      type="text"
                      value={editCode}
                      onChange={(e) => setEditCode(e.target.value)}
                    />
                    <input
                      type="text"
                      value={editLibelle}
                      onChange={(e) => setEditLibelle(e.target.value)}
                    />
                    <div className={styles.manageActions}>
                      <button
                        type="button"
                        disabled={editLoading || !editCode.trim() || !editLibelle.trim()}
                        onClick={async () => {
                          try {
                            setEditLoading(true)
                            await updateService(service.id, { code: editCode, libelle: editLibelle })
                            setEditingId(null)
                            await handleUpdated()
                          } catch (err: any) {
                            setError(err?.message || 'Mise à jour impossible.')
                          } finally {
                            setEditLoading(false)
                          }
                        }}
                      >
                        {editLoading ? 'Sauvegarde…' : 'Sauvegarder'}
                      </button>
                      <button
                        type="button"
                        className={styles.secondaryBtn}
                        onClick={() => setEditingId(null)}
                      >
                        Annuler
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className={styles.manageCode}>{service.code}</div>
                    <div className={styles.manageLibelle}>{service.libelle}</div>
                    <div className={styles.manageStatus}>
                      {service.is_active ? 'Actif' : 'Inactif'}
                    </div>
                    <div className={styles.manageActions}>
                      <button
                        type="button"
                        className={styles.secondaryBtn}
                        onClick={() => {
                          setEditingId(service.id)
                          setEditCode(service.code)
                          setEditLibelle(service.libelle)
                        }}
                      >
                        Modifier
                      </button>
                      <button
                        type="button"
                        className={service.is_active ? styles.dangerBtn : styles.primaryBtn}
                        onClick={async () => {
                          try {
                            await updateService(service.id, { is_active: !service.is_active })
                            await handleUpdated()
                          } catch (err: any) {
                            setError(err?.message || 'Action impossible.')
                          }
                        }}
                      >
                        {service.is_active ? 'Désactiver' : 'Activer'}
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
            {services.length === 0 && <div className={styles.state}>Aucun service disponible.</div>}
          </div>
        </>
      )}
    </section>
  )
}
