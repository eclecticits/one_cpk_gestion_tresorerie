import styles from '../pages/Encaissements.module.css'

interface EncaissementFiltersProps {
  dateDebut: string
  setDateDebut: (val: string) => void
  dateFin: string
  setDateFin: (val: string) => void
  applyDateFilters: () => void
  hasPendingDateFilters: boolean
  filterStatut: string
  setFilterStatut: (val: string) => void
  filterNumeroRecu: string
  setFilterNumeroRecu: (val: string) => void
  filterClient: string
  setFilterClient: (val: string) => void
  filterBudgetPosteId: string
  setFilterBudgetPosteId: (val: string) => void
  filterOperationStatus: string
  setFilterOperationStatus: (val: string) => void
  canViewCancelled: boolean
  budgetLines: any[]
  pageSize: number
  setPageSize: (val: number) => void
  hasActiveFilters: boolean
  resetFilters: () => void
  totalCount: number
  exportToExcel: () => void
  exportToPDF: () => void
  totalMontantFacture: number
  totalEncaissements: number
  totalResteAPayer: number
  formatCurrency: (amount: number) => string
  filteredCount: number
}

export default function EncaissementFilters({
  dateDebut,
  setDateDebut,
  dateFin,
  setDateFin,
  applyDateFilters,
  hasPendingDateFilters,
  filterStatut,
  setFilterStatut,
  filterNumeroRecu,
  setFilterNumeroRecu,
  filterClient,
  setFilterClient,
  filterBudgetPosteId,
  setFilterBudgetPosteId,
  filterOperationStatus,
  setFilterOperationStatus,
  canViewCancelled,
  budgetLines,
  pageSize,
  setPageSize,
  hasActiveFilters,
  resetFilters,
  totalCount,
  exportToExcel,
  exportToPDF,
  totalMontantFacture,
  totalEncaissements,
  totalResteAPayer,
  formatCurrency,
  filteredCount,
}: EncaissementFiltersProps) {
  return (
    <div className={styles.filtersSection}>
      <h3>Filtres</h3>

      <div className={styles.filterGrid}>
        <div className={styles.filterField}>
          <label>Date début</label>
          <input type="date" value={dateDebut} onChange={(e) => setDateDebut(e.target.value)} />
        </div>

        <div className={styles.filterField}>
          <label>Date fin</label>
          <input type="date" value={dateFin} onChange={(e) => setDateFin(e.target.value)} />
        </div>

        <div className={styles.filterField}>
          <label>Période</label>
          <button
            type="button"
            onClick={applyDateFilters}
            className={styles.applyBtn}
            disabled={!hasPendingDateFilters}
          >
            Appliquer
          </button>
        </div>

        <div className={styles.filterField}>
          <label>Statut</label>
          <select value={filterStatut} onChange={(e) => setFilterStatut(e.target.value)}>
            <option value="">Tous les statuts</option>
            <option value="complet">Payé</option>
            <option value="partiel">Paiement partiel</option>
            <option value="non_paye">Non payé</option>
            <option value="avance">Avance</option>
          </select>
        </div>

        <div className={styles.filterField}>
          <label>N° Reçu</label>
          <input
            type="text"
            value={filterNumeroRecu}
            onChange={(e) => setFilterNumeroRecu(e.target.value)}
            placeholder="ONEC-SLUG-2026-0001..."
          />
        </div>

        <div className={styles.filterField}>
          <label>Client</label>
          <input
            type="text"
            value={filterClient}
            onChange={(e) => setFilterClient(e.target.value)}
            placeholder="Nom ou numéro d'ordre"
          />
        </div>

        <div className={styles.filterField}>
          <label>Poste budgétaire</label>
          <select value={filterBudgetPosteId} onChange={(e) => setFilterBudgetPosteId(e.target.value)}>
            <option value="">Tous les postes</option>
            {budgetLines.map((line: any) => (
              <option key={line.id} value={String(line.id)}>
                {line.code} - {line.libelle}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.filterField}>
          <label>État opération</label>
          <select value={filterOperationStatus} onChange={(e) => setFilterOperationStatus(e.target.value)}>
            <option value="ACTIVE">Actifs</option>
            {canViewCancelled && <option value="ANNULEE">Annulés</option>}
            {canViewCancelled && <option value="ALL">Tous</option>}
          </select>
        </div>
      </div>

      <div className={styles.filterActions}>
        <div className={styles.pageSize}>
          <label>Affichage</label>
          <select
            value={String(pageSize)}
            onChange={(e) => setPageSize(Number(e.target.value))}
          >
            <option value="15">15 / page</option>
            <option value="20">20 / page</option>
            <option value="50">50 / page</option>
            <option value="100">100 / page</option>
          </select>
        </div>
        {hasActiveFilters && (
          <button onClick={resetFilters} className={styles.resetBtn}>
            Réinitialiser les filtres
          </button>
        )}
        {totalCount > 0 && (
          <>
            <button onClick={exportToExcel} className={styles.excelBtn}>
              Exporter Excel
            </button>
            <button onClick={exportToPDF} className={styles.pdfBtn}>
              Exporter PDF
            </button>
          </>
        )}
      </div>

      {hasActiveFilters && (
        <div className={styles.filterSummary}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
              gap: '16px',
              marginBottom: '12px',
            }}
          >
            <div>
              <div style={{ fontSize: '13px', color: '#6b7280', marginBottom: '4px' }}>Montant total facturé</div>
              <div style={{ fontSize: '20px', fontWeight: 700, color: '#1f2937' }}>
                {formatCurrency(totalMontantFacture)}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '13px', color: '#6b7280', marginBottom: '4px' }}>
                Montant encaissé (dans la caisse)
              </div>
              <div style={{ fontSize: '20px', fontWeight: 700, color: '#16a34a' }}>
                {formatCurrency(totalEncaissements)}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '13px', color: '#6b7280', marginBottom: '4px' }}>Reste à payer</div>
              <div style={{ fontSize: '20px', fontWeight: 700, color: totalResteAPayer > 0 ? '#f59e0b' : '#6b7280' }}>
                {formatCurrency(totalResteAPayer)}
              </div>
            </div>
          </div>

          <div className={styles.summaryCount}>
            {filteredCount} opération{filteredCount > 1 ? 's' : ''}
          </div>
        </div>
      )}
    </div>
  )
}
