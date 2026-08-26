# Audit de performance RÉSEAU — ONEC Smart

**Périmètre** : comportement réseau frontend ↔ API (nombre d'appels, séquencement, charge utile, cache HTTP, authentification).
**Méthode** : analyse statique du code d'appel uniquement. Docker est arrêté — **aucune latence n'a été mesurée**. Tous les chiffres ci-dessous sont des **décomptes d'appels** dérivés du code, pas des temps.
**Convention** : `[MESURÉ]` = comptage exact lisible dans le code · `[DÉDUIT]` = conséquence probable, non observée.

---

## 1. Diagramme de séquence

### (a) Ouverture de l'app (rechargement de page, session existante, atterrissage sur `/`)

```
NAVIGATEUR                                   RÉSEAU                              ÉTAT UI
──────────────────────────────────────────────────────────────────────────────────────────
                          ┌─ GET /index.html ..................... (no-cache, revalidé)
                          ├─ GET /assets/index-*.js ............... (immutable, cache OK)
 hop réseau 0 (statique)  ├─ GET /assets/vendor-react-*.js
                          ├─ GET fonts.googleapis.com/css2 ....... BLOQUANT le rendu
                          └─ GET fonts.gstatic.com/*.woff2 ....... (chaîné après le CSS)
                                                                    │
 React monte ─────────────────────────────────────────────────────► écran vide / PageLoader
                                                                    │
 AuthContext.useEffect  ── hop 1 ─► POST /auth/refresh              │ "Vérification de la session…"
   (AuthContext.tsx:31-46)              │                           │
                          ── hop 2 ─────┴─► GET /auth/me            │ (toujours PageLoader)
                                            │
 user != null ──► PrivateRoute passe ──► Layout monte
                                            │
                          ── hop 3 ──┬─► GET /permissions/menu      │ SQUELETTE VISIBLE
 (3 appels en parallèle)             ├─► GET /organisation/settings │ (sidebar sans menus,
                                     └─► GET /billing/status        │  car les menus dépendent
                                            │                       │  de /permissions/menu)
 permissionsLoading=false ──► ServiceAwareDashboard démonte le loader
                                            │
                          ── hop 4a ─► GET /assets/Dashboard-*.js   │ chunk lazy NON préchargé
                                            │                       │ → RTT supplémentaire ici
                          ── hop 4b ─┬─► GET /dashboard/stats?devise=USD
                                     ├─► GET /dashboard/stats?devise=CDF
                                     ├─► GET /budget/summary        │ PREMIÈRE DONNÉE UTILE
                                     ├─► GET /treasury/balances     │
                                     ├─► GET /print-settings        │
                                     ├─► GET /comptes-bancaires?active=true
                                     └─► GET /ai/cash-forecast  ◄── (déclenché par Layout)
                                            │
                          ── hop 5 ──► GET /ai/cash-forecast  ◄── (2ᵉ fois, par Dashboard)
```

**Allers-retours SÉQUENTIELS avant la première donnée utile : 4 hops API** (`refresh` → `me` → `permissions` → `stats`), plus **1 hop statique intercalé** (chunk `Dashboard-*.js` chargé seulement au hop 4a, après la résolution des permissions).
**Total requêtes API sur cette séquence : 12** (dont 1 strictement dupliquée).

### (b) Connexion réussie (chemin critique du formulaire)

```
clic « Se connecter »
   │
   ├─ hop 1 ─► GET /auth/discover-tenants?email=…   (Login.tsx:211, BLOQUANT et systématique)
   │            └─ son résultat n'est utilisé que pour un cas d'erreur (tenants.length > 1)
   ├─ hop 2 ─► POST /auth/login                     (renvoie déjà role, org_id, org_slug, plan_*)
   ├─ hop 3 ─► GET /auth/me                         (signIn → reloadProfile, AuthContext.tsx:51)
   │
   ├─ ⏱  setTimeout(650 ms)   ◄── DÉLAI ARTIFICIEL PUR (Login.tsx:230-232)
   │
   └─ navigate('/dashboard') → reprend au hop 3 du diagramme (a)
```

**Entre la soumission du formulaire et le premier chiffre du tableau de bord :
5 allers-retours API séquentiels + 650 ms de temporisation codée en dur + 1 chargement de chunk.**
Décompte total : **13 requêtes API** (`discover-tenants`, `login`, `me`, `permissions/menu`, `organisation/settings`, `billing/status`, 2× `dashboard/stats`, `budget/summary`, `treasury/balances`, `print-settings`, `comptes-bancaires`, 2× `ai/cash-forecast`).

### (c) Arrivée sur le tableau de bord

Le fan-out du hop 4b est déjà correctement parallélisé (`Promise.all`, `Dashboard.tsx:279-288`). Le problème n'est pas la largeur, c'est la **profondeur** : ce `Promise.all` ne peut pas démarrer avant que `/permissions/menu` soit revenu, à cause de la barrière `ServiceAwareDashboard` (`App.tsx:189-191`) doublée du garde `enabled: !permissionsLoading` (`Dashboard.tsx:261`).

### Rafraîchissement de jeton

Le refresh **ne s'insère pas** dans ce chemin : il est déclenché uniquement sur un 401 (`apiClient.ts:411`) et il est **correctement verrouillé** — voir constat #9. Aucun risque de N refresh concurrents sur ce chemin.

---

## 2. Constats classés par (gain × confiance)

### 🔴 #1 — 3 des 4 hops séquentiels du démarrage sont fusionnables en un seul appel

- **Preuve** : `frontend/src/contexts/AuthContext.tsx:35-38` (`await refresh()` puis `await reloadProfile()`), `frontend/src/contexts/PermissionsContext.tsx:36` (`getMenuPermissions()` gardé par `user?.id`), `frontend/src/contexts/OrganisationSettingsContext.tsx:25,37` (`getOrganisationSettings()` gardé par `user?.organisation_id`), `frontend/src/App.tsx:376-386` (les 3 providers empilés).
- **Nature du problème** : `POST /auth/refresh` (`backend/app/api/v1/endpoints/auth.py`) renvoie déjà `role`, `organisation_id`, `organisation_uuid`, `organisation_slug`, `plan_status`, `plan_type` (`frontend/src/api/auth.ts:33-44`). `GET /auth/me` (`auth.py:794-824`) n'y ajoute que `nom`, `prenom`, `service_ids`, `must_change_password`, `is_email_verified`, `organisation_name`, `plan_expires_at`, `user_limit`. Puis `/permissions/menu` et `/organisation/settings` ne peuvent partir qu'une fois `user` posé, alors qu'aucune de ces deux réponses ne dépend du corps de `/auth/me` — seulement du **jeton**, déjà disponible à la fin du hop 1.
- **Appels avant / après** : 4 requêtes en **3 hops séquentiels** → 1 requête en **1 hop**.
- **Correctif** : faire renvoyer à `POST /auth/refresh` **et** à `POST /auth/login` un enveloppe de démarrage `{ access_token, user, menu_permissions, organisation_settings }` (ou introduire `GET /auth/bootstrap` appelé une seule fois après le hop 1). `AuthContext` alimente alors les trois contextes via un état partagé, `PermissionsContext`/`OrganisationSettingsContext` conservant leur fetch actuel en repli quand la charge n'est pas fournie.
- **Gain attendu** : suppression de **2 allers-retours** sur le chemin critique du démarrage **et** du chemin critique de connexion. Fondement : décompte de hops, pas de mesure — le gain en millisecondes est exactement 2 × RTT + 2 × temps de traitement serveur, donc d'autant plus élevé que le réseau est lent (contexte RDC, mobile). `[MESURÉ]` pour le décompte, `[DÉDUIT]` pour l'effet perçu.
- **Risque** : moyen. Il faut garder les deux endpoints séparés fonctionnels (le refresh silencieux sur 401 en `apiClient.ts:412` ne doit **pas** payer le coût du bootstrap complet — prévoir un paramètre `?bootstrap=1` ou un endpoint distinct). Attention aussi à l'invalidation : les permissions deviennent figées jusqu'au prochain refresh.

### 🔴 #2 — 650 ms de latence perçue purement artificielle après la connexion

- **Preuve** : `frontend/src/pages/Login.tsx:230-232`
  ```ts
  window.setTimeout(() => { navigate('/dashboard', { replace: true }) }, 650)
  ```
- **Appels avant / après** : identique (0 requête concernée) — c'est du temps mort pur, ajouté **après** que `/auth/me` soit déjà revenu.
- **Correctif** : naviguer immédiatement ; si l'animation de succès a une valeur, la jouer pendant que la route suivante se monte (elle affiche de toute façon un `PageLoader`), pas avant de naviguer.
- **Gain attendu** : **650 ms fixes** retirés du temps perçu de connexion. C'est la seule valeur de ce rapport qui soit un temps réellement connu, parce qu'elle est écrite en dur dans le code. `[MESURÉ]`
- **Risque** : nul.

### 🔴 #3 — Aucun en-tête de cache HTTP nulle part dans l'API

- **Preuve** : `grep -rn "Cache-Control|ETag|max-age|If-None-Match" backend/app/` → **0 occurrence** sur du code de réponse HTTP. Le seul cache existant est côté serveur, invisible du navigateur : Redis TTL 60 s pour le tableau de bord (`backend/app/api/v1/endpoints/dashboard.py:33,104,519`), TTL configurable pour les rapports (`reports.py:169,1007`), cache de contexte d'auth (`deps.py:245-249`), cache de résolution de tenant (`core/tenant_resolver.py:105-124`).
- **Conséquence** : les référentiels quasi immuables sont **retéléchargés intégralement à chaque montage de composant**, sans même une revalidation conditionnelle 304 :
  - `/print-settings` — appelé depuis **10 endroits** (`Dashboard.tsx:287`, `Encaissements.tsx:298`, `Requisitions.tsx:405`, `SortiesFonds.tsx:364`, `Budget.tsx:252`, `ServiceDashboard.tsx:88`, `OrganisationSettings.tsx:72`, `Settings.tsx:520`, `PrintReceipt.tsx:124`, `hooks/useRequisitions.ts:32`)
  - `/services` — appelé depuis **10 endroits** (`Encaissements.tsx:169`, `SortiesFonds.tsx:271`, `Requisitions.tsx:385`, `RemboursementTransport.tsx:371`, `Budget.tsx:239`, `DossiersExamen.tsx:354`, `SortieDirecteProgrammee.tsx:96`, `ServiceDashboard.tsx:61`, `Settings.tsx:545`, `ServiceAdminPanel.tsx:24`)
  - `/comptes-bancaires?active=true` — **4 pages** (`Dashboard.tsx:506`, `Encaissements.tsx:279`, `Rapports.tsx:473`, `SortiesFonds.tsx:352`)
  - `/permissions/menu`, `/organisation/settings`, `/budget/postes`, `/experts-comptables`
- **Appels avant / après** : sur un parcours Tableau de bord → Encaissements → Réquisitions → Sorties, `/print-settings` part **4 fois** et `/services` **3 fois**. Avec un `Cache-Control: private, max-age=300` + ETag : **1 fois**, puis des 304 vides.
- **Correctif** : (a) côté API, poser `Cache-Control: private, max-age=…, stale-while-revalidate=…` + `ETag` sur les GET de référentiel ; (b) côté client, faire passer ces référentiels par TanStack Query (déjà installé et configuré, `App.tsx:361-368`) avec un `staleTime` long et une invalidation explicite après mutation. Le seul cache client existant aujourd'hui est celui, manuel, de `utils/pdfGenerator.ts:48-62` — la preuve que le besoin est déjà ressenti.
- **Gain attendu** : élimination de la majorité des requêtes de navigation inter-pages. `[MESURÉ]` pour l'absence d'en-têtes et le nombre de sites d'appel ; `[DÉDUIT]` pour le volume économisé.
- **Risque** : faible à moyen. Un `max-age` sur `/permissions/menu` retarde la prise en compte d'un changement de droits — préférer un ETag (revalidation) à un `max-age` sur cet endpoint précis.

### 🟠 #4 — TanStack Query est installé mais quasi inutilisé : aucune déduplication des requêtes

- **Preuve** : `QueryClientProvider` est bien monté (`App.tsx:374`) avec `staleTime: 30_000` (`App.tsx:364`), mais **10 fichiers seulement** utilisent `useQuery` contre **13 fichiers** qui appellent `apiRequest()` directement dans un `useEffect`, sur **44 pages**. Aucune couche de déduplication dans `apiClient.ts` non plus.
- **Conséquence directe** : deux composants montés au même rendu qui demandent la même ressource émettent deux requêtes. Cas confirmé ci-dessous (#5).
- **Correctif** : router les référentiels par `useQuery` avec des clés stables (`['services']`, `['print-settings']`, `['comptes-bancaires']`). Alternative moins invasive : un cache de promesses en vol dans `apiClient.ts` (coalescence par `method+url` pour les GET).
- **Gain attendu** : suppression des doublons intra-rendu. `[MESURÉ]` (comptage de fichiers), `[DÉDUIT]` (volume).
- **Risque** : faible.

### 🟠 #5 — `/ai/cash-forecast` demandé deux fois, avec des paramètres identiques

- **Preuve** :
  - `frontend/src/components/Layout.tsx:549` — `getCashForecast({ lookback_days: 30, horizon_days: 30, reserve_threshold: 1000 })`, appel brut hors TanStack Query, **plus un `setInterval` de 300 000 ms** (`Layout.tsx:556`)
  - `frontend/src/pages/Dashboard.tsx:464-468` — `useQuery({ queryKey: ['cash-forecast'], queryFn: () => getCashForecast({ lookback_days: 30, horizon_days: 30, reserve_threshold: 1000 }) })`
  - Paramètres strictement identiques ; le `useQuery` du Dashboard ne peut pas dédupliquer l'appel du Layout, qui est un `fetch` direct.
- **Appels avant / après** : sur le tableau de bord, **2 appels** à un endpoint de prévision (`backend/app/api/v1/endpoints/ai.py:212-224` → `compute_cash_forecast`, agrégation sur 30 jours d'historique) → **1 appel**. Et **2 appels toutes les 5 minutes** tant que l'onglet reste sur le tableau de bord.
- **Correctif** : convertir `Layout.tsx:543-558` en `useQuery({ queryKey: ['cash-forecast'], … })` avec le même `queryKey` que le Dashboard, `staleTime: 300_000` et `refetchInterval: 300_000`. Le doublon disparaît par construction et le `setInterval` manuel avec.
- **Gain attendu** : −1 requête coûteuse par affichage du tableau de bord, −50 % de la charge de prévision. `[MESURÉ]`
- **Risque** : nul.

### 🟠 #6 — Fan-out N+1 sur les exports : 1 requête HTTP **par ligne** exportée

- **Preuve** :
  - `frontend/src/pages/Requisitions.tsx:1969-1972` — `filteredRequisitions.map(async (req) => await apiRequest('GET', '/lignes-requisition', { params: { requisition_id: req.id } }))`, alors que la liste amont est chargée avec `limit: 5000` (`Requisitions.tsx:305`)
  - `frontend/src/pages/DossiersExamen.tsx:766-772` — même motif
  - `frontend/src/pages/Rapports.tsx:1191-1197` — même motif, liste amont à `limit: 5000` (`Rapports.tsx:889,898,901`)
  - `frontend/src/pages/ServiceDashboard.tsx:65-70` — 1 `GET /services/{id}/consommation` par service
  - `frontend/src/components/settings/BudgetTab.tsx:34-39` — 1 `GET /services/{id}/rubriques` par service
- **Appels avant / après** : un export PDF de réquisitions sur une période chargée = **1 + N requêtes**, N pouvant atteindre 5000 par le `limit` en amont. Toutes lancées d'un coup via `Promise.all`, sans limite de concurrence. Après : **2 requêtes** (la liste + un `GET /lignes-requisition?requisition_id=in.(…)` groupé), ou **1 seule** si la liste supporte `include=lignes`.
- **Correctif** : ajouter le filtrage multi-ids côté API (ou un `include=lignes` sur `/requisitions`) et remplacer le `map` par un appel groupé. À défaut immédiat, plafonner la concurrence (pool de 6) — mais c'est un pansement.
- **Gain attendu** : passage de O(N) à O(1) requêtes sur le chemin d'export. `[MESURÉ]` pour la structure de l'appel ; `[DÉDUIT]` pour le N réel en production.
- **Risque** : moyen — demande une évolution de contrat d'API et une revue de la limite de longueur d'URL pour l'`in.(…)`.

### 🟠 #7 — `pages/Settings.tsx` : 11 allers-retours strictement séquentiels au chargement

- **Preuve** : `frontend/src/pages/Settings.tsx:516-565` — onze `await` consécutifs sans aucune interdépendance :
  `adminGetPrintSettings()` → `getOrganisationSettings()` → `getComptaMappings()` → `adminGetNotificationSettings()` → `adminGetWeeklyReportStatus()` → `adminGetRoles()` → `adminGetPermissions()` → `adminListRequisitionApprovers()` → `getBudgetExercises()` → `getServices()` → `loadUsers()`.
  Aucune de ces réponses n'alimente la requête suivante — tous les `setState` sont regroupés en fin de fonction (lignes 547-558), ce qui **prouve** l'absence de dépendance.
- **Appels avant / après** : **11 hops séquentiels** → **1 hop** (`Promise.allSettled` — les `try/catch` individuels actuels se traduisent directement en `allSettled`).
- **Correctif** : `await Promise.allSettled([...])`, puis distribution des résultats. Transformation mécanique, à périmètre fonctionnel identique.
- **Gain attendu** : division du temps d'ouverture de la page Paramètres par ~10 en nombre de hops. `[MESURÉ]`
- **Risque** : faible. Seul point d'attention : `adminGetPermissions()` est conditionné par `isSuperAdmin` (ligne 542) — remplacer par `isSuperAdmin ? adminGetPermissions() : Promise.resolve([])` dans le tableau.
- **Aggravant** : `getOrganisationSettings()` (ligne 521) est **déjà** en mémoire dans `OrganisationSettingsContext` — cet appel est intégralement redondant.

### 🟡 #8 — Aucun `AbortController` dans tout le frontend : courses de données et requêtes fantômes

- **Preuve** : `grep -rn "AbortController|signal:" frontend/src/` → **0 occurrence**. `apiClient.ts:358-363` n'accepte aucun `signal` dans les options (`ApiOptions` ne connaît que `params` et `body`, `apiClient.ts:284-289`).
- **Conséquence** :
  - **Recherche pendant la frappe** : `useDebouncedValue` (300 ms, `hooks/useDebouncedValue.ts:16-24`) réduit le nombre de départs mais n'annule rien. Sur `pages/Encaissements.tsx:166-172`, chaque stabilisation de frappe lance **4 requêtes parallèles** ; si le réseau est lent, la réponse d'une frappe antérieure peut écraser une réponse plus récente (`setEncaissements` ligne 181, aucun garde de version). Le commentaire de `useDebouncedValue.ts:9-10` évoque explicitement le risque de « réponses qui reviennent dans le désordre » — le débounce ne le résout pas, seulement l'annulation ou un jeton de séquence le résout.
  - **Changement de page rapide** : les `useEffect` qui posent un drapeau `cancelled` (par ex. `PermissionsContext.tsx:33,50`, `ServiceDashboard.tsx`) protègent le `setState` mais **laissent la requête courir jusqu'au bout** — bande passante et travail serveur consommés pour un résultat jeté. Et beaucoup d'autres n'ont même pas ce drapeau (`Dashboard.tsx:503-513`, `Encaissements.tsx:277-287`, `Budget.tsx:236-260`).
- **Correctif** : ajouter `signal?: AbortSignal` à `ApiOptions` et le passer à `fetch` (une ligne dans `apiClient.ts:358-363`), traiter `AbortError` comme non-erreur dans le bloc `catch` réseau (`apiClient.ts:364-376`, sinon il déclencherait le retry !). Puis, dans les effets de recherche, créer un `AbortController` et l'abandonner dans la fonction de nettoyage.
- **Gain attendu** : suppression du travail serveur et du trafic obsolètes, et surtout **correction d'une classe de bug d'affichage** (résultat périmé écrasant le résultat courant). `[MESURÉ]` pour l'absence d'annulation ; `[DÉDUIT]` pour la fréquence réelle des courses.
- **Risque** : faible, **à condition** de traiter `AbortError` avant la logique de retry — sans quoi chaque annulation déclencherait 3 nouvelles tentatives espacées de 1,5 s / 3 s / 5 s.

### 🟡 #9 — Politique de retry : le refresh est correctement verrouillé, mais les retries se composent

- **Verrou de refresh : correct.** `apiClient.ts:425-431` :
  ```ts
  async function tryRefreshToken(): Promise<boolean> {
    if (refreshPromise) return refreshPromise
    refreshPromise = refreshTokenOnce().finally(() => { refreshPromise = null })
    return refreshPromise
  }
  ```
  N requêtes concurrentes recevant un 401 partagent **une seule** promesse de refresh, puis rejouent chacune leur requête une fois (`hasRetried = true`, `apiClient.ts:411-414`). **Pas de tempête de refresh.** C'est le bon design ; à préserver.
- **Le commit 3bcd556 n'a aucun impact sur les performances.** `[MESURÉ]` — il ne touche que `fallbackApiMessage`, `normalizeApiMessage` et le libellé d'une erreur réseau (`apiClient.ts:177-202, 204-253, 372`), plus les messages de refus 403 dans `backend/app/api/deps.py:481-580`. Aucune modification du séquencement, du retry ou du verrou.
- **Point d'attention réel — composition des retries** : trois mécanismes de reprise coexistent.
  1. Erreur réseau sur GET/DELETE → jusqu'à **3 tentatives**, délais `[1500, 3000, 5000]` ms (`apiClient.ts:55, 367-370`)
  2. Statut 502/503/504 sur GET/DELETE → **mêmes 3 tentatives** (`apiClient.ts:56, 378-385`)
  3. `refreshTokenOnce()` a **sa propre** boucle de 4 tentatives avec les mêmes délais (`apiClient.ts:435-467`)
  4. TanStack Query ajoute par-dessus `retry: 1` (`App.tsx:366`)
  - **Conséquence** `[DÉDUIT]` : au redémarrage du backend, une page de tableau de bord (≈ 7 GET parallèles) émet jusqu'à **28 requêtes** étalées sur ~9,5 s avant d'abandonner ; celles passées par `useQuery` peuvent doubler (`retry: 1`) → jusqu'à ~19 s de martèlement. Le rate limiter côté serveur (SlowAPI) peut alors répondre 429, message que l'utilisateur verra à la place de la vraie cause.
  - **Correctif** : un compteur d'échecs partagé (circuit breaker simple) coupant les retries après N échecs consécutifs sur la fenêtre courante ; et désactiver `retry` dans TanStack Query puisque `apiClient` reprend déjà (`App.tsx:366` → `retry: 0`).
  - **Risque** : faible.
- **Détail** : `shouldRetryTransientRequest` (`apiClient.ts:305-308`) rejoue les `DELETE` sur erreur réseau. `DELETE` est idempotent au sens HTTP, mais si un `DELETE` a abouti côté serveur et que seule la réponse s'est perdue, la reprise renverra un 404 — l'utilisateur verra « Ressource introuvable » alors que l'opération a réussi.

### 🟡 #10 — `adminListUsersAll` : pagination **séquentielle** côté client

- **Preuve** : `frontend/src/api/admin.ts:15-28` — boucle `while(true)` avec `await adminListUsers({ page, page_size: 200 })`, page par page, chaque page attendant la précédente.
- **Appels avant / après** : pour 900 utilisateurs, **5 allers-retours séquentiels**. La première réponse contient déjà `res.total` : les pages 2..N pourraient partir toutes ensemble → **2 hops**. Mieux : un endpoint dédié à la liste allégée.
- **Aggravant — payload jeté** : les deux appelants n'utilisent quasiment rien de l'objet `User` complet.
  - `frontend/src/components/UserRoleManager.tsx:37-38` — récupère **tous** les utilisateurs puis fait `adminListUserRoles()` **en séquence** (2 hops au lieu d'1 `Promise.all`), pour n'alimenter qu'une liste déroulante de noms.
  - `frontend/src/pages/Settings.tsx:420-427` — `loadServiceUsers` dans un `useEffect` dont les dépendances sont `[activeTab, users]` (ligne 428) : à chaque changement de la liste `users`, la pagination complète repart.
- **Correctif** : (a) paralléliser les pages 2..N ; (b) exposer `GET /admin/users?fields=id,nom,prenom,email` ou un endpoint `/admin/users/lookup` renvoyant une liste allégée ; (c) dans `UserRoleManager.tsx:37-38`, `Promise.all([adminListUsersAll(), adminListUserRoles()])`.
- **Gain attendu** : N hops → 2, et charge utile réduite au strict nécessaire. `[MESURÉ]` pour la structure ; `[DÉDUIT]` pour le volume (dépend du nombre réel d'utilisateurs par organisation).
- **Risque** : faible.

### 🟡 #11 — Deux appels `/dashboard/stats` là où un seul suffirait

- **Preuve** : `frontend/src/pages/Dashboard.tsx:280-281` — `getDashboardStats({...baseParams, devise: 'USD'})` **et** `getDashboardStats({...baseParams, devise: 'CDF'})`. Côté serveur, `devise` n'est qu'un filtre `WHERE` (`backend/app/api/v1/endpoints/dashboard.py:175-176, 243-244, 277-279`) : les deux réponses sont deux exécutions complètes de la même agrégation, sur deux clés de cache Redis distinctes (`dashboard.py:44-48`).
- **Appels avant / après** : **2 requêtes** → **1 requête** renvoyant `{ usd: {...}, cdf: {...} }`.
- **Correctif** : accepter `devise=ALL` (ou `devises=USD,CDF`) et renvoyer les deux ventilations en une réponse. Le client fait déjà exactement cette fusion en mémoire (`Dashboard.tsx:308-345`) — le regroupement est donc naturel.
- **Gain attendu** : −1 requête à chaque changement de période/filtre du tableau de bord, et −50 % d'entrées de cache Redis pour cet endpoint. `[MESURÉ]`
- **Risque** : faible (nouveau paramètre, rétrocompatible).

### 🟡 #12 — `<link rel="preconnect">` vers l'API sans `crossorigin` : préconnexion inutilisable

- **Preuve** : `frontend/index.html:12`
  ```html
  <link rel="preconnect" href="https://api.onec-rdc.org" />
  ```
  Or **toutes** les requêtes API partent avec `credentials: 'include'` (`apiClient.ts:362`). Une connexion préchauffée sans l'attribut `crossorigin` occupe une entrée de pool distincte de celle qu'utilisera un `fetch` crédenté : le navigateur **rouvre** une connexion (DNS déjà résolu, mais TCP + TLS repayés).
- **Correctif** : `<link rel="preconnect" href="https://api.onec-rdc.org" crossorigin />`. Un caractère de plus.
- **Gain attendu** : la préconnexion redevient effective — un handshake TLS économisé sur le tout premier appel (`/auth/refresh`), donc directement sur le hop 1 du chemin critique. `[DÉDUIT]` — l'effet dépend du déploiement (voir « non vérifié »).
- **Risque** : nul. Le commentaire de `index.html:9-11` montre que l'intention est déjà la bonne ; seul l'attribut manque.
- **Voisin** : `index.html:13-16` charge la feuille Google Fonts **de façon bloquante** dans `<head>`, ce qui insère une chaîne `googleapis → gstatic` devant le premier rendu, sur un hôte tiers. `media="print" onload="this.media='all'"` ou l'auto-hébergement de la police supprime ce blocage.

### 🟢 #13 — Le chunk du Tableau de bord n'est chargé qu'après la résolution des permissions

- **Preuve** : `App.tsx:22` (`lazy(() => import('./pages/Dashboard'))`) combiné à `App.tsx:189-191` — `ServiceAwareDashboard` rend un `PageLoader` tant que `permissionsLoading` est vrai, donc le `Suspense` n'est atteint (et le chunk demandé) qu'**après** le retour de `/permissions/menu`. `vite.config.ts:18-71` ne préchauffe aucun chunk de page.
- **Appels avant / après** : le téléchargement du chunk est aujourd'hui **sérialisé derrière** un aller-retour API. Après : parallélisé avec lui.
- **Correctif** : déclencher `import('./pages/Dashboard')` de façon spéculative dès que `POST /auth/login` réussit (et au montage de `AuthProvider` si `hasRefreshMarker()` est vrai) — un simple appel à la fonction d'import, dont le résultat est jeté ; `React.lazy` réutilisera le module déjà en cache.
- **Gain attendu** : recouvrement du téléchargement du chunk avec le hop `/permissions/menu`. `[DÉDUIT]`
- **Risque** : nul.

### 🟢 #14 — `GET /auth/discover-tenants` bloque la connexion pour un cas d'erreur rare

- **Preuve** : `frontend/src/pages/Login.tsx:209-219` — l'appel est `await`é avant `signIn` (ligne 226), et son unique usage est de refuser la soumission si `tenants.length > 1 && !tenantSlug`. Or ligne 194-197, la soumission est **déjà** refusée en amont si `!tenantSlug`. Le seul cas restant est donc : `tenantSlug` renseigné → la condition `!tenantSlug` est fausse → **le résultat n'est jamais utilisé**. L'échec de l'appel est d'ailleurs silencieusement ignoré (ligne 216-218), ce qui confirme qu'il n'est pas structurant.
- **Appels avant / après** : **1 aller-retour retiré** du chemin critique de connexion, dans le cas nominal.
- **Correctif** : supprimer l'appel de `handleSubmit` (le backend valide déjà l'appartenance au tenant lors du login), ou le déplacer sur le `onBlur` du champ e-mail, hors du chemin critique.
- **Gain attendu** : −1 hop séquentiel à la connexion. `[MESURÉ]` pour le décompte, `[DÉDUIT]` pour la neutralité fonctionnelle — à valider avec le métier.
- **Risque** : moyen (logique multi-tenant), d'où le classement bas malgré un gain net sur le chemin critique.

### 🟢 #15 — Téléversements / téléchargements

- **Fichiers joints : correct.** `backend/app/api/v1/endpoints/secure_uploads.py:53-58` renvoie un corps **vide** avec `X-Accel-Redirect: /_protected_uploads/…`, servi par Nginx en `internal` (`docs/nginx/backend-secure-uploads.conf:12-15`). Le fichier ne transite **jamais** par la mémoire du processus Python : c'est exactement le bon montage. `SERVE_UPLOADS_PUBLICLY` est à `false` par défaut (`backend/app/core/config.py:95`) et en prod (`docker-compose.prod.yml:44`). Rien à corriger. **Manque seulement** un `Cache-Control` sur ces réponses : logos, cachets et pièces jointes sont immuables et retéléchargés à chaque affichage.
- **Exports Excel : matérialisés en RAM.** `backend/app/utils/excel_io.py:22-32` — `wb.save(BytesIO())` construit le classeur **entier** en mémoire avant le premier octet envoyé ; `exports.py:149-154` l'enveloppe ensuite dans un `StreamingResponse` qui ne streame donc rien de réel. Sur un export à `limit: 5000` (`Rapports.tsx:889`), la mémoire du worker croît proportionnellement au nombre de lignes, et le **temps jusqu'au premier octet** est celui de la génération complète. `anyio.to_thread.run_sync` (ligne 32) préserve au moins la boucle d'événements — le point positif. `[MESURÉ]` pour la structure ; `[DÉDUIT]` pour l'empreinte réelle.
- **Gaspillage CPU sur les exports** : `GZipMiddleware` (`backend/app/main.py:75`, `minimum_size=1000`) recompresse les réponses `.xlsx`, qui sont **déjà** des archives ZIP. Coût CPU réel, gain de taille quasi nul. Correctif : exclure les types `application/vnd.openxmlformats-*`, `application/pdf` et `application/zip`.
- **Téléchargements côté client** : tous passent par `resp.blob()` → `URL.createObjectURL` (`utils/download.ts:34-35, 67-68, 95-96`, `pages/AuditLogs.tsx:293-295`, `ClotureCaisse.tsx:267-269`, etc.). Le fichier est donc intégralement bufferisé dans l'onglet avant d'être proposé. C'est imposé par le besoin d'envoyer l'en-tête `Authorization` — acceptable, mais à surveiller pour les gros exports sur poste modeste.

### 🟢 #16 — Statique bien réglé, HTTP/2 apparemment absent

- **Positif** `[MESURÉ]` : `frontend/nginx.conf:14-35` (gzip, niveau 6, bonne liste de types), `:65-78` (assets hashés en `immutable, 1y`), `:37-53` (`index.html` en `no-cache`, et le commentaire explique correctement le piège nginx du `add_header` qui écrase les en-têtes hérités). `backend/app/main.py:75` (gzip côté API, `compresslevel=6`, placé le plus à l'extérieur de la pile — commentaire juste). C'est du travail soigné.
- **Manque** `[DÉDUIT]` : aucun `http2` ni `listen 443` dans les deux seuls fichiers `.conf` du dépôt (`frontend/nginx.conf:2`, `docs/nginx/backend-secure-uploads.conf:2` — tous deux `listen 80;`). Si le terminal TLS de production ne parle qu'HTTP/1.1, le navigateur plafonne à **6 connexions par origine** : le fan-out de 7 requêtes du hop 4b se scinde alors en **2 vagues sérialisées**, ce qui ajoute un aller-retour invisible au chemin critique. Sous HTTP/2, tout ce fan-out tient en une vague. À vérifier sur l'infrastructure réelle (voir « non vérifié »).
- **CORS** : `backend/app/main.py:47-55` n'indique pas de `max_age` → défaut Starlette de 600 s. **Sans effet dans le déploiement du dépôt** (`docker-compose.prod.yml` ne passe pas `VITE_API_BASE_URL`, donc `apiClient.ts:36-39` retombe sur `/api/v1` **même origine** via le proxy `frontend/nginx.conf:55-63` : aucun préflight). Mais `index.html:12` et la CSP `connect-src https://api.onec-rdc.org` (`frontend/nginx.conf:9`) indiquent qu'un déploiement **cross-origin** existe. Dans ce cas, chaque URL distincte exige son propre `OPTIONS` — soit ~10 préflights supplémentaires au premier chargement du tableau de bord, renouvelés toutes les 10 minutes. Correctif si ce mode est utilisé : `max_age=7200` (plafond Chrome).

---

## 3. Hiérarchie : les 3 changements qui réduisent le plus le temps perçu

| # | Changement | Effet sur le chemin critique | Confiance | Effort |
|---|---|---|---|---|
| **1** | **Fusionner le démarrage de session** — `refresh`/`login` renvoient `user` + `menu_permissions` + `organisation_settings` (constat #1) | **−2 allers-retours séquentiels** au démarrage **et** à la connexion. Débloque aussi le fan-out du tableau de bord un cran plus tôt et rend le constat #13 sans objet | Élevée (décompte exact) | Moyen |
| **2** | **Supprimer le `setTimeout(…, 650)` de `Login.tsx:230`** (constat #2) — et, dans la foulée, précharger le chunk `Dashboard` dès le succès du login (constat #13) et retirer `discover-tenants` du chemin critique (constat #14) | **−650 ms fermes**, plus 1 hop et 1 téléchargement de chunk retirés de la sérialisation | Maximale pour les 650 ms (valeur codée en dur) | Trivial |
| **3** | **Cache HTTP + TanStack Query sur les référentiels** (constats #3, #4, #5) — `Cache-Control`/`ETag` côté API sur `/print-settings`, `/services`, `/comptes-bancaires`, `/organisation/settings` ; ces GET routés par `useQuery` ; `/ai/cash-forecast` dédupliqué entre `Layout` et `Dashboard` | N'améliore pas le **premier** chargement, mais rend **toutes** les navigations suivantes quasi instantanées — c'est là que se joue le ressenti quotidien d'un outil de gestion | Élevée (0 en-tête de cache dans tout le backend : fait vérifié) | Moyen |

Le constat #7 (`Settings.tsx`, 11 hops séquentiels) donne le plus gros ratio gain/effort du rapport — 11 hops → 1 par une transformation mécanique en `Promise.allSettled` — mais il ne concerne qu'une page d'administration, donc pas le temps perçu quotidien.

---

## 4. Ce que je n'ai pas pu vérifier

1. **Toute latence réelle.** Docker est arrêté : aucune requête n'a été émise, aucun temps de réponse, aucune taille de charge utile en octets n'a été observée. Tous les chiffres de ce rapport sont des **décomptes d'appels lus dans le code**. La seule durée citée (650 ms) l'est parce qu'elle est écrite en dur.
2. **La topologie réelle de production.** Le dépôt contient deux configurations Nginx en `listen 80;` sans TLS ni `http2`. Impossible de savoir si le terminal TLS réel active HTTP/2 (voire HTTP/3), ce qui change complètement l'analyse du fan-out (6 connexions max en HTTP/1.1 vs multiplexage). **Point à vérifier en premier** sur l'instance : `curl -I --http2 https://…`.
3. **Si le déploiement est same-origin ou cross-origin.** `docker-compose.prod.yml` ne passe pas `VITE_API_BASE_URL` (donc same-origin via le proxy Nginx, pas de préflight), mais `index.html:12` et la CSP visent `https://api.onec-rdc.org`. Le coût réel des préflights CORS (constat #16) en dépend entièrement.
4. **Les tailles de réponse.** Je peux affirmer que `/services`, `/print-settings` ou `adminListUsersAll` sont appelés N fois ; je ne peux pas dire s'ils pèsent 2 Ko ou 200 Ko. Un `SELECT` réel ou un simple `curl` sur l'API vivante trancherait — et changerait le classement des constats #3 et #10.
5. **La valeur de N dans les motifs N+1** (constat #6) — nombre réel de réquisitions par période, de services par organisation. Les `limit: 5000` dans `Rapports.tsx` et `Requisitions.tsx` disent ce que le code **autorise**, pas ce que les données contiennent.
6. **Si Redis est effectivement branché en production.** `core/cache.py` avale les exceptions en `logger.debug` (lignes 54, 66) : un Redis absent dégrade silencieusement tous les caches serveur (tableau de bord, rapports, contexte d'auth, résolution de tenant) sans qu'aucune alerte ne le signale.
7. **Le comportement de `React.StrictMode`** (`main.tsx:7`). En développement il double le montage des effets, donc double les appels de `AuthContext`, `PermissionsContext` et `OrganisationSettingsContext`. C'est un artefact de développement uniquement — mais il fausse toute lecture de l'onglet Réseau en `npm run dev`, ce dont il faut tenir compte avant de conclure à une régression.
8. **Le rendu React et le coût SQL** — hors périmètre, confiés aux deux autres audits. Je note simplement que le constat #11 (double `/dashboard/stats`) et le constat #6 (N+1) ont un versant SQL qui mérite d'être recoupé avec l'audit base de données.
