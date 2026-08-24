/**
 * Administration du canal WhatsApp — appels typés du routeur `/api/v1/whatsapp`.
 *
 * Les types miment exactement `app/schemas/whatsapp.py` : ce module ne devine
 * rien, il transcrit. Une seule règle mérite d'être rappelée ici, parce qu'elle
 * dicte la forme du formulaire côté écran :
 *
 *   **La clé API ne revient jamais du serveur.** `WhatsAppSettings.has_api_key`
 *   dit seulement qu'une clé est posée. En écriture, `api_key` absente ou vide
 *   laisse la clé en place ; sa suppression est un geste explicite
 *   (`clear_api_key`). Un champ mot de passe jamais pré-rempli qui renverrait
 *   `api_key: ''` à chaque enregistrement n'efface donc rien.
 */

import { apiRequest } from '../lib/apiClient'

// ── Codes de permission du routeur ───────────────────────────────────────────

export const WHATSAPP_PERMISSIONS = {
  read: 'treso.notifications.read',
  update: 'treso.notifications.update',
  history: 'treso.notifications.history',
  test: 'treso.notifications.test',
} as const

// ── Réglages ─────────────────────────────────────────────────────────────────

/** Famille d'activation d'un événement : la case qui commande son envoi. */
export type WhatsAppEventFamily = 'payments' | 'sorties' | 'service'

export type WhatsAppProviderOption = {
  value: string
  label: string
}

export type WhatsAppEventOption = {
  value: string
  label: string
  family: WhatsAppEventFamily | string
}

export type WhatsAppSettings = {
  enabled: boolean
  notify_payments: boolean
  notify_sorties: boolean
  provider: string
  provider_label: string
  api_url: string
  sender: string
  phone_number_id: string
  business_account_id: string
  /** Une clé est enregistrée — jamais sa valeur, pas même masquée. */
  has_api_key: boolean
  /** Surcharges de gabarits en place, indexées par type d'événement. */
  templates: Record<string, string>
}

export type WhatsAppSettingsEnvelope = {
  settings: WhatsAppSettings
  providers: WhatsAppProviderOption[]
  default_templates: Record<string, string>
  template_variables: Record<string, string>
  events: WhatsAppEventOption[]
  /** Motif pour lequel le canal ne pourrait pas émettre, ou chaîne vide. */
  warning: string
}

/**
 * Corps de `PUT /whatsapp/settings`. Seuls les champs transmis sont appliqués :
 * un écran qui n'édite que l'activation ne doit pas remettre l'URL à zéro.
 */
export type WhatsAppSettingsUpdate = {
  enabled?: boolean
  notify_payments?: boolean
  notify_sorties?: boolean
  provider?: string
  api_url?: string
  sender?: string
  phone_number_id?: string
  business_account_id?: string
  /** Clé en clair. Absente ou vide : la clé enregistrée n'est pas touchée. */
  api_key?: string
  /** Supprime la clé enregistrée. Prend le pas sur `api_key`. */
  clear_api_key?: boolean
}

export async function getWhatsAppSettings(): Promise<WhatsAppSettingsEnvelope> {
  return apiRequest('GET', '/whatsapp/settings')
}

export async function updateWhatsAppSettings(
  input: WhatsAppSettingsUpdate,
): Promise<WhatsAppSettingsEnvelope> {
  return apiRequest('PUT', '/whatsapp/settings', input)
}

// ── Destinataires (membres du Bureau) ────────────────────────────────────────

/** `ready` : joignable · `no_phone` : numéro absent ou invalide · `opted_out` : refus. */
export type WhatsAppRecipientStatus = 'ready' | 'no_phone' | 'opted_out'

export type WhatsAppRecipient = {
  id: number
  full_name: string
  /** Fonction au Bureau : Président, Trésorier… */
  function: string
  service_id: number | null
  email: string | null
  /** Numéro normalisé (E.164 sans « + »). */
  phone: string
  /** Numéro lisible : +243 810 123 456. */
  phone_display: string
  notify_whatsapp: boolean
  status: WhatsAppRecipientStatus | string
  status_label: string
}

/** `telephone: ''` retire le numéro ; champ absent, il n'est pas touché. */
export type WhatsAppRecipientUpdate = {
  telephone?: string
  notify_whatsapp?: boolean
}

export async function getWhatsAppRecipients(): Promise<WhatsAppRecipient[]> {
  return apiRequest('GET', '/whatsapp/recipients')
}

export async function updateWhatsAppRecipient(
  memberId: number,
  input: WhatsAppRecipientUpdate,
): Promise<WhatsAppRecipient> {
  return apiRequest('PATCH', `/whatsapp/recipients/${memberId}`, input)
}

