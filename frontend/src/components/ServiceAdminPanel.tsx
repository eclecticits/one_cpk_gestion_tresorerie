import { Building2, CheckCircle2, Pencil, Plus, Power, ShieldCheck } from 'lucide-react'
import type { FormEvent } from 'react'
import { useEffect, useMemo, useState } from 'react'
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

  const handleCreateService = async (event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault()
    if (createLoading) {
      return
    }

    try {
      setCreateLoading(true)
      setError(null)
      await createService({ code: createCode, libelle: createLibelle, is_active: true })
      setCreateCode('')
      setCreateLibelle('')
      await handleUpdated()
    } catch (err: any) {
      setError(err?.message || 'Création impossible.')
    } finally {
      setCreateLoading(false)
    }
  }

  const sortedServices = useMemo(
    () => [...services].sort((a, b) => a.code.localeCompare(b.code, 'fr', { sensitivity: 'base' })),
    [services]
  )

  return (
    <section className={styles.manage}>
      <div className={styles.manageHeader}>
        <div className={styles.manageHeaderIcon}>
          <Building2 size={20} />
        </div>
        <div>
          <h2>Administration des services</h2>
          <span>Ajouter, modifier ou activer/désactiver les commissions.</span>
        </div>
      </div>

      {error && <div className={styles.stateError}>{error}</div>}
      {loading && <div className={styles.state}>Chargement...</div>}

      {!loading && (
        <>
          <form className={styles.manageForm} onSubmit={handleCreateService}>
            <div className={styles.formField}>
              <label htmlFor="service-code">Code</label>
              <input
                id="service-code"
                type="text"
                placeholder="Ex : FORCO"
                value={createCode}
                onChange={(e) => setCreateCode(e.target.value)}
              />
            </div>
            <div className={styles.formField}>
              <label htmlFor="service-libelle">Libellé</label>
              <input
                id="service-libelle"
                type="text"
                placeholder="Nom de la commission"
                value={createLibelle}
                onChange={(e) => setCreateLibelle(e.target.value)}
              />
            </div>
            <div className={styles.formAction}>
              <button
                type="submit"
                className={styles.addBtn}
                disabled={createLoading || !createCode.trim() || !createLibelle.trim()}
              >
                <Plus size={16} />
                <span>{createLoading ? 'Création…' : 'Ajouter'}</span>
              </button>
            </div>
          </form>

          <div className={styles.tableCard}>
            <div className={styles.tableHeader}>
              <div className={styles.tableTitleWrap}>
                <div className={styles.tableTitle}>Commissions configurées</div>
                <div className={styles.tableSubtitle}>Gérez la liste des services disponibles dans votre espace.</div>
              </div>
              <div className={styles.tableCount}>
                <ShieldCheck size={16} />
                <span>{sortedServices.length} service{sortedServices.length > 1 ? 's' : ''}</span>
              </div>
            </div>

            <div className={styles.desktopTable}>
              <div className={styles.tableHead}>
                <div>Code</div>
                <div>Libellé</div>
                <div>Statut</div>
                <div>Actions</div>
              </div>
              <div className={styles.tableBody}>
                {sortedServices.map((service) => (
                  <div key={service.id} className={styles.tableRow}>
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
                        <div className={service.is_active ? styles.statusBadgeActive : styles.statusBadgeInactive}>
                          <span className={styles.statusDot} />
                          {service.is_active ? 'Actif' : 'Inactif'}
                        </div>
                        <div className={styles.manageActions}>
                          <button
                            type="button"
                            className={styles.primaryBtn}
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
                            <CheckCircle2 size={16} />
                            <span>{editLoading ? 'Sauvegarde…' : 'Sauvegarder'}</span>
                          </button>
                          <button type="button" className={styles.secondaryBtn} onClick={() => setEditingId(null)}>
                            Annuler
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        <div><span className={styles.codeBadge}>{service.code}</span></div>
                        <div className={styles.manageLibelle}>{service.libelle}</div>
                        <div className={service.is_active ? styles.statusBadgeActive : styles.statusBadgeInactive}>
                          <span className={styles.statusDot} />
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
                            <Pencil size={16} />
                            <span>Modifier</span>
                          </button>
                          <button
                            type="button"
                            className={service.is_active ? styles.dangerSoftBtn : styles.successBtn}
                            onClick={async () => {
                              try {
                                await updateService(service.id, { is_active: !service.is_active })
                                await handleUpdated()
                              } catch (err: any) {
                                setError(err?.message || 'Action impossible.')
                              }
                            }}
                          >
                            <Power size={16} />
                            <span>{service.is_active ? 'Désactiver' : 'Activer'}</span>
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className={styles.mobileCards}>
              {sortedServices.map((service) => (
                <div key={service.id} className={styles.mobileCard}>
                  {editingId === service.id ? (
                    <>
                      <div className={styles.mobileCardTop}>
                        <span className={styles.codeBadge}>{service.code}</span>
                        <div className={service.is_active ? styles.statusBadgeActive : styles.statusBadgeInactive}>
                          <span className={styles.statusDot} />
                          {service.is_active ? 'Actif' : 'Inactif'}
                        </div>
                      </div>
                      <div className={styles.mobileEditGrid}>
                        <div className={styles.formField}>
                          <label>Code</label>
                          <input type="text" value={editCode} onChange={(e) => setEditCode(e.target.value)} />
                        </div>
                        <div className={styles.formField}>
                          <label>Libellé</label>
                          <input type="text" value={editLibelle} onChange={(e) => setEditLibelle(e.target.value)} />
                        </div>
                      </div>
                      <div className={styles.manageActions}>
                        <button
                          type="button"
                          className={styles.primaryBtn}
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
                          <CheckCircle2 size={16} />
                          <span>{editLoading ? 'Sauvegarde…' : 'Sauvegarder'}</span>
                        </button>
                        <button type="button" className={styles.secondaryBtn} onClick={() => setEditingId(null)}>
                          Annuler
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className={styles.mobileCardTop}>
                        <span className={styles.codeBadge}>{service.code}</span>
                        <div className={service.is_active ? styles.statusBadgeActive : styles.statusBadgeInactive}>
                          <span className={styles.statusDot} />
                          {service.is_active ? 'Actif' : 'Inactif'}
                        </div>
                      </div>
                      <div className={styles.mobileCardTitle}>{service.libelle}</div>
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
                          <Pencil size={16} />
                          <span>Modifier</span>
                        </button>
                        <button
                          type="button"
                          className={service.is_active ? styles.dangerSoftBtn : styles.successBtn}
                          onClick={async () => {
                            try {
                              await updateService(service.id, { is_active: !service.is_active })
                              await handleUpdated()
                            } catch (err: any) {
                              setError(err?.message || 'Action impossible.')
                            }
                          }}
                        >
                          <Power size={16} />
                          <span>{service.is_active ? 'Désactiver' : 'Activer'}</span>
                        </button>
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>

            {sortedServices.length === 0 && <div className={styles.state}>Aucun service disponible.</div>}
          </div>
        </>
      )}
    </section>
  )
}
