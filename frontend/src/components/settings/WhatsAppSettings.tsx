/**
 * Notifications WhatsApp — écran d'administration du canal.
 *
 * Cinq blocs, dans l'ordre où on s'en sert : l'état du service (lisible d'un
 * coup d'œil), la configuration, les destinataires du Bureau, les gabarits de
 * message, puis l'historique récent.
 *
 * Deux règles gouvernent ce fichier :
 *
 *  1. **La clé API n'existe jamais durablement côté navigateur.** Le serveur ne
 *     la renvoie pas ; le champ de saisie part vide et se vide de nouveau dès
 *     l'enregistrement réussi. Laisser le champ vide conserve la clé en place —
 *     c'est écrit à l'écran, parce qu'un champ mot de passe vide a déjà fait
 *     croire à un administrateur qu'il n'avait pas de clé enregistrée.
 *  2. **L'état se lit à la forme autant qu'à la couleur.** Chaque statut porte
 *     une icône qui lui est propre et un libellé écrit en toutes lettres : un
 *     écran qui ne distingue « Envoyé » d'« Échec » que par une pastille verte
 *     ou rouge n'est pas lisible pour tout le monde.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  BadgeCheck,
  CheckCircle2,
  Clock3,
  Eye,
  History,
  Info,
  MessageSquareText,
  MinusCircle,
  Pencil,
  RefreshCw,
  RotateCcw,
  Save,
  Send,
  Settings2,
  Users,
  X,
  XCircle,
  type LucideIcon,
} from 'lucide-react'
import {
  getWhatsAppLogs,
  getWhatsAppRecipients,
  getWhatsAppSettings,
  getWhatsAppTemplates,
  resendWhatsAppLog,
  sendWhatsAppTest,
  updateWhatsAppRecipient,
  updateWhatsAppSettings,
  updateWhatsAppTemplates,
  WHATSAPP_PERMISSIONS,
  type WhatsAppLog,
  type WhatsAppLogPage,
  type WhatsAppLogStatus,
  type WhatsAppRecipient,
  type WhatsAppSettings as WhatsAppSettingsData,
  type WhatsAppSettingsEnvelope,
  type WhatsAppSettingsUpdate,
  type WhatsAppTemplate,
} from '../../api/whatsapp'
import { usePermissions } from '../../hooks/usePermissions'
import styles from './WhatsAppSettings.module.css'

// ── Vocabulaire d'affichage ──────────────────────────────────────────────────

/** Champs de configuration réellement éditables depuis cet écran. */
type ConfigForm = {
  enabled: boolean
  notify_payments: boolean
  notify_sorties: boolean
  provider: string
  api_url: string
  sender: string
  phone_number_id: string
  business_account_id: string
}

/**
 * Nature d'un état. Chaque valeur porte **sa propre icône** : deux états ne
 * partagent jamais une silhouette, même quand ils partagent une couleur —
 * « En attente » et « Numéro manquant » sont tous deux ambrés, l'horloge et le
 * triangle les séparent sans qu'on ait à lire l'étiquette.
 */
type StatusKind = 'ok' | 'fail' | 'pending' | 'warn' | 'off'

const STATUS_ICONS: Record<StatusKind, LucideIcon> = {
  ok: CheckCircle2,
  fail: XCircle,
  pending: Clock3,
  warn: AlertTriangle,
  off: MinusCircle,
}

const LOG_STATUS_ORDER: WhatsAppLogStatus[] = ['SENT', 'FAILED', 'PENDING', 'SKIPPED']

const LOG_STATUS_LABELS: Record<WhatsAppLogStatus, string> = {
  SENT: 'Envoyé',
  FAILED: 'Échec',
  PENDING: 'En attente',
  SKIPPED: 'Ignoré',
}

const LOG_STATUS_KINDS: Record<WhatsAppLogStatus, StatusKind> = {
  SENT: 'ok',
  FAILED: 'fail',
  PENDING: 'pending',
  SKIPPED: 'off',
}

const RECIPIENT_STATUS_KINDS: Record<string, StatusKind> = {
  ready: 'ok',
  no_phone: 'warn',
  opted_out: 'off',
}

/**
 * Valeurs d'exemple de l'aperçu. Elles n'existent que pour montrer la forme du
 * message : aucune n'est envoyée, aucune ne vient de la base.
 */
const SAMPLE_VALUES: Record<string, string> = {
  organisation: 'ONEC — Conseil Provincial de Kinshasa',
  nom: 'Jeanne Kabeya',
  fonction: 'Trésorière',
  reference: 'SF-2026-0184',
  date: '24/08/2026 à 10:32',
  montant: '1 250 000',
  devise: 'CDF',
  motif: 'Achat de fournitures de bureau',
  beneficiaire: 'Établissements Lokole',
  poste_budgetaire: '6.1.2 — Fournitures de bureau',
  canal: 'Banque',
  mode_paiement: 'Virement bancaire',
  auteur: 'Paul Mbuyi',
  validateur: 'Jeanne Kabeya',
  solde_apres: '8 430 000 CDF',
  tranche: 'Tranche 1 sur 3',
  reste_a_payer: '830 000 CDF',
  total: '2 080 000 CDF',
}

/** Miroir de `_PLACEHOLDER` côté serveur : `{{ variable }}`. */
const PLACEHOLDER_RE = /\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g

/** Miroir de `_strip_empty_fields` : « Étiquette : » sans valeur disparaît. */
const EMPTY_FIELD_RE = /^[^:]{1,40}:\s*$/

const TEMPLATE_MAX_LENGTH = 4000

const EMPTY_FORM: ConfigForm = {
  enabled: false,
  notify_payments: false,
  notify_sorties: false,
  provider: '',
  api_url: '',
  sender: '',
  phone_number_id: '',
  business_account_id: '',
}

