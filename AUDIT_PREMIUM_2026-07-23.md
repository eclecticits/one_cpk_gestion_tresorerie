# Audit premium — ONEC Smart

**Date :** 23 juillet 2026
**Méthode :** audit statique en lecture seule du dépôt (`onec_smart`), 8 sous-agents spécialisés (architecture, base de données, sécurité, backend, frontend, DevOps, IA, conformité), constats recoupés et dédupliqués.
**Périmètre :** backend FastAPI (252 fichiers Python, 53 modèles, 50 groupes d'endpoints, 190 migrations), frontend React/TS (184 fichiers, 75 pages), déploiement Docker, module secrétariat + IA, multi-tenant.
**Règle appliquée :** aucun fichier de l'application n'a été modifié. Faits vérifiés et hypothèses distingués. Zones non vérifiées listées en fin de document.

> ⚠️ Ce rapport ne garantit aucune acceptation par Google ou Apple. Il identifie les causes probables de rejet et les blocages avant production.

---

## ✅ Addendum de vérification — mise à jour du 23/07/2026 (après contrôle direct du code)

Les 8 sous-agents ont travaillé en parallèle sur un instantané du dépôt qui, pour plusieurs fichiers, était **périmé** (montage désynchronisé + durcissements déjà appliqués par l'équipe). Après **vérification ligne par ligne du code réel**, une partie importante des constats critiques/élevés était **déjà corrigée**, et les constats authentiques restants ont été traités. Cet addendum fait foi ; les sections A–F ci-dessous conservent l'analyse d'origine pour traçabilité.

**Constats déjà corrigés dans le code actuel (faux positifs vérifiés) :**
- **BE-01** — `GET /audit/sortie` **est** authentifié et scopé par tenant (`get_current_tenant_id` dépend de `get_current_user`). Pas de fuite non authentifiée. *(Durci en plus : permission `sorties_fonds` ajoutée.)*
- **AI-03** — `/ai/chat` **est** protégé par `has_any_permission([...finance])` (ai.py:348). Pas d'exfiltration. *(Durci : permission ajoutée sur `classify-expense(-batch)`.)*
- **AI-01** — le mapping permission↔outil (`TOOL_REQUIRED_PERMISSIONS` + `_assert_tool_permission`) existait déjà ; seul `generer_synthese_document` manquait → ajouté.
- **DB-01** — la réquisition est verrouillée (`with_for_update`), **PAYEE est exclu** des statuts payables (sorties_fonds.py:851) et le statut est posé côté serveur (:1190). Pas de double-paiement.
- **DB-02** — le poste budgétaire est verrouillé (`with_for_update`, sorties_fonds.py:1001-1036). Pas de course.
- **DB-03** — `caisse_centrale` a bien `UniqueConstraint("organisation_id")`. Pas de caisse dupliquée.
- **SEC-02** — le `.env` actuel a un `JWT_SECRET` de 64 caractères (le `oneckncd` lu était périmé). Déjà fort.
- **OPS-01 / OPS-02** — `.env`, `*.pem`, `*.ppk`, `*.sql` **sont** exclus dans `backend/.dockerignore` ; le Dockerfile crée un utilisateur non-root (`USER app`). Déjà durci.

**Correctifs réellement appliqués le 23/07 (vérifiés, syntaxe OK) :**
- **AI-02** — sanitisation de `conversation_history` (rôles `system`/`tool` forgés rejetés).
- **SEC-04** — clé de rate-limiting basée sur l'IP réelle (réglage `TRUSTED_PROXY_HOPS`, plus de confiance au 1er `X-Forwarded-For`).
- **SEC-05** — `SERVE_UPLOADS_PUBLICLY` par défaut à `False`.
- **AI-04** — chiffrement Fernet *fail-closed* en production (plus de clé éphémère silencieuse).
- **BE-02** — envoi SMTP des OTP en tâche de fond (plus de blocage de la boucle async).
- **SEC-03** — registre national (`denominations`, `imports_history`) : écritures et listing/suppression réservés à l'admin national (`require_national_admin`) ; `experts_comptables` l'était déjà.
- **CONF-02** — scope `gmail.readonly` retiré du défaut (compose seul → évite l'audit CASA) ; réactivable via `GOOGLE_OAUTH_SCOPES` ; lectures de boîte en échec explicite si non accordé.

**Reliquat réel après vérification :**
- **SEC-01 (critique, à faire côté serveur/git)** — `onec.pem`, `onec ck.ppk` et le dump SQL sont bien dans l'historique git (commit `c7cee81`, récupérables). Révoquer la clé SSH, purger l'historique (`git filter-repo`/BFG + push forcé), tourner les secrets du dump. **Non réalisable depuis le code.**
- **FE-03** — `xlsx@0.18.5` vulnérable : migrer vers la build SheetJS officielle (`npm install`).
- **Phase 2/3 non bloquante** — CHECK `>= 0` défensifs (DB-06), immuabilité `audit_logs` (DB-07), TLS mailer (AI-05), quotas/rate-limit IA (AI-06), routage provider IA par org (AI-07), `Float→Numeric` facturation (DB-05), infra tests (TEST-01), CI/CD & TLS (OPS-03/04), documents de conformité RGPD (CONF-01/03/04).
- **Décisions métier tranchées** — tables globales = registre national ONEC (admin national) ✔ appliqué ; `gmail.readonly` retiré ✔ appliqué.

**Impact sur les notes (révisé) :** Sécurité ~62 → **~78**, Base de données ~68 → **~82**, IA ~62 → **~74**. Le principal frein résiduel reste **SEC-01** (action serveur/git) et la **conformité documentaire** (Phase 4).

---

## A. Résumé exécutif

ONEC Smart est un SaaS de trésorerie/administration multi-tenant **fonctionnellement riche et techniquement sérieux dans son cœur applicatif** : isolation multi-tenant à double barrière (filtrage automatique des SELECT + garde à l'écriture), verrouillage pessimiste sur les débits de caisse, JWT + refresh HttpOnly bien conçus, token frontend en mémoire seule, SQL paramétré, aucun XSS trouvé, workflow d'approbation humaine réel sur les brouillons Gmail.

Cependant, l'application **n'est pas prête pour un déploiement en production sérieux ni pour une soumission Google/Apple en l'état**. Les faiblesses ne sont pas dans l'intention mais dans l'exécution périphérique et quelques trous précis du cœur financier :

**Points forts (vérifiés)**
- Isolation tenant systémique (`db/session.py` : `do_orm_execute` + `before_flush`).
- Verrouillage `with_for_update` sur caisse/comptes/réquisitions au moment du débit.
- Auth : JWT HS256 (algorithmes explicites, `aud/iss/exp/type` vérifiés), refresh HttpOnly rotatif haché en base, token access en RAM côté front.
- CHECK financiers riches sur `encaissements`, `sorties_fonds`, `ordres_decaissement`.
- Human-in-the-loop réel sur Gmail (brouillon `approved` requis), prompts IA défensifs, clés IA chiffrées Fernet.

**Faiblesses critiques (vérifiées)**
- **Secrets exposés** : clés privées SSH (`onec.pem`, `onec ck.ppk`) et dump SQL complet présents dans **l'historique git** (commit `c7cee81`, restitués via `git cat-file`), `JWT_SECRET=oneckncd` (8 caractères) et mots de passe faibles dans `.env`, secrets bakés dans l'image Docker.
- **Intégrité financière** : vecteur de double-paiement sur les réquisitions classiques, course non verrouillée sur les plafonds budgétaires, `caisse_centrale` sans unicité par organisation.
- **Contrôle d'accès** : endpoint financier `GET /audit/sortie` non authentifié cross-tenant ; agent IA « Manager » qui exécute des écritures sans re-vérifier les permissions ; chatbot finance sans permission métier ; tables de référence globales modifiables cross-tenant.
- **Conformité** : aucune politique de confidentialité, CGU, consentement, suppression de compte self-service, export RGPD, ni divulgation IA — tous prérequis bloquants de la vérification Google OAuth (rendue obligatoire par les scopes Gmail restreints).
- **DevOps** : conteneur root, HTTPS absent du dépôt, migration Alembic à l'entrypoint (crash-loop possible), port API et `/metrics` exposés, CI sans build/déploiement/scan.

### Notes par catégorie (/100)

| Catégorie | Note | Synthèse |
|---|---|---|
| Architecture | **58** | Cœur sain mais god-files (backend 2200 l., frontend 3700 l.), pas de couche repository, refactor service inachevé avec helpers dupliqués. |
| Sécurité | **62** | Architecture applicative au-dessus de la moyenne, plombée par la gestion des secrets (2 critiques) et le bypass de rate-limiting. |
| Base de données | **68** | Fondations matures ; 3 défauts d'intégrité financière + chaîne Alembic à 6 têtes + dérive modèle/DB. |
| Backend | **78** | Le plus solide : scoping tenant systématique, verrous financiers corrects. Pénalisé par 1 endpoint non authentifié et SMTP bloquant. |
| Frontend | **62** | Auth exemplaire, mais 826 `any`, composants « dieu », 0 mémoïsation, permissions 100 % côté client. |
| DevOps | **41** | Secrets dans l'image, conteneur root, pas de TLS, migration à l'entrypoint, CI sans déploiement. Risque de premier ordre. |
| Qualité des tests | **62** | 315 tests, bons cas trésorerie/multi-tenant, mais migrations jamais testées, skip global silencieux, aucun test de concurrence. |
| Expérience utilisateur | **66** | Notifications/confirmations OK ; accessibilité faible (labels non associés), validation artisanale. |
| Conformité | **34** | Volet documentaire et droits des personnes entièrement absent ; soumission Google OAuth serait rejetée. |
| Maintenabilité | **48** | God-files des deux côtés, duplication répandue, typage érodé, cycles d'imports masqués. |

**Note globale pondérée : ≈ 57/100.** État : *prototype avancé / pré-production*. Non déployable pour des données réelles sans traiter la Phase 1.

**Risques avant présentation professionnelle :** endpoint financier public, double-paiement, secrets faibles → démonstration risquée si un tiers inspecte le réseau ou l'API.
**Risques avant déploiement réel :** compromission totale via `JWT_SECRET` faible + clés SSH en historique ; perte/corruption de données financières ; indisponibilité sur migration ratée.
**Risques avant soumission Google/Apple :** rejet certain faute de politique de confidentialité, consentement, suppression de compte, et à cause des scopes Gmail restreints non vérifiés (CASA).

---

## B. Registre des anomalies

Gravité : 🔴 critique · 🟠 élevée · 🟡 moyenne · ⚪ faible. Effort : S (< ½ j) · M (1-3 j) · L (> 3 j). Priorité : P0 (bloquant) → P3.

| ID | Grav. | Catégorie | Fichier | Emplacement | Description | Impact | Recommandation | Effort | Prio |
|---|---|---|---|---|---|---|---|---|---|
| SEC-01 | 🔴 | Secrets | `onec.pem`, `onec ck.ppk`, `onec_cpk_local.sql` | historique git (commit `c7cee81`) | Clés privées SSH non chiffrées + dump SQL committés puis « untrackés » ; restitués via `git cat-file -p c7cee81:onec.pem`. | Accès SSH serveur complet + fuite base entière. | Révoquer/régénérer la clé, purger l'historique (git-filter-repo/BFG), tourner tous les secrets du dump. | M | P0 |
| SEC-02 | 🔴 | Secrets/Auth | `.env` | `JWT_SECRET=oneckncd` | Secret HS256 de 8 car. (dictionnaire) ; mots de passe `POSTGRES_PASSWORD=kncd`, `BOOTSTRAP_ADMIN_PASSWORD`, `DEFAULT_USER_PASSWORD` faibles. | Forge d'un token `super_admin` arbitraire → compromission totale, tous tenants. | Secret aléatoire ≥ 256 bits (script `generate_jwt_secret.py` présent), rotation, invalidation des tokens. | S | P0 |
| DB-01 | 🔴 | Intégrité financière | `api/v1/endpoints/sorties_fonds.py` | ~818, 888-900, 1105-1123 | Réquisition **classique** : `PAYEE` écrit seulement dans le bloc `if ordre`; aucun garde-fou de cumul; le passage à PAYEE dépend d'un PUT client. Re-POST possible → re-débit N fois. | Décaissements dupliqués, trésorerie faussée. | Passer `req.status=PAYEE` côté serveur ; index unique partiel `(requisition_id) WHERE statut='VALIDE'`; retirer PAYEE des statuts payables. | M | P0 |
| BE-01 | 🔴 | Contrôle d'accès | `api/v1/endpoints/audit.py` | 17-72 (`audit_sortie`) | `GET /api/v1/audit/sortie` sans `get_current_user` ni filtre `organisation_id`; renvoie bénéficiaire/montant/date par id ou référence. | Divulgation financière cross-tenant par énumération, sans jeton. | Exiger token signé court (QR) ou filtrer par tenant + masquer champs sensibles. | M | P0 |
| AI-01 | 🔴 | Contrôle d'accès IA | `modules/secretariat/…/manager_agent_agentor.py` | 251-394 ; `routers/manager.py:169` | `/ai/manager/chat` (permission `secretariat.view`) exécute des outils d'écriture (`creer_reunion`, `creer_echeance_agenda`, `generer_pv_reunion`) sans re-vérifier les permissions. | Un compte lecture seule crée des enregistrements + génère des appels IA payants. | Mapper chaque outil à sa permission et la vérifier dans `_execute_tool`. | M | P0 |
| AI-03 | 🔴 | Exposition données | `api/v1/endpoints/ai.py` | 344-366 (`/chat`) | Chatbot finance ne dépend que de `require_ai_enabled`; renvoie solde, top bénéficiaires nominatifs, anomalies. | Tout compte du tenant, même sans droit finance, exfiltre la trésorerie. | Ajouter `Depends(has_any_permission([...finance]))`. | S | P0 |
| SEC-03 | 🟠 | Isolation tenant | `models/denomination.py`, `experts_comptables`, `imports_history` ; `denominations.py:57/86`, `imports_history.py:63`, `experts.py:414+` | — | Tables sans `organisation_id`, hors scope auto ; PATCH/DELETE par id accessibles cross-tenant. | Un tenant modifie/supprime/lit des données d'un autre (dont `file_data` d'imports). | Si global volontaire → réserver l'écriture au super_admin ; sinon ajouter `organisation_id` + scope. **Décision métier requise.** | M | P1 |
| DB-02 | 🟠 | Concurrence | `sorties_fonds.py` | 940-964, 1058 | `budget_line` lu sans `with_for_update`; read-modify-write sur `montant_paye` et contrôle de plafond non verrouillés. | Deux sorties concurrentes → dépassement de plafond silencieux. | `.with_for_update()` sur le `select(BudgetPoste)` ou UPDATE atomique conditionnel. | S | P1 |
| DB-03 | 🟠 | Concurrence | `models/caisse_centrale.py` ; `sorties_fonds.py:335-343` | — | Pas d'`UniqueConstraint(organisation_id)`; `_get_or_create_caisse` fait SELECT LIMIT 1 puis INSERT sans verrou/upsert. | Deux caisses pour une org → solde scindé/incohérent. | `UniqueConstraint` + `INSERT … ON CONFLICT DO NOTHING RETURNING`. | M | P1 |
| DB-04 | 🟠 | Migrations | `backend/alembic/versions/` | 6 têtes | Graphe à 6 leaf-revisions non mergées ; `alembic upgrade head` (utilisé à l'entrypoint) échoue sur env neuf/CI. | Déploiement neuf / CI cassés. | `alembic merge` des têtes ; rattacher les branches orphelines. | S | P1 |
| DB-08 | 🟠 | Dérive modèle/DB | `models/sortie_fonds.py:50` | `requisition_id` | Colonne sans `ForeignKey` dans le modèle alors que la FK existe en base (dump). | Métamodèle désynchronisé, pas d'intégrité ORM, autogenerate faux. | Déclarer `ForeignKey("requisitions.id", ondelete="SET NULL")` + relationship. | S | P2 |
| OPS-01 | 🔴 | Secrets/Build | `backend/Dockerfile:13`, `backend/.dockerignore` | `COPY . .` | `backend/.env` non exclu → secrets bakés dans les couches de l'image (`docker history`). | Fuite de secrets via l'image ; rotation impossible sans rebuild. | Ajouter `.env*` au `.dockerignore` ; injecter au runtime. | S | P0 |
| OPS-02 | 🟠 | Moindre privilège | `backend/Dockerfile` | aucun `USER` | Gunicorn tourne en **root** dans le conteneur. | RCE app = root conteneur → escalade hôte. | `adduser` + `USER appuser`. | S | P1 |
| OPS-03 | 🟠 | Déploiement | `backend/entrypoint.sh:11` | `alembic upgrade head` | Migration à chaque boot ; `set -e` + `restart: always` → crash-loop ; migration destructive auto ; race multi-répliques. | Indisponibilité totale sur migration ratée ; risque de perte de données. | Migration en étape CI/CD dédiée (un exécuteur) ; snapshot avant. | M | P1 |
| OPS-04 | 🟠 | Réseau/TLS | `frontend/nginx.conf`, `docker-compose.prod.yml:34` | `listen 80`, `8000:8000` | Aucun TLS dans le dépôt ; port API publié direct ; `/metrics` sans `METRICS_TOKEN`. | JWT/identifiants en clair ; API et métriques exposées. | Terminaison TLS (ALB/ACM ou certbot), retirer le mapping 8000, protéger `/metrics`. | M | P1 |
| SEC-04 | 🟠 | Brute force | `core/limiter.py:8` | `_rate_limit_key` | Utilise le 1er `X-Forwarded-For` sans proxy de confiance → clé de rate-limit usurpable. | Contourne `5/minute` sur login/OTP → brute force. | Dériver l'IP via N proxys de confiance. | S | P1 |
| AI-02 | 🟠 | Prompt injection | `routers/manager.py:158`; `manager_agent_agentor.py:431` | `conversation_history` | Historique client injecté tel quel → messages `system`/`tool` forgeables. | Manipulation de l'agent, faux « approuvé ». | N'accepter que `role∈{user,assistant}` ; reconstruire l'historique côté serveur. | M | P1 |
| BE-02 | 🟡 | Performance | `api/v1/endpoints/auth.py:382,429` | `send_security_code` | SMTP synchrone (`smtplib`, timeout 20 s) appelé dans endpoint `async`. | Blocage de la boucle événementielle → stalle le worker. | `background_tasks.add_task(...)` ou `run_in_executor`. | S | P1 |
| BE-03 | 🟡 | Contrôle d'accès | `api/deps.py` | `require_module` | Accès accordé si module non configuré (fail-open). | Modules « désactivés » restent accessibles. | Fail-closed pour modules sensibles. | S | P2 |
| SEC-05 | 🟡 | Exposition fichiers | `core/config.py:76` | `SERVE_UPLOADS_PUBLICLY` | Défaut `True` : `/uploads` public si pas d'override. | Justificatifs financiers/personnels exposés. | Défaut `False`, servir via `secure_uploads`. | S | P1 |
| DB-05 | 🟡 | Types financiers | `models/saas_transaction.py:39` | `amount: Float` | Montant facturé en flottant (arrondis binaires). | Erreurs d'arrondi de facturation. | `Numeric(15,2)` + migration. | S | P2 |
| DB-06 | 🟡 | Contraintes | `caisse_centrale`, `budget`, `requisition` | soldes/montants | Aucun `CHECK >= 0` sur soldes/plafonds (contrairement à sorties/encaissements). | Solde négatif possible via bug/UPDATE direct. | Ajouter `CheckConstraint(">= 0")`. | S | P2 |
| DB-07 | 🟡 | Auditabilité | `models/audit_log.py` | — | `audit_logs` mutable, `organisation_id` SET NULL, pas de chaînage/hash. | Historique financier modifiable silencieusement. | `REVOKE UPDATE/DELETE` ou trigger ; `prev_hash` chaîné. | M | P2 |
| AI-04 | 🟡 | Secrets | `core/encryption.py:41-47` | clé Fernet | Clé absente → clé éphémère + `warning` (fail-open). | Secrets IA illisibles après reboot ; protection non maîtrisée. | Échec fatal en prod si clé absente. | S | P1 |
| AI-05 | 🟡 | Emails | `services/mailer.py:205-213` | STARTTLS opportuniste | Pas d'enforcement TLS ni vérif certificat. | MITM → identifiants SMTP + contenu en clair. | Exiger TLS + `ssl.create_default_context()`. | S | P2 |
| AI-06 | 🟡 | Coûts/DoS | endpoints `/ai/*` | — | Aucun rate-limit ni quota de tokens. | Abus de coûts, épuisement quota tenant. | Throttling + compteur de tokens par org. | M | P2 |
| AI-07 | 🟡 | Résidence données | `ai_chat.py:599`, `ai_syscebnl.py:53`, `ai_batch_service.py:25` | `get_ai_service()` | Ignore `get_ai_service_for_org` → snapshot financier envoyé au provider env, même si l'org a configuré un provider local. | Confidentialité/résidence non maîtrisée par tenant. | Router via `get_ai_service_for_org`. | S | P2 |
| FE-01 | 🟠 | Permissions UI | `PermissionsContext.tsx:52` + 15 écrans | `hasPermission(...)` | Gating d'actions sensibles 100 % client (décaissement, annulation, validation). | Élévation de privilège si le backend ne re-vérifie pas. | Recouper chaque action avec un contrôle serveur (cf. BE-01/AI-01). | L | P1 |
| FE-03 | 🟠 | Dépendance | `frontend/package.json` | `xlsx@^0.18.5` | CVE-2023-30533 (prototype pollution) + CVE-2024-22363, non corrigées sur npm. | Parsing de `.xlsx` importés exploitable. | Migrer vers build SheetJS officielle ≥ 0.20.2 ou `exceljs`. | S | P1 |
| FE-02 | 🟡 | Maintenabilité | `HRModule.tsx` (3747), `Requisitions.tsx` (3359), `Settings.tsx` (3151) | — | Composants « dieu », 826 `any` / 258 `as any`, 0 `React.memo`, pas de cache serveur. | Re-renders, régressions, tests impossibles. | Découper par onglet + hooks + TanStack Query ; typer les réponses. | L | P2 |
| FE-04 | 🟡 | Cohérence API | 26 `fetch()` hors `apiClient` (`billing.ts`, `AuditLogs.tsx`, `ClotureCaisse.tsx`) | — | Court-circuitent le refresh 401 silencieux. | Exports échouent après expiration du token. | Helper `apiFetchBlob()` réutilisant le flux refresh. | M | P2 |
| FE-05 | 🟡 | Accessibilité | formulaires (585 inputs / 11 `htmlFor`) | — | Labels non associés, navigation clavier partielle. | Non conforme WCAG 1.3.1/4.1.2. | `id`+`htmlFor` ou imbrication, `aria-*`. | M | P2 |
| ARCH-01 | 🟠 | Architecture | `db/session.py:359` | `_apply_tenant_criteria` | Isolation tenant sur **liste codée en dur** de ~60 modèles ; oubli = fuite silencieuse. | Fuite inter-organisations sur nouveau modèle non enregistré. | Dériver la liste d'un mixin `TenantScoped` + test de couverture ; RLS PostgreSQL en défense. | M | P1 |
| ARCH-02 | 🟡 | Maintenabilité | `requisitions.py` vs `requisition_service.py` | helpers dupliqués | `record_status_history`, `check_cash_watchdog`, `apply_snapshot_if_needed` en double ; l'import-PDF utilise les copies locales. | Divergence des règles métier (statuts, watchdog). | Supprimer les helpers locaux, router vers le service. | M | P2 |
| TEST-01 | 🟠 | Tests | `conftest.py:34-47` | `create_all` / skip | Schéma via `create_all` (migrations jamais testées) ; skip global si pas de `TEST_DATABASE_URL` (faux vert) ; aucun test de concurrence. | Divergence modèle/prod non détectée ; CI verte à vide. | Job CI `alembic upgrade head` sur base vierge ; échec si suite entièrement skippée ; test 2 sessions concurrentes. | M | P1 |
| CONF-01 | 🔴 | Confidentialité | (absent) | — | Aucune politique de confidentialité (fichier/route/lien). | Rejet certain de la vérif Google OAuth ; RGPD art. 13/14. | Rédiger + héberger + lier (données, finalités, sous-traitants, droits, contact). | M | P1 |
| CONF-02 | 🔴 | OAuth/Scopes | `modules/secretariat/…/oauth_service.py` | `gmail.readonly`, `gmail.compose` | Scope restreint `gmail.readonly` → Google Verification + CASA Tier 2 ; minimisation non respectée. | Écran « unverified » (100 users max), blocage prod. | Retirer `gmail.readonly` si possible, justifier, budgéter CASA. | L | P1 |
| CONF-03 | 🟠 | RGPD | `admin.py:757`, `Settings.tsx` | suppression compte | Pas de suppression self-service ni d'export des données personnelles. | Non-conformité RGPD art. 17/20 ; bloquant stores. | Endpoint self-service suppression/anonymisation + export. | M | P2 |
| CONF-04 | 🟠 | RGPD | `Signup.tsx` | consentement/CGU | Pas de consentement au signup, pas de CGU/mentions légales, pas de divulgation IA. | Non-conformité + mauvais signal en revue OAuth. | Case consentement horodatée + CGU + bandeau « contenu IA ». | M | P2 |

*(Registre resserré sur les constats majeurs ; les rapports détaillés des sous-agents contiennent les ~90 constats complets.)*

---

## C. Top 20 des problèmes prioritaires

Ordonnés selon : sécurité critique → perte/corruption → incohérence financière → contrôle d'accès → stabilité → conformité → performance → qualité → UX.

1. **SEC-01** — Clés SSH privées + dump SQL dans l'historique git (exploitables). 🔴
2. **SEC-02** — `JWT_SECRET` faible + mots de passe faibles → compromission totale. 🔴
3. **OPS-01** — Secrets `.env` bakés dans l'image Docker. 🔴
4. **DB-01** — Double-paiement des réquisitions classiques. 🔴
5. **DB-02** — Course budgétaire non verrouillée → dépassement de plafond. 🟠
6. **DB-03** — `caisse_centrale` sans unicité par organisation (race). 🟠
7. **BE-01** — `GET /audit/sortie` non authentifié, fuite financière cross-tenant. 🔴
8. **AI-01** — Agent Manager exécute des écritures sans re-vérifier les permissions. 🔴
9. **AI-03** — Chatbot finance sans permission métier (exfiltration trésorerie). 🔴
10. **SEC-03** — Tables globales (denominations, experts, imports) modifiables cross-tenant. 🟠
11. **ARCH-01** — Isolation tenant sur liste codée en dur (fuite silencieuse possible). 🟠
12. **AI-02** — `conversation_history` contrôlé par le client (injection de rôle). 🟠
13. **SEC-04** — Bypass du rate-limiting via `X-Forwarded-For` (brute force). 🟠
14. **OPS-03** — Migration Alembic à l'entrypoint (crash-loop / destructive auto). 🟠
15. **DB-04** — Chaîne Alembic à 6 têtes (déploiement neuf/CI cassés). 🟠
16. **OPS-04** — HTTPS absent + port API + `/metrics` exposés. 🟠
17. **OPS-02** — Conteneur Docker en root. 🟠
18. **CONF-01 / CONF-02** — Politique de confidentialité absente + scopes Gmail non vérifiés. 🔴
19. **TEST-01** — Migrations non testées + skip global silencieux + aucun test de concurrence. 🟠
20. **FE-03** — Dépendance `xlsx` vulnérable (CVE). 🟠

---

## D. Plan de correction (4 phases)

### Phase 1 — Blocages critiques (avant toute présentation/déploiement sérieux)
- SEC-01 : révoquer la clé SSH (la considérer compromise), purger l'historique git, sortir clés/dumps du répertoire projet.
- SEC-02 : régénérer `JWT_SECRET` (≥ 256 bits) + tous les mots de passe, invalider les tokens.
- OPS-01 : exclure `.env*` du build Docker, injecter les secrets au runtime.
- DB-01 : corriger le vecteur de double-paiement (statut serveur + index unique partiel).
- BE-01 : authentifier/scoper `GET /audit/sortie`.
- AI-01, AI-03 : re-vérifier les permissions dans les outils de l'agent Manager et sur `/ai/chat`.

### Phase 2 — Stabilisation (architecture, données, permissions, tests)
- DB-02, DB-03, DB-04, DB-08 : verrou budgétaire, unicité caisse, merge des têtes Alembic, FK modèle.
- SEC-03, ARCH-01, BE-03, SEC-05 : cloisonnement des tables globales, dérivation auto du scope tenant, fail-closed modules, uploads privés par défaut.
- AI-02, SEC-04, AI-04..07 : durcissement IA (historique serveur, rate-limit, chiffrement fail-closed, résidence données), rate-limit login.
- TEST-01 : tests de migration, échec si suite skippée, tests de concurrence trésorerie.
- ARCH-02, FE-03 : dédupliquer les helpers réquisition, corriger la dépendance `xlsx`.

### Phase 3 — Industrialisation (CI/CD, monitoring, sauvegardes, perf)
- OPS-02, OPS-03, OPS-04 : conteneur non-root, migration en étape de déploiement, TLS + retrait du port 8000 + `/metrics` protégé.
- CI/CD : build+push d'image taggée, scans (Trivy, pip-audit, npm audit, bandit), déploiement outillé, environnements dev/staging/prod séparés.
- Data : PostgreSQL managé (RDS Multi-AZ, PITR) ou sauvegardes chiffrées hors-hôte S3 ; Redis avec auth.
- Observabilité : healthchecks app, alertes 5xx, audit IA persisté (AI + DB-07).
- Perf/maintenabilité : découpage des god-files backend/frontend, TanStack Query, typage des réponses API (réduction des `any`).

### Phase 4 — Préparation Google/Apple
- CONF-01, CONF-04 : politique de confidentialité, CGU, mentions légales, consentement horodaté au signup, bandeau « contenu généré par IA ».
- CONF-02 : minimiser les scopes Gmail (retirer `gmail.readonly` si possible), préparer la vérification Google OAuth + audit CASA, révocation OAuth côté Google.
- CONF-03 : suppression de compte self-service + export/portabilité RGPD.
- Accessibilité (FE-05), page support/contact, captures et documentation de soumission.

---

## E. Corrections automatisables

**Que je peux appliquer directement (sur validation, sans risque de données) :**
- OPS-01 (`.dockerignore`), OPS-02 (`USER` non-root), FE-03 (bump `xlsx`), BE-02 (`background_tasks` SMTP), SEC-04 (clé de rate-limit), SEC-05 (défaut `SERVE_UPLOADS_PUBLICLY=False`), BE-03/AI-04 (fail-closed), DB-08 (FK modèle), AI-01/AI-03/BE-01 (ajout des dépendances de permission), AI-02 (filtrage de l'historique), AI-07 (routage provider par org), en-têtes Nginx + `client_max_body_size` (OPS-04 partiel).

**Décision métier requise (je ne tranche pas seul) :**
- SEC-03 : les tables `denominations`/`experts_comptables`/`imports_history` sont-elles volontairement globales (registre national) ou doivent-elles être tenant-scopées ?
- CONF-02 : peut-on retirer `gmail.readonly` (impact fonctionnel du module secrétariat) ?
- DB-01 : politique exacte (une seule sortie par réquisition classique ? paiements partiels autorisés hors mode progressif ?).

**Accès externes requis (hors dépôt) :**
- SEC-01 : révocation de la clé SSH sur le serveur, purge/force-push git, rotation des secrets d'infra.
- CONF-01/03/04 : hébergement des documents légaux, config de l'écran de consentement Google, audit CASA.
- OPS-03/04 : pipeline de déploiement, terminaison TLS, RDS/Redis managés.

**Test humain nécessaire :**
- DB-01, DB-02, DB-03 après correctif (rejouer paiements concurrents), workflow réquisition complet, module secrétariat/IA de bout en bout.

**Susceptible de modifier/supprimer des données (validation explicite obligatoire) :**
- Migrations Alembic : merge des têtes (DB-04), ajout de CHECK/FK/unicité (DB-03/06/08), `VALIDATE CONSTRAINT` sur données historiques, index unique partiel (DB-01). **Aucune migration destructive ne sera lancée sans votre accord et sans sauvegarde préalable.**

---

## F. Checklist de validation finale

**Avant démonstration professionnelle**
- [ ] `GET /audit/sortie` authentifié/scopé (BE-01)
- [ ] Double-paiement corrigé et testé (DB-01)
- [ ] Chatbot/agent IA gardés par permissions (AI-01, AI-03)
- [ ] Secrets de démo distincts, non faibles (SEC-02)

**Avant audit de sécurité**
- [ ] Historique git purgé, clé SSH révoquée (SEC-01)
- [ ] `JWT_SECRET` fort + rotation (SEC-02)
- [ ] Rate-limiting non contournable (SEC-04)
- [ ] Tables globales cloisonnées ou écriture super_admin (SEC-03)
- [ ] Scope tenant dérivé automatiquement + RLS (ARCH-01)

**Avant déploiement en production**
- [ ] Secrets hors image + conteneur non-root (OPS-01, OPS-02)
- [ ] Migration hors entrypoint + sauvegarde préalable (OPS-03)
- [ ] TLS actif, port API non exposé, `/metrics` protégé (OPS-04)
- [ ] Têtes Alembic mergées + migration testée en CI (DB-04, TEST-01)
- [ ] Verrous concurrence caisse/budget prouvés par test (DB-02, DB-03)
- [ ] Sauvegardes chiffrées hors-hôte + PITR

**Avant ouverture aux utilisateurs / données réelles**
- [ ] CHECK `>= 0` + audit_logs immuable (DB-06, DB-07)
- [ ] Uploads privés par défaut (SEC-05)
- [ ] Quotas/rate-limit IA + audit IA persisté (AI-06)

**Avant soumission Google/Apple**
- [ ] Politique de confidentialité + CGU + mentions légales publiées et liées (CONF-01, CONF-04)
- [ ] Consentement horodaté au signup + bandeau IA (CONF-04)
- [ ] Suppression de compte self-service + export RGPD (CONF-03)
- [ ] Scopes Gmail minimisés + vérification OAuth + CASA préparés (CONF-02)
- [ ] Page support/contact + accessibilité WCAG (FE-05)

---

## Zones non vérifiées (à confirmer)
- Runtime : couverture réelle du filtre `with_loader_criteria` sur les requêtes `text()`/agrégats, exécution réelle des 315 tests et couverture %, comportement concurrent réel (déductions statiques).
- Valeurs de production : `ENV`, `JWT_SECRET`, `METRICS_TOKEN`, `cors_origin_regex`, `SERVE_UPLOADS_PUBLICLY`, `refresh_cookie_secure` (lus dans `.env` local + compose, pas sur l'instance prod).
- Infrastructure AWS (EC2/RDS/S3/IAM/ALB/CloudFront) : hors dépôt — un ALB/CloudFront pourrait faire le TLS et atténuer OPS-04.
- Présence réelle de la FK `fk_sorties_fonds_requisition` sur l'instance courante (constatée dans un dump d'avril).
- Endpoints non échantillonnés (~40 sur 50) et migrations (190) non lus intégralement.
- Documents légaux éventuellement hébergés hors dépôt ; DPA avec providers IA/paiement (contractuel).
- Rendu Markdown/HTML des réponses IA côté client (risque XSS non tracé), `oauth_service`/stockage des refresh tokens Google non audités en détail.
- Ratios de contraste WCAG non mesurés ; `npm audit` réel non exécuté (seule `xlsx@0.18.5` analysée par version).

---

*Fin du rapport. Aucune modification de code n'a été effectuée. En attente de validation explicite avant d'engager les correctifs (à commencer par la Phase 1).*
