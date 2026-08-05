import { useEffect, useState } from 'react'
import { Pencil, Plus, Power } from 'lucide-react'
import { createProjetActivite, listProjetsActivites, ProjetActivite, ProjetActiviteType, updateProjetActivite } from '../../api/projetsActivites'
import { useNotification } from '../../contexts/NotificationContext'
import styles from './ProjectActivitySettings.module.css'

const emptyForm = { code: '', libelle: '', type: 'PROJET' as ProjetActiviteType, description: '', is_active: true }

export default function ProjectActivitySettings() {
  const { showSuccess, showError } = useNotification()
  const [items, setItems] = useState<ProjetActivite[]>([])
  const [form, setForm] = useState(emptyForm)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const load = async () => {
    try {
      setLoading(true)
      setItems(await listProjetsActivites())
    } catch (error: any) {
      showError('Projets et activités', error?.message || 'Impossible de charger le référentiel.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const reset = () => {
    setForm(emptyForm)
    setEditingId(null)
    setShowForm(false)
  }

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    try {
      setSaving(true)
      const payload = { ...form, code: form.code.trim(), libelle: form.libelle.trim(), description: form.description.trim() || null }
      if (editingId) await updateProjetActivite(editingId, payload)
      else await createProjetActivite(payload)
      showSuccess('Projets et activités', editingId ? 'Élément mis à jour.' : 'Élément ajouté.')
      reset()
      await load()
    } catch (error: any) {
      showError('Projets et activités', error?.message || 'Impossible de sauvegarder cet élément.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <div>
          <h2>Projets et activités</h2>
          <p>Référentiel facultatif pour préciser l’affectation analytique des encaissements.</p>
        </div>
        <button type="button" className={styles.primaryButton} onClick={() => { reset(); setShowForm(true) }}>
          <Plus size={16} /> Ajouter
        </button>
      </div>
      {showForm && (
        <form className={styles.form} onSubmit={submit}>
          <input placeholder="Code" value={form.code} onChange={e => setForm({ ...form, code: e.target.value })} required />
          <input placeholder="Libellé" value={form.libelle} onChange={e => setForm({ ...form, libelle: e.target.value })} required />
          <select value={form.type} onChange={e => setForm({ ...form, type: e.target.value as ProjetActiviteType })}>
            <option value="PROJET">Projet</option>
            <option value="ACTIVITE">Activité</option>
          </select>
          <input placeholder="Description (facultatif)" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
          <label className={styles.checkbox}><input type="checkbox" checked={form.is_active} onChange={e => setForm({ ...form, is_active: e.target.checked })} /> Actif</label>
          <button type="submit" className={styles.primaryButton} disabled={saving}>{saving ? 'Enregistrement...' : editingId ? 'Mettre à jour' : 'Enregistrer'}</button>
          <button type="button" className={styles.secondaryButton} onClick={reset}>Annuler</button>
        </form>
      )}
      {loading ? <div className={styles.empty}>Chargement...</div> : items.length === 0 ? <div className={styles.empty}>Aucun projet ou activité configuré.</div> : (
        <table className={styles.table}>
          <thead><tr><th>Code</th><th>Libellé</th><th>Type</th><th>Statut</th><th /></tr></thead>
          <tbody>{items.map(item => (
            <tr key={item.id}>
              <td>{item.code}</td><td>{item.libelle}</td><td>{item.type === 'PROJET' ? 'Projet' : 'Activité'}</td><td>{item.is_active ? 'Actif' : 'Inactif'}</td>
              <td className={styles.actions}>
                <button type="button" title="Modifier" onClick={() => { setEditingId(item.id); setForm({ code: item.code, libelle: item.libelle, type: item.type, description: item.description || '', is_active: item.is_active }); setShowForm(true) }}><Pencil size={15} /></button>
                <button type="button" title={item.is_active ? 'Désactiver' : 'Activer'} onClick={async () => { try { await updateProjetActivite(item.id, { is_active: !item.is_active }); await load() } catch (error: any) { showError('Projets et activités', error?.message || 'Impossible de modifier le statut.') } }}><Power size={15} /></button>
              </td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  )
}
