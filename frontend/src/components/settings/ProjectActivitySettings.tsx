import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { BarChart3, FolderKanban, Pencil, Plus, Power, Search, X } from 'lucide-react'
import {
  createProjetActivite,
  listProjetsActivites,
  ProjetActivite,
  ProjetActiviteType,
  updateProjetActivite,
} from '../../api/projetsActivites'
import { useNotification } from '../../contexts/NotificationContext'
import { usePermissions } from '../../hooks/usePermissions'
import styles from './ProjectActivitySettings.module.css'

const emptyForm = { code: '', libelle: '', type: 'PROJET' as ProjetActiviteType, description: '', is_active: true }

/**
 * Paramètres › Référentiels : créer, modifier, activer les projets et
 * activités. Le suivi de leurs entrées et sorties est dans Rapports ›
 * Projets & activités (RapportProjets).
 */
export default function ProjectActivitySettings() {
  const { showSuccess, showError } = useNotification()
  const { hasPermission } = usePermissions()
  const peutVoirRapport = hasPermission('rapports')
  const [items, setItems] = useState<ProjetActivite[]>([])
  const [form, setForm] = useState(emptyForm)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [recherche, setRecherche] = useState('')

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

  const visibles = useMemo(() => {
    const aiguille = recherche.trim().toLowerCase()
    if (!aiguille) return items
    return items.filter((i) => `${i.code} ${i.libelle} ${i.description || ''}`.toLowerCase().includes(aiguille))
  }, [items, recherche])

  const actifs = items.filter((i) => i.is_active).length

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <div className={styles.headerText}>
          <h2>Projets et activités</h2>
          <p>Le référentiel proposé sur les encaissements, les réquisitions et les sorties directes, où le rattachement reste facultatif. Ce que chaque projet a reçu et dépensé se lit dans Rapports › Projets & activités.</p>
        </div>
        <div className={styles.dialogActions}>
          {peutVoirRapport && (
            <Link to="/rapports/projets" className={styles.secondaryButton}>
              <BarChart3 size={16} /> Voir le suivi
            </Link>
          )}
          <button type="button" className={styles.primaryButton} onClick={() => { reset(); setShowForm(true) }}>
            <Plus size={16} /> Ajouter
          </button>
        </div>
      </div>

      <div className={styles.toolbar}>
        <div className={styles.searchField}>
          <Search size={15} aria-hidden="true" />
          <input
            type="search"
            placeholder="Rechercher un projet…"
            aria-label="Rechercher un projet ou une activité"
            value={recherche}
            onChange={(e) => setRecherche(e.target.value)}
          />
        </div>
        <span className={styles.muted}>{actifs} actif{actifs > 1 ? 's' : ''} sur {items.length}</span>
      </div>

      {loading ? <div className={styles.empty}>Chargement...</div> : items.length === 0 ? (
        <div className={styles.emptyState}>
          <FolderKanban size={28} aria-hidden="true" />
          <strong>Aucun projet ou activité configuré.</strong>
          <span>Créez-en un pour suivre ses entrées et ses sorties.</span>
        </div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Libellé</th>
                <th>Type</th>
                <th>Statut</th>
                <th />
              </tr>
            </thead>
            <tbody>{visibles.map((item) => (
              <tr key={item.id} className={item.is_active ? '' : styles.rowInactive}>
                <td data-label="Libellé">
                  <span className={styles.nomProjet}>
                    <span className={styles.code}>{item.code}</span>
                    <span className={styles.libelle}>{item.libelle}</span>
                  </span>
                  {item.description && <span className={styles.description}>{item.description}</span>}
                </td>
                <td data-label="Type">
                  <span className={`${styles.badge} ${item.type === 'PROJET' ? styles.badgeProjet : styles.badgeActivite}`}>
                    {item.type === 'PROJET' ? 'Projet' : 'Activité'}
                  </span>
                </td>
                <td data-label="Statut">
                  <span className={`${styles.statut} ${item.is_active ? styles.statutActif : ''}`}>{item.is_active ? 'Actif' : 'Inactif'}</span>
                </td>
                <td className={styles.actionsCell}>
                  <div className={styles.actions}>
                  {peutVoirRapport && (
                    <Link to={`/rapports/projets?projet=${item.id}`} title="Suivi : entrées et sorties" aria-label={`Suivi de ${item.libelle}`}><BarChart3 size={15} /></Link>
                  )}
                  <button type="button" title="Modifier" aria-label={`Modifier ${item.libelle}`} onClick={() => { setEditingId(item.id); setForm({ code: item.code, libelle: item.libelle, type: item.type, description: item.description || '', is_active: item.is_active }); setShowForm(true) }}><Pencil size={15} /></button>
                  <button type="button" title={item.is_active ? 'Désactiver' : 'Activer'} aria-label={item.is_active ? `Désactiver ${item.libelle}` : `Activer ${item.libelle}`} onClick={async () => { try { await updateProjetActivite(item.id, { is_active: !item.is_active }); await load() } catch (error: any) { showError('Projets et activités', error?.message || 'Impossible de modifier le statut.') } }}><Power size={15} /></button>
                  </div>
                </td>
              </tr>
            ))}</tbody>
          </table>
          {visibles.length === 0 && <div className={styles.empty}>Aucun résultat pour « {recherche} ».</div>}
        </div>
      )}

      {showForm && (
        <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby="projet-form-titre" onClick={reset}>
          <form className={styles.dialog} onSubmit={submit} onClick={(e) => e.stopPropagation()}>
            <div className={styles.dialogHeader}>
              <h3 id="projet-form-titre">{editingId ? 'Modifier' : 'Ajouter'} un projet ou une activité</h3>
              <button type="button" className={styles.iconButton} onClick={reset} aria-label="Fermer"><X size={18} /></button>
            </div>
            <div className={styles.formGrid}>
              <label className={styles.field}>
                <span>Code</span>
                <input placeholder="Ex. FORM-2026" value={form.code} onChange={e => setForm({ ...form, code: e.target.value })} required />
              </label>
              <label className={styles.field}>
                <span>Type</span>
                <select value={form.type} onChange={e => setForm({ ...form, type: e.target.value as ProjetActiviteType })}>
                  <option value="PROJET">Projet</option>
                  <option value="ACTIVITE">Activité</option>
                </select>
              </label>
              <label className={`${styles.field} ${styles.fieldWide}`}>
                <span>Libellé</span>
                <input placeholder="Ex. Formation continue 2026" value={form.libelle} onChange={e => setForm({ ...form, libelle: e.target.value })} required />
              </label>
              <label className={`${styles.field} ${styles.fieldWide}`}>
                <span>Description (facultatif)</span>
                <textarea rows={3} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
              </label>
              <label className={styles.checkbox}><input type="checkbox" checked={form.is_active} onChange={e => setForm({ ...form, is_active: e.target.checked })} /> Actif</label>
            </div>
            <div className={styles.dialogFooter}>
              <button type="button" className={styles.secondaryButton} onClick={reset}>Annuler</button>
              <button type="submit" className={styles.primaryButton} disabled={saving}>{saving ? 'Enregistrement...' : editingId ? 'Mettre à jour' : 'Enregistrer'}</button>
            </div>
          </form>
        </div>
      )}

    </div>
  )
}