// ── Gabarits ─────────────────────────────────────────────────────────────────

export type WhatsAppTemplate = {
  event_type: string
  label: string
  family: WhatsAppEventFamily | string
  /** Gabarit appliqué : la surcharge si elle existe, sinon le défaut. */
  template: string
  default_template: string
  is_custom: boolean
}

export type WhatsAppTemplatesEnvelope = {
  items: WhatsAppTemplate[]
  variables: Record<string, string>
}

export type WhatsAppTemplatesSaveResult = {
  ok: boolean
  updated: string[]
  reset: string[]
  /** Avertissements non bloquants : l'enregistrement a bien eu lieu. */
  warnings: Record<string, string>
}

export async function getWhatsAppTemplates(): Promise<WhatsAppTemplatesEnvelope> {
  return apiRequest('GET', '/whatsapp/templates')
}

/**
 * Enregistre des surcharges de gabarits. Une valeur vide retire la surcharge :
 * c'est le seul moyen de rétablir le gabarit par défaut sans recopier son texte.
 */
export async function updateWhatsAppTemplates(
  templates: Record<string, string | null>,
): Promise<WhatsAppTemplatesSaveResult> {
  return apiRequest('PUT', '/whatsapp/templates', { templates })
}

// ── Journal d'envoi ──────────────────────────────────────────────────────────

export type WhatsAppLogStatus = 'PENDING' | 'SENT' | 'FAILED' | 'SKIPPED'

export type WhatsAppLog = {
  id: string
  channel: string
  event_type: string
  event_label: string
  entity_type: string
  entity_id: string
  /** Déjà mis en forme par le serveur : lisible ou masqué selon la permission. */
  recipient: string
  recipient_name: string
  recipient_role: string
  message: string
  status: WhatsAppLogStatus | string
  status_label: string
  provider: string
  provider_message_id: string | null
  error_message: string | null
  attempts: number
  created_at: string | null
  sent_at: string | null
}

export type WhatsAppLogPage = {
  items: WhatsAppLog[]
  total: number
  limit: number
  offset: number
  /** Vrai quand les numéros sont voilés faute de `treso.notifications.history`. */
  masked: boolean
}

export type WhatsAppLogFilters = {
  status?: WhatsAppLogStatus | string
  channel?: string
  event_type?: string
  entity_type?: string
  entity_id?: string
  /** `2026-08-01` ou horodatage ISO complet. */
  date_debut?: string
  date_fin?: string
  /** 1 à 500, 50 par défaut côté serveur. */
  limit?: number
  offset?: number
}

export async function getWhatsAppLogs(filters?: WhatsAppLogFilters): Promise<WhatsAppLogPage> {
  const params: Record<string, string | number> = {}
  if (filters) {
    for (const [key, value] of Object.entries(filters)) {
      if (value === undefined || value === null || value === '') continue
      params[key] = value as string | number
    }
  }
  return apiRequest('GET', '/whatsapp/logs', { params })
}

// ── Envoi de vérification et renvoi ──────────────────────────────────────────

export type WhatsAppDelivery = {
  log_id: string | null
  recipient: string
  recipient_name: string
  status: WhatsAppLogStatus | string
  status_label: string
  error_message: string | null
}

export type WhatsAppTestResult = {
  ok: boolean
  queued: number
  detail: string
  deliveries: WhatsAppDelivery[]
}

/**
 * Cible d'un envoi de vérification : un numéro libre **ou** un membre du
 * Bureau. Les deux à la fois sont refusés en `422` — d'où l'union, qui rend
 * l'erreur impossible à écrire.
 */
export type WhatsAppTestTarget = { phone: string } | { member_id: number }

/**
 * Envoie un message de vérification. L'envoi est attendu dans la requête :
 * `detail` et `deliveries` portent le verdict réel du fournisseur. Le message
 * est rattaché à l'entité `whatsapp_test` — aucune opération métier n'est créée.
 */
export async function sendWhatsAppTest(target: WhatsAppTestTarget): Promise<WhatsAppTestResult> {
  return apiRequest('POST', '/whatsapp/test', target)
}

export type WhatsAppResendResult = {
  ok: boolean
  detail: string
  source_log_id: string
  delivery: WhatsAppDelivery | null
}

/**
 * Renvoie une ligne restée en échec. Le serveur recopie le message d'origine
 * mot pour mot dans une nouvelle ligne : la tentative ratée reste visible.
 * Seules les lignes WhatsApp en échec sont renvoyables.
 */
export async function resendWhatsAppLog(logId: string): Promise<WhatsAppResendResult> {
  return apiRequest('POST', `/whatsapp/logs/${logId}/resend`)
}
