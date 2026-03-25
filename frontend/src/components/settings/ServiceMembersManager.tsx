import { useEffect, useMemo, useState } from 'react'
import { UserPlus, Users, Crown, Search } from 'lucide-react'
import type { CommissionMember, CommissionRole, Service, User } from '../../types'
import { createServiceMember, deleteServiceMember, getServiceMembers, lookupCommissionMembers, multiAssignCommissionMember, updateServiceMember } from '../../api/services'
import MemberCard from '../Gouvernance/MemberCard'
import { useConfirm } from '../../contexts/ConfirmContext'
import styles from './ServiceMembersManager.module.css'

type Props = {
  services: Service[]
  users: User[]
  activeServiceId: number | null
}

const roleLabels: Record<CommissionRole, string> = {
  PRESIDENT: 'Président',
  DELEGUE: 'Délégué',
  MEMBRE: 'Membre',
  ASSISTANT: 'Assistant',
}

export default function ServiceMembersManager({ services, users, activeServiceId }: Props) {
  const confirm = useConfirm()
  const [members, setMembers] = useState<CommissionMember[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [selectedUserId, setSelectedUserId] = useState<string>('')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [matricule, setMatricule] = useState('')
  const [roleType, setRoleType] = useState<CommissionRole>('MEMBRE')
  const [customTitle, setCustomTitle] = useState('')
  const [isSigner, setIsSigner] = useState(false)
  const [selectedServiceIds, setSelectedServiceIds] = useState<number[]>([])
  const [serviceFilter, setServiceFilter] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [lookupQuery, setLookupQuery] = useState('')
  const [lookupResults, setLookupResults] = useState<{ full_name: string; email?: string | null; matricule?: string | null }[]>([])
  const [lookupOpen, setLookupOpen] = useState(false)
  const [lookupLoading, setLookupLoading] = useState(false)
  const [lastAutoFilledMatricule, setLastAutoFilledMatricule] = useState('')
  const [editingMemberId, setEditingMemberId] = useState<number | null>(null)

  const activeService = services.find((service) => service.id === activeServiceId) || null

  useEffect(() => {
    if (!activeServiceId) {
      setMembers([])
      return
    }
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await getServiceMembers(activeServiceId)
        setMembers(Array.isArray(res) ? res : [])
      } catch (err: any) {
        setError(err?.message || 'Impossible de charger les membres.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [activeServiceId])

  useEffect(() => {
    if (!selectedUserId) return
    const user = users.find((u) => String(u.id) === String(selectedUserId))
    if (!user) return
    const label = `${user.prenom || ''} ${user.nom || ''}`.trim() || user.email || ''
    if (label) {
      setFullName(label)
    }
    if (user.email) {
      setEmail(user.email)
    }
  }, [selectedUserId, users])

  useEffect(() => {
    if (!activeServiceId) return
    setSelectedServiceIds((prev) => (prev.length ? prev : [activeServiceId]))
  }, [activeServiceId])

  useEffect(() => {
    if (!lookupQuery || lookupQuery.trim().length < 2) {
      setLookupResults([])
      return
    }
    const timer = window.setTimeout(async () => {
      setLookupLoading(true)
      try {
        const results = await lookupCommissionMembers(lookupQuery.trim())
        setLookupResults(Array.isArray(results) ? results : [])
        setLookupOpen(true)
      } catch {
        setLookupResults([])
      } finally {
        setLookupLoading(false)
      }
    }, 300)
    return () => window.clearTimeout(timer)
  }, [lookupQuery])

  useEffect(() => {
    const trimmed = matricule.trim()
    if (trimmed.length < 2) return
    const canAutofill = !fullName.trim() || !email.trim() || lastAutoFilledMatricule === trimmed
    if (!canAutofill) return
    const timer = window.setTimeout(async () => {
      try {
        const results = await lookupCommissionMembers(trimmed)
        const items = Array.isArray(results) ? results : []
        if (!items.length) return
        const exact = items.find((item) => (item.matricule || '').toLowerCase() === trimmed.toLowerCase())
        const match = exact || items[0]
        if (!match) return
        if (match.full_name) {
          setFullName((prev) => prev.trim() ? prev : match.full_name || '')
        }
        if (match.email) {
          setEmail((prev) => prev.trim() ? prev : match.email || '')
        }
        if (match.matricule) {
          setMatricule(match.matricule)
          setLastAutoFilledMatricule(match.matricule)
        } else {
          setLastAutoFilledMatricule(trimmed)
        }
      } catch {
        // Ignore lookup failures to avoid blocking manual entry
      }
    }, 350)
    return () => window.clearTimeout(timer)
  }, [matricule, fullName, email, lastAutoFilledMatricule])

  const leadership = useMemo(
    () => members.filter((m) => m.role_type === 'PRESIDENT' || m.role_type === 'DELEGUE'),
    [members]
  )
  const experts = useMemo(() => members.filter((m) => m.role_type === 'MEMBRE'), [members])
  const assistants = useMemo(() => members.filter((m) => m.role_type === 'ASSISTANT'), [members])

  const resetForm = () => {
    setSelectedUserId('')
    setFullName('')
    setEmail('')
    setMatricule('')
    setRoleType('MEMBRE')
    setCustomTitle('')
    setIsSigner(false)
    setLookupQuery('')
    setLookupResults([])
    setLookupOpen(false)
    setEditingMemberId(null)
  }

  const handleAdd = async () => {
    const servicesToAssign = selectedServiceIds.length ? selectedServiceIds : (activeServiceId ? [activeServiceId] : [])
    if (!servicesToAssign.length) {
      setError('Sélectionnez au moins une commission.')
      return
    }
    if (!fullName.trim()) {
      setError('Veuillez saisir un nom complet.')
      return
    }
    setConfirmOpen(true)
  }

  const handleConfirmAdd = async () => {
    const servicesToAssign = selectedServiceIds.length ? selectedServiceIds : (activeServiceId ? [activeServiceId] : [])
    setSaving(true)
    setError(null)
    try {
      if (editingMemberId && activeServiceId) {
        const updated = await updateServiceMember(activeServiceId, editingMemberId, {
          user_id: selectedUserId || null,
          full_name: fullName.trim(),
          email: email.trim() || null,
          matricule: matricule.trim() || null,
          role_type: roleType,
          custom_title: customTitle.trim() || null,
          is_signer: isSigner,
        })
        setMembers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
        resetForm()
        setConfirmOpen(false)
        return
      }
      if (servicesToAssign.length === 1) {
        const created = await createServiceMember(servicesToAssign[0], {
          user_id: selectedUserId || null,
          full_name: fullName.trim(),
          email: email.trim() || null,
          matricule: matricule.trim() || null,
          role_type: roleType,
          custom_title: customTitle.trim() || null,
          is_signer: isSigner,
        })
        if (activeServiceId && servicesToAssign[0] === activeServiceId) {
          setMembers((prev) => [created, ...prev])
        }
      } else {
        const created = await multiAssignCommissionMember({
          service_ids: servicesToAssign,
          user_id: selectedUserId || null,
          full_name: fullName.trim(),
          email: email.trim() || null,
          matricule: matricule.trim() || null,
          role_type: roleType,
          custom_title: customTitle.trim() || null,
          is_signer: isSigner,
        })
        if (activeServiceId) {
          const forActive = created.filter((m) => m.service_id === activeServiceId)
          if (forActive.length) {
            setMembers((prev) => [...forActive, ...prev])
          }
        }
      }
      resetForm()
      setConfirmOpen(false)
    } catch (err: any) {
      setError(err?.message || "Impossible d'ajouter ce membre.")
    } finally {
      setSaving(false)
    }
  }

  const handleEdit = (member: CommissionMember) => {
    setEditingMemberId(member.id)
    setSelectedUserId(member.user_id || '')
    setFullName(member.full_name || '')
    setEmail(member.email || '')
    setMatricule(member.matricule || '')
    setRoleType(member.role_type || 'MEMBRE')
    setCustomTitle(member.custom_title || '')
    setIsSigner(Boolean(member.is_signer))
    setSelectedServiceIds(member.service_id ? [member.service_id] : (activeServiceId ? [activeServiceId] : []))
  }

  const handleToggleSigner = async (member: CommissionMember) => {
    if (!activeServiceId) return
    setSaving(true)
    setError(null)
    try {
      const updated = await updateServiceMember(activeServiceId, member.id, {
        is_signer: !member.is_signer,
      })
      setMembers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
    } catch (err: any) {
      setError(err?.message || "Impossible de modifier le rôle signataire.")
    } finally {
      setSaving(false)
    }
  }

  const handleRemove = async (member: CommissionMember) => {
    if (!activeServiceId) return
    const confirmed = await confirm({
      title: 'Retirer le membre',
      description: `Retirer ${member.full_name} de cette commission ?`,
      confirmText: 'Retirer',
      cancelText: 'Annuler',
      variant: 'danger',
    })
    if (!confirmed) return
    setSaving(true)
    setError(null)
    try {
      await deleteServiceMember(activeServiceId, member.id)
      setMembers((prev) => prev.filter((item) => item.id !== member.id))
    } catch (err: any) {
      setError(err?.message || "Impossible de retirer ce membre.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className={styles.panel}>
      <div className={styles.panelHeader}>
        <div>
          <div className={styles.panelTitle}>Membres & Gouvernance</div>
          <div className={styles.panelSubtitle}>
            {activeService ? `Service sélectionné : ${activeService.code} - ${activeService.libelle}` : 'Sélectionnez une commission.'}
          </div>
        </div>
      </div>

      <div className={styles.formCard}>
        <div className={styles.formTitle}>
          <UserPlus size={16} /> {editingMemberId ? 'Modifier un membre' : 'Enregistrer un membre'}
        </div>
        <div className={styles.formGrid}>
          <div className={styles.lookupField}>
            <label>Matricule / Recherche</label>
            <div className={styles.lookupInput}>
              <Search size={14} />
              <input
                type="text"
                placeholder="Matricule, nom ou email…"
                value={lookupQuery}
                onChange={(e) => setLookupQuery(e.target.value)}
                onFocus={() => lookupResults.length && setLookupOpen(true)}
                onBlur={() => setTimeout(() => setLookupOpen(false), 150)}
              />
            </div>
            {lookupOpen && (lookupResults.length > 0 || lookupLoading) && (
              <div className={styles.lookupList}>
                {lookupLoading && <div className={styles.lookupItem}>Recherche…</div>}
                {lookupResults.map((item, idx) => (
                  <button
                    key={`${item.matricule || item.email || item.full_name}-${idx}`}
                    type="button"
                    className={styles.lookupItem}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      setFullName(item.full_name || '')
                      setEmail(item.email || '')
                      setMatricule(item.matricule || '')
                      setLastAutoFilledMatricule(item.matricule || '')
                      setLookupOpen(false)
                    }}
                  >
                    <span>{item.full_name}</span>
                    <span className={styles.lookupMeta}>
                      {item.matricule ? item.matricule : item.email}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
          <select value={selectedUserId} onChange={(e) => setSelectedUserId(e.target.value)}>
            <option value="">Utilisateur existant (optionnel)</option>
            {users.map((user) => (
              <option key={user.id} value={user.id}>
                {(user.prenom || '') + ' ' + (user.nom || '')} {user.email ? `(${user.email})` : ''}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="Nom complet *"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
          />
          <input
            type="email"
            placeholder="Email (optionnel)"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            type="text"
            placeholder="Matricule (optionnel)"
            value={matricule}
            onChange={(e) => setMatricule(e.target.value)}
          />
          <select value={roleType} onChange={(e) => setRoleType(e.target.value as CommissionRole)}>
            <option value="PRESIDENT">Président</option>
            <option value="DELEGUE">Délégué</option>
            <option value="MEMBRE">Membre</option>
            <option value="ASSISTANT">Assistant</option>
          </select>
          <input
            type="text"
            placeholder="Titre spécifique (optionnel)"
            value={customTitle}
            onChange={(e) => setCustomTitle(e.target.value)}
          />
          <div className={styles.lookupField}>
            <label>Commissions</label>
            <div className={styles.serviceToolbar}>
              <input
                type="text"
                placeholder="Filtrer les commissions…"
                value={serviceFilter}
                onChange={(e) => setServiceFilter(e.target.value)}
              />
              <div className={styles.serviceToolbarButtons}>
                <button
                  type="button"
                  onClick={() => setSelectedServiceIds(services.map((s) => s.id))}
                >
                  Tout cocher
                </button>
                <button type="button" onClick={() => setSelectedServiceIds([])}>
                  Vider
                </button>
              </div>
            </div>
            <div className={styles.serviceGrid}>
              {services
                .filter((service) => {
                  const q = serviceFilter.trim().toLowerCase()
                  if (!q) return true
                  return (
                    service.code.toLowerCase().includes(q) ||
                    service.libelle.toLowerCase().includes(q)
                  )
                })
                .map((service) => {
                  const checked = selectedServiceIds.includes(service.id)
                  return (
                    <label
                      key={service.id}
                      className={`${styles.serviceCard} ${checked ? styles.serviceCardActive : ''}`}
                    >
                      <input
                        type="checkbox"
                        className={styles.hiddenCheckbox}
                        checked={checked}
                        onChange={() => {
                          setSelectedServiceIds((prev) =>
                            prev.includes(service.id)
                              ? prev.filter((id) => id !== service.id)
                              : [...prev, service.id]
                          )
                        }}
                      />
                      <span className={styles.serviceCode}>{service.code}</span>
                      <span className={styles.serviceLabel}>{service.libelle}</span>
                    </label>
                  )
                })}
            </div>
          </div>
        </div>
        <div className={styles.formActions}>
          <label className={styles.checkbox}>
            <input
              type="checkbox"
              checked={isSigner}
              onChange={(e) => setIsSigner(e.target.checked)}
            />
            Signataire
          </label>
          <button
            type="button"
            onClick={handleAdd}
            disabled={saving || selectedServiceIds.length === 0}
          >
            {saving ? 'Enregistrement…' : (editingMemberId ? 'Enregistrer' : 'Ajouter au service')}
          </button>
          {editingMemberId && (
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={resetForm}
              disabled={saving}
            >
              Annuler l’édition
            </button>
          )}
        </div>
        {error && <div className={styles.error}>{error}</div>}
      </div>

      {confirmOpen && (
        <div className={styles.confirmOverlay}>
          <div className={styles.confirmCard}>
            <h3>{editingMemberId ? 'Confirmer la mise à jour ?' : 'Confirmer l’attribution ?'}</h3>
            <p>
              {editingMemberId
                ? 'Vérifiez les informations avant de mettre à jour ce membre.'
                : 'Vérifiez les accès que vous allez accorder :'}
            </p>
            <div className={styles.confirmExpert}>
              <div className={styles.confirmBadge}>{matricule || 'Sans matricule'}</div>
              <div className={styles.confirmName}>{fullName || '—'}</div>
              <div className={styles.confirmMeta}>{email || '—'}</div>
              <div className={styles.confirmRoles}>
                <span>{roleLabels[roleType]}</span>
                {isSigner && <span className={styles.confirmSigner}>Signataire</span>}
              </div>
            </div>
            <div className={styles.confirmServices}>
              <div className={styles.confirmServicesTitle}>
                Commissions ciblées ({selectedServiceIds.length})
              </div>
              <div className={styles.confirmServicesList}>
                {services
                  .filter((s) => selectedServiceIds.includes(s.id))
                  .map((s) => (
                    <span key={s.id}>{s.code}</span>
                  ))}
              </div>
            </div>
            <div className={styles.confirmActions}>
              <button type="button" onClick={handleConfirmAdd} disabled={saving}>
                Confirmer et enregistrer
              </button>
              <button type="button" onClick={() => setConfirmOpen(false)} disabled={saving}>
                Annuler
              </button>
            </div>
          </div>
        </div>
      )}

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionTitle}>
            <Crown size={16} /> Bureau
          </div>
          <span className={styles.sectionCount}>{leadership.length}</span>
        </div>
        <div className={styles.membersGrid}>
          {leadership.map((member) => (
            <MemberCard
              key={member.id}
              member={member}
              serviceBadges={activeService ? [activeService.code] : []}
              onEdit={() => handleEdit(member)}
              onDelete={() => handleRemove(member)}
              onToggleSigner={() => handleToggleSigner(member)}
            />
          ))}
          {!loading && leadership.length === 0 && (
            <div className={styles.empty}>Aucun président ou délégué.</div>
          )}
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionTitle}>
            <Users size={16} /> Membres & Experts
          </div>
          <span className={styles.sectionCount}>{experts.length}</span>
        </div>
        <div className={styles.membersGrid}>
          {experts.map((member) => (
            <MemberCard
              key={member.id}
              member={member}
              serviceBadges={activeService ? [activeService.code] : []}
              onEdit={() => handleEdit(member)}
              onDelete={() => handleRemove(member)}
              onToggleSigner={() => handleToggleSigner(member)}
            />
          ))}
          {!loading && experts.length === 0 && (
            <div className={styles.empty}>Aucun membre déclaré.</div>
          )}
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionTitle}>
            <Users size={16} /> Assistants
          </div>
          <span className={styles.sectionCount}>{assistants.length}</span>
        </div>
        <div className={styles.membersGrid}>
          {assistants.map((member) => (
            <MemberCard
              key={member.id}
              member={member}
              serviceBadges={activeService ? [activeService.code] : []}
              onEdit={() => handleEdit(member)}
              onDelete={() => handleRemove(member)}
              onToggleSigner={() => handleToggleSigner(member)}
            />
          ))}
          {!loading && assistants.length === 0 && (
            <div className={styles.empty}>Aucun assistant enregistré.</div>
          )}
        </div>
      </div>
    </section>
  )
}
