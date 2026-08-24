# RAPPORT — Routeur d'administration WhatsApp

Livré sous `/home/claude/wa/`, en miroir de l'arborescence du projet :

| Fichier | Nature |
|---|---|
| `backend/app/schemas/whatsapp.py` | Schémas Pydantic v2 (nouveau) |
| `backend/app/api/v1/endpoints/whatsapp.py` | Routeur (nouveau) |
| `backend/app/api/v1/router.py` | Montage — modification chirurgicale, **5 lignes ajoutées, 0 modifiée** |

Rien n'a été touché sous `app/services/notifications/` ni dans
`app/models/notification_log.py` : ils sont consommés tels quels.

---

## 1. Endpoints

Préfixe `/api/v1/whatsapp`, tag `whatsapp`. Toutes les routes sont
tenant-scopées par `Depends(get_current_tenant_id)` et filtrent explicitement
sur l'organisation courante.

| Méthode | Chemin | Permission | Rôle |
|---|---|---|---|
| `GET` | `/whatsapp/settings` | `treso.notifications.read` | Réglages publics, fournisseurs, gabarits par défaut, variables, événements |
| `PUT` | `/whatsapp/settings` | `treso.notifications.update` | Activation, familles, fournisseur, URL, émetteur, identifiants, clé API (chiffrée) |
| `GET` | `/whatsapp/recipients` | `treso.notifications.read` | Membres du Bureau : nom, fonction, numéro, opt-in, statut |
| `PATCH` | `/whatsapp/recipients/{member_id}` | `treso.notifications.update` | Numéro et opt-in d'un membre |
| `GET` | `/whatsapp/templates` | `treso.notifications.read` | Gabarit effectif par événement + défaut + variables |
| `PUT` | `/whatsapp/templates` | `treso.notifications.update` | Surcharges, validées par `validate_template` |
| `GET` | `/whatsapp/logs` | `treso.notifications.read` **ou** `.history` | Historique paginé et filtrable |
| `POST` | `/whatsapp/test` | `treso.notifications.test` | Envoi de vérification (numéro libre **ou** membre) |
| `POST` | `/whatsapp/logs/{log_id}/resend` | `treso.notifications.test` | Renvoi d'une ligne en échec |

**Filtres de `GET /whatsapp/logs`** : `status` (`PENDING`/`SENT`/`FAILED`/`SKIPPED`),
`channel`, `event_type`, `entity_type`, `entity_id`, `date_debut`, `date_fin`
(`2026-08-01` ou ISO complet), `limit` (1–500, défaut 50), `offset`.

### Ce que le secret ne fait jamais

La clé API entre par `PUT /whatsapp/settings`, part chez `encrypt_secret`, et
ne ressort **d'aucune route, sous aucune forme** — pas même masquée, pas même
pour un super-admin. `has_api_key: bool` est la seule information rendue à son
sujet. Les schémas de sortie ne portent aucun champ susceptible de la contenir ;
`describe_whatsapp_settings` reste l'unique constructeur de la vue publique.

Corollaire tenu à l'écriture : poser une nouvelle clé **vide aussi** l'ancienne
colonne `whatsapp_api_key` en clair, et `clear_api_key` vide les deux. Sans
cela, le repli de `resolve_api_key` sur la colonne héritée ressusciterait une
clé qu'on vient de supprimer.

---

## 2. Exemples de charge utile

### 2.1 `GET /whatsapp/settings` → `200`

