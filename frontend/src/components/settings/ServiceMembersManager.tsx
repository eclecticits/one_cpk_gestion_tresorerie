import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Crown, Search, Settings2, UserPlus, Users } from 'lucide-react'
import {
  createServiceMember,
  createServiceMemberFunction,
  deleteServiceMemberFunction,
  deleteServiceMember,
  getServiceMemberFunctions,
  getServiceMembers,
  lookupCommissionMembers,
  multiAssignCommissionMember,
  updateServiceMember,
  updateServiceMemberFunction,
} from '../../api/services'
import type { CommissionMember, Service, ServiceMemberFunction, User } from '../../types'
import { useConfirm } from '../../contexts/ConfirmContext'
import { usePermissions } from '../../hooks/usePermissions'
import { isAssistantMember, isLeadershipMember, sortMemberFunctions } from '../../utils/serviceMemberFunctions'
import MemberCard from '../Gouvernance/MemberCard'
import styles from './ServiceMembersManager.module.css'

type Props = {
  services: Service[]
  users: User[]
  activeServiceId: number | null
}

type FunctionDraft = {
  label: string
  sort_order: string
  is_active: boolean
}

function draftFromFunction(item: ServiceMemberFunction): FunctionDraft {
  return {
    label: item.label,
    sort_order: String(item.sort_order),
    is_active: item.is_active,
  }
}

