import { useEffect, useMemo, useRef, useState } from 'react'
import { getBudgetPostesTree } from '../../api/budget'
import { getServiceRubriques, updateServiceRubriques } from '../../api/services'
import type { BudgetPosteSummary, BudgetPosteTree } from '../../types/budget'
import styles from './ServiceAccessManager.module.css'

type Props = {
  serviceId: number | null
  serviceLabel?: string
}

export default function ServiceAccessManager({ serviceId, serviceLabel }: Props) {
  const [allRubriques, setAllRubriques] = useState<BudgetPosteTree[]>([])
  const [assignedIds, setAssignedIds] = useState<number[]>([])
  const [searchTerm, setSearchTerm] = useState('')
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!serviceId) {
      setAllRubriques([])
      setAssignedIds([])
      return
    }
    const loadData = async () => {
      setLoading(true)
      setError(null)
      try {
        const [allRes, assignedRes] = await Promise.all([
          getBudgetPostesTree({ active: true }),
          getServiceRubriques(serviceId),
        ])
        const rubriques = Array.isArray(allRes?.postes) ? allRes.postes : []
        setAllRubriques(rubriques)
        setAssignedIds(assignedRes.map((r) => r.id))
      } catch (err: any) {
        setError(err?.message || 'Impossible de charger les postes budgétaires.')
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [serviceId])

  const filteredRubriques = useMemo(() => {
    const term = searchTerm.trim().toLowerCase()
    if (!term) return allRubriques
    const matches = (node: BudgetPosteTree) => {
      const code = String(node.code || '').toLowerCase()
      const libelle = String(node.libelle || '').toLowerCase()
      const type = String(node.type || '').toLowerCase()
      return code.includes(term) || libelle.includes(term) || type.includes(term)
    }
    const filterNodes = (nodes: BudgetPosteTree[]): BudgetPosteTree[] =>
      nodes
        .map((node) => {
          const children = filterNodes(node.children || [])
          if (matches(node) || children.length > 0) {
            return { ...node, children }
          }
          return null
        })
        .filter(Boolean) as BudgetPosteTree[]
    return filterNodes(allRubriques)
  }, [allRubriques, searchTerm])

  const descendantMap = useMemo(() => {
    const map = new Map<number, number[]>()
    const walk = (node: BudgetPosteTree): number[] => {
      const collected: number[] = []
      ;(node.children || []).forEach((child) => {
        collected.push(child.id)
        collected.push(...walk(child))
      })
      map.set(node.id, collected)
      return collected
    }
    allRubriques.forEach((node) => {
      walk(node)
    })
    return map
  }, [allRubriques])

  const toggleExpanded = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const forceExpand = searchTerm.trim().length > 0

  const TreeRow = ({ node, depth }: { node: BudgetPosteTree; depth: number }) => {
    const hasChildren = (node.children || []).length > 0
    const isExpanded = forceExpand || expandedIds.has(node.id)
    return (
      <>
        <tr>
          <td className={styles.checkCol}>
            <input
              type="checkbox"
              checked={assignedIds.includes(node.id)}
              onChange={() => toggleRubrique(node.id)}
            />
          </td>
          <td className={styles.codeCol}>{node.code}</td>
          <td className={styles.libelleCell}>
            <div className={styles.treeCell} style={{ paddingLeft: `${8 + depth * 16}px` }}>
              {hasChildren ? (
                <button
                  type="button"
                  className={styles.treeToggle}
                  onClick={() => toggleExpanded(node.id)}
                  aria-label={isExpanded ? 'Réduire' : 'Développer'}
                >
                  {isExpanded ? '▾' : '▸'}
                </button>
              ) : (
                <span className={styles.treeSpacer} />
              )}
              <span className={styles.treeLabel}>{node.libelle}</span>
            </div>
          </td>
          <td className={styles.typeCol}>
            <span className={`${styles.typeBadge} ${node.type?.toUpperCase() === 'RECETTE' ? styles.typeRecette : styles.typeDepense}`}>
              {node.type || '—'}
            </span>
          </td>
        </tr>
        {hasChildren && isExpanded && (node.children || []).map((child) => (
          <TreeRow key={child.id} node={child} depth={depth + 1} />
        ))}
      </>
    )
  }

  const toggleRubrique = (id: number) => {
    const scrollTop = listRef.current?.scrollTop ?? 0
    setAssignedIds((prev) => {
      const next = new Set(prev)
      const descendants = descendantMap.get(id) || []
      if (next.has(id)) {
        next.delete(id)
        descendants.forEach((childId) => next.delete(childId))
      } else {
        next.add(id)
        descendants.forEach((childId) => next.add(childId))
      }
      return Array.from(next)
    })
    requestAnimationFrame(() => {
      if (listRef.current) {
        listRef.current.scrollTop = scrollTop
      }
    })
  }

  const handleSave = async () => {
    if (!serviceId) return
    setSaving(true)
    setError(null)
    try {
      await updateServiceRubriques(serviceId, assignedIds)
    } catch (err: any) {
      setError(err?.message || 'Erreur lors de la sauvegarde.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className={styles.panel}>
      <div className={styles.panelHeader}>
        <div>
          <div className={styles.panelTitle}>Gestion des accès services</div>
          <div className={styles.panelSubtitle}>
            {serviceLabel ? `Service sélectionné : ${serviceLabel}` : 'Sélectionnez un service pour gérer ses postes budgétaires.'}
          </div>
        </div>
        <button
          type="button"
          className={styles.saveButton}
          onClick={handleSave}
          disabled={!serviceId || saving}
        >
          {saving ? 'Sauvegarde…' : 'Enregistrer les accès'}
        </button>
      </div>

      <div className={styles.searchRow}>
        <input
          type="search"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Rechercher par code ou libellé (ex: II.2.4)…"
          disabled={!serviceId}
        />
        <div className={styles.counts}>
          {assignedIds.length} sélectionnée(s) · {allRubriques.length} postes budgétaires
        </div>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.listWrap} ref={listRef}>
        {loading ? (
          <div className={styles.state}>Chargement…</div>
        ) : !serviceId ? (
          <div className={styles.state}>Aucun service sélectionné.</div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.checkCol}>Autoriser</th>
                <th className={styles.codeCol}>Code</th>
                <th>Libellé</th>
                <th className={styles.typeCol}>Type</th>
              </tr>
            </thead>
            <tbody>
              {filteredRubriques.map((rub) => (
                <TreeRow key={rub.id} node={rub} depth={0} />
              ))}
              {filteredRubriques.length === 0 && (
                <tr>
                  <td colSpan={4} className={styles.state}>
                    Aucun poste budgétaire trouvé.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </section>
  )
}