// ── Utilitaires purs ─────────────────────────────────────────────────────────

function toForm(settings: WhatsAppSettingsData): ConfigForm {
  return {
    enabled: settings.enabled,
    notify_payments: settings.notify_payments,
    notify_sorties: settings.notify_sorties,
    provider: settings.provider || '',
    api_url: settings.api_url || '',
    sender: settings.sender || '',
    phone_number_id: settings.phone_number_id || '',
    business_account_id: settings.business_account_id || '',
  }
}

/** Rend un gabarit avec les valeurs d'exemple, comme le ferait `render()`. */
function renderPreview(template: string, variables: Record<string, string>): string {
  const substituted = (template || '').replace(PLACEHOLDER_RE, (_match, name: string) => {
    if (SAMPLE_VALUES[name] !== undefined) return SAMPLE_VALUES[name]
    // Variable connue du serveur mais sans exemple : son intitulé fait l'affaire.
    if (variables[name] !== undefined) return variables[name]
    // Variable inconnue : le serveur la remplace par du vide, l'aperçu aussi.
    return ''
  })

  const kept = substituted
    .split('\n')
    .filter(line => !EMPTY_FIELD_RE.test(line.trim()))
    .map(line => line.replace(/\s+$/, ''))

  // Une ligne vide de respiration suffit, comme côté serveur.
  const out: string[] = []
  let blank = 0
  for (const line of kept) {
    if (line.trim()) {
      blank = 0
      out.push(line)
    } else {
      blank += 1
      if (blank <= 1) out.push('')
    }
  }
  return out.join('\n').trim()
}

/** Variables citées dans un gabarit mais absentes du référentiel serveur. */
function unknownVariables(template: string, variables: Record<string, string>): string[] {
  const found = new Set<string>()
  for (const match of (template || '').matchAll(PLACEHOLDER_RE)) {
    const name = match[1]
    if (!(name in variables)) found.add(name)
  }
  return Array.from(found).sort()
}

const DATE_FORMAT = new Intl.DateTimeFormat('fr-FR', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

function formatDate(value: string | null): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '—'
  return DATE_FORMAT.format(parsed)
}

function errorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === 'object' && 'message' in err) {
    const message = (err as { message?: unknown }).message
    if (typeof message === 'string' && message.trim()) return message
  }
  return fallback
}

// ── Puce de statut : une icône par état, jamais la couleur seule ─────────────

function StatusPill({ kind, label }: { kind: StatusKind; label: string }) {
  const toneClass =
    kind === 'ok'
      ? styles.pillSuccess
      : kind === 'fail'
        ? styles.pillDanger
        : kind === 'pending' || kind === 'warn'
          ? styles.pillWarning
          : styles.pillNeutral

  const Icon = STATUS_ICONS[kind]

  return (
    <span className={`${styles.pill} ${toneClass}`}>
      <Icon size={13} aria-hidden="true" />
      {label}
    </span>
  )
}

/** Ligne de la bande d'état : intitulé, puis Oui/Non avec sa propre icône. */
function SummaryItem({ label, value, active }: { label: string; value: string; active: boolean }) {
  const Icon = active ? CheckCircle2 : XCircle
  return (
    <div className={styles.summaryItem}>
      <span className={styles.summaryLabel}>{label}</span>
      <span className={active ? styles.summaryValueOn : styles.summaryValueOff}>
        <Icon size={14} aria-hidden="true" />
        {value}
      </span>
    </div>
  )
}

// ── Composant ────────────────────────────────────────────────────────────────