export default function ServiceMembersManager({ services, users, activeServiceId }: Props) {
  const confirm = useConfirm()
  const { hasPermission, isAdmin, loading: permissionsLoading } = usePermissions()
  const [members, setMembers] = useState<CommissionMember[]>([])
  const [memberFunctions, setMemberFunctions] = useState<ServiceMemberFunction[]>([])
  const [loading, setLoading] = useState(false)
  const [functionsLoading, setFunctionsLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [functionError, setFunctionError] = useState<string | null>(null)
  const [functionLoadError, setFunctionLoadError] = useState<string | null>(null)

  const [selectedUserId, setSelectedUserId] = useState('')
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [matricule, setMatricule] = useState('')
  const [selectedFunctionValue, setSelectedFunctionValue] = useState('')
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

  const [newFunctionLabel, setNewFunctionLabel] = useState('')
  const [newFunctionSortOrder, setNewFunctionSortOrder] = useState('')
  const [editingFunctionId, setEditingFunctionId] = useState<number | null>(null)
  const [editingFunctionDraft, setEditingFunctionDraft] = useState<FunctionDraft | null>(null)
  const [functionsOpen, setFunctionsOpen] = useState(false)

  const activeService = services.find((service) => service.id === activeServiceId) || null
  const canManageFunctions = isAdmin || hasPermission('can_manage_users')

  const sortedFunctions = useMemo(() => sortMemberFunctions(memberFunctions), [memberFunctions])
  const activeFunctions = useMemo(() => sortedFunctions.filter((item) => item.is_active), [sortedFunctions])
  const functionOptions = useMemo(
    () =>
      activeFunctions.map((item) => ({
        value: `id:${item.id}`,
        label: item.label,
      })),
    [activeFunctions]
  )
  const selectedFunctionLabel = useMemo(
    () => functionOptions.find((item) => item.value === selectedFunctionValue)?.label || '',
    [functionOptions, selectedFunctionValue]
  )
  const lastSelectableFunctionLabel = useMemo(
    () => (functionOptions.length ? functionOptions[functionOptions.length - 1].label : 'Aucune'),
    [functionOptions]
  )

  const leadership = useMemo(
    () => members.filter((member) => isLeadershipMember(member) && !isAssistantMember(member)),
    [members]
  )
  const assistants = useMemo(() => members.filter((member) => isAssistantMember(member)), [members])
  const experts = useMemo(
    () => members.filter((member) => !isLeadershipMember(member) && !isAssistantMember(member)),
    [members]
  )

  const loadFunctions = async () => {
    if (!activeServiceId) {
      setMemberFunctions([])
      setFunctionsLoading(false)
      setFunctionLoadError(null)
      return []
    }
    setFunctionsLoading(true)
    setFunctionLoadError(null)
    try {
      const res = await getServiceMemberFunctions(activeServiceId, { active: null })
      const items = Array.isArray(res) ? sortMemberFunctions(res) : []
      setMemberFunctions(items)
      return items
    } catch (err: any) {
      const message = err?.message || 'Erreur de chargement du référentiel.'
      setFunctionLoadError(message)
      setMemberFunctions([])
      throw err
    } finally {
      setFunctionsLoading(false)
    }
  }

  console.log('memberFunctions', memberFunctions)
  console.log('canManageFunctions', canManageFunctions)
  console.log('loaded memberFunctions', memberFunctions)
  console.log('functions loading error', functionLoadError)
  console.log('function options used in member form', functionOptions)

  useEffect(() => {
    setFunctionsOpen(false)
    setFunctionError(null)
    setFunctionLoadError(null)
    setEditingFunctionId(null)
    setEditingFunctionDraft(null)
    if (!activeServiceId) {
      setMemberFunctions([])
      setSelectedFunctionValue('')
      setFunctionsLoading(false)
      return
    }
    const run = async () => {
      try {
        const items = await loadFunctions()
        const fallback = items.find((item) => item.is_active) || null
        setSelectedFunctionValue(fallback ? `id:${fallback.id}` : '')
      } catch (err: any) {
        setFunctionError(err?.message || 'Impossible de charger les fonctions.')
        setSelectedFunctionValue('')
      }
    }
    run()
  }, [activeServiceId])

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
    const user = users.find((item) => String(item.id) === String(selectedUserId))
    if (!user) return
    const label = `${user.prenom || ''} ${user.nom || ''}`.trim() || user.email || ''
    if (label) setFullName(label)
    if (user.email) setEmail(user.email)
  }, [selectedUserId, users])

  useEffect(() => {
    if (!activeServiceId) return
    setSelectedServiceIds([activeServiceId])
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
        if (match.full_name) setFullName((prev) => (prev.trim() ? prev : match.full_name || ''))
        if (match.email) setEmail((prev) => (prev.trim() ? prev : match.email || ''))
        if (match.matricule) {
          setMatricule(match.matricule)
          setLastAutoFilledMatricule(match.matricule)
        } else {
          setLastAutoFilledMatricule(trimmed)
        }
      } catch {
        // ignore
      }
    }, 350)
    return () => window.clearTimeout(timer)
  }, [matricule, fullName, email, lastAutoFilledMatricule])

  const resetForm = () => {
    setSelectedUserId('')
    setFullName('')
    setEmail('')
    setMatricule('')
    const fallback = activeFunctions[0] || null
    setSelectedFunctionValue(fallback ? `id:${fallback.id}` : '')
    setCustomTitle('')
    setIsSigner(false)
    setLookupQuery('')
    setLookupResults([])
    setLookupOpen(false)
    setEditingMemberId(null)
  }

  const handleAdd = async () => {
    const servicesToAssign = selectedServiceIds.length ? selectedServiceIds : activeServiceId ? [activeServiceId] : []
    if (!servicesToAssign.length) {
      setError('Sélectionnez au moins une commission.')
      return
    }
    if (!fullName.trim()) {
      setError('Veuillez saisir un nom complet.')
      return
    }
    if (!selectedFunctionValue) {
      setError('Veuillez sélectionner une fonction.')
      return
    }
    setConfirmOpen(true)
  }

  const handleConfirmAdd = async () => {
    const servicesToAssign = selectedServiceIds.length ? selectedServiceIds : activeServiceId ? [activeServiceId] : []
    if (!selectedFunctionValue) {
      setError('Veuillez sélectionner une fonction.')
      return
    }
    const functionId = selectedFunctionValue.startsWith('id:') ? Number(selectedFunctionValue.slice(3)) : null
    setSaving(true)
    setError(null)
    try {
      const payload = {
        user_id: selectedUserId || null,
        full_name: fullName.trim(),
        email: email.trim() || null,
        matricule: matricule.trim() || null,
        function_id: servicesToAssign.length === 1 && Number.isFinite(functionId as number) ? functionId : null,
        function_label: selectedFunctionLabel || null,
        custom_title: customTitle.trim() || null,
        is_signer: isSigner,
      }

      if (editingMemberId && activeServiceId) {
        const updated = await updateServiceMember(activeServiceId, editingMemberId, payload)
        setMembers((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      } else if (servicesToAssign.length === 1) {
        const created = await createServiceMember(servicesToAssign[0], payload)
        if (activeServiceId && servicesToAssign[0] === activeServiceId) {
          setMembers((prev) => [created, ...prev])
        }
      } else {
        const created = await multiAssignCommissionMember({
          service_ids: servicesToAssign,
          ...payload,
        })
        if (activeServiceId) {
          const forActive = created.filter((item) => item.service_id === activeServiceId)
          if (forActive.length) setMembers((prev) => [...forActive, ...prev])
        }
      }

      resetForm()
      setConfirmOpen(false)
    } catch (err: any) {
      setError(err?.message || "Impossible d'enregistrer ce membre.")
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
    if (member.function_id || member.function?.id) {
      setSelectedFunctionValue(`id:${member.function_id || member.function?.id}`)
    } else {
      const matchedFunction = sortedFunctions.find(
        (item) => item.label.trim().toLowerCase() === String(member.function_label || '').trim().toLowerCase()
      )
      setSelectedFunctionValue(matchedFunction ? `id:${matchedFunction.id}` : '')
    }
    setCustomTitle(member.custom_title || '')
    setIsSigner(Boolean(member.is_signer))
    setSelectedServiceIds(member.service_id ? [member.service_id] : activeServiceId ? [activeServiceId] : [])
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

  const handleCreateFunction = async () => {
    if (!activeServiceId) {
      setFunctionError('Sélectionnez un service avant de gérer les fonctions.')
      return
    }
    if (!canManageFunctions) {
      setFunctionError("Vous n'avez pas les droits pour modifier le référentiel des fonctions.")
      return
    }
    const label = newFunctionLabel.trim()
    if (!label) {
      setFunctionError('Veuillez saisir un libellé de fonction.')
      return
    }
    setSaving(true)
    setFunctionError(null)
    try {
      const created = await createServiceMemberFunction(activeServiceId, {
        label,
        sort_order: newFunctionSortOrder.trim() ? Number(newFunctionSortOrder) : null,
        is_active: true,
      })
      setMemberFunctions((prev) => sortMemberFunctions([...prev, created]))
      setNewFunctionLabel('')
      setNewFunctionSortOrder('')
    } catch (err: any) {
      setFunctionError(err?.message || 'Impossible de créer cette fonction.')
    } finally {
      setSaving(false)
    }
  }

  const handleSaveFunction = async () => {
    if (!activeServiceId) {
      setFunctionError('Sélectionnez un service avant de gérer les fonctions.')
      return
    }
    if (!canManageFunctions) {
      setFunctionError("Vous n'avez pas les droits pour modifier le référentiel des fonctions.")
      return
    }
    if (!editingFunctionId || !editingFunctionDraft) return
    setSaving(true)
    setFunctionError(null)
    try {
      const updated = await updateServiceMemberFunction(activeServiceId, editingFunctionId, {
        label: editingFunctionDraft.label.trim(),
        sort_order: editingFunctionDraft.sort_order.trim() ? Number(editingFunctionDraft.sort_order) : null,
        is_active: editingFunctionDraft.is_active,
      })
      setMemberFunctions((prev) => sortMemberFunctions(prev.map((item) => (item.id === updated.id ? updated : item))))
      setEditingFunctionId(null)
      setEditingFunctionDraft(null)
    } catch (err: any) {
      setFunctionError(err?.message || 'Impossible de mettre à jour cette fonction.')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteFunction = async (item: ServiceMemberFunction) => {
    if (!activeServiceId) {
      setFunctionError('Sélectionnez un service avant de gérer les fonctions.')
      return
    }
    if (!canManageFunctions) {
      setFunctionError("Vous n'avez pas les droits pour modifier le référentiel des fonctions.")
      return
    }
    const confirmed = await confirm({
      title: 'Supprimer la fonction',
      description: `Supprimer définitivement la fonction "${item.label}" ?`,
      confirmText: 'Supprimer',
      cancelText: 'Annuler',
      variant: 'danger',
    })
    if (!confirmed) return
    setSaving(true)
    setFunctionError(null)
    try {
      await deleteServiceMemberFunction(activeServiceId, item.id)
      setMemberFunctions((prev) => prev.filter((entry) => entry.id !== item.id))
      if (selectedFunctionValue === `id:${item.id}`) {
        const fallback = activeFunctions.find((entry) => entry.id !== item.id) || null
        setSelectedFunctionValue(fallback ? `id:${fallback.id}` : '')
      }
    } catch (err: any) {
      setFunctionError(err?.message || 'Impossible de supprimer cette fonction.')
    } finally {
      setSaving(false)
    }
  }

  const handleToggleFunctionActive = async (item: ServiceMemberFunction) => {
    if (!activeServiceId) {
      setFunctionError('Sélectionnez un service avant de gérer les fonctions.')
      return
    }
    if (!canManageFunctions) {
      setFunctionError("Vous n'avez pas les droits pour modifier le référentiel des fonctions.")
      return
    }
    setSaving(true)
    setFunctionError(null)
    try {
      const updated = await updateServiceMemberFunction(activeServiceId, item.id, { is_active: !item.is_active })
      setMemberFunctions((prev) => sortMemberFunctions(prev.map((entry) => (entry.id === updated.id ? updated : entry))))
    } catch (err: any) {
      setFunctionError(err?.message || 'Impossible de modifier cette fonction.')
    } finally {
      setSaving(false)
    }
  }

  const handleMoveFunction = async (item: ServiceMemberFunction, direction: 'up' | 'down') => {
    if (!activeServiceId) {
      setFunctionError('Sélectionnez un service avant de gérer les fonctions.')
      return
    }
    if (!canManageFunctions) {
      setFunctionError("Vous n'avez pas les droits pour modifier le référentiel des fonctions.")
      return
    }
    const currentIndex = sortedFunctions.findIndex((entry) => entry.id === item.id)
    if (currentIndex === -1) return
    const targetIndex = direction === 'up' ? currentIndex - 1 : currentIndex + 1
    const target = sortedFunctions[targetIndex]
    if (!target) return

    setSaving(true)
    setFunctionError(null)
    try {
      const updatedCurrent = await updateServiceMemberFunction(activeServiceId, item.id, { sort_order: target.sort_order })
      const updatedTarget = await updateServiceMemberFunction(activeServiceId, target.id, { sort_order: item.sort_order })
      setMemberFunctions((prev) =>
        sortMemberFunctions(
          prev.map((entry) => {
            if (entry.id === updatedCurrent.id) return updatedCurrent
            if (entry.id === updatedTarget.id) return updatedTarget
            return entry
          })
        )
      )
    } catch (err: any) {
      setFunctionError(err?.message || "Impossible de modifier l'ordre de cette fonction.")
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
                    <span className={styles.lookupMeta}>{item.matricule ? item.matricule : item.email}</span>
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

          <input type="text" placeholder="Nom complet *" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          <input type="email" placeholder="Email (optionnel)" value={email} onChange={(e) => setEmail(e.target.value)} />
          <input type="text" placeholder="Matricule (optionnel)" value={matricule} onChange={(e) => setMatricule(e.target.value)} />

          <div className={styles.lookupField}>
            <label>Fonction *</label>
            <select
              value={selectedFunctionValue}
              onChange={(e) => setSelectedFunctionValue(e.target.value)}
              disabled={functionsLoading || Boolean(functionLoadError) || functionOptions.length === 0}
            >
              <option value="">Sélectionner une fonction</option>
              {functionOptions.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <div className={styles.functionHint}>
              Le référentiel des fonctions est administré ci-dessous. Pour un cas particulier, sélectionnez la fonction la plus proche puis précisez-la dans `Titre spécifique`.
            </div>
          </div>

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
                <button type="button" onClick={() => setSelectedServiceIds(services.map((item) => item.id))}>
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
                  return service.code.toLowerCase().includes(q) || service.libelle.toLowerCase().includes(q)
                })
                .map((service) => {
                  const checked = selectedServiceIds.includes(service.id)
                  return (
                    <label key={service.id} className={`${styles.serviceCard} ${checked ? styles.serviceCardActive : ''}`}>
                      <input
                        type="checkbox"
                        className={styles.hiddenCheckbox}
                        checked={checked}
                        onChange={() => {
                          setSelectedServiceIds((prev) =>
                            prev.includes(service.id) ? prev.filter((id) => id !== service.id) : [...prev, service.id]
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
            <input type="checkbox" checked={isSigner} onChange={(e) => setIsSigner(e.target.checked)} />
            Signataire
          </label>
          <button type="button" onClick={handleAdd} disabled={saving || selectedServiceIds.length === 0}>
            {saving ? 'Enregistrement…' : editingMemberId ? 'Enregistrer' : 'Ajouter au service'}
          </button>
          {editingMemberId && (
            <button type="button" className={styles.secondaryBtn} onClick={resetForm} disabled={saving}>
              Annuler l’édition
            </button>
          )}
        </div>
        {error && <div className={styles.error}>{error}</div>}
      </div>

      <div className={styles.formCard}>
        <button
          type="button"
          className={styles.functionAccordionToggle}
          onClick={() => setFunctionsOpen((prev) => !prev)}
        >
          <div>
            <div className={styles.formTitle}>
              <Settings2 size={16} /> Référentiel des fonctions
            </div>
            <div className={styles.functionAccordionSummary}>
              <span>Fonctions configurées : {sortedFunctions.length}</span>
              <span>Dernière fonction sélectionnable : {lastSelectableFunctionLabel}</span>
            </div>
          </div>
          <span className={styles.functionAccordionIcon}>
            {functionsOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </span>
        </button>

        {!functionsOpen ? (
          <div className={styles.functionCollapsedRow}>
            <span className={styles.functionHeroSubtitle}>
              Gérer les fonctions utilisées par les membres sans surcharger l’écran principal.
            </span>
            <button type="button" onClick={() => setFunctionsOpen(true)} className={styles.secondaryBtn}>
              Gérer les fonctions
            </button>
          </div>
        ) : (
          <>
            <div className={styles.functionHeroSubtitle}>
              Créer, modifier, ordonner, désactiver ou supprimer les fonctions utilisées par les membres.
            </div>
            {!permissionsLoading && !canManageFunctions && (
              <div className={styles.functionNotice}>
                Vous n’avez pas les droits pour modifier le référentiel des fonctions.
              </div>
            )}

            <div className={styles.functionCreateHeader}>
              <button type="button" onClick={handleCreateFunction} disabled={saving || !canManageFunctions}>
                Ajouter une fonction
              </button>
            </div>
            <div className={styles.functionCreateGrid}>
              <input
                type="text"
                placeholder="Libellé"
                value={newFunctionLabel}
                onChange={(e) => setNewFunctionLabel(e.target.value)}
                disabled={!canManageFunctions}
              />
              <input
                type="number"
                placeholder="Ordre"
                value={newFunctionSortOrder}
                onChange={(e) => setNewFunctionSortOrder(e.target.value)}
                disabled={!canManageFunctions}
              />
              <label className={styles.checkbox}>
                <input type="checkbox" checked readOnly />
                Actif
              </label>
            </div>

            {functionsLoading ? (
              <div className={styles.empty}>Chargement des fonctions...</div>
            ) : functionLoadError ? (
              <div className={styles.error}>Erreur de chargement du référentiel : {functionLoadError}</div>
            ) : sortedFunctions.length === 0 ? (
              <div className={styles.empty}>Aucune fonction enregistrée.</div>
            ) : (
              <div className={styles.functionsList}>
                {sortedFunctions.map((item) => {
                  const isEditing = editingFunctionId === item.id && editingFunctionDraft
                  return (
                    <div key={item.id} className={styles.functionRow}>
                      {isEditing ? (
                        <div className={styles.functionEditGrid}>
                          <input
                            type="text"
                            value={editingFunctionDraft.label}
                            onChange={(e) =>
                              setEditingFunctionDraft((prev) => (prev ? { ...prev, label: e.target.value } : prev))
                            }
                          />
                          <input
                            type="number"
                            value={editingFunctionDraft.sort_order}
                            onChange={(e) =>
                              setEditingFunctionDraft((prev) => (prev ? { ...prev, sort_order: e.target.value } : prev))
                            }
                          />
                          <label className={styles.checkbox}>
                            <input
                              type="checkbox"
                              checked={editingFunctionDraft.is_active}
                              onChange={(e) =>
                                setEditingFunctionDraft((prev) => (prev ? { ...prev, is_active: e.target.checked } : prev))
                              }
                            />
                            Active
                          </label>
                        </div>
                      ) : (
                        <div className={styles.functionIdentity}>
                          <span className={styles.functionLabel}>{item.label}</span>
                          <span className={styles.functionMeta}>
                            {item.is_default ? 'Défaut' : 'Personnalisée'} · ordre {item.sort_order} · {item.is_active ? 'active' : 'inactive'}
                          </span>
                        </div>
                      )}

                      <div className={styles.functionActions}>
                        {isEditing ? (
                          <>
                            <button type="button" onClick={handleSaveFunction} disabled={saving || !canManageFunctions}>
                              Sauvegarder
                            </button>
                            <button
                              type="button"
                              className={styles.secondaryBtn}
                              onClick={() => {
                                setEditingFunctionId(null)
                                setEditingFunctionDraft(null)
                              }}
                            >
                              Annuler
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              type="button"
                              className={styles.secondaryBtn}
                              onClick={() => handleMoveFunction(item, 'up')}
                              disabled={saving || !canManageFunctions || sortedFunctions[0]?.id === item.id}
                            >
                              Monter
                            </button>
                            <button
                              type="button"
                              className={styles.secondaryBtn}
                              onClick={() => handleMoveFunction(item, 'down')}
                              disabled={saving || !canManageFunctions || sortedFunctions[sortedFunctions.length - 1]?.id === item.id}
                            >
                              Descendre
                            </button>
                            <button
                              type="button"
                              className={styles.secondaryBtn}
                              onClick={() => {
                                setEditingFunctionId(item.id)
                                setEditingFunctionDraft(draftFromFunction(item))
                              }}
                              disabled={!canManageFunctions}
                            >
                              Modifier
                            </button>
                            <button
                              type="button"
                              className={styles.secondaryBtn}
                              onClick={() => handleToggleFunctionActive(item)}
                              disabled={!canManageFunctions}
                            >
                              {item.is_active ? 'Désactiver' : 'Réactiver'}
                            </button>
                            {!item.is_default && (
                              <button
                                type="button"
                                className={styles.dangerBtn}
                                onClick={() => handleDeleteFunction(item)}
                                disabled={!canManageFunctions}
                              >
                                Supprimer
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
            {functionError && <div className={styles.error}>{functionError}</div>}
          </>
        )}
      </div>

      {confirmOpen && (
        <div className={styles.confirmOverlay}>
          <div className={styles.confirmCard}>
            <h3>{editingMemberId ? 'Confirmer la mise à jour ?' : 'Confirmer l’attribution ?'}</h3>
            <p>{editingMemberId ? 'Vérifiez les informations avant de mettre à jour ce membre.' : 'Vérifiez les accès que vous allez accorder :'}</p>
            <div className={styles.confirmExpert}>
              <div className={styles.confirmBadge}>{matricule || 'Sans matricule'}</div>
              <div className={styles.confirmName}>{fullName || '—'}</div>
              <div className={styles.confirmMeta}>{email || '—'}</div>
              <div className={styles.confirmRoles}>
                <span>{selectedFunctionLabel || '—'}</span>
                {customTitle.trim() && <span>{customTitle.trim()}</span>}
                {isSigner && <span className={styles.confirmSigner}>Signataire</span>}
              </div>
            </div>
            <div className={styles.confirmServices}>
              <div className={styles.confirmServicesTitle}>Commissions ciblées ({selectedServiceIds.length})</div>
              <div className={styles.confirmServicesList}>
                {services.filter((item) => selectedServiceIds.includes(item.id)).map((item) => <span key={item.id}>{item.code}</span>)}
              </div>
            </div>
            <div className={styles.confirmActions}>
              <button type="button" onClick={handleConfirmAdd} disabled={saving}>Confirmer et enregistrer</button>
              <button type="button" onClick={() => setConfirmOpen(false)} disabled={saving}>Annuler</button>
            </div>
          </div>
        </div>
      )}

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionTitle}><Crown size={16} /> Bureau</div>
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
          {!loading && leadership.length === 0 && <div className={styles.empty}>Aucun membre du bureau enregistré.</div>}
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionTitle}><Users size={16} /> Membres & Experts</div>
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
          {!loading && experts.length === 0 && <div className={styles.empty}>Aucun membre déclaré.</div>}
        </div>
      </div>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <div className={styles.sectionTitle}><Users size={16} /> Assistants</div>
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
          {!loading && assistants.length === 0 && <div className={styles.empty}>Aucun assistant enregistré.</div>}
        </div>
      </div>
    </section>
  )
}
