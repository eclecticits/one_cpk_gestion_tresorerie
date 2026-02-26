import { useEffect, useMemo, useState } from 'react'
import { ArrowUpCircle, FileSpreadsheet, ListChecks } from 'lucide-react'
import * as XLSX from 'xlsx'
import ImportBudgetPostes from '../ImportBudgetPostes'
import ServiceAccessManager from './ServiceAccessManager'
import type { Service } from '../../types'
import { getServiceRubriques } from '../../api/services'
import styles from './BudgetTab.module.css'

type Props = {
  services: Service[]
  activeServiceId: number | null
  setActiveServiceId: (id: number) => void
  fiscalYear?: number | null
  exercises?: { annee: number; statut?: string | null }[]
}

export default function BudgetTab({
  services,
  activeServiceId,
  setActiveServiceId,
  fiscalYear,
  exercises = [],
}: Props) {
  const [importOpen, setImportOpen] = useState(false)
  const [importType, setImportType] = useState<'DEPENSE' | 'RECETTE'>('DEPENSE')
  const [selectedYear, setSelectedYear] = useState<number | null>(null)
  const [rubriqueCounts, setRubriqueCounts] = useState<Record<number, number>>({})
  const [loadingCounts, setLoadingCounts] = useState(false)

  const years = useMemo(() => {
    const values = exercises.map((e) => e.annee).filter(Boolean)
    if (fiscalYear) values.unshift(fiscalYear)
    return Array.from(new Set(values)).sort((a, b) => b - a)
  }, [exercises, fiscalYear])

  const effectiveYear = selectedYear ?? years[0] ?? fiscalYear ?? null

  useEffect(() => {
    if (!services.length) {
      setRubriqueCounts({})
      return
    }
    let cancelled = false
    const loadCounts = async () => {
      setLoadingCounts(true)
      try {
        const entries = await Promise.all(
          services.map(async (service) => {
            try {
              const rubs = await getServiceRubriques(service.id)
              return [service.id, Array.isArray(rubs) ? rubs.length : 0] as const
            } catch {
              return [service.id, 0] as const
            }
          })
        )
        if (!cancelled) {
          const next: Record<number, number> = {}
          entries.forEach(([id, count]) => {
            next[id] = count
          })
          setRubriqueCounts(next)
        }
      } finally {
        if (!cancelled) setLoadingCounts(false)
      }
    }
    loadCounts()
    return () => {
      cancelled = true
    }
  }, [services])

  const downloadTemplate = () => {
    const rows = [
      { code: 'II', libelle: 'DEPENSES DE FONCTIONNEMENT', plafond: 0, parent_code: '' },
      { code: 'II.1', libelle: 'Personnel', plafond: 150000, parent_code: 'II' },
    ]
    const worksheet = XLSX.utils.json_to_sheet(rows)
    const workbook = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(workbook, worksheet, 'Modele')
    XLSX.writeFile(workbook, 'modele_postes_budgetaires.xlsx')
  }

  return (
    <div className={styles.wrapper}>
      <section className={styles.importCard}>
        <div className={styles.importIcon}>
          <FileSpreadsheet size={28} />
        </div>
        <h3 className={styles.importTitle}>Mise à jour du budget</h3>
        <p className={styles.importText}>
          Importez un fichier Excel pour mettre à jour les postes budgétaires et les plafonds de l’exercice.
        </p>
        <div className={styles.importActions}>
          <select
            className={styles.importSelect}
            value={effectiveYear ?? ''}
            onChange={(e) => setSelectedYear(e.target.value ? Number(e.target.value) : null)}
          >
            {years.map((year) => (
              <option key={year} value={year}>{year}</option>
            ))}
          </select>
          <select
            className={styles.importSelect}
            value={importType}
            onChange={(e) => setImportType(e.target.value as 'DEPENSE' | 'RECETTE')}
          >
            <option value="DEPENSE">Dépenses</option>
            <option value="RECETTE">Recettes</option>
          </select>
          <button
            type="button"
            className={styles.importButton}
            onClick={() => setImportOpen(true)}
            disabled={!effectiveYear}
          >
            <ArrowUpCircle size={18} /> Sélectionner un fichier
          </button>
          <button
            type="button"
            className={styles.importButton}
            onClick={downloadTemplate}
          >
            Télécharger le modèle
          </button>
        </div>
        <div className={styles.importHint}>Formats acceptés : .xlsx, .csv (max 10 Mo)</div>
      </section>

      <section className={styles.whitelistCard}>
        <div className={styles.whitelistHeader}>
          <h3>
            <ListChecks size={18} /> Répartition des droits budgétaires
          </h3>
          <p className={styles.importText} style={{ marginTop: 4 }}>
            Définissez les postes budgétaires autorisés pour chaque commission.
          </p>
        </div>
        <div className={styles.whitelistGrid}>
          <div className={styles.serviceList}>
            {services.map((service) => (
              <button
                key={service.id}
                type="button"
                className={`${styles.serviceItem} ${activeServiceId === service.id ? styles.serviceItemActive : ''}`}
                onClick={() => setActiveServiceId(service.id)}
              >
                <span className={styles.serviceCode}>{service.code}</span>
                <span className={styles.serviceLabel}>{service.libelle}</span>
                <span className={styles.serviceMeta}>
                  {loadingCounts ? 'Chargement…' : `${rubriqueCounts[service.id] ?? 0} postes budgétaires`}
                </span>
              </button>
            ))}
            {services.length === 0 && (
              <div className={styles.emptyState}>Aucun service disponible.</div>
            )}
          </div>
          <ServiceAccessManager
            serviceId={activeServiceId}
            serviceLabel={
              services.find((s) => s.id === activeServiceId)
                ? `${services.find((s) => s.id === activeServiceId)?.code} - ${services.find((s) => s.id === activeServiceId)?.libelle}`
                : undefined
            }
          />
        </div>
      </section>

      {importOpen && effectiveYear && (
        <ImportBudgetPostes
          annee={effectiveYear}
          type={importType}
          onClose={() => setImportOpen(false)}
          onSuccess={() => setImportOpen(false)}
        />
      )}
    </div>
  )
}
