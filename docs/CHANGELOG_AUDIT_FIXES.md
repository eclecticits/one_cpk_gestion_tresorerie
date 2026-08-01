# Changelog — correctifs post-audit (ONEC Smart)

**Période :** 23–30/07/2026. **Contexte :** remédiation suite à l'audit premium (`AUDIT_PREMIUM_2026-07-23.md`).

> ⚠️ **Important :** l'environnement d'exécution (sandbox) étant indisponible sur la fin, une partie des modifications **n'a pas pu être compilée/testée automatiquement** (revue manuelle uniquement). Avant déploiement : lancer `pytest` (backend), `npm run build` (frontend), et les tests manuels listés plus bas.

---

## 1. Backend — sécurité & permissions

| Réf | Fichier | Changement | À tester |
|---|---|---|---|
| BE-01 | `api/v1/endpoints/audit.py` | Ajout de la permission `sorties_fonds` sur `GET /audit/sortie` (était seulement authentifié/scopé). | Un user sans `sorties_fonds` reçoit 403 ; un user autorisé voit la sortie. |
| AI-03 | `api/v1/endpoints/ai.py` | Garde `has_any_permission` sur `/classify-expense` et `/classify-expense-batch`. | Un user sans permission finance reçoit 403. |
| AI-01 | `modules/secretariat/services/manager_agent_agentor.py` | Ajout de `generer_synthese_document` au mapping permission↔outil. | L'agent refuse cet outil sans `secretariat.generate_document_summary`. |
| AI-02 | idem | `_sanitize_history` : n'accepte que `role user/assistant`, rejette `system`/`tool` forgés. | Historique client avec un faux message `system` ignoré. |
| SEC-04 | `core/limiter.py` + `core/config.py` | Clé de rate-limit basée sur l'IP réelle via `TRUSTED_PROXY_HOPS` (défaut 1). | Brute-force login limité même en variant `X-Forwarded-For`. |
| SEC-05 | `core/config.py` | `serve_uploads_publicly` défaut `False`. | `/uploads` non servi publiquement sans override. |
| AI-04 | `core/encryption.py` | En prod, échec au démarrage si `AI_PROVIDER_ENCRYPTION_KEY` absente/invalide (plus de clé éphémère). | Démarrage prod sans clé → erreur claire. |
| BE-02 | `api/v1/endpoints/auth.py` | `send_security_code` (OTP) déplacé en `BackgroundTasks`. | Envoi OTP non bloquant ; l'e-mail arrive toujours. |
| SEC-03 | `api/deps.py`, `denominations.py`, `imports_history.py` | Nouvelle dépendance `require_national_admin` ; écritures dénominations + list/delete imports réservés à l'admin national (super_admin ou org « CN »). | Un admin d'un autre tenant reçoit 403 ; l'admin national passe. |
| AI-05 | `services/mailer.py` + `core/config.py` | TLS SMTP durci (STARTTLS/SMTPS + vérif certificat), fail-closed via `SMTP_REQUIRE_TLS` (défaut True). | Envoi OK en TLS ; refus si serveur sans STARTTLS et `SMTP_REQUIRE_TLS=true`. |
| AI-07 | `services/ai_chat.py`, `services/ai_batch_service.py` | Routage IA via `get_ai_service_for_org` (provider par organisation). | Un provider configuré par tenant est bien utilisé. |
| CONF-02 | `services/oauth_service.py`, `services/gmail_service.py`, `core/config.py` | Scope Google par défaut = `gmail.compose` seul (readonly retiré) ; lectures de boîte en erreur explicite si non accordé. | Nouveau consentement ne demande plus readonly ; lecture boîte → 403 explicite. |
| CONF (OAuth) | `services/oauth_service.py` | Révocation Google (`/revoke`) à la déconnexion, best-effort. | Après déconnexion, le jeton n'est plus valide côté Google. |

## 2. Frontend — conformité

| Fichier | Changement | À tester |
|---|---|---|
| `pages/Signup.tsx` | Case de consentement obligatoire (CGU + confidentialité) à l'étape 2 ; blocage de la création tant que non cochée. | Impossible de continuer sans cocher ; liens ouvrent les documents. |
| `components/AiContentBanner.tsx` (nouveau) | Bandeau réutilisable « contenu généré par IA ». | Rendu correct. |
| `pages/SecretariatPage.tsx` | Bandeau IA en tête du hub secrétariat. | Visible sur toutes les vues agents. |
| `components/SecretariatAgentChat.tsx` | Bandeau IA compact en tête du chat. | Visible dans le chat. |

## 3. Configuration

- `backend/.env.example` et `.env.example` (racine) : ajout/doc de `TRUSTED_PROXY_HOPS`, `GOOGLE_OAUTH_SCOPES`, `SMTP_REQUIRE_TLS` ; `SERVE_UPLOADS_PUBLICLY=false` ; `JWT_SECRET` en placeholder à générer.

## 4. À valider / appliquer séparément (ne PAS auto-exécuter)

- **Migration DB** `docs/pending_migrations/20260726_db_hardening_REVIEW.py` : CHECK `>= 0` (budget/réquisitions), `transactions.amount` → Numeric, immuabilité `audit_logs`. Volontairement **hors** `alembic/versions/`. Procédure : sauvegarde → pré-checks (dans le fichier) → déplacer dans `alembic/versions/` → `alembic upgrade head`.

## 5. Constats d'audit vérifiés comme DÉJÀ traités (aucune action)

DB-01 (double-paiement), DB-02 (verrou budget), DB-03 (unicité caisse), DB-04 (têtes Alembic — fusionnées par `20260723c_merge_heads`), DB-06 partiel (CHECK caisse/comptes via `20260723a_finance_guards`), SEC-02 (JWT_SECRET fort), OPS-01/02 (Docker : `.env` exclu, non-root).

## 6. Reste à faire (hors code déjà livré)

- **SEC-01 (critique, serveur/git) :** révoquer la clé SSH `onec.pem` et purger l'historique git (`git filter-repo` + push forcé).
- **FE-03 :** `cd frontend && npm rm xlsx && npm i --save https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz && npm run build`.
- **Documents légaux :** compléter RCCM/ID.NAT/NIF/autorité ; **héberger** CGU + confidentialité aux URLs `onec-rdc.org/cgu` et `/confidentialite` (liées depuis le signup) ; créer `support@` et `security@onec-rdc.org`.
- **RGPD (spec `docs/legal/RGPD_EXPORT_SUPPRESSION.md`) :** implémenter l'export (sûr) puis l'anonymisation — **en attente de 2 décisions** : (1) durée légale de conservation des écritures (RDC) ; (2) suppression self-service ou par admin.
- **Consentement horodaté** au signup à enregistrer côté backend (preuve RGPD).
- **Compilation/tests** de l'ensemble des changements ci-dessus.
