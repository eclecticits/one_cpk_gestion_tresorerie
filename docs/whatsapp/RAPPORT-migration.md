# Rapport — agent MIGRATION (canal WhatsApp)

Livrables, tous sous `/home/claude/wa/` :

| Fichier | Nature |
|---|---|
| `backend/alembic/versions/20260823_whatsapp_notifs.py` | migration (nouveau) |
| `backend/app/models/system_settings.py` | modifié, additif |
| `backend/app/models/commission_member.py` | modifié, additif |
| `backend/app/db/session.py` | modifié, 2 lignes |
| `backend/alembic/env.py` | modifié, 1 ligne |

---

## 1. Révision et chaîne

* **Révision : `20260823_whatsapp_notifs`** — 24 caractères, sous la limite de 32 rappelée dans `AGENTS.md`.
* **`down_revision = "20260823_saas_invoicing"`.**

Tête vérifiée mécaniquement, pas sur parole : parsing des 230 fichiers de `backend/alembic/versions/`, calcul de `{révisions} − {révisions citées en down_revision}`. Sept candidats sortent, dont six sont en réalité absorbés par des migrations de fusion (`0006_merge_heads`, `20260723c_merge_heads`, `20260326_merge_org_theme_svc`, `20260509_tenant_strict_scope`). Le seul qu'aucun fichier ne cite est bien `20260823_saas_invoicing`. Après cette migration, la tête unique devient `20260823_whatsapp_notifs`.

## 2. Colonnes ajoutées

### `system_settings` — 12 colonnes, aucune suppression ni renommage

| Colonne | Type | Null | `server_default` |
|---|---|---|---|
| `whatsapp_enabled` | Boolean | NOT NULL | `false` |
| `whatsapp_notify_payments` | Boolean | NOT NULL | `false` |
| `whatsapp_notify_sorties` | Boolean | NOT NULL | `false` |
| `whatsapp_provider` | String(30) | NOT NULL | `'evolution'` |
| `whatsapp_api_key_encrypted` | **Text** | NOT NULL | `''` |
| `whatsapp_phone_number_id` | String(64) | NOT NULL | `''` |
| `whatsapp_business_account_id` | String(64) | NOT NULL | `''` |
| `whatsapp_sender` | String(40) | NOT NULL | `''` |
| `whatsapp_templates` | JSONB | NULL | — |
| `whatsapp_template_name` | String(120) | NOT NULL | `''` |
| `whatsapp_account_sid` | String(64) | NOT NULL | `''` |
| `whatsapp_graph_version` | String(10) | NOT NULL | `''` |

`whatsapp_api_url`, `whatsapp_api_key` et `whatsapp_agents` **restent** : trois sites d'appel les lisent encore (`requisitions.py:1966-1984`, `requisitions.py:2045-2063`, `encaissements.py:1637-1657`) et `whatsapp_agents` reste la liste de repli de `recipients.resolve_outflow_recipients`.

`whatsapp_api_key_encrypted` est en `Text` et non `String(255)` : mesuré sur la base d'essai, un secret de 16 caractères produit un jeton Fernet de 120. Au-delà de ~190 caractères de clé en clair, `String(255)` tronquerait — c'est-à-dire détruirait — le secret.

Défauts volontairement fermés (`whatsapp_enabled = false`, les deux `notify_* = false`) : une migration ne met pas un canal sortant en marche toute seule vers de vrais numéros.

### `commission_members` — 2 colonnes

| Colonne | Type | Null | `server_default` |
|---|---|---|---|
| `telephone` | String(50) | NULL | — |
| `notify_whatsapp` | Boolean | NOT NULL | `false` |

`server_default` sur le NOT NULL : la table n'est pas vide en production, l'`ALTER` échouerait sans lui.

### `notification_logs` — table créée