```json
{
  "settings": {
    "enabled": true,
    "notify_payments": true,
    "notify_sorties": true,
    "provider": "evolution",
    "provider_label": "Evolution API / Baileys (auto-hébergé)",
    "api_url": "https://evo.exemple.org/message/sendText/onec",
    "sender": "",
    "phone_number_id": "",
    "business_account_id": "",
    "has_api_key": true,
    "templates": {
      "FUND_OUTFLOW": "{{organisation}} — SORTIE DE FONDS\n\nRéférence : {{reference}}\nMontant : {{montant}} {{devise}}"
    }
  },
  "providers": [
    { "value": "evolution", "label": "Evolution API / Baileys (auto-hébergé)" },
    { "value": "meta", "label": "Meta WhatsApp Business Cloud" },
    { "value": "twilio", "label": "Twilio WhatsApp" }
  ],
  "default_templates": { "FUND_OUTFLOW": "{{organisation}} — SORTIE DE FONDS\n…" },
  "template_variables": {
    "organisation": "Nom de l'organisation",
    "reference": "Référence de la pièce",
    "montant": "Montant formaté"
  },
  "events": [
    { "value": "PAYMENT_RECEIVED", "label": "Paiement reçu", "family": "payments" },
    { "value": "FUND_OUTFLOW", "label": "Sortie de fonds", "family": "sorties" },
    { "value": "TEST_MESSAGE", "label": "Message de test", "family": "service" }
  ],
  "warning": ""
}
```

### 2.2 `PUT /whatsapp/settings`

Entrée — seuls les champs transmis sont appliqués (`exclude_unset`) :

```json
{
  "enabled": true,
  "notify_sorties": true,
  "provider": "evolution",
  "api_url": "https://evo.exemple.org/message/sendText/onec",
  "sender": "",
  "api_key": "B7c1e9…f2"
}
```

Sortie — la même enveloppe que `GET`, relue après enregistrement. `warning`
reprend le motif de `WhatsAppProvider.is_configured()` quand le canal ne
pourrait pas émettre :

```json
{
  "settings": { "enabled": true, "has_api_key": true, "…": "…" },
  "warning": "Clé API Evolution non renseignée."
}
```

Sentinelle de la clé (voir écart n° 2) :

| Corps envoyé | Effet sur la clé |
|---|---|
| `api_key` absent | inchangée |
| `"api_key": ""` | inchangée |
| `"api_key": "B7c1…"` | remplacée, chiffrée |
| `"clear_api_key": true` | supprimée (chiffrée **et** héritée en clair) |

### 2.3 `POST /whatsapp/test`

Entrée — l'un **ou** l'autre, jamais les deux (refus `422` sinon) :

```json
{ "member_id": 12 }
```
```json
{ "phone": "0810 123 456" }
```

Sortie `200` — l'envoi est attendu dans la requête, le verdict est donc réel :

```json
{
  "ok": true,
  "queued": 1,
  "detail": "Message de test envoyé.",
  "deliveries": [
    {
      "log_id": "6b1f2c74-6b0e-4c2f-9a11-0d5b2e7c9a31",
      "recipient": "+243 810 123 456",
      "recipient_name": "Jeanne Kabeya",
      "status": "SENT",
      "status_label": "Envoyé",
      "error_message": null
    }
  ]
}
```

En échec, `ok: false` et `detail` porte le motif remonté par le fournisseur
(`"HTTP 401 — {\"message\":\"Unauthorized\"}"`). Le canal désactivé est refusé
en amont par un `400` explicite, parce que `queue_whatsapp` ne créerait alors
aucune ligne et que l'écran ne saurait pas distinguer « désactivé » de « panne ».

### 2.4 `GET /whatsapp/logs?status=FAILED&limit=2` (extrait)

```json
{
  "items": [
    {
      "id": "6b1f2c74-…",
      "channel": "WHATSAPP",
      "event_type": "FUND_OUTFLOW",
      "event_label": "Sortie de fonds",
      "entity_type": "sortie_fonds",
      "entity_id": "1841",
      "recipient": "+243 ••• ••• 456",
      "recipient_name": "Jeanne Kabeya",
      "recipient_role": "Trésorière",
      "status": "FAILED",
      "status_label": "Échec",
      "provider": "evolution",
      "error_message": "HTTP 401 — {\"message\":\"Unauthorized\"}",
      "attempts": 1,
      "created_at": "2026-08-23T09:12:44.512Z",
      "sent_at": null
    }
  ],
  "total": 3,
  "limit": 2,
  "offset": 0,
  "masked": true
}
```

