import React, { useCallback, useEffect, useState } from 'react'
import {
  AIProviderConfig,
  AIProviderCreate,
  AIProviderUpdate,
  ProviderType,
  createAIProvider,
  deleteAIProvider,
  generateEncryptionKey,
  listAIProviders,
  testAIProvider,
  updateAIProvider,
} from '../api/aiProviders'
import BackButton from '../components/BackButton'
import styles from './AIProvidersPage.module.css'

const PROVIDER_LABELS: Record<ProviderType, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic Claude',
  gemini: 'Google Gemini',
  ollama: 'Ollama (local)',
}

const PROVIDER_COLORS: Record<ProviderType, string> = {
  openai: '#10a37f',
  anthropic: '#c96442',
  gemini: '#4285f4',
  ollama: '#6366f1',
}

const DEFAULT_MODELS: Record<ProviderType, string> = {
  openai: 'gpt-4o-mini',
  anthropic: 'claude-haiku-4-5-20251001',
  gemini: 'gemini-1.5-flash',
  ollama: 'gemma2:2b',
}

const PRIORITY_ORDER = [1, 2, 3, 5, 10, 20, 50, 100]

type FormMode = 'create' | 'edit'

interface FormState {
  mode: FormMode
  open: boolean
  editId?: number
  name: string
  provider_type: ProviderType
  api_key: string
  base_url: string
  default_model: string
  is_active: boolean
  is_default: boolean
  fallback_priority: number
}

const EMPTY_FORM: FormState = {
  mode: 'create',
  open: false,
  name: '',
  provider_type: 'openai',
  api_key: '',
  base_url: '',
  default_model: 'gpt-4o-mini',
  is_active: true,
  is_default: false,
  fallback_priority: 10,
}

export { AIProvidersPage as AIProvidersPanel }