Conforme au contrat de `app/models/notification_log.py`, vérifié colonne par colonne par comparaison programmatique du `MetaData` du modèle avec le DDL de la migration : **0 colonne manquante, 0 en trop, 0 divergence de type ou de nullabilité**. Contrainte `uq_notification_logs_dedup_key` et les 5 index (`organisation_id`, `event_type`, `status`, `entity`, `org_created`) présents. FK `organisation_id → organisations.id ON DELETE CASCADE`.

## 3. Reprise de la clé API

`whatsapp_api_key` est aujourd'hui en clair et renvoyée telle quelle par `GET /admin/notification-settings` (`admin.py:269`). La migration la recopie chiffrée dans `whatsapp_api_key_encrypted` via `app.core.encryption.encrypt_secret`, puis vide la colonne en clair.

**Le piège évité.** `encrypt_secret` ne lève pas quand la clé maître manque : hors production il fabrique une clé Fernet **éphémère** (`encryption.py:73-80`). Chiffrer avec cette clé puis vider la colonne en clair détruirait définitivement le secret du tenant au premier redémarrage. La migration teste donc explicitement la présence de `AI_PROVIDER_ENCRYPTION_KEY` (`_master_key_available`) avant toute reprise :

* **clé maître absente** → aucune reprise, valeurs laissées en clair, `logger.warning` explicite. `settings_loader.resolve_api_key` retombe sur la colonne en clair : rien ne casse ;
* **échec de chiffrement sur un tenant** → `try/except` par ligne, la clé reste en clair, les autres tenants sont traités ;
* **rejeu** → la sélection ne prend que `whatsapp_api_key <> '' AND whatsapp_api_key_encrypted = ''`. Un second passage ne trouve rien. Un tenant sauté faute de clé maître est repris automatiquement au prochain `alembic upgrade` lancé avec la clé — comportement voulu.

`downgrade()` **déchiffre et restaure** les clés en clair avant de supprimer la colonne chiffrée. Sans cela, tout downgrade détruirait la clé de chaque tenant.

**Destinataires : rien n'est amorcé, rien n'est inventé.** `whatsapp_agents` n'est ni lu, ni copié, ni effacé — la migration n'y touche pas. Aucun numéro n'est fabriqué. `commission_members.telephone` naît à NULL et `notify_whatsapp` à `false` : l'opt-in est un geste humain.

## 4. Permissions semées

Quatre codes, description en français, `ON CONFLICT (code) DO UPDATE SET description` :

`treso.notifications.read` · `treso.notifications.update` · `treso.notifications.history` · `treso.notifications.test`

