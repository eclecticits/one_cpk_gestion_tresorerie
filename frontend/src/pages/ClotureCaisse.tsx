import { useEffect, useMemo, useState } from 'react'
import {
  createCloture,
  getClotureBalance,
  getClotureCaissiers,
  getCloturePdfData,
  listClotures,
  listCloturesWithFilters,
  uploadCloturePdf,
  ClotureBalance,
  ClotureOut
} from '../api/clotures'
import { useToast } from '../hooks/useToast'
import { toNumber } from '../utils/amount'
import { generateCloturePDF } from '../utils/pdfClotureGenerator'
import { API_BASE_URL, getAccessToken } from '../lib/apiClient'
import { listDenominations } from '../api/denominations'
import styles from './ClotureCaisse.module.css'

const USD_DENOMS = [100, 50, 20, 10, 5, 1]
const CDF_DENOMS = [20000, 10000, 5000, 2000, 1000, 500, 200, 100, 50]

const formatMoney = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(value)
const formatMoneyCdf = (value: number) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'CDF' }).format(value)

const toInt = (value: string) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : 0
}

export default function ClotureCaisse() {
  const { notifyError, notifySuccess } = useToast()
  const [balance, setBalance] = useState<ClotureBalance | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [billetageUsd, setBilletageUsd] = useState<Record<string, number>>({})
  const [billetageCdf, setBilletageCdf] = useState<Record<string, number>>({})
  const [observation, setObservation] = useState('')
  const [lastCloture, setLastCloture] = useState<ClotureOut | null>(null)
  const [history, setHistory] = useState<ClotureOut[]>([])
  const [exporting, setExporting] = useState(false)
  const [selectedClotureId, setSelectedClotureId] = useState<number | null>(null)
  const [historyFilters, setHistoryFilters] = useState({
    date_debut: '',
    date_fin: '',
    caissier_id: '',
  })
  const [caissiers, setCaissiers] = useState<{ id: string; label: string }[]>([])
  const [denomsUsd, setDenomsUsd] = useState<number[]>(USD_DENOMS)
  const [denomsCdf, setDenomsCdf] = useState<number[]>(CDF_DENOMS)

  useEffect(() => {
    const loadBalance = async () => {
      setLoading(true)
      try {
        const data = await getClotureBalance()
        setBalance(data)
      } catch (error: any) {
        notifyError('Erreur', error?.payload?.detail || error?.message || 'Impossible de charger le solde.')
      } finally {
        setLoading(false)
      }
    }
    loadBalance()
  }, [notifyError])

  useEffect(() => {
    const loadHistory = async () => {
      try {
        const items = await listClotures(20, 0)
        setHistory(items || [])
      } catch (error) {
        console.error('Erreur chargement clôtures:', error)
      }
    }
    loadHistory()
  }, [])

  useEffect(() => {
    const loadDenoms = async () => {
      try {
        const data = await listDenominations({ active: true })
        const usd = data.filter((d) => d.devise === 'USD').map((d) => Number(d.valeur))
        const cdf = data.filter((d) => d.devise === 'CDF').map((d) => Number(d.valeur))
        setDenomsUsd(usd.length ? usd : USD_DENOMS)
        setDenomsCdf(cdf.length ? cdf : CDF_DENOMS)
      } catch (error) {
        setDenomsUsd(USD_DENOMS)
        setDenomsCdf(CDF_DENOMS)
      }
    }
    loadDenoms()
  }, [])

  useEffect(() => {
    const loadCaissiers = async () => {
      try {
        const data = await getClotureCaissiers()
        setCaissiers(data || [])
      } catch (error) {
        console.error('Erreur chargement caissiers:', error)
      }
    }
    loadCaissiers()
  }, [])

  const totalUsd = useMemo(
    () => denomsUsd.reduce((sum, denom) => sum + denom * (billetageUsd[String(denom)] || 0), 0),
    [billetageUsd, denomsUsd]
  )
  const totalCdf = useMemo(
    () => denomsCdf.reduce((sum, denom) => sum + denom * (billetageCdf[String(denom)] || 0), 0),
    [billetageCdf, denomsCdf]
  )

  const tauxChange = toNumber(balance?.taux_change || 1)
  const soldeTheoUsd = toNumber(balance?.solde_theorique_usd || 0)
  const soldeTheoCdf = toNumber(balance?.solde_theorique_cdf || 0)
  const totalUsdEquiv = totalUsd + (tauxChange > 0 ? totalCdf / tauxChange : 0)
  const ecartUsd = totalUsdEquiv - soldeTheoUsd
  const ecartCdf = totalCdf - soldeTheoCdf

  const verdict = () => {
    if (ecartUsd === 0 && ecartCdf === 0) return { label: 'Caisse équilibrée', tone: styles.ok }
    if (ecartUsd < 0 || ecartCdf < 0) return { label: 'Manquant de caisse', tone: styles.danger }
    return { label: 'Excédent de caisse', tone: styles.warn }
  }

  const handleSubmit = async () => {
    setSaving(true)
    try {
      const payload = {
        solde_physique_usd: totalUsd,
        solde_physique_cdf: totalCdf,
        billetage_usd: billetageUsd,
        billetage_cdf: billetageCdf,
        observation: observation.trim() || undefined,
      }
      const res = await createCloture(payload)
      setLastCloture(res)
      setHistory((prev) => [res, ...prev].slice(0, 20))
      notifySuccess('Clôture enregistrée', `Réf: ${res.reference_numero}`)
    } catch (error: any) {
      notifyError('Erreur', error?.payload?.detail || error?.message || 'Impossible d’enregistrer la clôture.')
    } finally {
      setSaving(false)
    }
  }

  const handlePrint = () => {
    const run = async () => {
      if (!lastCloture) return
      const data = await getCloturePdfData(lastCloture.id)
      const blob = generateCloturePDF({
        date: data.cloture.date_cloture,
        total: toNumber(data.cloture.total_sorties_usd || 0),
        details: data.details || [],
        reference_numero: data.cloture.reference_numero,
        solde_initial_usd: data.cloture.solde_initial_usd,
        total_entrees_usd: data.cloture.total_entrees_usd,
        total_sorties_usd: data.cloture.total_sorties_usd,
        solde_theorique_usd: data.cloture.solde_theorique_usd,
        solde_physique_usd: data.cloture.solde_physique_usd,
        ecart_usd: data.cloture.ecart_usd,
        solde_initial_cdf: data.cloture.solde_initial_cdf,
        total_entrees_cdf: data.cloture.total_entrees_cdf,
        total_sorties_cdf: data.cloture.total_sorties_cdf,
        solde_theorique_cdf: data.cloture.solde_theorique_cdf,
        solde_physique_cdf: data.cloture.solde_physique_cdf,
        ecart_cdf: data.cloture.ecart_cdf,
        taux_change_applique: data.cloture.taux_change_applique,
        billetage_usd: data.cloture.billetage_usd || {},
        billetage_cdf: data.cloture.billetage_cdf || {},
      }, { returnBlob: true })
      if (blob) {
        await uploadCloturePdf(lastCloture.id, blob)
      }
    }
    run().catch((error) => {
      notifyError('Erreur PDF', error?.message || 'Impossible de générer le PV.')
    })
  }

  const handleSelectCloture = (value: string) => {
    const id = Number(value)
    if (!Number.isFinite(id)) {
      setSelectedClotureId(null)
      return
    }
    const selected = history.find((c) => c.id === id) || null
    setSelectedClotureId(id)
    if (selected) {
      setLastCloture(selected)
    }
  }

  const handleExportHistory = async () => {
    setExporting(true)
    try {
      const token = getAccessToken()
      const url = `${API_BASE_URL}/clotures/export-xlsx`
      const resp = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!resp.ok) {
        const message = await resp.text()
        throw new Error(message || `HTTP ${resp.status}`)
      }
      const blob = await resp.blob()
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = `clotures_${new Date().toISOString().slice(0, 10)}.xlsx`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(link.href)
    } catch (error: any) {
      notifyError('Export impossible', error?.message || 'Erreur inconnue')
    } finally {
      setExporting(false)
    }
  }

  const applyHistoryFilters = async () => {
    try {
      const items = await listCloturesWithFilters({
        date_debut: historyFilters.date_debut || undefined,
        date_fin: historyFilters.date_fin || undefined,
        caissier_id: historyFilters.caissier_id || undefined,
        limit: 50,
        offset: 0,
      })
      setHistory(items || [])
    } catch (error) {
      notifyError('Erreur', 'Impossible de filtrer les clôtures.')
    }
  }

  const downloadArchivedPdf = async (cloture: ClotureOut) => {
    try {
      const token = getAccessToken()
      const url = `${API_BASE_URL}/clotures/${cloture.id}/pdf`
      const resp = await fetch(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!resp.ok) {
        const message = await resp.text()
        throw new Error(message || `HTTP ${resp.status}`)
      }
      const blob = await resp.blob()
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = cloture.pdf_path || `cloture_${cloture.reference_numero}.pdf`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(link.href)
    } catch (error: any) {
      notifyError('Téléchargement impossible', error?.message || 'PV introuvable')
    }
  }

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1>Clôture de caisse</h1>
        <p>Inventaire journalier du billetage et comparaison avec le solde théorique.</p>
      </header>

      {loading && <div className={styles.loading}>Chargement du solde théorique…</div>}

      {balance && (
        <section className={styles.summary}>
          <div>
            <span>Taux de change</span>
            <strong>{tauxChange.toFixed(2)}</strong>
          </div>
          <div>
            <span>Solde initial USD</span>
            <strong>{formatMoney(toNumber(balance.solde_initial_usd))}</strong>
          </div>
          <div>
            <span>Entrées USD</span>
            <strong>{formatMoney(toNumber(balance.total_entrees_usd))}</strong>
          </div>
          <div>
            <span>Sorties USD</span>
            <strong>{formatMoney(toNumber(balance.total_sorties_usd))}</strong>
          </div>
          <div>
            <span>Solde théorique USD</span>
            <strong>{formatMoney(soldeTheoUsd)}</strong>
          </div>
          <div>
            <span>Solde théorique CDF</span>
            <strong>{formatMoneyCdf(soldeTheoCdf)}</strong>
          </div>
        </section>
      )}

      <section className={styles.billetageSection}>
        <div className={styles.billetageCard}>
          <h2>Billetage USD</h2>
          <table>
            <thead>
              <tr>
                <th>Coupure</th>
                <th>Quantité</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              {denomsUsd.map((denom) => {
                const qty = billetageUsd[String(denom)] || 0
                return (
                  <tr key={denom}>
                    <td>{formatMoney(denom)}</td>
                    <td>
                      <input
                        type="number"
                        min={0}
                        value={qty}
                        onChange={(e) =>
                          setBilletageUsd((prev) => ({ ...prev, [String(denom)]: toInt(e.target.value) }))
                        }
                      />
                    </td>
                    <td>{formatMoney(denom * qty)}</td>
                  </tr>
                )
              })}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={2}>Total USD</td>
                <td>{formatMoney(totalUsd)}</td>
              </tr>
            </tfoot>
          </table>
        </div>

        <div className={styles.billetageCard}>
          <h2>Billetage CDF</h2>
          <table>
            <thead>
              <tr>
                <th>Coupure</th>
                <th>Quantité</th>
                <th>Total</th>
              </tr>
            </thead>
            <tbody>
              {denomsCdf.map((denom) => {
                const qty = billetageCdf[String(denom)] || 0
                return (
                  <tr key={denom}>
                    <td>{formatMoneyCdf(denom)}</td>
                    <td>
                      <input
                        type="number"
                        min={0}
                        value={qty}
                        onChange={(e) =>
                          setBilletageCdf((prev) => ({ ...prev, [String(denom)]: toInt(e.target.value) }))
                        }
                      />
                    </td>
                    <td>{formatMoneyCdf(denom * qty)}</td>
                  </tr>
                )
              })}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={2}>Total CDF</td>
                <td>{formatMoneyCdf(totalCdf)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <section className={styles.verdict}>
        <div>
          <span>Solde physique USD</span>
          <strong>{formatMoney(totalUsd)}</strong>
        </div>
        <div>
          <span>Solde physique USD (équiv.)</span>
          <strong>{formatMoney(totalUsdEquiv)}</strong>
        </div>
        <div>
          <span>Écart USD</span>
          <strong className={ecartUsd === 0 ? styles.okText : ecartUsd < 0 ? styles.dangerText : styles.warnText}>
            {formatMoney(ecartUsd)}
          </strong>
        </div>
        <div>
          <span>Solde physique CDF</span>
          <strong>{formatMoneyCdf(totalCdf)}</strong>
        </div>
        <div>
          <span>Écart CDF</span>
          <strong className={ecartCdf === 0 ? styles.okText : ecartCdf < 0 ? styles.dangerText : styles.warnText}>
            {formatMoneyCdf(ecartCdf)}
          </strong>
        </div>
        <div className={`${styles.verdictBadge} ${verdict().tone}`}>{verdict().label}</div>
      </section>

      <section className={styles.observation}>
        <label>Observations</label>
        <textarea
          value={observation}
          onChange={(e) => setObservation(e.target.value)}
          placeholder="Notes ou explications (optionnel)."
        />
      </section>

      <div className={styles.actions}>
        <button type="button" onClick={handleSubmit} disabled={saving || loading}>
          {saving ? 'Enregistrement...' : 'Valider la clôture'}
        </button>
        <button type="button" className={styles.secondary} onClick={handlePrint} disabled={!lastCloture}>
          Imprimer PV
        </button>
        <button type="button" className={styles.secondary} onClick={handleExportHistory} disabled={exporting}>
          {exporting ? 'Export...' : 'Export historique'}
        </button>
      </div>

      <section className={styles.history}>
        <div className={styles.historyHeader}>
          <h3>Historique des clôtures</h3>
        </div>
        <div className={styles.historySelector}>
          <label>Consulter une clôture</label>
          <select value={selectedClotureId ?? ''} onChange={(e) => handleSelectCloture(e.target.value)}>
            <option value="">Sélectionner une date</option>
            {history.map((c) => (
              <option key={c.id} value={c.id}>
                {new Date(c.date_cloture).toLocaleString('fr-FR')} · {c.reference_numero}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.historyFilters}>
          <input
            type="date"
            value={historyFilters.date_debut}
            onChange={(e) => setHistoryFilters((prev) => ({ ...prev, date_debut: e.target.value }))}
          />
          <input
            type="date"
            value={historyFilters.date_fin}
            onChange={(e) => setHistoryFilters((prev) => ({ ...prev, date_fin: e.target.value }))}
          />
          <select
            value={historyFilters.caissier_id}
            onChange={(e) => setHistoryFilters((prev) => ({ ...prev, caissier_id: e.target.value }))}
          >
            <option value="">Tous les caissiers</option>
            {caissiers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
          <button type="button" className={styles.secondary} onClick={applyHistoryFilters}>
            Filtrer
          </button>
        </div>
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Référence</th>
              <th>Solde théorique USD</th>
              <th>Solde physique USD</th>
              <th>Écart USD</th>
              <th>Solde théorique CDF</th>
              <th>Solde physique CDF</th>
              <th>Écart CDF</th>
              <th>PV</th>
            </tr>
          </thead>
          <tbody>
            {history.length === 0 && (
              <tr>
                <td colSpan={9} className={styles.emptyCell}>
                  Aucune clôture enregistrée.
                </td>
              </tr>
            )}
            {history.map((c) => (
              <tr key={c.id}>
                <td>{new Date(c.date_cloture).toLocaleString('fr-FR')}</td>
                <td>{c.reference_numero}</td>
                <td>{formatMoney(toNumber(c.solde_theorique_usd))}</td>
                <td>{formatMoney(toNumber(c.solde_physique_usd))}</td>
                <td className={toNumber(c.ecart_usd) === 0 ? styles.okText : toNumber(c.ecart_usd) < 0 ? styles.dangerText : styles.warnText}>
                  {formatMoney(toNumber(c.ecart_usd))}
                </td>
                <td>{formatMoneyCdf(toNumber(c.solde_theorique_cdf))}</td>
                <td>{formatMoneyCdf(toNumber(c.solde_physique_cdf))}</td>
                <td className={toNumber(c.ecart_cdf) === 0 ? styles.okText : toNumber(c.ecart_cdf) < 0 ? styles.dangerText : styles.warnText}>
                  {formatMoneyCdf(toNumber(c.ecart_cdf))}
                </td>
                <td>
                  <button
                    type="button"
                    className={styles.secondary}
                    onClick={() => downloadArchivedPdf(c)}
                    disabled={!c.pdf_path}
                  >
                    Télécharger
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