export default function AIProvidersPage() {
  const [providers, setProviders] = useState<AIProviderConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [testing, setTesting] = useState(false)
  const [encKey, setEncKey] = useState<{ key: string; warning: string } | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null)
  const [ollamaActivating, setOllamaActivating] = useState(false)
  // Ollama inline edit state
  const [ollamaUrl, setOllamaUrl] = useState('http://localhost:11434')
  const [ollamaModel, setOllamaModel] = useState('gemma2:2b')

  const load = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await listAIProviders()
      setProviders(data)
      const existing = data.find(p => p.provider_type === 'ollama')
      if (existing) {
        setOllamaUrl(existing.base_url ?? 'http://localhost:11434')
        setOllamaModel(existing.default_model ?? 'gemma2:2b')
      }
    } catch (e: any) {
      setError(e?.message ?? 'Erreur de chargement')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const ollamaProvider = providers.find(p => p.provider_type === 'ollama')
  const cloudProviders = providers.filter(p => p.provider_type !== 'ollama')

  // ── Ollama : activation directe ─────────────────────────────────────────────

  async function handleActivateOllama() {
    setOllamaActivating(true)
    try {
      await createAIProvider({
        name: 'Ollama Local',
        provider_type: 'ollama',
        base_url: ollamaUrl || 'http://localhost:11434',
        default_model: ollamaModel || 'gemma2:2b',
        is_active: true,
        is_default: false,
        fallback_priority: 50,
      } as AIProviderCreate)
      await load()
    } catch (e: any) {
      setError(e?.message ?? 'Erreur')
    } finally {
      setOllamaActivating(false)
    }
  }

  async function handleSaveOllama() {
    if (!ollamaProvider) return
    try {
      await updateAIProvider(ollamaProvider.id, {
        base_url: ollamaUrl || 'http://localhost:11434',
        default_model: ollamaModel || 'gemma2:2b',
      })
      await load()
    } catch (e: any) {
      setError(e?.message ?? 'Erreur')
    }
  }

  async function toggleOllamaActive() {
    if (!ollamaProvider) return
    try {
      await updateAIProvider(ollamaProvider.id, { is_active: !ollamaProvider.is_active })
      await load()
    } catch (e: any) {
      setError(e?.message ?? 'Erreur')
    }
  }

  async function setOllamaDefault() {
    if (!ollamaProvider) return
    try {
      await updateAIProvider(ollamaProvider.id, { is_default: true })
      await load()
    } catch (e: any) {
      setError(e?.message ?? 'Erreur')
    }
  }

  // ── Cloud providers ─────────────────────────────────────────────────────────

  function openCreate() {
    setForm({ ...EMPTY_FORM, open: true, mode: 'create' })
    setTestResult(null)
  }

  function openEdit(p: AIProviderConfig) {
    setForm({
      mode: 'edit',
      open: true,
      editId: p.id,
      name: p.name,
      provider_type: p.provider_type,
      api_key: '',
      base_url: p.base_url ?? '',
      default_model: p.default_model,
      is_active: p.is_active,
      is_default: p.is_default,
      fallback_priority: p.fallback_priority,
    })
    setTestResult(null)
  }

  function closeForm() {
    setForm(EMPTY_FORM)
    setTestResult(null)
  }

  function setField<K extends keyof FormState>(key: K, val: FormState[K]) {
    setForm(f => {
      const next = { ...f, [key]: val }
      if (key === 'provider_type') {
        next.default_model = DEFAULT_MODELS[val as ProviderType]
        next.base_url = ''
      }
      return next
    })
  }

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await testAIProvider({
        provider_type: form.provider_type,
        api_key: form.api_key || null,
        base_url: form.base_url || null,
        model: form.default_model || null,
      })
      setTestResult({ ok: res.ok, message: res.message })
    } catch (e: any) {
      setTestResult({ ok: false, message: e?.message ?? 'Erreur' })
    } finally {
      setTesting(false)
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      const payload: AIProviderCreate & AIProviderUpdate = {
        name: form.name,
        provider_type: form.provider_type,
        api_key: form.api_key || undefined,
        base_url: form.base_url || null,
        default_model: form.default_model,
        is_active: form.is_active,
        is_default: form.is_default,
        fallback_priority: form.fallback_priority,
      }
      if (form.mode === 'create') {
        await createAIProvider(payload)
      } else {
        await updateAIProvider(form.editId!, payload)
      }
      closeForm()
      await load()
    } catch (e: any) {
      setError(e?.message ?? 'Erreur lors de la sauvegarde')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteAIProvider(id)
      setDeleteConfirm(null)
      await load()
    } catch (e: any) {
      setError(e?.message ?? 'Erreur lors de la suppression')
    }
  }

  async function toggleActive(p: AIProviderConfig) {
    try {
      await updateAIProvider(p.id, { is_active: !p.is_active })
      await load()
    } catch (e: any) {
      setError(e?.message ?? 'Erreur')
    }
  }

  async function setDefault(p: AIProviderConfig) {
    try {
      await updateAIProvider(p.id, { is_default: true })
      await load()
    } catch (e: any) {
      setError(e?.message ?? 'Erreur')
    }
  }

  async function handleGenerateKey() {
    try {
      const res = await generateEncryptionKey()
      setEncKey(res)
    } catch (e: any) {
      setError(e?.message ?? 'Erreur')
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <BackButton fallback="/super-admin" />
          <h1 className={styles.title}>Fournisseurs IA</h1>
          <p className={styles.subtitle}>
            Configurez les providers IA disponibles pour la plateforme. Les clés API sont chiffrées avant stockage.
          </p>
        </div>
        <div className={styles.headerActions}>
          <button className={styles.btnSecondary} onClick={handleGenerateKey}>
            Générer clé de chiffrement
          </button>
          <button className={styles.btnPrimary} onClick={openCreate}>
            + Ajouter un provider
          </button>
        </div>
      </div>

      {error && (
        <div className={styles.errorBanner}>
          {error}
          <button onClick={() => setError(null)}>✕</button>
        </div>
      )}

      {encKey && (
        <div className={styles.encKeyBox}>
          <strong>Nouvelle clé de chiffrement générée</strong>
          <code className={styles.encKeyValue}>{encKey.key}</code>
          <p className={styles.encKeyWarn}>{encKey.warning}</p>
          <button className={styles.btnSmall} onClick={() => setEncKey(null)}>Fermer</button>
        </div>
      )}

      {loading ? (
        <div className={styles.loading}>Chargement...</div>
      ) : (
        <>
          {/* ── Bloc Ollama local ── */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>Provider local</h2>
            <div className={styles.ollamaCard}>
              <div className={styles.ollamaLeft}>
                <div className={styles.ollamaDot} style={{ background: ollamaProvider?.is_active ? '#6366f1' : '#d1d5db' }} />
                <div>
                  <div className={styles.ollamaName}>
                    Ollama
                    {ollamaProvider?.is_default && <span className={styles.badgeDefault}>Défaut</span>}
                    {ollamaProvider && !ollamaProvider.is_active && <span className={styles.badgeInactive}>Inactif</span>}
                  </div>
                  <div className={styles.ollamaDesc}>
                    Modèle IA tournant en local — aucune clé API requise.
                  </div>
                </div>
              </div>

              <div className={styles.ollamaFields}>
                <label className={styles.ollamaFieldLabel}>
                  URL
                  <input
                    className={styles.ollamaInput}
                    value={ollamaUrl}
                    onChange={e => setOllamaUrl(e.target.value)}
                    placeholder="http://localhost:11434"
                  />
                </label>
                <label className={styles.ollamaFieldLabel}>
                  Modèle
                  <input
                    className={styles.ollamaInput}
                    value={ollamaModel}
                    onChange={e => setOllamaModel(e.target.value)}
                    placeholder="gemma2:2b"
                  />
                </label>
              </div>

              <div className={styles.ollamaActions}>
                {!ollamaProvider ? (
                  <button
                    className={styles.btnPrimary}
                    onClick={handleActivateOllama}
                    disabled={ollamaActivating}
                  >
                    {ollamaActivating ? 'Activation...' : 'Activer Ollama'}
                  </button>
                ) : (
                  <>
                    <button className={styles.btnSecondary} onClick={handleSaveOllama}>
                      Enregistrer
                    </button>
                    {!ollamaProvider.is_default && ollamaProvider.is_active && (
                      <button className={styles.btnMini} onClick={setOllamaDefault}>
                        Définir par défaut
                      </button>
                    )}
                    <button
                      className={`${styles.btnMini} ${ollamaProvider.is_active ? styles.btnMiniDanger : styles.btnMiniSuccess}`}
                      onClick={toggleOllamaActive}
                    >
                      {ollamaProvider.is_active ? 'Désactiver' : 'Activer'}
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>

          {/* ── Cloud providers ── */}
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>Providers cloud</h2>
            {cloudProviders.length === 0 ? (
              <div className={styles.empty}>
                <p>Aucun provider cloud configuré.</p>
                <p>Cliquez sur "Ajouter un provider" pour configurer OpenAI, Anthropic ou Gemini.</p>
              </div>
            ) : (
              <div className={styles.grid}>
                {cloudProviders.map(p => (
                  <ProviderCard
                    key={p.id}
                    provider={p}
                    onEdit={() => openEdit(p)}
                    onDelete={() => setDeleteConfirm(p.id)}
                    onToggleActive={() => toggleActive(p)}
                    onSetDefault={() => setDefault(p)}
                    confirmingDelete={deleteConfirm === p.id}
                    onCancelDelete={() => setDeleteConfirm(null)}
                    onConfirmDelete={() => handleDelete(p.id)}
                  />
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* ── Modal cloud provider ── */}
      {form.open && (
        <div className={styles.modalOverlay} onClick={closeForm}>
          <div className={styles.modal} onClick={e => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2>{form.mode === 'create' ? 'Nouveau fournisseur IA' : 'Modifier le fournisseur'}</h2>
              <button className={styles.closeBtn} onClick={closeForm}>✕</button>
            </div>

            <form onSubmit={handleSave} className={styles.modalForm}>
              <label className={styles.label}>
                Nom du provider
                <input
                  className={styles.input}
                  value={form.name}
                  onChange={e => setField('name', e.target.value)}
                  placeholder="Ex: OpenAI Production"
                  required
                />
              </label>

              <label className={styles.label}>
                Type de fournisseur
                <select
                  className={styles.input}
                  value={form.provider_type}
                  onChange={e => setField('provider_type', e.target.value as ProviderType)}
                >
                  {(['openai', 'anthropic', 'gemini'] as ProviderType[]).map(t => (
                    <option key={t} value={t}>{PROVIDER_LABELS[t]}</option>
                  ))}
                </select>
              </label>

              <label className={styles.label}>
                Clé API {form.mode === 'edit' ? "(laisser vide pour conserver l'actuelle)" : ''}
                <input
                  className={styles.input}
                  type="password"
                  value={form.api_key}
                  onChange={e => setField('api_key', e.target.value)}
                  placeholder={form.mode === 'edit' ? '••••••••••••••••' : 'Clé API'}
                  autoComplete="new-password"
                />
              </label>

              <label className={styles.label}>
                Modèle par défaut
                <input
                  className={styles.input}
                  value={form.default_model}
                  onChange={e => setField('default_model', e.target.value)}
                  placeholder={DEFAULT_MODELS[form.provider_type]}
                />
              </label>

              {form.provider_type === 'openai' && (
                <label className={styles.label}>
                  URL de base (optionnel)
                  <input
                    className={styles.input}
                    value={form.base_url}
                    onChange={e => setField('base_url', e.target.value)}
                    placeholder="https://api.openai.com/v1"
                  />
                </label>
              )}

              <div className={styles.row}>
                <label className={styles.label}>
                  Priorité de fallback
                  <select
                    className={styles.input}
                    value={form.fallback_priority}
                    onChange={e => setField('fallback_priority', Number(e.target.value))}
                  >
                    {PRIORITY_ORDER.map(n => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                </label>

                <div className={styles.checkboxGroup}>
                  <label className={styles.checkLabel}>
                    <input
                      type="checkbox"
                      checked={form.is_active}
                      onChange={e => setField('is_active', e.target.checked)}
                    />
                    Actif
                  </label>
                  <label className={styles.checkLabel}>
                    <input
                      type="checkbox"
                      checked={form.is_default}
                      onChange={e => setField('is_default', e.target.checked)}
                    />
                    Provider par défaut
                  </label>
                </div>
              </div>

              {testResult && (
                <div className={testResult.ok ? styles.testOk : styles.testFail}>
                  {testResult.ok ? '✓' : '✗'} {testResult.message}
                </div>
              )}

              <div className={styles.modalActions}>
                <button
                  type="button"
                  className={styles.btnSecondary}
                  onClick={handleTest}
                  disabled={testing}
                >
                  {testing ? 'Test en cours...' : 'Tester la connexion'}
                </button>
                <div className={styles.modalActionsRight}>
                  <button type="button" className={styles.btnGhost} onClick={closeForm}>
                    Annuler
                  </button>
                  <button type="submit" className={styles.btnPrimary} disabled={saving}>
                    {saving ? 'Sauvegarde...' : form.mode === 'create' ? 'Créer' : 'Enregistrer'}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

// ── ProviderCard (cloud) ──────────────────────────────────────────────────────

interface CardProps {
  provider: AIProviderConfig
  onEdit: () => void
  onDelete: () => void
  onToggleActive: () => void
  onSetDefault: () => void
  confirmingDelete: boolean
  onCancelDelete: () => void
  onConfirmDelete: () => void
}

function ProviderCard({
  provider: p,
  onEdit,
  onDelete,
  onToggleActive,
  onSetDefault,
  confirmingDelete,
  onCancelDelete,
  onConfirmDelete,
}: CardProps) {
  const color = PROVIDER_COLORS[p.provider_type] ?? '#888'

  return (
    <div
      className={`${styles.card} ${!p.is_active ? styles.cardInactive : ''}`}
      style={{ borderTop: `3px solid ${color}` }}
    >
      <div className={styles.cardHead}>
        <div className={styles.cardTitle}>
          <span className={styles.providerDot} style={{ background: color }} />
          <strong>{p.name}</strong>
          {p.is_default && <span className={styles.badgeDefault}>Défaut</span>}
          {!p.is_active && <span className={styles.badgeInactive}>Inactif</span>}
        </div>
        <div className={styles.cardMenu}>
          <button className={styles.iconBtn} title="Modifier" onClick={onEdit}>✏️</button>
          <button className={styles.iconBtn} title="Supprimer" onClick={onDelete}>🗑️</button>
        </div>
      </div>

      <div className={styles.cardMeta}>
        <span className={styles.chip}>{PROVIDER_LABELS[p.provider_type]}</span>
        <span className={styles.chip}>{p.default_model}</span>
        <span className={styles.chip}>Priorité {p.fallback_priority}</span>
      </div>

      {p.base_url && (
        <div className={styles.cardUrl}>{p.base_url}</div>
      )}

      <div className={styles.cardFooter}>
        <span className={p.has_api_key ? styles.keyOk : styles.keyMissing}>
          {p.has_api_key ? '🔑 Clé configurée' : '⚠️ Aucune clé API'}
        </span>
        <div className={styles.cardActions}>
          {!p.is_default && p.is_active && (
            <button className={styles.btnMini} onClick={onSetDefault}>
              Définir par défaut
            </button>
          )}
          <button
            className={`${styles.btnMini} ${p.is_active ? styles.btnMiniDanger : styles.btnMiniSuccess}`}
            onClick={onToggleActive}
          >
            {p.is_active ? 'Désactiver' : 'Activer'}
          </button>
        </div>
      </div>

      {confirmingDelete && (
        <div className={styles.deleteConfirm}>
          <span>Supprimer ce provider ?</span>
          <button className={styles.btnMiniDanger} onClick={onConfirmDelete}>Oui, supprimer</button>
          <button className={styles.btnMini} onClick={onCancelDelete}>Annuler</button>
        </div>
      )}
    </div>
  )
}