Rétro-accordés à **tout rôle détenant déjà `can_edit_settings`**, par la requête `_grant_from_sources` reprise mot pour mot de `20260822_treso_actions.py`. `can_edit_settings` est la garde effective actuelle de `GET/PUT /admin/notification-settings` (`admin.py:1146`, `:1164`) et du test de connexion (`:1241`) : personne ne perd un accès au déploiement. Le rôle `admin` reçoit aussi les quatre codes, par convention du dépôt (matrice de l'écran Rôles).

Source volontairement unique. `menu_settings` n'est **pas** dans la liste : l'y ajouter accorderait un droit à des rôles qui n'ont aujourd'hui aucun accès aux réglages de notification.

## 5. Enregistrement des modèles

`app/db/base.py` ne contient que `Base` et `app/models/__init__.py` est vide (2 octets, vérifié sur le poste) : **c'est `alembic/env.py` qui enregistre les modèles**, par imports explicites. `NotificationLog` y est donc ajouté — sans quoi Alembic ne verrait jamais la table.

* `backend/alembic/env.py` : `from app.models.notification_log import NotificationLog  # noqa: F401`.
* `backend/app/db/session.py` : import + `with_loader_criteria(NotificationLog, lambda cls: cls.organisation_id == tenant_id, include_aliases=True)`, inséré après `SystemEvent`. Deux lignes ajoutées, aucune autre touchée (fichier de 33 Ko).

## 6. Vérification effectuée

`python3 -m py_compile` passe sur les 6 fichiers Python. Au-delà, la migration a été **exécutée pour de vrai** sur un PostgreSQL 16 local, sur un schéma reproduisant les tables prérequises **peuplées** (3 organisations, 3 `system_settings` dont une sans clé, 3 membres de commission, 3 rôles) :

| Scénario | Résultat |
|---|---|
| `upgrade` sans clé maître | OK — clés laissées **en clair**, chiffré vide, `whatsapp_agents` intact |
| `upgrade` rejoué sans clé | OK — aucun effet de bord |
| `upgrade` rejoué **avec** clé | OK — clair vidé, chiffré posé (120 car.), org sans clé ignorée |
| déchiffrement `resolve_api_key` | OK — `'SECRET-KEY-ORG-1'` et `'SECRET-KEY-ORG-3'` retrouvés |
| `downgrade` | OK — clés **restaurées en clair**, 12+2 colonnes retirées, table supprimée, 4 permissions retirées, les 2 attributions préexistantes intactes |
| `upgrade` complet en un coup | OK |
| insertion ORM `NotificationLog` | OK, y compris `event_metadata` → colonne `metadata` |
| doublon sur `dedup_key` | **refusé par la contrainte** `uq_notification_logs_dedup_key` |
| `DELETE` d'une organisation | journal purgé par la CASCADE |
| rétro-attribution | `secretaire` (a `can_edit_settings`) et `admin` reçoivent les 4 ; `caissier` (n'a que `menu_settings`) ne reçoit **rien** |

## 7. Risques

1. **Le plus important — les trois sites d'appel hérités enverront avec une clé vide.** `requisitions.py:1984`, `requisitions.py:2063` et `encaissements.py:1657` passent `ns.whatsapp_api_key` directement à `send_whatsapp_message`. Une fois la reprise faite, cette colonne est vide : ces trois envois échoueront jusqu'à ce que les sites soient basculés sur le nouveau service, ou au minimum sur `settings_loader.resolve_api_key(ns)`. **C'est le point à coordonner avec l'agent qui touche les endpoints — sans lui, la migration provoque une régression fonctionnelle immédiate.** Idem pour `admin.py:268-270`, qui exposera une clé vide à l'écran de réglages.
2. **Précédence figée du chiffré.** `resolve_api_key` préfère `whatsapp_api_key_encrypted`. Si un admin ressaisit une clé via l'ancien endpoint (qui écrit en clair) alors qu'une clé chiffrée existe, la nouvelle valeur sera ignorée en silence, et un rejeu de la migration ne la reprendra pas non plus (filtre `encrypted = ''`). L'endpoint d'écriture doit écrire dans la colonne chiffrée.
3. **`consolidate_system_settings` ignore les 12 nouvelles colonnes.** `system_settings_service.py:44-57` fusionne les lignes doublons champ par champ sur une liste codée en dur. Un tenant avec plusieurs lignes `system_settings` perdrait sa configuration WhatsApp à la consolidation. Hors périmètre de la migration, mais à corriger.
4. **`AI_PROVIDER_ENCRYPTION_KEY` doit être posé avant le déploiement en production.** À défaut, `encryption.py` refuse le démarrage en prod (`is_production` → `RuntimeError`), et la migration se contentera de journaliser sans rien reprendre.
5. **Chargement d'`app.core.encryption` depuis une migration.** Précédent existant (`20260822_treso_actions` importe `app.modules.secretariat.permissions`), et les deux imports sont dans un `try/except`, mais cela couple la migration au code applicatif : un `alembic upgrade` hors du conteneur, sans `cryptography`, sautera la reprise en la journalisant.
6. **`whatsapp_provider` en `String(30)`** : suffisant pour `evolution` / `meta` / `twilio`. Un identifiant de fournisseur plus long exigerait un `ALTER`.
7. **Rétro-attribution étroite par choix.** Un rôle qui accède aux réglages via `menu_settings` sans détenir `can_edit_settings` n'obtient aucun des quatre codes. C'est cohérent avec la garde actuelle, mais à revoir si l'écran Notifications doit être lisible plus largement.
