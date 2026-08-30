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
  //: Ce qui est tapé — ne pilote que les propositions.
  numeroSaisi: string
  setNumeroSaisi: (val: string) => void
  //: Ce qui est retenu — pilote la liste, ses totaux et sa pagination.
  appliquerNumero: (val: string) => void
  numeroSuggestions: any[]
  isSearchingNumeros: boolean
  rechercheNumerosEnEchec: boolean
  filterNumeroRecu: string
  clientSaisi: string
  setClientSaisi: (val: string) => void
  appliquerClient: (val: string) => void
  clientSuggestions: any[]
  isSearchingClients: boolean
  rechercheClientsEnEchec: boolean
  filterClient: string
  filterBudgetPosteId: string
  setFilterBudgetPosteId: (val: string) => void
  filterOperationStatus: string
  setFilterOperationStatus: (val: string) => void
  filterDeletedStatus: string
  setFilterDeletedStatus: (val: string) => void
  canViewCancelled: boolean
  budgetLines: any[]
  pageSize: number
  setPageSize: (val: number) => void
  hasActiveFilters: boolean
  resetFilters: () => void
  totalCount: number
  exportToExcel: () => void
  exportToPDF: () => void
  totalMontantNotesDebit: number
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
  numeroSaisi,
  setNumeroSaisi,
  appliquerNumero,
  numeroSuggestions,
  isSearchingNumeros,
  rechercheNumerosEnEchec,
  filterNumeroRecu,
  clientSaisi,
  setClientSaisi,
  appliquerClient,
  clientSuggestions,
  isSearchingClients,
  rechercheClientsEnEchec,
  filterClient,
  filterBudgetPosteId,
  setFilterBudgetPosteId,
  filterOperationStatus,
  setFilterOperationStatus,
  filterDeletedStatus,
  setFilterDeletedStatus,
  canViewCancelled,
  budgetLines,
  pageSize,
  setPageSize,
  hasActiveFilters,
  resetFilters,
  totalCount,
  exportToExcel,
  exportToPDF,
  totalMontantNotesDebit,
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
            disabled={!hasPendingDateFilters || Boolean(filterNumeroRecu || filterClient)}
          >
            Appliquer
          </button>
          {/* Sans ce mot, les champs de date paraissent cassés : on les change,
              on applique, et rien ne bouge. */}
          {(filterNumeroRecu || filterClient) && (
            <small style={{ color: '#6b7280' }}>
              Période ignorée : recherche ciblée.
            </small>
          )}
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
          <label>N° Note de débit</label>
          {/* Même geste que le choix d'un client dans le formulaire : on tape,
              on choisit, et c'est le choix qui filtre. Tant qu'on tape, la liste
              derrière ne bouge pas — c'est ce qui rendait l'écran illisible. */}
          <div style={{ position: 'relative' }}>
            <input
              type="text"
              value={numeroSaisi}
              onChange={(e) => setNumeroSaisi(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  // Entrée retient le numéro tel quel : celui qui colle un
                  // numéro complet ne doit pas avoir à viser une proposition.
                  appliquerNumero(numeroSaisi)
                } else if (e.key === 'Escape') {
                  setNumeroSaisi('')
                }
              }}
              placeholder="Tapez le numéro : les notes seront proposées"
              style={{ borderColor: filterNumeroRecu ? '#10b981' : undefined }}
            />
            {filterNumeroRecu && (
              <button
                type="button"
                onClick={() => appliquerNumero('')}
                title="Effacer le filtre"
                aria-label="Effacer le filtre sur le numéro"
                style={{
                  position: 'absolute', right: '8px', top: '50%',
                  transform: 'translateY(-50%)', border: 'none', background: 'none',
                  cursor: 'pointer', color: '#6b7280', fontSize: '16px', lineHeight: 1,
                }}
              >
                ×
              </button>
            )}
            {/* Dans le conteneur positionné, pour que `.dropdown` (top: 100%)
                s'ancre sous le champ et non sous un ancêtre lointain. */}
            {numeroSuggestions.length > 0 && (
              <div className={styles.dropdown} onMouseDown={(e) => e.preventDefault()}>
                {numeroSuggestions.map((n) => (
                  <div
                    key={n.numero}
                    className={styles.dropdownItem}
                    onClick={() => appliquerNumero(n.numero)}
                  >
                    <strong>{n.numero}</strong>
                    {n.est_proforma && (
                      <span style={{ marginLeft: 6, fontSize: 11, color: '#92400e' }}>
                        pro forma
                      </span>
                    )}
                    <div style={{ fontSize: 12, color: '#6b7280' }}>
                      {[n.client_nom, `${n.montant_total} ${n.devise}`]
                        .filter(Boolean)
                        .join(' · ')}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          {isSearchingNumeros && <small>Recherche…</small>}
          {/* Ne jamais annoncer une absence quand on n'a pas su chercher : le
              lecteur en conclurait que la note n'existe pas. */}
          {!isSearchingNumeros && rechercheNumerosEnEchec && (
            <small style={{ color: '#b91c1c' }}>
              La recherche n’a pas abouti. Réessayez ; si cela persiste, le service est
              momentanément indisponible.
            </small>
          )}
          {!isSearchingNumeros
            && !rechercheNumerosEnEchec
            && numeroSaisi.trim().length >= 2
            && numeroSuggestions.length === 0
            && !filterNumeroRecu && (
            <small style={{ color: '#92400e' }}>Aucune note ne porte ce numéro.</small>
          )}
        </div>

        <div className={styles.filterField}>
          <label>Client</label>
          {/* Mêmes règles que le numéro : on tape, on choisit, le choix filtre.
              Les propositions viennent des encaissements réels, avec leur
              nombre — ce qui est proposé rend toujours quelque chose. */}
          <div style={{ position: 'relative' }}>
            <input
              type="text"
              value={clientSaisi}
              onChange={(e) => setClientSaisi(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  appliquerClient(clientSaisi)
                } else if (e.key === 'Escape') {
                  setClientSaisi('')
                }
              }}
              placeholder="Nom ou numéro d'ordre : les payeurs seront proposés"
              style={{ borderColor: filterClient ? '#10b981' : undefined }}
            />
            {filterClient && (
              <button
                type="button"
                onClick={() => appliquerClient('')}
                title="Effacer le filtre"
                aria-label="Effacer le filtre sur le payeur"
                style={{
                  position: 'absolute', right: '8px', top: '50%',
                  transform: 'translateY(-50%)', border: 'none', background: 'none',
                  cursor: 'pointer', color: '#6b7280', fontSize: '16px', lineHeight: 1,
                }}
              >
                ×
              </button>
            )}
            {clientSuggestions.length > 0 && (
              <div className={styles.dropdown} onMouseDown={(e) => e.preventDefault()}>
                {clientSuggestions.map((c) => (
                  <div
                    key={`${c.type}-${c.valeur}`}
                    className={styles.dropdownItem}
                    onClick={() => appliquerClient(c.valeur)}
                  >
                    <strong>{c.libelle}</strong>
                    {c.type === 'expert' && (
                      <span style={{ marginLeft: 6, fontSize: 11, color: '#0369a1' }}>
                        expert comptable{c.detail ? ` · ${c.detail}` : ''}
                      </span>
                    )}
                    <div style={{ fontSize: 12, color: '#6b7280' }}>
                      {c.nb} opération{c.nb > 1 ? 's' : ''}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          {isSearchingClients && <small>Recherche…</small>}
          {!isSearchingClients && rechercheClientsEnEchec && (
            <small style={{ color: '#b91c1c' }}>
              La recherche n’a pas abouti. Réessayez ; si cela persiste, le service est
              momentanément indisponible.
            </small>
          )}
          {!isSearchingClients
            && !rechercheClientsEnEchec
            && clientSaisi.trim().length >= 2
            && clientSuggestions.length === 0
            && !filterClient && (
            <small style={{ color: '#92400e' }}>Aucun payeur ne porte ce nom.</small>
          )}
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

        <div className={styles.filterField}>
          <label>Suppression</label>
          <select value={filterDeletedStatus} onChange={(e) => setFilterDeletedStatus(e.target.value)}>
            <option value="all">Tous</option>
            <option value="active">Actifs</option>
            <option value="deleted">Supprimés</option>
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
              <div style={{ fontSize: '13px', color: '#6b7280', marginBottom: '4px' }}>Montant total des notes de débit</div>
              <div style={{ fontSize: '20px', fontWeight: 700, color: '#1f2937' }}>
                {formatCurrency(totalMontantNotesDebit)}
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
