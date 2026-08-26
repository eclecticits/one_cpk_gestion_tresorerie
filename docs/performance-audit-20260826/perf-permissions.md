# Audit de performance — écran Paramètres & système de permissions

**Dépôt** : `/mnt/d/Projet_dev_ck/onec_smart` — branche `perf-write-contention-validation-20260803`
**Base auditée** : état d'après `425c3d9` (« Permissions : le nouvel éditeur par rôle remplace la matrice »).
**Mode** : lecture seule, aucun fichier modifié.
**Exécution** : Docker indisponible → aucun profilage runtime, aucune mesure SQL réelle.
Seule mesure réellement exécutée : `npm run build` (build de production Vite).

Convention :
- **MESURÉ** = obtenu par exécution (build) ou par comptage exact dans le code.
- **DÉDUIT** = raisonnement sur le code, non vérifié à l'exécution.

---

## Résumé exécutif

Deux univers très différents.

**Le chemin d'évaluation des permissions (tout le trafic) est déjà optimisé et je n'y trouve pas de gain majeur.**
Contrairement à l'hypothèse de la mission, une vérification de permission ne déclenche **aucune requête SQL**
sur le chemin nominal : `get_current_user` construit un `AuthUser` porteur d'un `frozenset` de codes, et chaque
garde n'y fait qu'un test d'appartenance O(1). Un endpoint qui vérifie 3 permissions fait 3 tests de `frozenset`,
pas 3 requêtes. Les résidus sont réels mais petits (§B1–B4) et le principal point d'attention n'est pas la
performance mais la **sécurité du TTL de 30 s** (§S1).

**L'écran Paramètres, lui, a un vrai défaut structurel** : `loadData()` est une cascade **strictement séquentielle
de 11 appels API**, exécutée intégralement quel que soit l'onglet demandé. Pour
`/settings?tab=permissions&sub=permissions`, **13 appels partent au montage, 2 sont utiles** (§F1). C'est le
constat n°1 par gain × confiance, mais son impact est borné à un écran d'administration.

Le nouvel éditeur `RolePermissionsEditor` a des recalculs non mémoïsés réels et faciles à corriger (§F2, §F3),
mais leur coût absolu est modeste ; je ne les gonfle pas.

**Une régression de performance a bien été introduite par `425c3d9`**, mais pas là où on l'attendait : ce n'est pas
le `adminGetRoles()` après sauvegarde (négligeable), c'est le passage à « une sauvegarde par rôle » qui **multiplie
par le nombre de rôles édités les purges globales du cache d'authentification** (§B5).

---

## Classement par (gain × confiance)

| # | Constat | Périmètre | Gain | Confiance |
|---|---|---|---|---|
| F1 | `loadData()` : 11 appels séquentiels, 13 au montage, 2 utiles | Écran Paramètres | Élevé | Élevée |
| B5 | Purge globale du cache auth à **chaque** sauvegarde de rôle (régression `425c3d9`) | Tout le trafic (par à-coups) | Moyen | Élevée |
| B1 | `require_module` / `require_ai_enabled` : 1 SQL `OrganisationSettings` par requête, non caché | RH + Compta + Secrétariat (~74+ routes) | Moyen | Élevée |
| B2 | Copies locales de `_user_has_permission` qui ignorent le cache | RH, ordres de décaissement | Faible-moyen | Élevée |
| F2 | `countFor` / `spreadFor` appelés en ligne pour chaque carte de rôle, à chaque rendu | Éditeur de permissions | Faible | Élevée |
| F3 | `grantedTotal` non mémoïsé + `normalize()` recalculé à chaque frappe | Éditeur de permissions | Faible | Élevée |
| B3 | `has_permission` : 1 SQL `Role.code` sur **chaque** refus 403 | Tout le trafic (chemin de refus) | Faible | Élevée |
| B4 | `/permissions/menu` réinterroge `role_permissions` alors que le contexte les porte | 1×/session | Négligeable | Élevée |
| F4 | Barre latérale : filtrage O(nœuds) à chaque rendu | Layout | Négligeable | Élevée |
| S1 | **Sécurité** : décision de permission cachée 30 s — latence de révocation | Tout le trafic | — | Élevée |

---

# A. Le chemin d'évaluation des permissions à l'exécution

## A0. Ce que fait réellement une vérification de permission — le fait central

**MESURÉ (lecture de code, chemin complet tracé).**

`get_current_user` (`backend/app/api/deps.py:217`) ne renvoie **jamais** une instance ORM `User` : il renvoie un
`AuthUser` (`backend/app/core/auth_user.py:20`), objet détaché `@dataclass(slots=True)` qui **porte déjà**
l'ensemble des permissions et des services :

```python
# backend/app/core/auth_user.py:34-35
permission_codes: frozenset[str] = field(default_factory=frozenset)
service_ids: tuple[int, ...] = ()
```

```python
# backend/app/api/deps.py:244-252
cache_key = _auth_context_cache_key(user_id)
ctx = await cache_get(cache_key) if settings.auth_context_cache_enabled else None
if ctx is None:
    ctx = await _load_auth_context(db, user_id=user_id)
    if ctx is not None and settings.auth_context_cache_enabled:
        await cache_set(cache_key, ctx, ttl=settings.auth_context_cache_ttl_seconds)
...
user = AuthUser.from_context(ctx)
```