`masked: true` dit à l'écran **pourquoi** les numéros sont voilés : l'appelant
n'a pas `treso.notifications.history`. Avec cette permission, le même champ
vaut `+243 810 123 456` et `masked: false`.

### 2.5 `PATCH /whatsapp/recipients/{member_id}` et `PUT /whatsapp/templates`

```json
{ "telephone": "0810 123 456", "notify_whatsapp": true }
```
→ `{"id": 12, "full_name": "Jeanne Kabeya", "function": "Trésorière",
"phone": "243810123456", "phone_display": "+243 810 123 456",
"notify_whatsapp": true, "status": "ready", "status_label": "Prêt"}`

Le numéro est **stocké normalisé** (E.164 sans « + »), via `normalize_phone` :
un numéro rangé sous deux formes se dé-duplique mal. `"telephone": ""` retire le
numéro ; une saisie inexploitable est refusée en `400`.

```json
{ "templates": { "FUND_OUTFLOW": "{{organisation}} — SORTIE\nRéf. {{reference}}", "PAYMENT_REMINDER": "" } }
```
→ `{"ok": true, "updated": ["FUND_OUTFLOW"], "reset": ["PAYMENT_REMINDER"], "warnings": {}}`

Valeur vide = retour au gabarit par défaut. Un refus de `validate_template`
(gabarit vide, > 4 000 caractères) donne `400` ; un simple avertissement
(variable inconnue) n'empêche pas l'enregistrement et remonte dans `warnings`.

---

## 3. Écarts par rapport à la spécification

### 3.1 `GET /whatsapp/logs` accepte `read` **ou** `history` — et non `history` seul

La spécification demande `treso.notifications.history` pour les journaux, et
demande aussi qu'un numéro « affiché dans les journaux à un utilisateur n'ayant
que `read` » soit masqué. Les deux ne peuvent pas tenir ensemble : avec un garde
`has_permission("treso.notifications.history")`, l'utilisateur qui n'a que
`read` n'atteint jamais la route, et la règle de masquage ne s'applique jamais.

Retenu : garde `has_any_permission(["treso.notifications.read",
"treso.notifications.history"])`, et `history` décide de ce qu'on voit —
numéros en clair avec, masqués par `mask_phone` sans. C'est la lecture qui rend
les deux exigences vraies en même temps.

### 3.2 Sentinelle de la clé API : `clear_api_key` ajouté

La consigne dit « champ absent **ou vide** = ne pas changer », ce que dit aussi
la docstring de `AIProviderConfigUpdate.api_key` (« Laisser vide pour ne pas
modifier la clé. »). Mais le *code* d'`ai_providers.py` traite `""` comme un
effacement (`encrypt_secret(payload.api_key) if payload.api_key else None`).

Retenu : la sémantique demandée (absent ou vide = inchangée), plus un drapeau
explicite `clear_api_key: bool` pour rendre la suppression possible. Sans lui,
la suppression deviendrait impossible ; sans la sentinelle, un formulaire dont
le champ mot de passe n'est jamais pré-rempli effacerait la clé à la première
sauvegarde — l'accident que la convention existe précisément pour éviter.

### 3.3 Le renvoi **recopie** la ligne au lieu de la rejouer

`notify_whatsapp` rend le message à partir du gabarit et des variables. Or les
variables d'origine ne sont pas stockées dans `notification_logs` (`metadata`
n'est pas alimenté par `queue_whatsapp`) : un renvoi qui repasserait par
`notify_whatsapp` produirait un message aux trous vides — référence, montant et
bénéficiaire perdus.

