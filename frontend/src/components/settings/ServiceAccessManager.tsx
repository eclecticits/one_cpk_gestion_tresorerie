import { useEffect, useMemo, useState } from 'react'
import { getBudgetPostes } from '../../api/budget'
import { getServiceRubriques, updateServiceRubriques } from '../../api/services'
import type { BudgetPosteSummary } from '../../types/budget'
import styles from './ServiceAccessManager.module.css'

type Props = {
  serviceId: number | null
  serviceLabel?: string
}

export default function ServiceAccessManager({ serviceId, serviceLabel }: Props) {
  const [allRubriques, setAllRubriques] = useState<BudgetPosteSummary[]>([])
  const [assignedIds, setAssignedIds] = useState<number[]>([])
  const [searchTerm, setSearchTerm] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
          getBudgetPostes({ active: true }),
          getServiceRubriques(serviceId),
        ])
        const rubriques = Array.isArray(allRes?.postes) ? allRes.postes : []
        setAllRubriques(rubriques)
        setAssignedIds(assignedRes.map((r) => r.id))
      } catch (err: any) {
        setError(err?.message || 'Impossible de charger les rubriques.')
      } finally {
        setLoading(false)
      }
    }
    loadData()
  }, [serviceId])

  const filteredRubriques = useMemo(() => {
    const term = searchTerm.trim().toLowerCase()
    if (!term) return allRubriques
    return allRubriques.filter((rub) => {
      const code = String(rub.code || '').toLowerCase()
      const libelle = String(rub.libelle || '').toLowerCase()
      return code.includes(term) || libelle.includes(term)
    })
  }, [allRubriques, searchTerm])

  const toggleRubrique = (id: number) => {
    setAssignedIds((prev) =>
      prev.includes(id) ? prev.filter((rid) => rid !== id) : [...prev, id]
    )
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
            {serviceLabel ? `Service sélectionné : ${serviceLabel}` : 'Sélectionnez un service pour gérer ses rubriques.'}
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
          {assignedIds.length} sélectionnée(s) · {allRubriques.length} rubriques
        </div>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.listWrap}>
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
              </tr>
            </thead>
            <tbody>
              {filteredRubriques.map((rub) => (
                <tr key={rub.id}>
                  <td className={styles.checkCol}>
                    <input
                      type="checkbox"
                      checked={assignedIds.includes(rub.id)}
                      onChange={() => toggleRubrique(rub.id)}
                    />
                  </td>
                  <td className={styles.codeCol}>{rub.code}</td>
                  <td className={styles.libelleCell}>{rub.libelle}</td>
                </tr>
              ))}
              {filteredRubriques.length === 0 && (
                <tr>
                  <td colSpan={3} className={styles.state}>
                    Aucune rubrique trouvée.
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