Conséquence décisive : **que le cache Redis touche ou non**, `user.permission_codes` est peuplé. Le
`frozenset` provient soit de Redis, soit d'un `_load_auth_context` frais. Donc dans `has_permission` :

```python
# backend/app/api/deps.py:564-566
user_permissions = cached_permission_codes(user)
...
if user_permissions is not None and resolved_permission_code in user_permissions:
    return user
```

`cached_permission_codes` renvoie `None` **uniquement** si l'objet n'est pas un `AuthUser`
(`backend/app/core/auth_user.py:57-65`). Sur du trafic HTTP, ce n'est jamais le cas.

### Réponses directes aux questions de la mission

**« Combien de requêtes SQL une seule vérification de permission déclenche-t-elle ? »**
**Zéro**, sur le chemin nominal (accès accordé). Un test d'appartenance dans un `frozenset` — O(1),
de l'ordre de la centaine de nanosecondes. Sur le chemin de refus, **une** requête parasite (§B3).

**« Y a-t-il un cache par requête, ou l'appel est-il refait pour chaque garde ? »**
Il y a **deux** niveaux de cache, et ils fonctionnent :
1. **Cache par requête** : FastAPI mémoïse les sous-dépendances par requête (`use_cache=True` par défaut ;
   `grep -rn "use_cache" backend/app` → **0 occurrence**, donc aucune désactivation — MESURÉ).
   Toutes les gardes déclarent `Depends(get_current_user)`, le **même objet callable** : `get_current_user`
   ne s'exécute donc **qu'une fois par requête HTTP**, quel que soit le nombre de gardes.
2. **Cache inter-requêtes** : `authctx:v1:{user_id}` dans Redis, TTL 30 s
   (`backend/app/core/config.py:87-88`, `docker-compose.yml:72-73`).

**« Un endpoint qui vérifie 3 permissions fait-il 3 fois le travail ? »**
**Non.** Cas concret vérifiable — `GET /api/v1/encaissements` empile quatre évaluations :

| Niveau | Fichier:ligne | Garde |
|---|---|---|
| routeur v1 | `backend/app/api/v1/router.py:111` | `has_any_permission(["encaissements","sorties_fonds","requisitions"])` |
| routeur module | `backend/app/api/v1/endpoints/encaissements.py:71` | `has_permission("menu_encaissements")` |
| handler | `backend/app/api/v1/endpoints/encaissements.py:810` | `_user_has_permission(..., "view_cancelled_financial_operations")` |
| handler | `backend/app/api/v1/endpoints/encaissements.py:814` | `has_module_menu_access(..., "menu_encaissements")` |

Coût total : **1 exécution de `get_current_user`** (1 `GET` Redis, ou 4 SQL si le cache rate) + **4 tests de
`frozenset`**. Pas 4 fois le travail.

**Ce que couvre réellement le cache d'authentification** (`_load_auth_context`, `backend/app/api/deps.py:84-160`) —
MESURÉ, 4 requêtes SQL exactement :