Retenu : insertion d'une **nouvelle ligne** qui recopie `message`, `recipient`
et l'entité d'origine, avec un `dedup_key` calculé par `build_dedup_key(...,
nonce=uuid4().hex)` — le `nonce` demandé —, puis `deliver_pending`. Le message
part mot pour mot, et la tentative ratée reste visible dans l'historique.
Seules les lignes `FAILED` du canal `WHATSAPP` sont renvoyables (`409` / `400`
sinon).

### 3.4 `POST /whatsapp/test` et `/resend` envoient **dans la requête**

`notify_whatsapp(db, None, …)` : `background_tasks=None` fait attendre la remise
au lieu de la programmer. Un test dont on n'apprend le sort qu'en rafraîchissant
l'historique ne teste rien d'utile ; la réponse porte donc le statut réel et le
motif d'échec. Coût assumé : la requête dure le temps de l'appel fournisseur
(20 s de plafond côté Evolution). Les envois métier, eux, restent en tâche de
fond — ce routeur ne change rien à leur chemin.

### 3.5 Ajouts non demandés, tous en lecture

- `warning` dans l'enveloppe des réglages : reprend le motif de
  `is_configured()` (« Clé API Evolution non renseignée. »), pour que l'écran
  affiche la cause plutôt qu'un silence. Ne contient jamais la clé.
- `events` dans `GET /whatsapp/settings` : l'écran d'activation a besoin de
  savoir quel événement dépend de quelle case (`family`).
- `masked` dans la page de journal, `status`/`status_label` sur les
  destinataires (`ready` / `no_phone` / `opted_out`).

### 3.6 Non exposé

`whatsapp_template_name`, `whatsapp_account_sid`, `whatsapp_graph_version`
existent en colonnes et alimentent `ProviderConfig.extra`, mais ne figurent pas
dans `describe_whatsapp_settings`. Les mettre en écriture seule rendrait `GET`
et `PUT` asymétriques — un champ qu'on enregistre sans jamais le relire. Ils
restent réglables par le chemin existant.

### 3.7 Masquage limité aux journaux

Appliqué à la lettre : `GET /whatsapp/recipients` montre les numéros du Bureau
en clair à qui possède `treso.notifications.read`. C'est l'écran de
configuration — on n'y vérifie pas un numéro qu'on ne voit pas. Le masquage
protège l'historique, qui contient aussi des numéros de clients et d'experts.
À rediscuter si le produit veut une lecture « aveugle » de la configuration.

### 3.8 Duplication assumée d'un helper

`_member_function_label` reprend `recipients._function_label` (libellé du
référentiel → titre libre → rôle). Cette fonction est privée au service, que je
n'avais pas à modifier ; la recopier était préférable à l'importer par son nom
souligné.

---

## 4. Point d'attention — à traiter hors de ce lot

**Les quatre permissions `treso.notifications.read | .update | .history | .test`
n'existent pas encore en base.** Elles ne figurent ni dans
`app/core/permissions.py` (elles n'ont pas à y être : `resolve_permission_code`
les laisse passer telles quelles), ni dans `frontend/src/data/permissionTree.ts`,
ni dans les migrations qui sèment la table `permissions`.

Conséquence immédiate : `has_permission` court-circuite `admin` et
`super_admin`, donc **l'écran fonctionnera pour eux et pour eux seuls**. Tout
autre rôle recevra `403 Privilèges insuffisants` tant qu'une migration Alembic
n'aura pas semé les quatre codes et qu'ils n'auront pas été rattachés à un rôle.

Il faut donc, en complément : une migration semant les quatre `Permission`, et
quatre entrées dans `permissionTree.ts` (menu « Paramètres » ou un menu
« Notifications » dédié), avec `isNew: true`.

## 5. Vérification

`python3 -m py_compile` passe sur les trois fichiers produits ; `pyflakes` ne
signale ni nom indéfini ni import inutilisé. Le diff de `router.py` par rapport
à l'original tient en cinq lignes ajoutées (un import, trois lignes de
commentaire, un `include_router`) — aucune ligne existante n'est modifiée.
