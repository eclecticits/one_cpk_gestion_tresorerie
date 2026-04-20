import { useState, useEffect, useMemo, useCallback } from 'react'
import { apiRequest } from '../lib/apiClient'
import { Requisition, Service } from '../types'
import { getServices } from '../api/services'
import { getBudgetPostes } from '../api/budget'
import { getPrintSettings } from '../api/settings'

export function useRequisitions() {
  // -- State: Data --
  const [requisitions, setRequisitions] = useState<Requisition[]>([])
  const [services, setServices] = useState<Service[]>([])
  const [budgetPostes, setBudgetPostes] = useState<any[]>([])
  const [rubriques, setRubriques] = useState<any[]>([])
  const [printSettings, setPrintSettings] = useState<any | null>(null)
  const [loading, setLoading] = useState(true)
  
  // -- State: Filters --
  const [searchQuery, setSearchQuery] = useState('')
  const [filterStatut, setFilterStatut] = useState<string>('')
  const [filterServiceId, setFilterServiceId] = useState<string>('')

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [reqs, svcs, budgets, rubs, settings] = await Promise.all([
        apiRequest('GET', '/requisitions', {
          params: { include: 'demandeur,validateur,approbateur,examinateur,caissier' }
        }),
        getServices({ active: true }),
        getBudgetPostes({ type: 'DEPENSE', active: true }),
        apiRequest('GET', '/rubriques', { params: { active: true } }),
        getPrintSettings()
      ])
      
      setRequisitions(Array.isArray(reqs) ? reqs : (reqs as any)?.items ?? [])
      setServices(Array.isArray(svcs) ? svcs : [])
      setBudgetPostes(budgets?.postes ?? [])
      setRubriques(Array.isArray(rubs) ? rubs : (rubs as any)?.items ?? [])
      setPrintSettings(settings)
    } catch (error) {
      console.error('Error loading requisitions data:', error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  // Filtered requisitions
  const filteredRequisitions = useMemo(() => {
    return requisitions.filter(req => {
      const matchesSearch = !searchQuery || 
        req.numero_requisition?.toLowerCase().includes(searchQuery.toLowerCase()) ||
        req.objet?.toLowerCase().includes(searchQuery.toLowerCase())
      
      const matchesStatut = !filterStatut || req.status === filterStatut
      const matchesService = !filterServiceId || String(req.service_id) === filterServiceId
      
      return matchesSearch && matchesStatut && matchesService
    })
  }, [requisitions, searchQuery, filterStatut, filterServiceId])

  return {
    requisitions: filteredRequisitions,
    allRequisitions: requisitions,
    services,
    budgetPostes,
    rubriques,
    printSettings,
    loading,
    filters: {
      searchQuery,
      setSearchQuery,
      filterStatut,
      setFilterStatut,
      filterServiceId,
      setFilterServiceId
    },
    refresh: loadData
  }
}
