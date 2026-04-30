import { useEffect, useMemo, useState } from 'react'
import { Landmark, PencilLine, Plus, Trash2, WalletCards } from 'lucide-react'
import {
  listDenominations,
  createDenomination,
  updateDenomination,
  deleteDenomination,
  Denomination,
} from '../api/denominations'
import { useToast } from '../hooks/useToast'
import PageHeader from '../components/PageHeader'
import styles from './Denominations.module.css'

const defaultForm = {
  devise: 'USD',
  valeur: 0,
  label: '',
  est_actif: true,
  ordre: 0,
}

const currencyMeta = {
  USD: {
    label: 'USD',
    subtitle: 'Coupures en dollars américains',
    symbol: '$',
    cardClass: 'usdCard',
    badgeClass: 'badgeUsd',
  },
  CDF: {
    label: 'CDF',
    subtitle: 'Coupures en francs congolais',
    symbol: 'FC',
    cardClass: 'cdfCard',
    badgeClass: 'badgeCdf',
  },
} as const

const formatValue = (value: number, devise: string) => {
  const formatted = Number(value || 0).toLocaleString('fr-FR')
  return devise === 'CDF' ? `${formatted} FC` : `${formatted} $`
}

export default function Denominations() {
  const { notifyError, notifySuccess } = useToast()
  const [items, setItems] = useState<Denomination[]>([])
  const [loading, setLoading] = useState(false)
  const [form, setForm] = useState({ ...defaultForm })

  const loadData = async () => {
    setLoading(true)
    try {
      const data = await listDenominations()
      setItems(data || [])
    } catch (error: any) {
      notifyError('Erreur', error?.message || 'Chargement impossible')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const groupedItems = useMemo(
    () => ({
      USD: items
        .filter((item) => String(item.devise).toUpperCase() === 'USD')
        .sort((a, b) => Number(a.ordre || 0) - Number(b.ordre || 0) || Number(a.valeur || 0) - Number(b.valeur || 0)),
      CDF: items
        .filter((item) => String(item.devise).toUpperCase() === 'CDF')
        .sort((a, b) => Number(a.ordre || 0) - Number(b.ordre || 0) || Number(a.valeur || 0) - Number(b.valeur || 0)),
    }),
    [items]
  )

  const counts = useMemo(
    () => ({
      total: items.length,
      active: items.filter((item) => item.est_actif).length,
    }),
    [items]
  )

  const handleCreate = async () => {
    try {
      const payload = {
        devise: form.devise,
        valeur: Number(form.valeur),
        label: form.label,
        est_actif: form.est_actif,
        ordre: Number(form.ordre),
      }
      const res = await createDenomination(payload)
      setItems((prev) => [...prev, res])
      setForm({ ...defaultForm })
      notifySuccess('Ajouté', 'Dénomination créée.')
    } catch (error: any) {
      notifyError('Erreur', error?.payload?.detail || error?.message || 'Création impossible')
    }
  }

  const handleToggle = async (denom: Denomination) => {
    try {
      const res = await updateDenomination(denom.id, { est_actif: !denom.est_actif })
      setItems((prev) => prev.map((d) => (d.id === denom.id ? res : d)))
    } catch (error: any) {
      notifyError('Erreur', error?.payload?.detail || error?.message || 'Mise à jour impossible')
    }
  }

  const handleUpdateField = async (denom: Denomination, field: keyof Denomination, value: any) => {
    try {
      const res = await updateDenomination(denom.id, { [field]: value })
      setItems((prev) => prev.map((d) => (d.id === denom.id ? res : d)))
    } catch (error: any) {
      notifyError('Erreur', error?.payload?.detail || error?.message || 'Mise à jour impossible')
    }
  }

  const handleDelete = async (denom: Denomination) => {
    try {
      await deleteDenomination(denom.id)
      setItems((prev) => prev.filter((d) => d.id !== denom.id))
      notifySuccess('Supprimé', 'Dénomination supprimée.')
    } catch (error: any) {
      notifyError('Erreur', error?.payload?.detail || error?.message || 'Suppression impossible')
    }
  }

  const renderDesktopTable = (currency: 'USD' | 'CDF', data: Denomination[]) => {
    if (!data.length) {
      return (
        <div className={styles.emptyState}>
          <WalletCards size={20} />
          <p>Aucune coupure configurée pour {currency}.</p>
        </div>
      )
    }

    return (
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Devise</th>
              <th>Valeur</th>
              <th>Libellé</th>
              <th>Ordre</th>
              <th>Statut</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.id}>
                <td>
                  <span className={`${styles.currencyBadge} ${styles[currencyMeta[currency].badgeClass]}`}>
                    {currency}
                  </span>
                </td>
                <td>
                  <div className={styles.valueCell}>
                    <strong>{formatValue(d.valeur, d.devise)}</strong>
                    <input
                      className={styles.inlineInput}
                      type="number"
                      defaultValue={d.valeur}
                      onBlur={(e) => handleUpdateField(d, 'valeur', Number(e.target.value))}
                    />
                  </div>
                </td>
                <td>
                  <div className={styles.labelCell}>
                    <span className={styles.labelPreview}>{d.label || 'Sans libellé'}</span>
                    <input
                      className={styles.inlineInput}
                      defaultValue={d.label}
                      onBlur={(e) => handleUpdateField(d, 'label', e.target.value)}
                    />
                  </div>
                </td>
                <td>
                  <div className={styles.orderCell}>
                    <span className={styles.orderPill}>#{d.ordre}</span>
                    <input
                      className={`${styles.inlineInput} ${styles.orderInput}`}
                      type="number"
                      defaultValue={d.ordre}
                      onBlur={(e) => handleUpdateField(d, 'ordre', Number(e.target.value))}
                    />
                  </div>
                </td>
                <td>
                  <button type="button" className={styles.statusBtn} onClick={() => handleToggle(d)}>
                    <span className={`${styles.statusBadge} ${d.est_actif ? styles.statusActive : styles.statusInactive}`}>
                      {d.est_actif ? 'Actif' : 'Inactif'}
                    </span>
                  </button>
                </td>
                <td>
                  <div className={styles.actionsCell}>
                    <span className={styles.editHint}>
                      <PencilLine size={14} />
                      Édition inline
                    </span>
                    <button type="button" className={styles.deleteBtn} onClick={() => handleDelete(d)}>
                      <Trash2 size={14} />
                      Supprimer
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  const renderMobileCards = (currency: 'USD' | 'CDF', data: Denomination[]) => {
    if (!data.length) {
      return (
        <div className={styles.emptyState}>
          <WalletCards size={20} />
          <p>Aucune coupure configurée pour {currency}.</p>
        </div>
      )
    }

    return (
      <div className={styles.mobileList}>
        {data.map((d) => (
          <article key={d.id} className={styles.mobileCard}>
            <div className={styles.mobileCardHeader}>
              <span className={`${styles.currencyBadge} ${styles[currencyMeta[currency].badgeClass]}`}>{currency}</span>
              <span className={`${styles.statusBadge} ${d.est_actif ? styles.statusActive : styles.statusInactive}`}>
                {d.est_actif ? 'Actif' : 'Inactif'}
              </span>
            </div>

            <div className={styles.mobileValue}>{formatValue(d.valeur, d.devise)}</div>
            <p className={styles.mobileLabel}>{d.label || 'Sans libellé'}</p>

            <div className={styles.mobileGrid}>
              <div className={styles.mobileField}>
                <label>Valeur</label>
                <input
                  className={styles.inlineInput}
                  type="number"
                  defaultValue={d.valeur}
                  onBlur={(e) => handleUpdateField(d, 'valeur', Number(e.target.value))}
                />
              </div>
              <div className={styles.mobileField}>
                <label>Ordre</label>
                <input
                  className={styles.inlineInput}
                  type="number"
                  defaultValue={d.ordre}
                  onBlur={(e) => handleUpdateField(d, 'ordre', Number(e.target.value))}
                />
              </div>
              <div className={`${styles.mobileField} ${styles.mobileFieldFull}`}>
                <label>Libellé</label>
                <input
                  className={styles.inlineInput}
                  defaultValue={d.label}
                  onBlur={(e) => handleUpdateField(d, 'label', e.target.value)}
                />
              </div>
            </div>

            <div className={styles.mobileActions}>
              <button type="button" className={styles.mobileEditBtn} onClick={() => handleToggle(d)}>
                {d.est_actif ? 'Désactiver' : 'Activer'}
              </button>
              <button type="button" className={styles.deleteBtn} onClick={() => handleDelete(d)}>
                <Trash2 size={14} />
                Supprimer
              </button>
            </div>
          </article>
        ))}
      </div>
    )
  }

  return (
    <div className={styles.container}>
      <PageHeader
        title="Configuration des billets"
        subtitle="Gérer les coupures USD/CDF utilisées pour le billetage."
        actions={
          <div className={styles.headerMeta}>
            <div className={styles.headerIcon}>
              <Landmark size={18} />
            </div>
            <div className={styles.headerStats}>
              <span>{counts.total} coupures</span>
              <span>{counts.active} actives</span>
            </div>
          </div>
        }
      />

      <section className={styles.formCard}>
        <div className={styles.formIntro}>
          <div>
            <h2>Ajouter une coupure</h2>
            <p>Renseignez les informations principales pour créer une nouvelle dénomination de billetage.</p>
          </div>
        </div>

        <div className={styles.form}>
          <div className={styles.formField}>
            <label>Devise</label>
            <select value={form.devise} onChange={(e) => setForm((p) => ({ ...p, devise: e.target.value }))}>
              <option value="USD">USD</option>
              <option value="CDF">CDF</option>
            </select>
          </div>
          <div className={styles.formField}>
            <label>Valeur</label>
            <input
              type="number"
              value={form.valeur}
              onChange={(e) => setForm((p) => ({ ...p, valeur: e.target.valueAsNumber || 0 }))}
            />
          </div>
          <div className={styles.formField}>
            <label>Libellé</label>
            <input value={form.label} onChange={(e) => setForm((p) => ({ ...p, label: e.target.value }))} />
          </div>
          <div className={styles.formField}>
            <label>Ordre</label>
            <input
              type="number"
              value={form.ordre}
              onChange={(e) => setForm((p) => ({ ...p, ordre: e.target.valueAsNumber || 0 }))}
            />
          </div>
          <div className={styles.formActions}>
            <button type="button" className={styles.addBtn} onClick={handleCreate}>
              <Plus size={16} />
              Ajouter
            </button>
          </div>
        </div>
      </section>

      <div className={styles.sections}>
        {(['USD', 'CDF'] as const).map((currency) => (
          <section key={currency} className={`${styles.currencySection} ${styles[currencyMeta[currency].cardClass]}`}>
            <div className={styles.sectionHeader}>
              <div className={styles.sectionTitleWrap}>
                <span className={`${styles.currencyBadge} ${styles[currencyMeta[currency].badgeClass]}`}>
                  {currencyMeta[currency].symbol} {currencyMeta[currency].label}
                </span>
                <div>
                  <h2>{currencyMeta[currency].subtitle}</h2>
                  <p>{groupedItems[currency].length} coupure(s) configurée(s)</p>
                </div>
              </div>
              <span className={styles.inlineLegend}>Les modifications sont enregistrées à la sortie du champ.</span>
            </div>

            {loading ? (
              <div className={styles.emptyState}>
                <WalletCards size={20} />
                <p>Chargement des coupures...</p>
              </div>
            ) : (
              <>
                <div className={styles.desktopOnly}>{renderDesktopTable(currency, groupedItems[currency])}</div>
                <div className={styles.mobileOnly}>{renderMobileCards(currency, groupedItems[currency])}</div>
              </>
            )}
          </section>
        ))}
      </div>
    </div>
  )
}
