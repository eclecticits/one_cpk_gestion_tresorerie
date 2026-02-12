import { useEffect, useState } from 'react'
import {
  listDenominations,
  createDenomination,
  updateDenomination,
  deleteDenomination,
  Denomination,
} from '../api/denominations'
import { useToast } from '../hooks/useToast'
import styles from './Denominations.module.css'

const defaultForm = {
  devise: 'USD',
  valeur: 0,
  label: '',
  est_actif: true,
  ordre: 0,
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

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1>Configuration des billets</h1>
        <p>Gérer les coupures USD/CDF utilisées pour le billetage.</p>
      </header>

      <section className={styles.form}>
        <div>
          <label>Devise</label>
          <select value={form.devise} onChange={(e) => setForm((p) => ({ ...p, devise: e.target.value }))}>
            <option value="USD">USD</option>
            <option value="CDF">CDF</option>
          </select>
        </div>
        <div>
          <label>Valeur</label>
          <input
            type="number"
            value={form.valeur}
            onChange={(e) => setForm((p) => ({ ...p, valeur: e.target.valueAsNumber || 0 }))}
          />
        </div>
        <div>
          <label>Libellé</label>
          <input value={form.label} onChange={(e) => setForm((p) => ({ ...p, label: e.target.value }))} />
        </div>
        <div>
          <label>Ordre</label>
          <input
            type="number"
            value={form.ordre}
            onChange={(e) => setForm((p) => ({ ...p, ordre: e.target.valueAsNumber || 0 }))}
          />
        </div>
        <div className={styles.formActions}>
          <button type="button" onClick={handleCreate}>
            Ajouter
          </button>
        </div>
      </section>

      <section className={styles.tableWrap}>
        <table>
          <thead>
            <tr>
              <th>Devise</th>
              <th>Valeur</th>
              <th>Libellé</th>
              <th>Ordre</th>
              <th>Actif</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6} className={styles.emptyCell}>
                  Aucune dénomination.
                </td>
              </tr>
            )}
            {items.map((d) => (
              <tr key={d.id}>
                <td>{d.devise}</td>
                <td>
                  <input
                    type="number"
                    defaultValue={d.valeur}
                    onBlur={(e) => handleUpdateField(d, 'valeur', Number(e.target.value))}
                  />
                </td>
                <td>
                  <input
                    defaultValue={d.label}
                    onBlur={(e) => handleUpdateField(d, 'label', e.target.value)}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    defaultValue={d.ordre}
                    onBlur={(e) => handleUpdateField(d, 'ordre', Number(e.target.value))}
                  />
                </td>
                <td>
                  <button type="button" className={styles.toggle} onClick={() => handleToggle(d)}>
                    {d.est_actif ? 'Actif' : 'Inactif'}
                  </button>
                </td>
                <td>
                  <button type="button" className={styles.delete} onClick={() => handleDelete(d)}>
                    Supprimer
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
