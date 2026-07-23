import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Ban, CheckCircle2, Pencil, Trash2, Users } from 'lucide-react'
import {
  Client,
  ClientUpdatePayload,
  deleteClient,
  listClients,
  updateClient,
} from '../api/clients'
import { TypeClient } from '../types'
import { TYPE_CLIENT_LABELS } from '../utils/encaissementHelpers'
import styles from './Clients.module.css'

type StatutFilter = 'actifs' | 'bloques' | 'tous'

// Libellés partagés avec le formulaire d'encaissement (source unique).
const TYPE_LABELS: Record<string, string> = TYPE_CLIENT_LABELS

// Types proposés à l'édition d'un client. « Personne physique / morale » en
// tête (nature juridique), expert-comptable exclu (écran dédié).
const TYPE_OPTIONS: TypeClient[] = [
  'personne_physique',
  'personne_morale',
  'client_externe',
  'banque_institution',
  'partenaire',
  'organisation',
  'autre',
]

function errMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return 'Une erreur est survenue.'
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export default function Clients() {
  const navigate = useNavigate()
  const [clients, setClients] = useState<Client[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [statut, setStatut] = useState<StatutFilter>('actifs')

  const [editing, setEditing] = useState<Client | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const activeParam = useMemo(() => {
    if (statut === 'actifs') return true
    if (statut === 'bloques') return false
    return undefined
  }, [statut])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const rows = await listClients({ search: debouncedSearch, active: activeParam, limit: 200 })
      setClients(rows)
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setLoading(false)
    }
  }, [debouncedSearch, activeParam])

  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedSearch(search), 300)
    return () => window.clearTimeout(id)
  }, [search])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!success) return
    const id = window.setTimeout(() => setSuccess(null), 3500)
    return () => window.clearTimeout(id)
  }, [success])

  const handleToggleActive = async (client: Client) => {
    setBusyId(client.id)
    setError(null)
    try {
      await updateClient(client.id, { active: !client.active })
      setSuccess(client.active ? `« ${client.nom} » bloqué.` : `« ${client.nom} » débloqué.`)
      await load()
    } catch (e) {
      setError(errMessage(e))
    } finally {
      setBusyId(null)
    }
  }

  const handleDelete = async (client: Client) => {
    if (!window.confirm(`Supprimer définitivement le client « ${client.nom} » ?`)) return
    setBusyId(client.id)
    setError(null)
    try {
      await deleteClient(client.id)
      setSuccess(`« ${client.nom} » supprimé.`)
      await load()
    } catch (e) {
      // Le backend renvoie un 409 explicite si le client a des encaissements.
      setError(errMessage(e))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <button type="button" className={styles.backBtn} onClick={() => navigate(-1)}>
            <ArrowLeft size={15} style={{ verticalAlign: '-3px', marginRight: 4 }} />
            Retour
          </button>
          <h1 className={styles.title}>
            <Users size={22} style={{ verticalAlign: '-4px', marginRight: 8 }} />
            Clients
          </h1>
          <p className={styles.subtitle}>
            Référentiel des clients externes, institutions et partenaires. Modifiez, bloquez ou
            supprimez leurs fiches. Les experts-comptables se gèrent dans leur propre écran.
          </p>
        </div>
      </div>

      <div className={styles.toolbar}>
        <input
          className={styles.search}
          type="search"
          placeholder="Rechercher par nom, email ou téléphone…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <div className={styles.filterGroup} role="tablist" aria-label="Filtrer par statut">
          {(['actifs', 'bloques', 'tous'] as StatutFilter[]).map(key => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={statut === key}
              className={`${styles.filterBtn} ${statut === key ? styles.filterBtnActive : ''}`}
              onClick={() => setStatut(key)}
            >
              {key === 'actifs' ? 'Actifs' : key === 'bloques' ? 'Bloqués' : 'Tous'}
            </button>
          ))}
        </div>
      </div>

      {error && <div className={`${styles.banner} ${styles.bannerError}`}>{error}</div>}
      {success && <div className={`${styles.banner} ${styles.bannerSuccess}`}>{success}</div>}

      <div className={styles.card}>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Nom</th>
                <th>Type</th>
                <th>Contact</th>
                <th>Encaissements</th>
                <th>Statut</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={6} className={styles.loading}>Chargement…</td>
                </tr>
              ) : clients.length === 0 ? (
                <tr>
                  <td colSpan={6} className={styles.empty}>Aucun client trouvé.</td>
                </tr>
              ) : (
                clients.map(client => (
                  <tr key={client.id}>
                    <td>
                      <div className={styles.clientName}>{client.nom}</div>
                      {client.adresse && <div className={styles.muted}>{client.adresse}</div>}
                    </td>
                    <td>
                      {client.type_client ? (
                        <span className={styles.typeBadge}>
                          {TYPE_LABELS[client.type_client] ?? client.type_client}
                        </span>
                      ) : (
                        <span className={styles.muted}>—</span>
                      )}
                    </td>
                    <td>
                      {client.email || client.telephone ? (
                        <>
                          {client.email && <div>{client.email}</div>}
                          {client.telephone && <div className={styles.muted}>{client.telephone}</div>}
                        </>
                      ) : (
                        <span className={styles.muted}>—</span>
                      )}
                    </td>
                    <td>
                      {client.nb_encaissements ? (
                        <>
                          <div>{client.nb_encaissements}</div>
                          <div className={styles.muted}>
                            Dernier : {formatDate(client.dernier_encaissement)}
                          </div>
                        </>
                      ) : (
                        <span className={styles.muted}>0</span>
                      )}
                    </td>
                    <td>
                      <span
                        className={`${styles.statusBadge} ${client.active ? styles.statusActive : styles.statusBlocked}`}
                      >
                        {client.active ? 'Actif' : 'Bloqué'}
                      </span>
                    </td>
                    <td>
                      <div className={styles.actions}>
                        <button
                          type="button"
                          className={styles.actionBtn}
                          onClick={() => setEditing(client)}
                          disabled={busyId === client.id}
                        >
                          <Pencil size={13} style={{ verticalAlign: '-2px', marginRight: 4 }} />
                          Modifier
                        </button>
                        <button
                          type="button"
                          className={styles.actionBtn}
                          onClick={() => handleToggleActive(client)}
                          disabled={busyId === client.id}
                        >
                          {client.active ? (
                            <>
                              <Ban size={13} style={{ verticalAlign: '-2px', marginRight: 4 }} />
                              Bloquer
                            </>
                          ) : (
                            <>
                              <CheckCircle2 size={13} style={{ verticalAlign: '-2px', marginRight: 4 }} />
                              Débloquer
                            </>
                          )}
                        </button>
                        <button
                          type="button"
                          className={`${styles.actionBtn} ${styles.actionDanger}`}
                          onClick={() => handleDelete(client)}
                          disabled={busyId === client.id}
                        >
                          <Trash2 size={13} style={{ verticalAlign: '-2px', marginRight: 4 }} />
                          Supprimer
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {editing && (
        <EditClientModal
          client={editing}
          onClose={() => setEditing(null)}
          onSaved={(msg) => {
            setEditing(null)
            setSuccess(msg)
            load()
          }}
          onError={setError}
        />
      )}
    </div>
  )
}

interface EditModalProps {
  client: Client
  onClose: () => void
  onSaved: (message: string) => void
  onError: (message: string) => void
}

function EditClientModal({ client, onClose, onSaved, onError }: EditModalProps) {
  const [nom, setNom] = useState(client.nom)
  const [typeClient, setTypeClient] = useState<TypeClient | ''>(client.type_client ?? '')
  const [email, setEmail] = useState(client.email ?? '')
  const [telephone, setTelephone] = useState(client.telephone ?? '')
  const [adresse, setAdresse] = useState(client.adresse ?? '')
  const [notes, setNotes] = useState(client.notes ?? '')
  const [saving, setSaving] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (nom.trim().length < 2) {
      onError('Le nom du client est trop court.')
      return
    }
    setSaving(true)
    try {
      const payload: ClientUpdatePayload = {
        nom: nom.trim(),
        type_client: (typeClient || null) as TypeClient | null,
        email: email.trim() || null,
        telephone: telephone.trim() || null,
        adresse: adresse.trim() || null,
        notes: notes.trim() || null,
      }
      await updateClient(client.id, payload)
      onSaved(`Fiche de « ${nom.trim()} » mise à jour.`)
    } catch (err) {
      onError(err instanceof Error && err.message ? err.message : 'Échec de la mise à jour.')
      setSaving(false)
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <form className={styles.modal} onClick={e => e.stopPropagation()} onSubmit={handleSubmit}>
        <div className={styles.modalHeader}>
          <h2 className={styles.modalTitle}>Modifier le client</h2>
        </div>
        <div className={styles.modalBody}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="client-nom">Nom *</label>
            <input
              id="client-nom"
              className={styles.input}
              value={nom}
              onChange={e => setNom(e.target.value)}
              required
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="client-type">Type</label>
            <select
              id="client-type"
              className={styles.select}
              value={typeClient}
              onChange={e => setTypeClient(e.target.value as TypeClient | '')}
            >
              <option value="">— Non précisé —</option>
              {TYPE_OPTIONS.map(t => (
                <option key={t} value={t}>{TYPE_LABELS[t]}</option>
              ))}
            </select>
          </div>
          <div className={styles.fieldRow}>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="client-email">Email</label>
              <input
                id="client-email"
                type="email"
                className={styles.input}
                value={email}
                onChange={e => setEmail(e.target.value)}
              />
            </div>
            <div className={styles.field}>
              <label className={styles.label} htmlFor="client-tel">Téléphone</label>
              <input
                id="client-tel"
                className={styles.input}
                value={telephone}
                onChange={e => setTelephone(e.target.value)}
              />
            </div>
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="client-adresse">Adresse</label>
            <input
              id="client-adresse"
              className={styles.input}
              value={adresse}
              onChange={e => setAdresse(e.target.value)}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="client-notes">Notes</label>
            <textarea
              id="client-notes"
              className={styles.textarea}
              value={notes}
              onChange={e => setNotes(e.target.value)}
            />
          </div>
        </div>
        <div className={styles.modalFooter}>
          <button type="button" className={styles.btnGhost} onClick={onClose} disabled={saving}>
            Annuler
          </button>
          <button type="submit" className={styles.btnPrimary} disabled={saving}>
            {saving ? 'Enregistrement…' : 'Enregistrer'}
          </button>
        </div>
      </form>
    </div>
  )
}