export default function WhatsAppSettings() {
  const { hasPermission } = usePermissions()
  const canRead = hasPermission(WHATSAPP_PERMISSIONS.read)
  const canUpdate = hasPermission(WHATSAPP_PERMISSIONS.update)
  const canTest = hasPermission(WHATSAPP_PERMISSIONS.test)

  const [loading, setLoading] = useState(true)
  const [banner, setBanner] = useState<{ tone: 'success' | 'error' | 'info'; text: string } | null>(null)

  const [envelope, setEnvelope] = useState<WhatsAppSettingsEnvelope | null>(null)
  const [form, setForm] = useState<ConfigForm>(EMPTY_FORM)
  const [baseline, setBaseline] = useState<ConfigForm>(EMPTY_FORM)
  // Jamais lue ailleurs, jamais persistée, remise à vide dès l'enregistrement.
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [clearApiKey, setClearApiKey] = useState(false)
  const [savingConfig, setSavingConfig] = useState(false)

  const [recipients, setRecipients] = useState<WhatsAppRecipient[]>([])
  const [editingId, setEditingId] = useState<number | null>(null)
  const [phoneDraft, setPhoneDraft] = useState('')
  const [busyRecipientId, setBusyRecipientId] = useState<number | null>(null)
  const [testFeedback, setTestFeedback] = useState<Record<number, { ok: boolean; text: string }>>({})

  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([])
  const [templateVariables, setTemplateVariables] = useState<Record<string, string>>({})
  const [templateDrafts, setTemplateDrafts] = useState<Record<string, string>>({})
  const [activeEvent, setActiveEvent] = useState('')
  const [savingTemplates, setSavingTemplates] = useState(false)
  const templateRef = useRef<HTMLTextAreaElement | null>(null)

  const [logPage, setLogPage] = useState<WhatsAppLogPage | null>(null)
  const [logStatus, setLogStatus] = useState<WhatsAppLogStatus | ''>('')
  const [logsLoading, setLogsLoading] = useState(false)
  const [resendingId, setResendingId] = useState<string | null>(null)

  // ── Chargements ────────────────────────────────────────────────────────────

  const applyEnvelope = useCallback((next: WhatsAppSettingsEnvelope) => {
    setEnvelope(next)
    const shaped = toForm(next.settings)
    setForm(shaped)
    setBaseline(shaped)
  }, [])

  const loadLogs = useCallback(
    async (status: WhatsAppLogStatus | '') => {
      setLogsLoading(true)
      try {
        const page = await getWhatsAppLogs({ channel: 'WHATSAPP', status: status || undefined, limit: 25 })
        setLogPage(page)
      } catch (err) {
        setBanner({ tone: 'error', text: errorMessage(err, "L'historique des envois n'a pas pu être chargé.") })
      } finally {
        setLogsLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    if (!canRead) {
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        const [settingsEnvelope, recipientList, templatesEnvelope] = await Promise.all([
          getWhatsAppSettings(),
          getWhatsAppRecipients(),
          getWhatsAppTemplates(),
        ])
        if (cancelled) return
        applyEnvelope(settingsEnvelope)
        setRecipients(recipientList)
        setTemplates(templatesEnvelope.items)
        setTemplateVariables(templatesEnvelope.variables)
        setTemplateDrafts(
          Object.fromEntries(templatesEnvelope.items.map(item => [item.event_type, item.template])),
        )
        setActiveEvent(current => current || templatesEnvelope.items[0]?.event_type || '')
      } catch (err) {
        if (!cancelled) {
          setBanner({ tone: 'error', text: errorMessage(err, 'Les réglages WhatsApp n’ont pas pu être chargés.') })
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [canRead, applyEnvelope])

  useEffect(() => {
    if (!canRead) return
    void loadLogs(logStatus)
  }, [canRead, logStatus, loadLogs])

  // ── Configuration ──────────────────────────────────────────────────────────

  const settings = envelope?.settings ?? null
  const providers = envelope?.providers ?? []
  const events = envelope?.events ?? []

  const configDirty = useMemo(() => {
    const changed = (Object.keys(baseline) as Array<keyof ConfigForm>).some(key => form[key] !== baseline[key])
    return changed || apiKeyInput.trim().length > 0 || clearApiKey
  }, [form, baseline, apiKeyInput, clearApiKey])

  const setField = useCallback(<K extends keyof ConfigForm>(key: K, value: ConfigForm[K]) => {
    setForm(current => ({ ...current, [key]: value }))
  }, [])

  const resetConfig = useCallback(() => {
    setForm(baseline)
    setApiKeyInput('')
    setClearApiKey(false)
    setBanner(null)
  }, [baseline])

  const saveConfig = useCallback(async () => {
    if (!canUpdate || savingConfig) return
    setSavingConfig(true)
    setBanner(null)

    // Champ par champ, et non par boucle : le serveur applique `exclude_unset`,
    // donc une clé transmise « au cas où » écraserait une valeur qu'on n'a pas
    // touchée. L'écriture explicite garde aussi le typage de chaque champ.
    const payload: WhatsAppSettingsUpdate = {}
    if (form.enabled !== baseline.enabled) payload.enabled = form.enabled
    if (form.notify_payments !== baseline.notify_payments) payload.notify_payments = form.notify_payments
    if (form.notify_sorties !== baseline.notify_sorties) payload.notify_sorties = form.notify_sorties
    if (form.provider !== baseline.provider) payload.provider = form.provider
    if (form.api_url !== baseline.api_url) payload.api_url = form.api_url
    if (form.sender !== baseline.sender) payload.sender = form.sender
    if (form.phone_number_id !== baseline.phone_number_id) payload.phone_number_id = form.phone_number_id
    if (form.business_account_id !== baseline.business_account_id) {
      payload.business_account_id = form.business_account_id
    }

    // La clé quitte l'état de React **avant** le départ de la requête : elle ne
    // vit plus que dans cette variable locale, le temps de l'appel. Un échec la
    // perd donc aussi — c'est voulu, et l'écran le dit plutôt que de garder un
    // secret en mémoire au cas où l'utilisateur voudrait réessayer.
    const submittedKey = apiKeyInput.trim()
    const clearRequested = clearApiKey
    setApiKeyInput('')
    setClearApiKey(false)

    if (clearRequested) {
      payload.clear_api_key = true
    } else if (submittedKey) {
      payload.api_key = submittedKey
    }

    try {
      const next = await updateWhatsAppSettings(payload)
      applyEnvelope(next)
      setBanner({
        tone: next.warning ? 'info' : 'success',
        text: next.warning
          ? `Réglages enregistrés. ${next.warning}`
          : 'Réglages WhatsApp enregistrés.',
      })
    } catch (err) {
      const base = errorMessage(err, "Les réglages n'ont pas pu être enregistrés.")
      setBanner({
        tone: 'error',
        text: submittedKey
          ? `${base} La clé saisie a été effacée du formulaire par sécurité : saisissez-la de nouveau.`
          : base,
      })
    } finally {
      setSavingConfig(false)
    }
  }, [canUpdate, savingConfig, baseline, form, clearApiKey, apiKeyInput, applyEnvelope])

  // ── Destinataires ──────────────────────────────────────────────────────────

  const patchRecipient = useCallback(
    async (member: WhatsAppRecipient, input: { telephone?: string; notify_whatsapp?: boolean }) => {
      setBusyRecipientId(member.id)
      setBanner(null)
      try {
        const updated = await updateWhatsAppRecipient(member.id, input)
        setRecipients(current => current.map(row => (row.id === updated.id ? updated : row)))
        setEditingId(null)
      } catch (err) {
        setBanner({ tone: 'error', text: errorMessage(err, "Le destinataire n'a pas pu être mis à jour.") })
      } finally {
        setBusyRecipientId(null)
      }
    },
    [],
  )

  const testRecipient = useCallback(
    async (member: WhatsAppRecipient) => {
      setBusyRecipientId(member.id)
      setBanner(null)
      try {
        const result = await sendWhatsAppTest({ member_id: member.id })
        setTestFeedback(current => ({ ...current, [member.id]: { ok: result.ok, text: result.detail } }))
        void loadLogs(logStatus)
      } catch (err) {
        setTestFeedback(current => ({
          ...current,
          [member.id]: { ok: false, text: errorMessage(err, "L'envoi de vérification a échoué.") },
        }))
      } finally {
        setBusyRecipientId(null)
      }
    },
    [loadLogs, logStatus],
  )

  // ── Gabarits ───────────────────────────────────────────────────────────────

  const activeTemplate = useMemo(
    () => templates.find(item => item.event_type === activeEvent) ?? null,
    [templates, activeEvent],
  )
  const activeDraft = activeEvent ? (templateDrafts[activeEvent] ?? '') : ''

  const changedTemplates = useMemo(
    () => templates.filter(item => (templateDrafts[item.event_type] ?? '') !== item.template),
    [templates, templateDrafts],
  )

  const insertVariable = useCallback(
    (name: string) => {
      if (!activeEvent || !canUpdate) return
      const token = `{{${name}}}`
      const node = templateRef.current
      setTemplateDrafts(current => {
        const text = current[activeEvent] ?? ''
        const start = node ? node.selectionStart : text.length
        const end = node ? node.selectionEnd : text.length
        const next = `${text.slice(0, start)}${token}${text.slice(end)}`
        // Le curseur doit rester derrière la variable qu'on vient de poser.
        window.requestAnimationFrame(() => {
          if (!node) return
          node.focus()
          node.setSelectionRange(start + token.length, start + token.length)
        })
        return { ...current, [activeEvent]: next }
      })
    },
    [activeEvent, canUpdate],
  )

  const restoreDefault = useCallback(() => {
    if (!activeTemplate || !canUpdate) return
    setTemplateDrafts(current => ({ ...current, [activeTemplate.event_type]: activeTemplate.default_template }))
  }, [activeTemplate, canUpdate])

  const saveTemplates = useCallback(async () => {
    if (!canUpdate || savingTemplates || changedTemplates.length === 0) return
    setSavingTemplates(true)
    setBanner(null)

    const payload: Record<string, string | null> = {}
    for (const item of changedTemplates) {
      const draft = (templateDrafts[item.event_type] ?? '').trim()
      // Revenu au texte d'origine : on retire la surcharge plutôt que de la
      // recopier — c'est ce que le serveur entend par valeur vide.
      payload[item.event_type] = draft && draft !== item.default_template.trim() ? draft : ''
    }

    try {
      const result = await updateWhatsAppTemplates(payload)
      const fresh = await getWhatsAppTemplates()
      setTemplates(fresh.items)
      setTemplateVariables(fresh.variables)
      setTemplateDrafts(Object.fromEntries(fresh.items.map(item => [item.event_type, item.template])))

      const warnings = Object.values(result.warnings)
      const summary = [
        result.updated.length ? `${result.updated.length} gabarit(s) personnalisé(s)` : '',
        result.reset.length ? `${result.reset.length} rétabli(s) par défaut` : '',
      ]
        .filter(Boolean)
        .join(' · ')
      setBanner({
        tone: warnings.length ? 'info' : 'success',
        text: warnings.length
          ? `Gabarits enregistrés (${summary}). ${warnings.join(' ')}`
          : `Gabarits enregistrés${summary ? ` : ${summary}` : ''}.`,
      })
    } catch (err) {
      setBanner({ tone: 'error', text: errorMessage(err, "Les gabarits n'ont pas pu être enregistrés.") })
    } finally {
      setSavingTemplates(false)
    }
  }, [canUpdate, savingTemplates, changedTemplates, templateDrafts])

  // ── Historique ─────────────────────────────────────────────────────────────

  const resendLog = useCallback(
    async (log: WhatsAppLog) => {
      setResendingId(log.id)
      setBanner(null)
      try {
        const result = await resendWhatsAppLog(log.id)
        setBanner({ tone: result.ok ? 'success' : 'error', text: result.detail })
        await loadLogs(logStatus)
      } catch (err) {
        setBanner({ tone: 'error', text: errorMessage(err, "Le renvoi n'a pas abouti.") })
      } finally {
        setResendingId(null)
      }
    },
    [loadLogs, logStatus],
  )

  // ── Rendu ──────────────────────────────────────────────────────────────────

  if (!canRead) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.bannerError}>
          <AlertTriangle size={15} aria-hidden="true" />
          <span>Vous n'avez pas l'autorisation de consulter les réglages de notifications WhatsApp.</span>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className={styles.wrapper}>
        <div className={styles.emptyState}>Chargement des réglages WhatsApp…</div>
      </div>
    )
  }

  const providerIsMeta = form.provider === 'meta'
  const providerIsTwilio = form.provider === 'twilio'
  const providerLabel = settings?.provider_label || form.provider || 'Non défini'
  const senderDisplay = form.sender.trim() || (providerIsMeta ? form.phone_number_id.trim() : '')

  const paymentEvents = events.filter(event => event.family === 'payments')
  const sortieEvents = events.filter(event => event.family === 'sorties')

  return (
    <div className={styles.wrapper}>
      {banner && (
        <div
          className={
            banner.tone === 'success'
              ? styles.bannerSuccess
              : banner.tone === 'error'
                ? styles.bannerError
                : styles.bannerInfo
          }
          role="status"
        >
          {banner.tone === 'success' ? (
            <CheckCircle2 size={15} aria-hidden="true" />
          ) : banner.tone === 'error' ? (
            <XCircle size={15} aria-hidden="true" />
          ) : (
            <Info size={15} aria-hidden="true" />
          )}
          <span>{banner.text}</span>
          <button type="button" className={styles.bannerClose} onClick={() => setBanner(null)} aria-label="Fermer">
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      )}

      {/* ── 1. État du service ────────────────────────────────────────────── */}

      <section className={form.enabled ? styles.summaryBandOn : styles.summaryBandOff} aria-label="État du service">
        <div className={styles.summaryHead}>
          <span className={form.enabled ? styles.summaryBadgeOn : styles.summaryBadgeOff}>
            {form.enabled ? <BadgeCheck size={15} aria-hidden="true" /> : <MinusCircle size={15} aria-hidden="true" />}
            {form.enabled ? 'Service actif' : 'Service inactif'}
          </span>
          <span className={styles.summaryHint}>
            {form.enabled
              ? 'Les messages configurés ci-dessous partent automatiquement.'
              : 'Aucun message ne part tant que le service reste inactif.'}
          </span>
        </div>
        <div className={styles.summaryGrid}>
          <div className={styles.summaryItem}>
            <span className={styles.summaryLabel}>Fournisseur</span>
            <span className={styles.summaryValueText}>{providerLabel}</span>
          </div>
          <div className={styles.summaryItem}>
            <span className={styles.summaryLabel}>Numéro émetteur</span>
            <span className={styles.summaryValueText}>{senderDisplay || 'Non renseigné'}</span>
          </div>
          <SummaryItem
            label="Notifications paiements"
            value={form.notify_payments ? 'Oui' : 'Non'}
            active={form.notify_payments}
          />
          <SummaryItem
            label="Notifications sorties"
            value={form.notify_sorties ? 'Oui' : 'Non'}
            active={form.notify_sorties}
          />
          <SummaryItem
            label="Clé API enregistrée"
            value={settings?.has_api_key ? 'Oui' : 'Non'}
            active={Boolean(settings?.has_api_key)}
          />
        </div>
        {envelope?.warning && (
          <div className={styles.summaryWarning}>
            <AlertTriangle size={14} aria-hidden="true" />
            <span>{envelope.warning}</span>
          </div>
        )}
      </section>

      {/* ── 2. Configuration ──────────────────────────────────────────────── */}

      <section className={styles.panel} aria-label="Configuration du canal">
        <header className={styles.panelHeader}>
          <h4 className={styles.panelTitle}>
            <Settings2 size={15} aria-hidden="true" />
            Configuration du canal
          </h4>
          {configDirty && (
            <span className={styles.dirtyBadge}>
              <AlertTriangle size={12} aria-hidden="true" />
              Modifications non enregistrées
            </span>
          )}
        </header>

        <div className={styles.panelBody}>
          <div className={styles.toggleList}>
            <label className={styles.toggleRow}>
              <span className={styles.toggleText}>
                <strong>Activer les notifications WhatsApp</strong>
                <em>Interrupteur général : coupé, plus aucun message ne part, quelles que soient les cases ci-dessous.</em>
              </span>
              <span className={styles.switch}>
                <input
                  type="checkbox"
                  checked={form.enabled}
                  disabled={!canUpdate}
                  onChange={event => setField('enabled', event.target.checked)}
                />
                <span />
              </span>
            </label>

            <label className={styles.toggleRow}>
              <span className={styles.toggleText}>
                <strong>Notifications de paiements</strong>
                <em>
                  {paymentEvents.length
                    ? `Concerne : ${paymentEvents.map(event => event.label).join(', ')}.`
                    : 'Encaissements, relances et compléments de paiement.'}
                </em>
              </span>
              <span className={styles.switch}>
                <input
                  type="checkbox"
                  checked={form.notify_payments}
                  disabled={!canUpdate || !form.enabled}
                  onChange={event => setField('notify_payments', event.target.checked)}
                />
                <span />
              </span>
            </label>

            <label className={styles.toggleRow}>
              <span className={styles.toggleText}>
                <strong>Notifications de sorties de fonds</strong>
                <em>
                  {sortieEvents.length
                    ? `Concerne : ${sortieEvents.map(event => event.label).join(', ')}.`
                    : 'Sorties de fonds et réquisitions approuvées.'}
                </em>
              </span>
              <span className={styles.switch}>
                <input
                  type="checkbox"
                  checked={form.notify_sorties}
                  disabled={!canUpdate || !form.enabled}
                  onChange={event => setField('notify_sorties', event.target.checked)}
                />
                <span />
              </span>
            </label>
          </div>

          <div className={styles.formGrid}>
            <div className={styles.field}>
              <label htmlFor="wa-provider">Fournisseur</label>
              <select
                id="wa-provider"
                value={form.provider}
                disabled={!canUpdate}
                onChange={event => setField('provider', event.target.value)}
              >
                <option value="">— Choisir un fournisseur —</option>
                {providers.map(option => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <p className={styles.fieldHint}>Détermine les champs à renseigner ci-dessous.</p>
            </div>

            <div className={styles.field}>
              <label htmlFor="wa-url">
                {providerIsMeta
                  ? "URL de l'API Graph"
                  : providerIsTwilio
                    ? "URL de base de l'API Twilio"
                    : 'URL Evolution / Baileys'}
              </label>
              <input
                id="wa-url"
                type="text"
                value={form.api_url}
                disabled={!canUpdate}
                onChange={event => setField('api_url', event.target.value)}
                placeholder={
                  providerIsMeta
                    ? 'https://graph.facebook.com'
                    : providerIsTwilio
                      ? 'https://api.twilio.com/2010-04-01'
                      : 'https://wa.exemple.org/message/sendText/onec'
                }
              />
              <p className={styles.fieldHint}>
                {providerIsMeta || providerIsTwilio
                  ? "Facultatif : laissez vide pour l'adresse standard du fournisseur."
                  : "Adresse complète d'envoi de message de votre instance."}
              </p>
            </div>

            <div className={styles.field}>
              <label htmlFor="wa-sender">Numéro émetteur</label>
              <input
                id="wa-sender"
                type="text"
                value={form.sender}
                disabled={!canUpdate}
                onChange={event => setField('sender', event.target.value)}
                placeholder="243810123456"
              />
              <p className={styles.fieldHint}>Numéro depuis lequel les messages sont envoyés, au format international.</p>
            </div>

            <div className={styles.field}>
              <label htmlFor="wa-key">Clé API</label>
              <input
                id="wa-key"
                type="password"
                autoComplete="new-password"
                value={apiKeyInput}
                disabled={!canUpdate || clearApiKey}
                onChange={event => setApiKeyInput(event.target.value)}
                placeholder={settings?.has_api_key ? '•••••••• (clé enregistrée)' : 'Saisissez la clé du fournisseur'}
              />
              <p className={styles.fieldHint}>
                {settings?.has_api_key
                  ? 'Une clé est enregistrée. Elle n’est jamais réaffichée : laissez ce champ vide pour la conserver, ou saisissez-en une nouvelle pour la remplacer.'
                  : 'Aucune clé enregistrée pour le moment. Elle sera chiffrée et ne sera plus jamais réaffichée.'}
                {' '}Le champ se vide à chaque enregistrement, réussi ou non.
              </p>
              {settings?.has_api_key && canUpdate && (
                <label className={styles.clearKeyRow}>
                  <input
                    type="checkbox"
                    checked={clearApiKey}
                    onChange={event => {
                      setClearApiKey(event.target.checked)
                      if (event.target.checked) setApiKeyInput('')
                    }}
                  />
                  Supprimer la clé enregistrée à l'enregistrement
                </label>
              )}
            </div>

            {providerIsMeta && (
              <>
                <div className={styles.field}>
                  <label htmlFor="wa-phone-id">Identifiant du numéro émetteur (Meta)</label>
                  <input
                    id="wa-phone-id"
                    type="text"
                    value={form.phone_number_id}
                    disabled={!canUpdate}
                    onChange={event => setField('phone_number_id', event.target.value)}
                    placeholder="123456789012345"
                  />
                  <p className={styles.fieldHint}>
                    Champ obligatoire pour Meta : c'est lui, et non le numéro, qui adresse l'envoi.
                  </p>
                </div>
                <div className={styles.field}>
                  <label htmlFor="wa-business-id">Identifiant du compte professionnel (Meta)</label>
                  <input
                    id="wa-business-id"
                    type="text"
                    value={form.business_account_id}
                    disabled={!canUpdate}
                    onChange={event => setField('business_account_id', event.target.value)}
                    placeholder="098765432109876"
                  />
                  <p className={styles.fieldHint}>Identifiant du compte WhatsApp Business rattaché au numéro.</p>
                </div>
              </>
            )}

            {providerIsTwilio && (
              <div className={styles.fieldWide}>
                <div className={styles.inlineNotice}>
                  <Info size={14} aria-hidden="true" />
                  <span>
                    Twilio : la clé API correspond au jeton d'authentification (Auth Token). Le SID de compte
                    (Account SID) n'est pas modifiable depuis cet écran — l'API de réglages ne l'expose pas ; il reste
                    réglable par le paramétrage serveur.
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className={styles.actionBar}>
          <span className={styles.actionHint}>
            {canUpdate
              ? 'Seuls les champs modifiés sont transmis.'
              : "Consultation seule : vous n'avez pas l'autorisation de modifier ces réglages."}
          </span>
          <div className={styles.actionButtons}>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={resetConfig}
              disabled={!configDirty || savingConfig}
            >
              <RotateCcw size={14} aria-hidden="true" />
              Annuler les modifications
            </button>
            <button
              type="button"
              className={styles.primaryButton}
              onClick={() => void saveConfig()}
              disabled={!canUpdate || !configDirty || savingConfig}
            >
              <Save size={14} aria-hidden="true" />
              {savingConfig ? 'Enregistrement…' : 'Enregistrer la configuration'}
            </button>
          </div>
        </div>
      </section>

      {/* ── 3. Destinataires du Bureau ────────────────────────────────────── */}

      <section className={styles.panel} aria-label="Destinataires du Bureau">
        <header className={styles.panelHeader}>
          <h4 className={styles.panelTitle}>
            <Users size={15} aria-hidden="true" />
            Destinataires du Bureau
          </h4>
          <span className={styles.countPill}>{recipients.length} membre(s)</span>
        </header>

        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Nom</th>
                <th scope="col">Fonction</th>
                <th scope="col">Numéro WhatsApp</th>
                <th scope="col" className={styles.colCenter}>Notifications sorties</th>
                <th scope="col">Statut</th>
                <th scope="col" className={styles.colActions}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {recipients.length === 0 && (
                <tr>
                  <td colSpan={6} className={styles.emptyRow}>
                    Aucun membre du Bureau n'est enregistré pour cette organisation.
                  </td>
                </tr>
              )}
              {recipients.map(member => {
                const busy = busyRecipientId === member.id
                const editing = editingId === member.id
                const feedback = testFeedback[member.id]
                return (
                  <tr key={member.id}>
                    <td className={styles.cellStrong}>{member.full_name || '—'}</td>
                    <td>{member.function || '—'}</td>
                    <td>
                      {editing ? (
                        <div className={styles.inlineEdit}>
                          <input
                            type="text"
                            value={phoneDraft}
                            onChange={event => setPhoneDraft(event.target.value)}
                            placeholder="0810 123 456"
                            aria-label={`Numéro WhatsApp de ${member.full_name || 'ce membre'}`}
                          />
                          <button
                            type="button"
                            className={styles.miniPrimary}
                            disabled={busy}
                            onClick={() => void patchRecipient(member, { telephone: phoneDraft })}
                          >
                            Enregistrer
                          </button>
                          <button
                            type="button"
                            className={styles.miniButton}
                            disabled={busy}
                            onClick={() => setEditingId(null)}
                          >
                            Annuler
                          </button>
                        </div>
                      ) : (
                        <span className={member.phone_display ? styles.phone : styles.phoneMissing}>
                          {member.phone_display || 'Non renseigné'}
                        </span>
                      )}
                    </td>
                    <td className={styles.colCenter}>
                      <label className={styles.switch}>
                        <input
                          type="checkbox"
                          checked={member.notify_whatsapp}
                          disabled={!canUpdate || busy}
                          aria-label={`Notifications de sorties pour ${member.full_name || 'ce membre'}`}
                          onChange={event =>
                            void patchRecipient(member, { notify_whatsapp: event.target.checked })
                          }
                        />
                        <span />
                      </label>
                    </td>
                    <td>
                      <StatusPill
                        kind={RECIPIENT_STATUS_KINDS[member.status] ?? 'off'}
                        label={member.status_label || member.status}
                      />
                      {feedback && (
                        <div className={feedback.ok ? styles.rowFeedbackOk : styles.rowFeedbackKo}>
                          {feedback.ok ? (
                            <CheckCircle2 size={12} aria-hidden="true" />
                          ) : (
                            <XCircle size={12} aria-hidden="true" />
                          )}
                          {feedback.text}
                        </div>
                      )}
                    </td>
                    <td className={styles.colActions}>
                      <div className={styles.rowActions}>
                        <button
                          type="button"
                          className={styles.miniButton}
                          disabled={!canUpdate || busy}
                          onClick={() => {
                            setEditingId(member.id)
                            setPhoneDraft(member.phone_display || member.phone || '')
                          }}
                        >
                          <Pencil size={12} aria-hidden="true" />
                          Modifier
                        </button>
                        <button
                          type="button"
                          className={styles.miniButton}
                          disabled={!canUpdate || busy}
                          onClick={() => void patchRecipient(member, { notify_whatsapp: !member.notify_whatsapp })}
                        >
                          {member.notify_whatsapp ? 'Désactiver' : 'Activer'}
                        </button>
                        <button
                          type="button"
                          className={styles.miniPrimary}
                          disabled={!canTest || busy || !form.enabled || member.status !== 'ready'}
                          title={
                            !form.enabled
                              ? 'Activez le canal WhatsApp avant de tester.'
                              : member.status !== 'ready'
                                ? 'Ce membre doit avoir un numéro valide et les notifications activées.'
                                : 'Envoie un message de vérification. Aucune opération n’est créée.'
                          }
                          onClick={() => void testRecipient(member)}
                        >
                          <Send size={12} aria-hidden="true" />
                          {busy ? 'Envoi…' : 'Tester'}
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <div className={styles.panelFooterNote}>
          <Info size={13} aria-hidden="true" />
          <span>
            « Tester » envoie un vrai message de vérification au membre choisi. Il est enregistré comme test dans
            l'historique et ne crée aucune opération de caisse ni sortie de fonds.
          </span>
        </div>
      </section>

      {/* ── 4. Gabarits de message ────────────────────────────────────────── */}

      <section className={styles.panel} aria-label="Gabarits de message">
        <header className={styles.panelHeader}>
          <h4 className={styles.panelTitle}>
            <MessageSquareText size={15} aria-hidden="true" />
            Gabarits de message
          </h4>
          {changedTemplates.length > 0 && (
            <span className={styles.dirtyBadge}>
              <AlertTriangle size={12} aria-hidden="true" />
              {changedTemplates.length} gabarit(s) non enregistré(s)
            </span>
          )}
        </header>

        <div className={styles.eventTabs} role="group" aria-label="Types d'événement">
          {templates.map(item => {
            const modified = (templateDrafts[item.event_type] ?? '') !== item.template
            return (
              <button
                key={item.event_type}
                type="button"
                aria-pressed={item.event_type === activeEvent}
                className={item.event_type === activeEvent ? styles.eventTabActive : styles.eventTab}
                onClick={() => setActiveEvent(item.event_type)}
              >
                {item.label || item.event_type}
                {item.is_custom && <span className={styles.tabDot} title="Gabarit personnalisé" />}
                {modified && <span className={styles.tabDotWarn} title="Modification non enregistrée" />}
              </button>
            )
          })}
        </div>

        {activeTemplate ? (
          <div className={styles.templateBody}>
            <div className={styles.templateEditor}>
              <div className={styles.templateToolbar}>
                <span className={styles.templateHint}>
                  Cliquez sur une variable pour l'insérer à l'endroit du curseur.
                </span>
                <button
                  type="button"
                  className={styles.miniButton}
                  disabled={!canUpdate || activeDraft === activeTemplate.default_template}
                  onClick={restoreDefault}
                >
                  <RotateCcw size={12} aria-hidden="true" />
                  Rétablir le gabarit par défaut
                </button>
              </div>

              <div className={styles.variableList}>
                {Object.entries(templateVariables).map(([name, description]) => (
                  <button
                    key={name}
                    type="button"
                    className={styles.variableChip}
                    disabled={!canUpdate}
                    title={description}
                    onClick={() => insertVariable(name)}
                  >
                    {`{{${name}}}`}
                  </button>
                ))}
              </div>

              <textarea
                ref={templateRef}
                className={styles.templateArea}
                rows={14}
                value={activeDraft}
                disabled={!canUpdate}
                maxLength={TEMPLATE_MAX_LENGTH}
                aria-label={`Gabarit du message « ${activeTemplate.label || activeTemplate.event_type} »`}
                onChange={event =>
                  setTemplateDrafts(current => ({ ...current, [activeTemplate.event_type]: event.target.value }))
                }
              />
              <div className={styles.templateMeta}>
                <span>
                  {activeDraft.length} / {TEMPLATE_MAX_LENGTH} caractères
                </span>
                {activeDraft.trim().length === 0 && (
                  <span className={styles.metaWarn}>Un gabarit vide rétablit le texte par défaut.</span>
                )}
                {unknownVariables(activeDraft, templateVariables).length > 0 && (
                  <span className={styles.metaWarn}>
                    Variables inconnues, elles resteront vides :{' '}
                    {unknownVariables(activeDraft, templateVariables).join(', ')}
                  </span>
                )}
              </div>
            </div>

            <div className={styles.previewPane}>
              <div className={styles.previewHeader}>
                <Eye size={13} aria-hidden="true" />
                Aperçu avec des valeurs d'exemple
              </div>
              <pre className={styles.previewBody}>{renderPreview(activeDraft, templateVariables) || '—'}</pre>
              <p className={styles.previewFoot}>
                Les valeurs affichées sont fictives ; le message réel reprendra les données de l'opération.
              </p>
            </div>
          </div>
        ) : (
          <div className={styles.emptyState}>Aucun gabarit disponible.</div>
        )}

        <div className={styles.actionBar}>
          <span className={styles.actionHint}>
            Un gabarit ramené à son texte d'origine cesse d'être une personnalisation.
          </span>
          <div className={styles.actionButtons}>
            <button
              type="button"
              className={styles.secondaryButton}
              disabled={changedTemplates.length === 0 || savingTemplates}
              onClick={() =>
                setTemplateDrafts(Object.fromEntries(templates.map(item => [item.event_type, item.template])))
              }
            >
              <RotateCcw size={14} aria-hidden="true" />
              Annuler les modifications
            </button>
            <button
              type="button"
              className={styles.primaryButton}
              disabled={!canUpdate || changedTemplates.length === 0 || savingTemplates}
              onClick={() => void saveTemplates()}
            >
              <Save size={14} aria-hidden="true" />
              {savingTemplates ? 'Enregistrement…' : 'Enregistrer les gabarits'}
            </button>
          </div>
        </div>
      </section>

      {/* ── 5. Historique récent ──────────────────────────────────────────── */}

      <section className={styles.panel} aria-label="Historique récent des envois">
        <header className={styles.panelHeader}>
          <h4 className={styles.panelTitle}>
            <History size={15} aria-hidden="true" />
            Historique récent
          </h4>
          <div className={styles.panelHeaderActions}>
            <div className={styles.filterChips} role="group" aria-label="Filtrer par statut">
              <button
                type="button"
                className={logStatus === '' ? styles.chipActive : styles.chip}
                onClick={() => setLogStatus('')}
              >
                Tous
              </button>
              {LOG_STATUS_ORDER.map(status => (
                <button
                  key={status}
                  type="button"
                  className={logStatus === status ? styles.chipActive : styles.chip}
                  onClick={() => setLogStatus(status)}
                >
                  {LOG_STATUS_LABELS[status]}
                </button>
              ))}
            </div>
            <button
              type="button"
              className={styles.miniButton}
              disabled={logsLoading}
              onClick={() => void loadLogs(logStatus)}
            >
              <RefreshCw size={12} aria-hidden="true" />
              Actualiser
            </button>
          </div>
        </header>

        {logPage?.masked && (
          <div className={styles.inlineNotice}>
            <Info size={14} aria-hidden="true" />
            <span>
              Les numéros sont partiellement masqués : leur affichage complet demande l'autorisation « Historique des
              notifications ».
            </span>
          </div>
        )}

        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Événement</th>
                <th scope="col">Destinataire</th>
                <th scope="col">Statut</th>
                <th scope="col">Motif</th>
                <th scope="col" className={styles.colActions}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {logsLoading && (
                <tr>
                  <td colSpan={6} className={styles.emptyRow}>
                    Chargement de l'historique…
                  </td>
                </tr>
              )}
              {!logsLoading && (logPage?.items.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={6} className={styles.emptyRow}>
                    Aucun envoi enregistré pour ce filtre.
                  </td>
                </tr>
              )}
              {!logsLoading &&
                logPage?.items.map(log => {
                  const status = (LOG_STATUS_ORDER as string[]).includes(log.status)
                    ? (log.status as WhatsAppLogStatus)
                    : null
                  return (
                    <tr key={log.id}>
                      <td className={styles.cellNowrap}>{formatDate(log.created_at)}</td>
                      <td>{log.event_label || log.event_type}</td>
                      <td>
                        <span className={styles.cellStrong}>{log.recipient_name || '—'}</span>
                        <span className={styles.cellSub}>
                          {log.recipient || '—'}
                          {log.recipient_role ? ` · ${log.recipient_role}` : ''}
                        </span>
                      </td>
                      <td>
                        <StatusPill
                          kind={status ? LOG_STATUS_KINDS[status] : 'off'}
                          label={log.status_label || (status ? LOG_STATUS_LABELS[status] : log.status)}
                        />
                        {log.attempts > 1 && <span className={styles.cellSub}>{log.attempts} tentatives</span>}
                      </td>
                      <td className={styles.cellReason}>{log.error_message || '—'}</td>
                      <td className={styles.colActions}>
                        {log.status === 'FAILED' ? (
                          <button
                            type="button"
                            className={styles.miniPrimary}
                            disabled={!canTest || resendingId === log.id}
                            onClick={() => void resendLog(log)}
                          >
                            <Send size={12} aria-hidden="true" />
                            {resendingId === log.id ? 'Renvoi…' : 'Renvoyer'}
                          </button>
                        ) : (
                          <span className={styles.cellSub}>—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
            </tbody>
          </table>
        </div>

        {logPage && logPage.total > logPage.items.length && (
          <div className={styles.panelFooterNote}>
            <Info size={13} aria-hidden="true" />
            <span>
              {logPage.items.length} envoi(s) affiché(s) sur {logPage.total} enregistré(s) — les plus récents d'abord.
            </span>
          </div>
        )}
      </section>
    </div>
  )
}