| # | Requête | Ligne |
|---|---|---|
| 1 | `User ⟕ Organisation` (identité, rôle, `role_id`, `service_id`, `organisation_id`, flags, statut d'abonnement) | `deps.py:91-110` |
| 2 | `Permission.code ⋈ role_permissions WHERE role_id = …` | `deps.py:117-124` |
| 3 | `user_services.service_id WHERE user_id = …` | `deps.py:129-133` |
| 4 | `CommissionMember.service_id ⋈ Service WHERE user_id = …` | `deps.py:135-141` |

Le raccourci `admin`/`super_admin` (`deps.py:116`) saute la requête 2 : 3 SQL pour un admin.

**Ce que le cache NE couvre PAS** (et qui reste à la charge de chaque requête) :
- `OrganisationSettings` → `require_module` et `require_ai_enabled` (§B1). **C'est le seul vrai coût SQL
  par requête restant sur le chemin des gardes.**
- `Organisation` quand le tenant est résolu par slug pour un super-admin (`deps.py:308-315`) — cas marginal.
- Le statut SaaS sur les écritures — mais il a son propre cache Redis (`deps.py:186-206`).
- Les copies locales de `_user_has_permission` en RH et ordres de décaissement (§B2).
- `Role.code` sur le chemin de refus (§B3).

### Ce que cela implique pour les recommandations

Les fallbacks SQL de `has_permission` (`deps.py:585-592`), `has_any_permission` (`deps.py:526-533`) et
`user_has_permission` (`backend/app/services/service_access.py:73-81`) sont **du code mort pour le trafic HTTP** :
ils ne s'exécutent que si un appelant passe un vrai `User` ORM (tâches de fond, scripts). Ils ne coûtent rien.
Idem pour `can_view_all_services` (`service_access.py:84-91`), qui enchaîne jusqu'à 4 appels à
`user_has_permission` : avec un `AuthUser`, ce sont 4 tests de `frozenset`, pas 4 requêtes.
`lignes_requisition.py:70,77,134` l'appelle trois fois dans le même handler — **gratuit** ici, mais ce serait
12 requêtes SQL si un `User` ORM y transitait un jour.

**Correctif proposé (hygiène, pas performance)** : les annotations `user: User` dans `deps.py` et
`service_access.py` mentent sur le type réel (`AuthUser`). Les passer en `User | AuthUser` (comme
`service_access.py:31` le fait déjà) documenterait que le chemin SQL est un fallback et éviterait qu'un futur
refactor le remette dans le chemin chaud sans s'en apercevoir. **Gain : 0 aujourd'hui. Risque : nul.**

---

## B1. `require_module` / `require_ai_enabled` : 1 SQL par requête, non caché

**MESURÉ** (comptage exact des montages et des routes).

```python
# backend/app/api/deps.py:637-646
res = await db.execute(
    select(OrganisationSettings)
    .where(OrganisationSettings.organisation_id == org_id)
    .limit(1)
)
```

Monté au niveau **routeur**, donc sur **toutes** les routes du module :

```
backend/app/api/v1/router.py:143  hr.router                       → require_module("rh")
backend/app/api/v1/router.py:147  secretariat.router              → require_module("secretariat")
backend/app/api/v1/router.py:148-151  comptabilite ×4             → require_module("comptabilite")
```

**Coût quantifié (MESURÉ)** : `grep -c "@router\.(get|post|put|patch|delete)"` →
`hr.py` = **45 routes**, `comptabilite/routers/{ecritures,parametrage,restitutions,etats}.py` = **12+9+3+5 = 29
routes**, plus le module secrétariat (sous-routeurs, non comptés). Soit **≥ 74 endpoints** qui paient
**1 SELECT `OrganisationSettings` supplémentaire par requête**, en plus du `GET` Redis du contexte auth.

`require_ai_enabled` (`deps.py:608-618`) fait la même requête, sur 11 points de montage (MESURÉ), et n'est
**pas** mutualisé avec `require_module` : un endpoint IA du module RH paie les **deux** (2 SELECT identiques,
FastAPI ne mémoïse pas entre deux callables distincts).

**Correctif proposé** : ajouter `modules_config` / `is_ai_enabled` au contexte d'authentification déjà caché
(`_load_auth_context` renvoie déjà `org_id`, `org_uuid`, `plan_status` — la jointure `OrganisationSettings`
s'ajoute à la requête 1 sans requête supplémentaire), ou lui donner son propre cache Redis par
`organisation_id` sur le modèle de `get_cached_saas_status` (`deps.py:186-206`).

**Gain attendu et son fondement** : suppression de 1 (parfois 2) requête SQL sur ≥ 74 endpoints. Fondement :
comptage exact des montages, plus l'absence de tout `cache_get` dans `require_module`. **DÉDUIT** pour la part
« combien de ms » — je n'ai aucune mesure de latence.

**Risque SÉCURITÉ** : réel mais maîtrisable. Cacher `modules_config` signifie qu'une désactivation de module
n'est effective qu'après expiration du TTL. Contrairement aux permissions de rôle, je **ne trouve aucun appel à
`invalidate_auth_context_cache` sur les écritures d'`OrganisationSettings`** — il faudrait en ajouter un, sinon
on remplace une garantie immédiate par une garantie à 30 s. À décider explicitement : la désactivation d'un
module est un geste commercial/contractuel, pas une révocation de sécurité, donc 30 s de latence est sans doute
acceptable — mais ce doit être un choix assumé, pas un effet de bord.

---

## B2. Copies locales de `_user_has_permission` qui contournent le cache

**MESURÉ.** Le projet contient **trois** implémentations privées de la même fonction. Une seule consulte le cache.

**Correcte** — `backend/app/api/v1/endpoints/encaissements.py:456-471` :
```python
resolved_permissions = cached_permission_codes(user)
if resolved_permissions is not None:
    return permission_code in resolved_permissions
```

**Contourne le cache** — `backend/app/api/v1/endpoints/hr.py:108-122` :
```python
async def _user_has_permission(db: AsyncSession, user: User, code: str) -> bool:
    if (user.role or "").lower() in {"admin", "super_admin"}:
        return True
    if not user.role_id:
        return False
    res = await db.execute(
        select(Permission.id)
        .join(role_permissions, role_permissions.c.permission_id == Permission.id)
        .where(role_permissions.c.role_id == user.role_id, Permission.code == code)
        .limit(1)
    )
    if res.scalar_one_or_none() is not None:
        return True
    role_res = await db.execute(select(Role.code).where(Role.id == user.role_id))
    return (role_res.scalar_one_or_none() or "").lower() == "admin"
```
Aucun `cached_permission_codes` : **1 SQL si accordé, 2 SQL si refusé**, à chaque appel.

**Contourne le cache** — `backend/app/api/v1/endpoints/ordres_decaissement.py:58-71` : même schéma, 1 SQL.

**Coût quantifié (MESURÉ, points d'appel)** :
- `hr.py:164` (tableau de bord RH), `hr.py:297` (liste des contrats), `hr.py:310`, `hr.py:333` — un appel par
  requête, hors boucle. **+1 à +2 SQL sur 4 endpoints RH**, dont deux listes probablement très sollicitées.
- `ordres_decaissement.py:228` (`can_direct_disbursement`), `:322` (`can_authorize_disbursement`) — **+1 SQL**
  sur deux écritures.

Rapporté à la requête `hr.py:297` : la liste des contrats fait 1 SELECT métier + 1 SELECT permission, soit
**+100 % de requêtes** sur cet endpoint (DÉDUIT du décompte des `db.execute` dans le handler).

**Correctif proposé** : supprimer les copies et importer
`app.services.service_access.user_has_permission`, qui gère déjà le cas `AuthUser`
(`service_access.py:58-81`). Attention à un écart de comportement : la version RH accorde l'accès si
`Role.code == "admin"` même quand `User.role` ne vaut pas `admin` ; `user_has_permission` ne le fait pas.
Cette différence doit être tranchée avant unification — elle peut **retirer** un accès à un compte dont
`User.role` et `Role.code` divergent.

**Gain attendu** : −1 à −2 SQL sur 6 endpoints. **Fondement** : comptage exact des `db.execute` dans les
fonctions concernées. **Risque** : moyen, à cause de l'écart de comportement ci-dessus. Non nul.

---

## B3. `has_permission` : une requête SQL parasite sur chaque refus

**MESURÉ.** `backend/app/api/deps.py:584-602` :

```python
granted = False
if user_permissions is None:
    perm_query = (...)
    granted = (await db.execute(perm_query)).scalar_one_or_none() is not None

if not granted:
    # allow admin by role table if role_id resolves to admin
    role_res = await db.execute(select(Role.code).where(Role.id == user.role_id))
    role_code = (role_res.scalar_one_or_none() or "").lower()
    if role_code != "admin":
        raise HTTPException(status_code=403, ...)
```

Quand le contexte est disponible (cas nominal), `user_permissions is not None`, donc le bloc `if` est sauté et
`granted` reste `False` — **le `select(Role.code)` s'exécute systématiquement à chaque refus**, alors même que
le commentaire juste au-dessus (`deps.py:582-583`) affirme que « l'absence du code vaut refus, sans requête ».
Le code contredit son propre commentaire.

**Coût quantifié** : 1 SQL par réponse 403 issue de `has_permission`. Sur du trafic normal c'est marginal ;
sur une UI mal filtrée qui sonde des endpoints interdits, ou sous un scan, cela devient un amplificateur de
charge DB piloté par un appelant non autorisé — un petit vecteur de DoS asymétrique. `has_any_permission`
(`deps.py:536-543`) n'a **pas** ce défaut : il refuse sans requête.

**Correctif proposé** : garder la vérification `Role.code` uniquement dans la branche `user_permissions is None`,
c'est-à-dire l'aligner sur `has_any_permission`.

**Risque SÉCURITÉ** : **attention, ce correctif retire un accès.** Un utilisateur dont `Role.code == "admin"`
mais dont `User.role` ne vaut pas `"admin"` passe aujourd'hui grâce à cette requête et serait refusé après.
Il faut d'abord vérifier en base qu'aucun compte n'est dans cet état (requête impossible ici, Docker mort).
À défaut, l'alternative sans risque est de résoudre `Role.code` **une fois** dans `_load_auth_context` et de le
stocker dans le contexte : même sémantique, zéro requête.

---

## B4. `/permissions/menu` réinterroge la base

**MESURÉ.** `backend/app/api/v1/endpoints/permissions.py:28-35` refait
`select(Permission.code) ⋈ role_permissions WHERE role_id = …` alors que `user.permission_codes` porte
exactement ce résultat. Idem `get_user_service_ids` juste après (`permissions.py:40`) — celui-ci, lui,
consulte bien le cache (`service_access.py:29-32`).

**Coût** : 1 SQL évitable, **une fois par session frontend** (`PermissionsContext` n'appelle
`getMenuPermissions()` que sur changement de `user?.id` —
`frontend/src/contexts/PermissionsContext.tsx:24,50`). **Impact négligeable**, cité pour cohérence.

**Risque** : nul (mêmes données, même fraîcheur que toutes les autres gardes).

---

## B5. RÉGRESSION `425c3d9` : purge globale du cache à chaque sauvegarde de rôle

**MESURÉ (code) + DÉDUIT (effet de charge).** C'est la vraie régression de performance du rebranchement,
et elle n'est pas là où la mission la cherchait.

```python
# backend/app/api/v1/endpoints/admin.py:1023-1027
await db.commit()
# Une modification de rôle impacte tous ses porteurs : on ne peut pas cibler
# les utilisateurs concernés sans requête supplémentaire, on purge donc tout
# le namespace (opération d'administration, rare).
await invalidate_auth_context_cache()
```

`invalidate_auth_context_cache(None)` → `cache_delete_pattern("authctx:v1:*")`
(`deps.py:82`), qui itère en `SCAN` sur tout le keyspace Redis (`backend/app/core/cache.py:80-89`).
**Toutes** les entrées de contexte de **tous** les utilisateurs de **tous** les tenants sont détruites.
Chaque utilisateur actif repaie ensuite **4 requêtes SQL** (§A0) à sa requête suivante — un effet de
troupeau (*thundering herd*) proportionnel au nombre de sessions actives.

**Ce que `425c3d9` a changé** : le commit indique explicitement que « l'ancienne matrice réécrivait tous les
codes de tous les rôles à chaque sauvegarde », en **un seul** `PUT /admin/role-permissions`. Le nouvel éditeur
enregistre **un rôle à la fois** :

```tsx
// frontend/src/pages/Settings.tsx:289
await adminUpdateRolePermissions({ roles: [{ role_id: roleId, permission_codes: permissionCodes }] })
```

Or l'invalidation est **hors** de la boucle `for role_update in payload.roles` (`admin.py:987`), donc son coût
est **par appel HTTP**, pas par rôle.

**Coût quantifié** : un administrateur qui ajuste **N rôles** déclenche désormais **N** purges globales
(N × `SCAN` complet + N × effet de troupeau), là où l'ancienne matrice en déclenchait **1**. Pour N = 6 rôles
et 100 sessions actives : **~2 400 requêtes SQL** de reconstruction de contexte au lieu de ~400 (DÉDUIT :
6 purges × 100 utilisateurs × 4 SQL).

Le commentaire du code — « opération d'administration, rare » — était juste avec l'ancienne matrice ;
le nouveau flux le rend faux.

**Correctif proposé** : cibler la purge. Le prix de la précision est **une** requête —
`SELECT id FROM users WHERE role_id = :role_id` — puis `invalidate_auth_context_cache(uid)` par porteur.
Un rôle a typiquement bien moins de porteurs que le keyspace ne compte de sessions. Le commentaire dit
« on ne peut pas cibler les utilisateurs concernés sans requête supplémentaire » : c'est exact, mais cette
requête supplémentaire est **beaucoup** moins chère que la purge totale.

**Gain attendu** : purge de O(porteurs du rôle) au lieu de O(toutes les sessions), et suppression de l'effet
de troupeau multi-tenant. **Fondement** : lecture du code d'invalidation + du nouveau flux de sauvegarde.
**Risque SÉCURITÉ** : ⚠️ **c'est le point délicat.** Un ciblage incomplet laisse des permissions révoquées
actives jusqu'à 30 s. Il faut purger les porteurs **avant et après** le changement (un `role_id` ne change pas
ici, donc l'ensemble est stable — mais la règle générale s'applique) et **conserver la purge globale en
repli** si la requête de ciblage échoue. Ne jamais remplacer un `delete_pattern` par un ciblage sans filet.

**Sur la question posée par la mission** — `handleSaveRolePermissions` refait `adminGetRoles()` après chaque
sauvegarde (`Settings.tsx:294`) : **acceptable**. `list_roles` (`admin.py:942-966`) n'est **pas** un N+1 :

```python
res = await db.execute(select(Role).order_by(Role.code.asc()))          # 1 requête
all_perm_res = await db.execute(                                        # 1 requête, tous rôles
    select(role_permissions.c.role_id, Permission.code)
    .join(Permission, role_permissions.c.permission_id == Permission.id)
    .where(role_permissions.c.role_id.in_([role.id for role in roles]))
)
```
**2 requêtes SQL au total** (MESURÉ), agrégation en Python via `perm_codes_by_role`. La charge utile est de
l'ordre de N_rôles × ~91 codes — quelques dizaines de Ko au pire. Un refetch par sauvegarde est un prix
raisonnable pour garantir la cohérence de l'affichage. **Rien à corriger ici.**

**Quant au « DELETE + INSERT massif »** (`admin.py:986-1013`) : par rôle, **5 requêtes** — SELECT des anciens
codes (pour l'audit), DELETE des liaisons du rôle, SELECT des `Permission` par code, INSERT en lot
(`executemany`), plus le `log_action`. Le DELETE est **borné au seul `role_id`**, pas à toute la table.
C'est correct et, depuis `425c3d9`, **moins** coûteux qu'avant par sauvegarde (1 rôle au lieu de tous).
Le problème n'est pas l'écriture, c'est l'invalidation qui la suit.

---

## S1. SÉCURITÉ — ce que coûte le fait de cacher une décision de permission

Le cache d'authentification est un cache de **décision d'autorisation**. C'est exactement la catégorie de
cache qui peut ouvrir un accès indu. Analyse de sa sûreté actuelle :

**Ce qui est bien fait :**
- Clé par utilisateur seul (`deps.py:60-68`), documentée : ni le hint de tenant ni l'org du jeton n'entrent
  dans le contenu, donc pas de risque de collision inter-tenant sur la clé.
- Le drapeau `active` est revérifié à chaque requête et **purge la clé** en cas de désactivation
  (`deps.py:254-257`) — une désactivation prend effet à la requête suivante, pas au bout de 30 s.
- La résolution de tenant, le conflit de hint, le statut d'abonnement sur les écritures et l'obligation de
  changer de mot de passe sont **hors** cache et réévalués à chaque requête (`deps.py:271-378`).
- L'invalidation ciblée est appelée sur les bons chemins d'écriture (**MESURÉ**, 15 sites) :
  `admin.py:498,621,662,705,787,830` (modifications d'utilisateur, statut, mots de passe),
  `admin.py:1026` (permissions de rôle, globale), `auth.py:371,393`,
  `services.py:1294,1396,1487,1521` (appartenance aux commissions/services, qui alimente `service_ids`),
  `super_admin.py` (globale).

**Les angles morts que j'identifie :**

1. **Latence de révocation de 30 s sur tout chemin d'écriture non instrumenté.** Toute modification de
   `role_permissions`, `user_services` ou `commission_members` faite **hors** de ces 15 sites — migration,
   script d'admin, seed, correction SQL manuelle, futur endpoint — laisse un droit révoqué **actif jusqu'à
   30 s**. C'est le compromis assumé du design ; il doit être documenté comme une **règle d'ingénierie** :
   *toute écriture sur les tables RBAC ou d'appartenance doit appeler `invalidate_auth_context_cache`.*

2. **L'invalidation échoue en silence.** `cache_delete` / `cache_delete_pattern` avalent `RedisError` et
   renvoient `False`/`0` (`cache.py:68-77`, `:80+`), et **aucun appelant ne teste la valeur de retour**
   (vérifié sur les 15 sites). Si Redis a un hoquet au moment précis d'une révocation, celle-ci est perdue et
   le droit reste actif 30 s de plus, **sans aucune trace au-dessus du niveau `debug`**. Correctif suggéré :
   journaliser en `warning` un échec d'invalidation sur un chemin de révocation. Coût nul, valeur défensive
   réelle.

3. **`delete_role` (`admin.py:1107-1136`) n'invalide pas.** Analysé : il refuse de supprimer un rôle porté par
   un utilisateur (`admin.py:1121-1123`), donc aucun contexte caché ne peut référencer ce `role_id`.
   **Pas de faille** — mais c'est une sûreté qui repose sur cette garde précise ; si elle disparaissait,
   le trou apparaîtrait.

4. **`modules_config` — ne pas céder à la tentation.** Le correctif §B1 consiste à cacher `modules_config`.
   Je le recommande, mais **avec** un appel d'invalidation sur les écritures d'`OrganisationSettings`,
   que je ne trouve nulle part aujourd'hui. Sans lui, la désactivation d'un module deviendrait effective
   à retardement.

5. **Ne pas descendre le TTL comme réflexe de sécurité.** Passer de 30 s à 5 s multiplierait par 6 la charge
   de `_load_auth_context` (4 SQL) sans supprimer la fenêtre. Le bon levier est l'invalidation ciblée
   exhaustive, pas le raccourcissement du TTL.

---

# C. L'écran Paramètres

## F1. `loadData()` charge tout, séquentiellement, quel que soit l'onglet — **constat n°1**

**MESURÉ (comptage exact des `await` dans le code).**

`frontend/src/pages/Settings.tsx:516-563`. Onze appels API, **tous en `await` successifs**, aucun `Promise.all` :

```tsx
const printSettingsRes  = await adminGetPrintSettings()              // :520
const tenantSettingsRes = await getOrganisationSettings()            // :521
const mappings          = await getComptaMappings()                  // :524
notificationSettingsRes = await adminGetNotificationSettings()       // :531
weeklyStatusRes         = await adminGetWeeklyReportStatus()         // :537
const rolesRes          = await adminGetRoles()                      // :541  ← utile
const permissionsRes    = isSuperAdmin ? await adminGetPermissions() : []  // :542  ← utile
const approversData     = await adminListRequisitionApprovers()      // :543
const exercisesRes      = await getBudgetExercises()                 // :544
const servicesRes       = await getServices()                        // :545
await loadUsers()                                                    // :560 → adminListUsers (:497)
```

Déclenché sans condition d'onglet :
```tsx
// frontend/src/pages/Settings.tsx:412-415
useEffect(() => {
  if (authLoading) return
  loadData()
}, [authLoading])
```

À quoi s'ajoute, également au montage et sans condition, un `useEffect([])` qui charge les postes budgétaires
(`Settings.tsx:154-168`, `Promise.all` de `getBudgetPostes` RECETTE + DEPENSE) : **+2 appels**.

**Coût quantifié pour `/settings?tab=permissions&sub=permissions` (MESURÉ)** :

| | Appels |
|---|---|
| `loadData()` (séquentiels) | 11 |
| postes budgétaires (`Settings.tsx:154`, parallèles) | 2 |
| **Total au montage** | **13** |
| Réellement nécessaires pour cet onglet (`adminGetRoles`, `adminGetPermissions`) | **2** |
| **Inutiles** | **11 — soit 85 %** |

Et surtout : **11 allers-retours réseau strictement sérialisés**. Le temps d'affichage est ≈ 11 × RTT, là où
un `Promise.all` donnerait ≈ 1 × RTT. Je ne dispose d'aucune mesure de RTT (Docker mort) — le facteur ~11×
est de l'**arithmétique sur le nombre d'appels**, pas une mesure de latence.

Deux effets conditionnels s'y ajoutent selon l'onglet :
- `Settings.tsx:418-430` — si `activeTab === 'services'` : `adminListUsersAll()`. Ses dépendances sont
  `[activeTab, users]`, or `users` est **réassigné à chaque `loadUsers()`** : l'effet **se redéclenche** à
  chaque rechargement de la liste des utilisateurs. Sur l'onglet Services, chaque pagination ou recherche
  d'utilisateur relance donc un chargement **intégral** de tous les utilisateurs. **DÉDUIT** (chaîne de
  dépendances), confiance élevée.
- `Settings.tsx:466-483` — si `activeTab === 'general'` (l'onglet **par défaut**) : `GET /budget/audit-logs`,
  dépendances `[activeTab, printSettings?.fiscal_year]`, donc **deux exécutions** : une au montage
  (`printSettings` encore `null`, requête sans paramètre `annee`) puis une seconde quand `loadData` renseigne
  `printSettings` — **la première requête est intégralement jetée**. **DÉDUIT**, confiance élevée.
  Pour l'atterrissage par défaut, le total monte donc à **15 appels**.

**Correctif proposé**, par ordre de rapport gain/risque :
1. **Paralléliser** — `Promise.allSettled` sur les 11 appels indépendants (ils le sont tous : aucun ne
   consomme le résultat d'un autre ; `loadUsers()` seul dépend de l'état de pagination, déjà local).
   Passe de ~11 RTT à ~1 RTT. **Risque : quasi nul**, ce n'est qu'un réordonnancement ; il faut simplement
   conserver les `try/catch` individuels, ce que `allSettled` permet directement.
2. **Charger par onglet** — découper `loadData` en fonctions par onglet, déclenchées sur `activeTab`.
   Élimine les 11 appels inutiles. **Risque : moyen** — il faut vérifier chaque consommateur d'état
   (`printSettings` sert à `encaissementLibelles` `Settings.tsx:245`, `roles` sert à `userForm.role`
   `Settings.tsx:432-437`, `services` sert à `serviceMap` `Settings.tsx:405`) ; certains sont transverses aux
   onglets et devront rester au montage.
3. **Corriger la dépendance `users`** de l'effet `services` (`Settings.tsx:430`) — la retirer ou la remplacer
   par un déclencheur explicite.
4. **Attendre `printSettings`** dans l'effet `audit-logs` (`Settings.tsx:466`) — un `if (!printSettings) return`
   supprime la requête jetée.

**Gain attendu et son fondement** : −11 appels sur 13 et −10 RTT sérialisés. **Fondement : comptage exact des
`await` et des `useEffect` du fichier.** L'impact est **borné à un écran d'administration** — il n'affecte
aucun trafic métier.

---

## F2. `countFor` / `spreadFor` recalculés pour chaque carte de rôle, à chaque rendu

**MESURÉ.** `frontend/src/components/admin/RolePermissionsEditor.tsx:766-769` :

```tsx
{!loading &&
  filteredRoles.map((role) => {
    const isActive = role.id === selectedRoleId
    const count = countFor(role)      // ← appelé en ligne, à chaque rendu
    const spread = spreadFor(role)    // ← idem
```

Les deux fonctions sont bien des `useCallback` (`:314` et `:328`), mais **`useCallback` mémoïse la fonction,
pas ses résultats** : chaque rendu du composant les rappelle pour **chaque** rôle affiché.

Ce que fait chacune, par rôle (`:314-341`) :
- construction d'un `new Set(role.permissions ?? [])` — **une fois dans `countFor`, une seconde fois dans
  `spreadFor`**, sur le même tableau ;
- un parcours complet de l'arbre avec un `.filter()` par menu.

**Coût quantifié** — taille de l'arbre, **MESURÉ** sur `frontend/src/data/permissionTree.ts` :
171 entrées `code:`, 48 menus, 4 modules, dont 6 marquées `hidden` (`usableTasks` filtre en plus sur le
catalogue serveur, `RolePermissionsEditor.tsx:94-96`).

Par rendu : **2 × N_rôles constructions de `Set`** + **2 × N_rôles × ~171 tests d'appartenance**.
Pour 8 rôles : ~2 700 tests de `Set` + 16 `Set` reconstruits. Répété à **chaque frappe** dans l'un ou l'autre
champ de recherche (`roleSearch` `:235`, `taskSearch` `:236` sont des `useState` du **même** composant, donc
chaque caractère provoque un rendu complet).

**Réponse à la question de la mission** — « le `spreadFor` est-il appelé pour chaque carte de rôle à chaque
rendu ? » **Oui, confirmé, ligne 769.** Et « les recalculs se font-ils à chaque frappe dans les champs de
recherche ? » **Oui**, y compris pour les rôles que la recherche ne touche pas.

**Honnêteté sur l'ampleur** : quelques milliers d'opérations sur des `Set` représentent un ordre de grandeur
**sub-milliseconde** en JS moderne. Ce n'est **pas** un goulot d'étranglement mesurable ; c'est du gaspillage
propre à supprimer, pas une urgence. **Je ne prétends pas le contraire.**

**Correctif proposé** : un unique `useMemo` produisant une `Map<roleId, { count, spread }>`, dépendant de
`[tree, roles, totalTasks]` — soit **un** parcours pour tous les rôles, invalidé seulement quand les rôles ou
l'arbre changent, et **insensible aux frappes de recherche**. Passe de « 2 × N_rôles parcours par rendu » à
« N_rôles parcours par changement de données ».

**Risque** : nul (calcul pur, dépendances explicites).

---

## F3. `grantedTotal` non mémoïsé et `normalize()` recalculé à chaque frappe

**MESURÉ.** `RolePermissionsEditor.tsx:667-673` :

```tsx
const grantedTotal = isAdminRole
  ? totalTasks
  : tree.reduce(
      (acc, m) => acc + m.menus.reduce((a, menu) => a + menu.tasks.filter((t) => granted.has(t.code)).length, 0),
      0,
    )
```

Pas de `useMemo`, alors que ses voisins immédiats `grantedInModule` (`:653`) et `totalInModule` (`:661`) en
ont un. **Un parcours complet des 171 tâches à chaque rendu**, y compris pour un rendu déclenché par une
frappe dans un champ de recherche, qui ne peut pas changer `granted`.

Second point, `RolePermissionsEditor.tsx:625-644` — `otherModuleHits` applique
`normalize()` (`:85-86` : `toLowerCase()` + `normalize('NFD')` + remplacement par expression régulière) sur
le libellé **et** le code de **chaque tâche de l'arbre entier**, à chaque changement de `query` :

```tsx
: menu.tasks.filter(
    (t) => normalize(t.label).includes(query) || normalize(t.code).includes(query),
  ).length
```

**Coût quantifié** : jusqu'à **~342 appels à `normalize`** par frappe (171 tâches × 2 chaînes), plus
`visibleMenus` (`:603-623`) sur le module actif. Les libellés étant **statiques**, ces normalisations sont
identiques à chaque frappe.

**Correctif proposé** : (a) envelopper `grantedTotal` dans un `useMemo([tree, granted, isAdminRole, totalTasks])` ;
(b) pré-calculer une fois, dans le `useMemo` de `tree` (`:248`), un champ `search` par tâche contenant
`normalize(label) + ' ' + normalize(code)`, et n'appliquer `normalize` qu'à la requête. Passe de O(tâches)
normalisations par frappe à O(1).

**Gain attendu** : réel mais modeste — même ordre de grandeur que §F2. **Risque** : nul.

---

## F4. Contexte de permissions et barre latérale

**MESURÉ. Rien à corriger — les deux points suspectés par la mission sont déjà traités.**

**« Les vérifications sont-elles O(n) sur un tableau au lieu d'un Set ? »** Non.
`frontend/src/contexts/PermissionsContext.tsx:19-20` stocke des `Set<string>`, et
`hasPermission` (`:52-58`) est un `useCallback` faisant deux `Set.has()` — **O(1)**.

**« Le contexte re-rend-il tout l'arbre applicatif quand il change ? »** Sa valeur est correctement mémoïsée
(`PermissionsContext.tsx:60-63`) sur `[menuPermissions, permissionCodes, isAdmin, loading, hasPermission]`,
et ces états ne changent qu'**une fois par session** — l'effet de chargement dépend de `[user?.id]`
(`:50`). Il y a donc **un** re-rendu global au chargement initial des permissions, ce qui est inévitable
et correct. `frontend/src/hooks/usePermissions.ts` n'est qu'un ré-export (2 lignes).

**Barre latérale** (`frontend/src/components/Layout.tsx`) : `canAccessNavItem` (`:418-424`) est appelée à
chaque rendu pour chaque nœud, en récursion, depuis `renderNavItem` (`:640`) et `renderSubNavItem` (`:492`),
plus un second appel via `subItem.subItems?.some(...)` (`:494`).
**Coût quantifié (MESURÉ)** : `grep -c "permission:"` → **77 nœuds de navigation** dans le fichier, mais
un seul jeu de navigation est monté à la fois (`NAV_BY_APP[activeApp]`, `Layout.tsx:342-346`) — donc de
l'ordre de quelques dizaines de `Set.has()` par rendu. **Négligeable**, aucune action recommandée.
Une remarque : `navItems` et `mobileNavItems` (`:342-359`) sont reconstruits à chaque rendu — cela casse la
mémoïsation d'éventuels enfants `React.memo`, mais il n'y en a pas ici, donc c'est sans effet.

---

# Ce que je n'ai pas pu vérifier

**Faute d'exécution (Docker indisponible)** — aucune de ces affirmations n'est mesurée, toutes sont déduites
du code :

1. **Aucun décompte SQL réel.** Tous mes chiffres de requêtes viennent de la lecture des `db.execute` /
   `db.scalar` / `db.get`. Je n'ai pas pu instrumenter, alors que le projet dispose de
   `backend/app/core/db_perf.py` (`record_db_query`, `record_db_connection_usage`, branché dans
   `backend/app/db/session.py`) — c'est **l'outil à utiliser pour valider ce rapport** dès que
   l'environnement redémarre. Un `GET /encaissements` et un `GET /hr/contrats` instrumentés trancheraient
   §A0, §B1 et §B2 en quelques minutes.
2. **Aucune mesure de latence** — ni RTT API, ni temps de rendu React, ni durée de requête SQL. Les facteurs
   « ~11× » de §F1 sont de l'arithmétique sur des nombres d'appels, pas des millisecondes.
3. **Aucun profilage React** (React DevTools Profiler). Les coûts de §F2/§F3 sont des décomptes d'opérations,
   pas des temps mesurés — c'est précisément pourquoi je les classe bas et refuse de les présenter comme des
   goulots d'étranglement.
4. **Taux de succès du cache Redis inconnu.** Avec un TTL de 30 s, le taux dépend entièrement du rythme des
   requêtes par utilisateur. Un utilisateur actif touche presque toujours ; un utilisateur au rythme lent
   rate presque toujours et paie 4 SQL. **Impossible à trancher sans métriques de production.** C'est la
   plus grosse inconnue de ce rapport : si le taux de succès est bas, `_load_auth_context` devient un coût
   de 4 SQL par requête sur **tout** le trafic, ce qui changerait radicalement les priorités.
5. **Plans d'exécution et index.** Je n'ai vérifié aucun `EXPLAIN`. En particulier l'existence d'index sur
   `role_permissions(role_id)`, `user_services(user_id)`, `commission_members(user_id)` et
   `organisation_settings(organisation_id)` — dont dépendent directement les coûts de §A0 et §B1.
6. **État réel de la base.** Trois questions ouvertes qui conditionnent des correctifs :
   (a) existe-t-il des comptes où `User.role` et `Role.code` divergent ? (bloque §B3 et §B2) ;
   (b) le catalogue serveur compte-t-il bien 91 permissions ? je n'ai compté que les **171 codes de l'arbre
   frontend** (`permissionTree.ts`), pas la table `permissions` ;
   (c) combien de sessions actives simultanées ? (dimensionne l'effet de troupeau de §B5).
7. **Le module secrétariat** — `app/modules/secretariat/routes.py` n'expose aucun `@router.<verbe>` direct
   (sous-routeurs) ; je n'ai donc pas compté ses routes dans le décompte « ≥ 74 endpoints » de §B1, qui est
   par conséquent un **minorant**.
8. **Aucun test backend n'a été exécuté** (le commit `425c3d9` lui-même signale que ses tests n'ont pas
   tourné, pour la même raison). Les correctifs de §B2 et §B3 modifient des décisions d'autorisation et
   **ne doivent pas être appliqués sans campagne de tests**.
