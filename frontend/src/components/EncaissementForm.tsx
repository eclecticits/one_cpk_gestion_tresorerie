import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { format } from 'date-fns'
import { apiRequest } from '../lib/apiClient'
import { ExpertComptable, ModePaiement, TypeClient, Service } from '../types'
import { toNumber } from '../utils/amount'
import { TYPE_CLIENT_LABELS } from '../utils/encaissementHelpers'
import ClosureLockBanner from './ClosureLockBanner'
import styles from '../pages/Encaissements.module.css'

interface EncaissementFormProps {
  user: any
  services: Service[]
  comptesBancaires: any[]
  isCashClosed: boolean
  tauxChange: number
  libellePresets: string[]
  budgetTree: any[]
  onClose: () => void
  onSuccess: (message: string, details?: string) => void
  onError: (title: string, message: string, details?: string) => void
  onProformaCreated: (numero: string, montant: number) => void
  loadData: () => Promise<void>
}

const roundMoney = (value: number): number => {
  return Math.round((value + Number.EPSILON) * 100) / 100
}

const formatCurrency = (amount: string | number | null | undefined) => {
  return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(toNumber(amount))
}

export default function EncaissementForm({
  user,
  services,
  comptesBancaires,
  isCashClosed,
  tauxChange,
  libellePresets,
  budgetTree,
  onClose,
  onSuccess,
  onError,
  onProformaCreated,
  loadData,
}: EncaissementFormProps) {
  const [formData, setFormData] = useState({
    type_client: 'expert_comptable' as TypeClient,
    expert_comptable_id: '',
    client_nom: '',
    libelle: '',
    description: '',
    devise_perception: 'USD',
    montant: '',
    montant_paye: '',
    canal: 'CAISSE' as 'CAISSE' | 'BANQUE',
    compte_bancaire_id: '',
    mode_paiement: 'cash' as ModePaiement,
    reference: '',
    notes_paiement: '',
    date_encaissement: format(new Date(), 'yyyy-MM-dd'),
    budget_poste_id: '',
    service_id: '',
  })

  const [searchEC, setSearchEC] = useState('')
  const [filteredExperts, setFilteredExperts] = useState<ExpertComptable[]>([])
  const [isSearchingExperts, setIsSearchingExperts] = useState(false)
  const [budgetSearch, setBudgetSearch] = useState('')
  const [showBudgetDropdown, setShowBudgetDropdown] = useState(false)
  const [expandedBudgetIds, setExpandedBudgetIds] = useState<Set<number>>(() => new Set())
  const [filteredComptes, setFilteredComptes] = useState<any[]>([])

  const userServiceIds = useMemo(() => {
    if (user?.service_ids && user.service_ids.length > 0) return user.service_ids
    if (user?.service_id) return [user.service_id]
    return []
  }, [user?.service_ids, user?.service_id])

  const isServiceUser = useMemo(() => {
    return userServiceIds.length > 0 && user?.role !== 'admin' && user?.role !== 'super_admin'
  }, [userServiceIds, user?.role])

  const mustSelectService = useMemo(() => {
    return user?.role !== 'admin' && user?.role !== 'super_admin' && services.length > 0
  }, [user?.role, services.length])

  const getMontantPayeUSD = useCallback(() => {
    const raw = toNumber(formData.montant_paye || 0)
    if (formData.devise_perception === 'CDF') {
      return tauxChange > 0 ? raw / tauxChange : 0
    }
    return raw
  }, [formData.montant_paye, formData.devise_perception, tauxChange])

  useEffect(() => {
    if (isCashClosed && formData.canal === 'CAISSE') {
      setFormData((prev) => ({
        ...prev,
        canal: 'BANQUE',
        mode_paiement: 'virement',
        reference: prev.reference || '',
      }))
    }
  }, [isCashClosed, formData.canal])

  useEffect(() => {
    if (formData.canal === 'BANQUE' && formData.mode_paiement === 'cash') {
      setFormData((prev) => ({ ...prev, mode_paiement: 'virement', reference: prev.reference || '' }))
    }
    if (formData.canal === 'CAISSE' && formData.mode_paiement !== 'cash') {
      setFormData((prev) => ({ ...prev, mode_paiement: 'cash', reference: '' }))
    }
  }, [formData.canal, formData.mode_paiement])

  useEffect(() => {
    const devise = formData.devise_perception || 'USD'
    const next = comptesBancaires.filter(
      (compte) =>
        String(compte.devise || '').toUpperCase() === devise &&
        (formData.canal === 'BANQUE' 
          ? String(compte.account_type || 'BANK').toUpperCase() === 'BANK'
          : String(compte.account_type || 'BANK').toUpperCase() === 'CASH')
    )
    setFilteredComptes(next)
    
    if (!next.find((c) => String(c.id) === String(formData.compte_bancaire_id))) {
      setFormData((prev) => ({
        ...prev,
        compte_bancaire_id: next.length > 0 ? String(next[0].id) : '',
      }))
    }
  }, [formData.devise_perception, formData.canal, formData.compte_bancaire_id, comptesBancaires])

  useEffect(() => {
    if (isServiceUser && userServiceIds.length === 1 && !formData.service_id) {
      setFormData((prev) => ({ ...prev, service_id: String(userServiceIds[0]) }))
    }
  }, [isServiceUser, userServiceIds, formData.service_id])

  useEffect(() => {
    if (mustSelectService && services.length === 1 && !formData.service_id) {
      setFormData((prev) => ({ ...prev, service_id: String(services[0].id) }))
    }
  }, [mustSelectService, services, formData.service_id])

  useEffect(() => {
    if (!searchEC) {
      setFilteredExperts([])
      return
    }
    const timer = window.setTimeout(async () => {
      try {
        setIsSearchingExperts(true)
        const res = await apiRequest<ExpertComptable[]>('GET', `/experts-comptables?q=${searchEC.trim()}&active=true&limit=20`)
        setFilteredExperts(Array.isArray(res) ? res : [])
      } catch (error) {
        console.error('Error searching experts:', error)
        setFilteredExperts([])
      } finally {
        setIsSearchingExperts(false)
      }
    }, 300)
    return () => window.clearTimeout(timer)
  }, [searchEC])

  const selectExpert = (expert: ExpertComptable) => {
    setFormData((prev) => ({ ...prev, expert_comptable_id: expert.id, client_nom: '' }))
    setSearchEC(`${expert.numero_ordre} - ${expert.nom_denomination}`)
    setFilteredExperts([])
  }

  const filteredBudgetTree = useMemo(() => {
    const query = budgetSearch.trim().toLowerCase()
    if (!query) return budgetTree

    const matches = (node: any) => {
      const code = String(node.code || '').toLowerCase()
      const libelle = String(node.libelle || '').toLowerCase()
      return code.includes(query) || libelle.includes(query)
    }

    const filterNodes = (nodes: any[]): any[] => {
      return nodes
        .map((node) => {
          const children = filterNodes(node.children || [])
          if (matches(node) || children.length > 0) {
            return { ...node, children }
          }
          return null
        })
        .filter(Boolean)
    }
    return filterNodes(budgetTree)
  }, [budgetTree, budgetSearch])

  const selectBudgetPoste = (line: any) => {
    if ((line.children?.length || 0) > 0) return
    setFormData((prev) => ({ ...prev, budget_poste_id: String(line.id) }))
    setBudgetSearch(`${line.code} - ${line.libelle}`)
    setShowBudgetDropdown(false)
  }

  const toggleBudgetNode = (id: number) => {
    setExpandedBudgetIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validateForm()) return

    try {
      const devise = formData.devise_perception === 'CDF' ? 'CDF' : 'USD'
      const montantTotal = roundMoney(parseFloat(formData.montant))
      const montantPayeInput = roundMoney(parseFloat(formData.montant_paye))
      const montantPaye = devise === 'CDF'
        ? roundMoney(tauxChange > 0 ? montantPayeInput / tauxChange : 0)
        : montantPayeInput
      const montantPercu = montantPayeInput

      const statutPaiement = montantPaye >= montantTotal ? 'complet' : montantPaye > 0 ? 'partiel' : 'non_paye'

      const created = await apiRequest<any>('POST', '/encaissements', {
        type_client: formData.type_client,
        expert_comptable_id: formData.type_client === 'expert_comptable' ? formData.expert_comptable_id : null,
        client_nom: formData.type_client !== 'expert_comptable' ? formData.client_nom.trim() : null,
        libelle: formData.libelle.trim(),
        description: formData.description || null,
        montant: montantTotal,
        montant_total: montantTotal,
        montant_paye: montantPaye,
        montant_percu: montantPercu,
        devise_perception: devise,
        taux_change_applique: devise === 'CDF' ? tauxChange : 1,
        budget_poste_id: Number(formData.budget_poste_id),
        service_id: formData.service_id ? Number(formData.service_id) : null,
        statut_paiement: statutPaiement,
        mode_paiement: formData.mode_paiement,
        reference: formData.reference || null,
        notes_paiement: formData.notes_paiement || null,
        date_encaissement: formData.date_encaissement,
        canal: formData.canal,
        compte_bancaire_id: formData.compte_bancaire_id ? Number(formData.compte_bancaire_id) : null,
        created_by: user?.id,
      })

      const encCreated = Array.isArray(created) ? created[0] : created
      onClose()
      await loadData()
      window.dispatchEvent(new Event('dashboard-refresh'))

      const statutMessage = statutPaiement === 'complet' 
        ? 'Payé en totalité' 
        : `Paiement partiel - Reste à payer : ${formatCurrency(montantTotal - montantPaye)}`
      
      onSuccess(
        `Le reçu ${encCreated?.numero_recu || '—'} a été enregistré.`,
        `Statut : ${statutMessage}\nMontant total : ${formatCurrency(montantTotal)}\nMontant payé : ${formatCurrency(montantPaye)}`
      )
    } catch (error: any) {
      onError('Erreur d\'enregistrement', error?.message || 'Une erreur inconnue est survenue.')
    }
  }

  const handleCreateProforma = async () => {
    if (!validateForm(true)) return

    try {
      const devise = formData.devise_perception === 'CDF' ? 'CDF' : 'USD'
      const montantTotal = roundMoney(parseFloat(formData.montant))

      const created = await apiRequest<any>('POST', '/encaissements/proformas', {
        type_client: formData.type_client,
        expert_comptable_id: formData.type_client === 'expert_comptable' ? formData.expert_comptable_id : null,
        client_nom: formData.type_client !== 'expert_comptable' ? formData.client_nom.trim() : null,
        libelle: formData.libelle.trim(),
        description: formData.description || null,
        montant: montantTotal,
        montant_total: montantTotal,
        montant_paye: 0,
        montant_percu: 0,
        devise_perception: devise,
        taux_change_applique: devise === 'CDF' ? tauxChange : 1,
        budget_poste_id: Number(formData.budget_poste_id),
        service_id: formData.service_id ? Number(formData.service_id) : null,
        statut_paiement: 'non_paye',
        mode_paiement: formData.mode_paiement,
        reference: formData.reference || null,
        notes_paiement: formData.notes_paiement || null,
        date_encaissement: formData.date_encaissement,
        canal: formData.canal,
        compte_bancaire_id: formData.compte_bancaire_id ? Number(formData.compte_bancaire_id) : null,
        created_by: user?.id,
      })

      const proCreated = Array.isArray(created) ? created[0] : created
      onClose()
      await loadData()
      onProformaCreated(proCreated?.numero_proforma || '—', montantTotal)
    } catch (error: any) {
      onError('Erreur de création', error?.message || 'Une erreur inconnue est survenue.')
    }
  }

  const validateForm = (isProforma = false) => {
    if (formData.type_client === 'expert_comptable' && !formData.expert_comptable_id) {
      onError('Expert-comptable non sélectionné', 'Veuillez sélectionner un expert-comptable depuis la liste.')
      return false
    }
    if (formData.type_client !== 'expert_comptable' && !formData.client_nom.trim()) {
      onError('Nom du client requis', 'Veuillez saisir le nom complet du client.')
      return false
    }
    if (!formData.libelle.trim()) {
      onError('Libellé requis', 'Veuillez renseigner un libellé clair.')
      return false
    }
    if (!formData.montant) {
      onError('Montant requis', 'Veuillez saisir le montant total.')
      return false
    }
    if (!isProforma && !formData.montant_paye) {
      onError('Montant payé requis', 'Veuillez saisir le montant payé.')
      return false
    }
    if (!formData.compte_bancaire_id) {
      onError('Compte requis', 'Veuillez sélectionner un compte de dépôt.')
      return false
    }
    if (!formData.budget_poste_id) {
      onError('Poste requis', 'Veuillez sélectionner un poste budgétaire.')
      return false
    }
    if (mustSelectService && !formData.service_id) {
      onError('Service requis', 'Veuillez sélectionner la commission concernée.')
      return false
    }
    return true
  }

  const BudgetDropdownNode = ({ node, depth }: { node: any; depth: number }) => {
    const hasChildren = (node.children || []).length > 0
    const isExpanded = budgetSearch.trim().length > 0 || expandedBudgetIds.has(node.id)
    return (
      <>
        <div
          className={`${styles.dropdownItem} ${hasChildren ? styles.parentItem : ''}`}
          style={{ paddingLeft: `${10 + depth * 16}px` }}
          onClick={() => hasChildren ? toggleBudgetNode(node.id) : selectBudgetPoste(node)}
        >
          {hasChildren && <span className={`${styles.treeToggle} ${isExpanded ? styles.treeToggleOpen : ''}`} />}
          <strong>{node.code}</strong> - {node.libelle}
          {hasChildren && <span className={styles.parentBadge}>Parent</span>}
        </div>
        {hasChildren && isExpanded && node.children.map((child: any) => (
          <BudgetDropdownNode key={child.id} node={child} depth={depth + 1} />
        ))}
      </>
    )
  }

  return (
    <div className={styles.modal}>
      <div className={styles.modalContent}>
        <div className={styles.modalHeader}>
          <h2>Nouvel encaissement</h2>
          <button onClick={onClose} className={styles.closeBtn}>×</button>
        </div>

        <form onSubmit={handleSubmit} className={styles.form}>
          <ClosureLockBanner isClosed={isCashClosed} />
          
          <div className={styles.field}>
            <label>Type de client *</label>
            <select
              value={formData.type_client}
              onChange={(e) => setFormData(prev => ({ 
                ...prev, 
                type_client: e.target.value as TypeClient,
                expert_comptable_id: '',
                client_nom: ''
              }))}
            >
              {Object.entries(TYPE_CLIENT_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>

          {formData.type_client === 'expert_comptable' ? (
            <div className={styles.field}>
              <label>Expert-Comptable *</label>
              <div style={{ position: 'relative' }}>
                <input
                  type="text"
                  value={searchEC}
                  onChange={(e) => setSearchEC(e.target.value)}
                  placeholder="Rechercher par numéro d'ordre ou nom"
                  style={{ borderColor: formData.expert_comptable_id ? '#10b981' : undefined }}
                />
                {formData.expert_comptable_id && <span style={{ position: 'absolute', right: '12px', top: '50%', transform: 'translateY(-50%)', color: '#10b981', fontWeight: 'bold' }}>✓</span>}
              </div>
              {filteredExperts.length > 0 && (
                <div className={styles.dropdown}>
                  {filteredExperts.map(expert => (
                    <div key={expert.id} onClick={() => selectExpert(expert)} className={styles.dropdownItem}>
                      <strong>{expert.numero_ordre}</strong> - {expert.nom_denomination}
                    </div>
                  ))}
                </div>
              )}
              {isSearchingExperts && <small>Recherche en cours…</small>}
            </div>
          ) : (
            <div className={styles.field}>
              <label>Nom du client *</label>
              <input
                type="text"
                value={formData.client_nom}
                onChange={(e) => setFormData(prev => ({ ...prev, client_nom: e.target.value }))}
                required
              />
            </div>
          )}

          <div className={styles.fieldRow}>
            <div className={styles.field}>
              <label>Service / Commission {mustSelectService ? '*' : '(optionnel)'}</label>
              <select
                value={formData.service_id}
                onChange={(e) => setFormData(prev => ({ ...prev, service_id: e.target.value }))}
                disabled={isServiceUser && userServiceIds.length === 1}
              >
                {!mustSelectService && <option value="">-- Recette générale --</option>}
                {services.filter(s => !isServiceUser || userServiceIds.includes(s.id)).map(s => (
                  <option key={s.id} value={s.id}>{s.code} - {s.libelle}</option>
                ))}
              </select>
            </div>
          </div>

          <div className={styles.fieldRow}>
            <div className={styles.field}>
              <label>Poste budgétaire *</label>
              <div style={{ position: 'relative' }}>
                <input
                  type="text"
                  value={budgetSearch}
                  onChange={(e) => {
                    setBudgetSearch(e.target.value)
                    setFormData(prev => ({ ...prev, budget_poste_id: '' }))
                    setShowBudgetDropdown(true)
                  }}
                  onFocus={() => setShowBudgetDropdown(true)}
                  onBlur={() => setTimeout(() => setShowBudgetDropdown(false), 120)}
                  placeholder="Rechercher par code ou libellé"
                />
                {showBudgetDropdown && filteredBudgetTree.length > 0 && (
                  <div className={`${styles.dropdown} ${styles.dropdownWide}`} onMouseDown={e => e.preventDefault()}>
                    {filteredBudgetTree.map(node => <BudgetDropdownNode key={node.id} node={node} depth={0} />)}
                  </div>
                )}
              </div>
            </div>

            <div className={styles.field}>
              <label>Libellé *</label>
              <input
                type="text"
                value={formData.libelle}
                onChange={(e) => setFormData(prev => ({ ...prev, libelle: e.target.value }))}
                list="encaissement-libelles"
                required
              />
              <datalist id="encaissement-libelles">
                {libellePresets.map(l => <option key={l} value={l} />)}
              </datalist>
            </div>

            <div className={styles.field}>
              <label>Montant comptable (USD) *</label>
              <input
                type="number"
                step="0.01"
                value={formData.montant}
                onChange={(e) => setFormData(prev => ({ ...prev, montant: e.target.value }))}
                required
              />
            </div>
          </div>

          <div className={styles.fieldRow}>
            <div className={styles.field}>
              <label>Devise de perception *</label>
              <select
                value={formData.devise_perception}
                onChange={(e) => setFormData(prev => ({ ...prev, devise_perception: e.target.value }))}
              >
                <option value="USD">USD</option>
                <option value="CDF">CDF</option>
              </select>
            </div>
            <div className={styles.field}>
              <label>Montant dû (USD)</label>
              <input type="text" value={formatCurrency(Math.max(0, toNumber(formData.montant || 0) - getMontantPayeUSD()))} disabled />
            </div>
          </div>

          <div className={styles.fieldRow}>
            <div className={styles.field}>
              <label>Canal de réception *</label>
              <select
                value={formData.canal}
                onChange={(e) => setFormData(prev => ({ ...prev, canal: e.target.value as 'CAISSE' | 'BANQUE' }))}
              >
                <option value="CAISSE" disabled={isCashClosed}>Caisse</option>
                <option value="BANQUE">Banque</option>
              </select>
            </div>
            <div className={styles.field}>
              <label>Compte de dépôt *</label>
              <select
                value={formData.compte_bancaire_id}
                onChange={(e) => setFormData(prev => ({ ...prev, compte_bancaire_id: e.target.value }))}
                required
              >
                <option value="">Sélectionner un compte</option>
                {filteredComptes.map(c => (
                  <option key={c.id} value={c.id}>
                    {c.banque?.nom || 'Caisse'} - {c.intitule} ({c.devise})
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className={styles.field}>
            <label>Description</label>
            <textarea value={formData.description} onChange={e => setFormData(prev => ({ ...prev, description: e.target.value }))} rows={2} />
          </div>

          <div className={styles.fieldRow}>
            <div className={styles.field}>
              <label>Montant payé ({formData.devise_perception}) *</label>
              <input type="number" step="0.01" value={formData.montant_paye} onChange={e => setFormData(prev => ({ ...prev, montant_paye: e.target.value }))} required />
            </div>
            <div className={styles.field}>
              <label>Mode de paiement *</label>
              <select value={formData.mode_paiement} onChange={e => setFormData(prev => ({ ...prev, mode_paiement: e.target.value as ModePaiement }))}>
                <option value="cash" disabled={isCashClosed}>Cash</option>
                <option value="mobile_money">Mobile Money</option>
                <option value="card">Carte</option>
                <option value="virement">Virement</option>
              </select>
            </div>
          </div>

          <div className={styles.formActions}>
            <button type="button" onClick={onClose} className={styles.secondaryBtn}>Annuler</button>
            <button type="button" onClick={handleCreateProforma} className={styles.secondaryBtn}>Générer Proforma</button>
            <button type="submit" className={styles.primaryBtn}>Enregistrer</button>
          </div>
        </form>
      </div>
    </div>
  )
}
