# Audit de performance — backend ONEC Smart

**Date :** 2026-08-26
**Branche :** `perf-write-contention-validation-20260803`
**Méthode :** lecture de code + **micro-benchmarks exécutés localement**.
Docker est arrêté, il n'y a ni base ni API : aucun temps de réponse HTTP n'a été
mesuré. En revanche `sqlalchemy 2.0.37`, `fastapi 0.115.6` et `pydantic 2.10.6`
sont importables dans l'environnement, et `import app.db.session` fonctionne —
j'ai donc pu **mesurer réellement** le coût CPU Python de la couche SQLAlchemy
en instanciant les vrais modèles et les vrais listeners de l'application contre
une base SQLite en mémoire. Tout ce qui est marqué MESURÉ vient de là.

**Machine de mesure :** WSL2, la même que celle des campagnes de charge des
Phases 1 à 4. Elle est lente (construire un `select()` nu y coûte ~99 µs, contre
~25 µs sur un CPU serveur courant). **Les rapports et les ratios sont
exploitables ; les millisecondes absolues sont à diviser par 3 à 4 pour une
machine de production.** Aucune valeur n'est extrapolée au-delà de ça.

**Aucun fichier du dépôt n'a été modifié.**

---

## Ce qui est déjà fait et que je ne re-propose pas

Vérifié dans le code, effectif :

| Acquis | Preuve |
|---|---|
| Pool configurable + instrumentation (capacité, checkout lent, SQL lent) | `backend/app/db/session.py:90-176` |
| Contexte d'auth mis en cache Redis, 0 SQL sur cache chaud | `backend/app/api/deps.py:85-162`, `:233-240` |
| `AuthUser` détaché, plus d'objet ORM en cache | `backend/app/core/auth_user.py:20-53` |
| Séquences documentaires sans `FOR UPDATE` (INSERT … ON CONFLICT DO UPDATE … RETURNING) | `backend/app/services/document_sequences.py` |
| `budget/postes/tree` en projection de colonnes, hors ORM | `backend/app/api/v1/endpoints/budget.py` |
| Sérialisation Excel déportée en thread, avec la justification | `backend/app/utils/excel_io.py:1-32` |
| Les 5 exports lourds construisent leur classeur en thread | `backend/app/api/v1/endpoints/exports.py:1161, 1467, 1760, 2020, 2117` |
| Hachage/vérification de mot de passe en thread | `backend/app/core/security.py:32-36` |
| PDF officiels et rapports mensuels en thread | `backend/app/services/official_pdf.py:416, 629`, `monthly_report.py:81` |
| Notifications WhatsApp : mise en file en base puis remise en `BackgroundTask` | `backend/app/services/notifications/service.py:415-421` |
| `cache_delete_pattern` en SCAN et non KEYS | `backend/app/core/cache.py:79-100` |
| Prédicats de date sargables sur le dashboard (plage, pas de CAST dans le WHERE) | `backend/app/api/v1/endpoints/dashboard.py:432, 457` |

**Point 5 du périmètre (appels bloquants dans la boucle async) : je le considère
traité.** J'ai passé tout `app/` à un détecteur AST cherchant `requests`,
`smtplib`, `subprocess`, `time.sleep`, `open()`, `Workbook.save`, `pd.read_excel`
appelés depuis une `async def` : **aucun HTTP synchrone, aucun `time.sleep`,
aucun SMTP direct**. Les seuls restes sont des `open()`/`os.makedirs` sur des
uploads unitaires (`requisitions.py:1370-1372`, `sorties_fonds.py:1967-1969`,
`clotures.py:1050-1054`, `encaissements.py:1644-1646`) — quelques centaines de
Ko, non significatif. Ce n'est pas là qu'est le problème.

Par ailleurs, conformément à la mise à jour du coordinateur : le retrait de
`GZipMiddleware` (`app/main.py:65`) et le dimensionnement du pool en prod
(`docker-compose.prod.yml`) ne sont pas traités ici.

---

## Tableau des constats, classés par (gain attendu × confiance)

| # | Constat | Portée | Gain attendu | Confiance | Coût / risque | Statut |
|---|---|---|---|---|---|---|
| **1** | `_apply_tenant_criteria` construit **78 `with_loader_criteria` à chaque SELECT ORM** | **100 % du trafic authentifié** | **×7 sur le coût CPU d'un SELECT ORM** (6,41 ms → 0,84 ms) | **Haute** | Moyen — touche l'isolation multi-tenant, à tester | **MESURÉ** |
| **2** | Requêtes de permissions / modules / réglages non cachées, exécutées avant ou juste après l'entrée du handler | `/hr/*` (45 routes), `/secretariat/*`, `/comptabilite/*`, `sorties_fonds`, `ordres_decaissement`, 20 sites `get_system_settings` | 1 à 3 SQL en moins par requête, soit 5 à 18 ms de CPU (via #1) | **Haute** | Faible — le mécanisme de cache existe déjà | **MESURÉ** (compte de requêtes : DÉDUIT) |
| **3** | Listes RH non paginées + prédicats `func.extract` non-sargables | 14 endpoints `/hr/*`, dont `attendances` et `payroll-entries` | Évite un scan complet de table et une réponse non bornée | **Haute** | Faible (index + `limit`) / Moyen (contrat d'API) | **DÉDUIT** |
| 4 | 4 agrégats séquentiels sur le même prédicat dans la liste des sorties de fonds | `GET /sorties-fonds?include_summary=true` | 4 requêtes → 1 | Haute | Faible | DÉDUIT |
| 5 | `verify-report` matérialise toute la période pour un `sum()`/`len()` Python | `GET /requisitions/verify-report` | O(n) lignes → 1 ligne | Haute | Très faible | DÉDUIT |
| 6 | `/reports/summary` : 21 requêtes séquentielles à froid | `GET /reports/summary` | 21 → 8-10 | Moyenne | Moyen (SQL financier délicat) | DÉDUIT |
| 7 | Construction des lignes openpyxl sur la boucle d'événements (2 exports sur 7) | `/audit-logs/export`, `/clotures/export` | Mineur, borné par `limit` | Haute | Très faible | DÉDUIT |

### Les 3 correctifs qui rapportent le plus

1. **Constat #1** — à lui seul il divise par ~7 le coût CPU de chaque SELECT ORM.
   C'est le multiplicateur global. Rien d'autre dans ce rapport n'est du même
   ordre de grandeur.
2. **Constat #2** — supprime des requêtes SQL sur le chemin de *toutes* les
   requêtes d'un module. Chaque requête supprimée vaut deux fois : l'aller-retour
   DB **et** le surcoût CPU du constat #1.
3. **Constat #3** — le seul endroit où j'ai trouvé un risque de dégradation
   *non linéaire* avec le volume de production, c'est-à-dire le risque n°1
   explicitement laissé ouvert par la Phase 4.

Les constats 4 à 7 sont réels mais marginaux à côté. Je ne les développe qu'en
fiches courtes.

---

# Fiche 1 — `_apply_tenant_criteria` : 78 options construites à chaque SELECT ORM

**Statut : MESURÉ.**

### Endpoints touchés

**Tous les endpoints authentifiés d'un tenant**, sans exception. Le listener est
branché sur `sqlalchemy.orm.Session`, donc sur toute exécution ORM de
l'application, quel que soit le routeur.

Ne sont *pas* touchés : les endpoints super-admin sur hôte d'administration
(`get_current_tenant_id()` y vaut `None`, `session.py:481-483` sort tôt) et les
requêtes écrites en `text()` brut — notamment `reports.py`, qui en compte 25.

### Preuve

`backend/app/db/session.py:477-489` :

```python
@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_criteria(execute_state) -> None:
    if execute_state.session.info.get("skip_tenant_scope"):
        return
    if not execute_state.is_select:
        return
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(User, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        with_loader_criteria(Requisition, lambda cls: cls.organisation_id == tenant_id, include_aliases=True),
        ...
```

La liste court de `session.py:485` à `session.py:565` : **78 appels à
`with_loader_criteria`**, comptés programmatiquement. Ils sont **tous** attachés
à **chaque** SELECT, y compris quand la requête ne touche qu'une seule entité —
y compris un simple `select(func.count())`.

Le mécanisme est fonctionnellement correct : c'est ce qui garantit l'isolation
multi-tenant, et le commentaire de `session.py:544-546` avertit à juste titre
qu'oublier une table crée une fuite. **Le constat ne porte pas sur la sécurité,
il porte sur le fait que le travail est refait intégralement à chaque requête.**

### Mesure

Protocole : les modèles et le listener réels de l'application, chargés via
`import app.db.session`, contre une base SQLite en mémoire ; une entité
factice de 3 colonnes, 200 lignes, `select(...).limit(20)` matérialisé en objets
ORM ; 150 itérations après échauffement. Le seul paramètre qui change entre les
trois mesures est le listener.

| Configuration | Coût d'un SELECT ORM complet |
|---|---:|
| **A — actuel** : 78 `with_loader_criteria` reconstruits à chaque appel | **6,41 ms** |
| **B — ciblé** : seules les entités réellement présentes (`ORMExecuteState.all_mappers`), options mémoïsées par `(tenant, modèle)` | **1,13 ms** |
| **C — témoin** : aucun listener | **0,84 ms** |

Décomposition du surcoût (mesurée séparément, même protocole) :

| Poste | Coût |
|---|---:|
| Construction des 78 objets `LoaderCriteriaOption` | ~5,5 ms |
| Calcul de la clé de cache du statement, 78 options vs 0 | 6 969 µs vs 180 µs |
| Construction du `select()` lui-même, pour référence | 99 µs |

Profil `cProfile` du listener seul : sur 2 340 appels à `with_loader_criteria`
(30 exécutions × 78), le temps part dans
`sqlalchemy/orm/util.py:1359 LoaderCriteriaOption.__init__` →
`sql/lambdas.py:220 _retrieve_tracker_rec` →
`sql/lambdas.py:1355 _extract_bound_parameters`. Autrement dit : l'analyse de la
lambda et l'extraction de ses paramètres liés, rejouée 78 fois par requête SQL.

### Requêtes SQL avant / après

**Le nombre de requêtes SQL ne change pas.** C'est un constat de coût CPU par
requête, pas de nombre de requêtes. C'est précisément ce qui le rend difficile à
voir : il est invisible dans un compteur de requêtes SQL, et invisible dans
`pg_stat_statements`, parce que PostgreSQL n'y participe pas.

### Gain attendu, et sur quoi je le fonde

Sur la machine de mesure, **5,3 ms de CPU Python économisés par SELECT ORM**
(6,41 → 1,13). Sur un CPU serveur, en divisant par 3-4 : **1,3 à 1,8 ms par
SELECT ORM**.

Traduit par requête HTTP, avec les comptages de requêtes SQL déjà établis par
vos campagnes (`docs/PERFORMANCE_SQL_OPTIMIZATION_20260803.md`,
`docs/PERFORMANCE_WRITE_CONTENTION_20260803.md`) :

| Endpoint | SQL/appel (mesuré en Phase 2/3) | CPU économisé, machine de test | CPU économisé, estimation serveur |
|---|---:|---:|---:|
| `encaissement_create` | 19-20 | ~100 ms | ~30 ms |
| `requisition_create` | 13 | ~69 ms | ~20 ms |
| `experts-comptables` (liste) | 11 | ~58 ms | ~17 ms |
| `encaissements` (liste, cache auth froid) | 10,6 | ~56 ms | ~16 ms |
| `reports/summary` | 15-21 | **~0** (requêtes en `text()`) | ~0 |

**Ce constat explique le diagnostic resté ouvert de la Phase 4.** Le profil
py-spy de `docs/PERFORMANCE_WORKER_SCALING_20260817.md` attribue **46,1 % du CPU
du worker à SQLAlchemy « alors que la base de données est inactive »**, et
conclut : « ce n'est pas de l'attente de réponse SQL, c'est du coût Python de
construction de requêtes et de matérialisation ORM. C'est le gisement
principal. » Le document impute ensuite ce coût à la matérialisation d'entités
ORM et recommande des projections de colonnes endpoint par endpoint. **La mesure
ci-dessus montre que l'essentiel n'est pas dans la matérialisation mais dans la
construction : 6,41 ms contre 0,84 ms sur exactement le même SELECT et la même
matérialisation.** Le correctif est central et unique, pas endpoint par endpoint.

Cela explique aussi pourquoi le débit croît linéairement avec les workers
(12,7 → 23,7 → 48,1 RPS) alors que PostgreSQL reste inactif : le goulot est un
coût CPU constant, payé par requête SQL, dans le processus Python.

### Piste de correction

Deux leviers, cumulables, du plus sûr au plus efficace :

1. **Mémoïser** les options par `tenant_id` dans un petit dict. Supprime la
   reconstruction, garde les 78 options. Mesuré à part : 5 459 µs → 1 097 µs.
   Changement quasi nul en surface, mais laisse le coût de clé de cache.
2. **Cibler** : `ORMExecuteState.all_mappers` (vérifié disponible en SQLAlchemy
   2.0.37, et vérifié : pour `select(Row)` il rend bien `['Row']` et rien
   d'autre) donne les entités réellement impliquées. N'attacher que les options
   correspondantes. Combiné à la mémoïsation : **6,41 ms → 1,13 ms**.

### Coût / risque

**Moyen, et à ne pas sous-estimer** : c'est le mécanisme d'isolation
multi-tenant. Un ciblage trop agressif rouvrirait une fuite inter-tenant.

Garde-fous que je recommanderais si ce correctif est engagé :
- `all_mappers` doit inclure les entités atteintes par `selectinload`/
  `joinedload` — c'est le cas *si* les options sont recalculées pour les
  requêtes secondaires émises par les loaders (elles repassent par
  `do_orm_execute`) ; **à vérifier explicitement par un test avant de livrer.**
- `backend/tests/test_multi_tenant_isolation.py` et
  `test_operation_visibility_scope.py` existent déjà et couvrent le sujet : ils
  doivent passer à l'identique.
- Conserver le commentaire d'avertissement de `session.py:544-546` : la table de
  correspondance modèle → colonne tenant reste à tenir à jour.

---

# Fiche 2 — Requêtes de permissions, de modules et de réglages non cachées

**Statut : MESURÉ pour le coût unitaire (via fiche 1) ; DÉDUIT pour le nombre de
requêtes par appel, compté par lecture du code.**

C'est le point 9 du périmètre : **combien de requêtes SQL avant d'atteindre le
handler.** Réponse : sur cache d'auth chaud, **0 pour la plupart des routeurs —
c'est bon — mais 1 systématique et incompressible sur `/hr/*`, `/secretariat/*`
et `/comptabilite/*`**, plus 1 à 3 de plus juste après l'entrée dans le handler.

### 2a — `require_module` : 1 SQL par requête, jamais caché

`backend/app/api/deps.py:611-645` :

```python
def require_module(module_name: str):
    async def _dep(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
        if (user.role or "").lower() == "super_admin":
            return user
        ...
        res = await db.execute(
            select(OrganisationSettings)
            .where(OrganisationSettings.organisation_id == org_id)
            .limit(1)
        )
```

Branché au niveau du routeur, donc sur **toutes** les routes en dessous —
`backend/app/api/v1/router.py:143-151` :

```python
api_router.include_router(hr.router, prefix="/hr", tags=["hr"], dependencies=[Depends(require_module("rh"))])
api_router.include_router(secretariat.router, prefix="/secretariat", ..., dependencies=[Depends(require_module("secretariat"))])
api_router.include_router(comptabilite.router, ..., dependencies=[Depends(require_module("comptabilite"))])
# + comptabilite_parametrage, comptabilite_restitutions, comptabilite_etats
```

`hr.py` compte à lui seul **45 routes**. `modules_config` est une configuration
qui change quelques fois par an. Elle est relue en SELECT ORM à chaque appel HTTP
— donc au prix plein du constat #1 (~6,4 ms sur la machine de test).

À noter : le SELECT charge l'entité `OrganisationSettings` entière alors que
seule la colonne `modules_config` est lue (`deps.py:637`).

Le cache Redis existe et est déjà utilisé pour le statut SaaS juste au-dessus
(`deps.py:184-196`, TTL ≥ 30 s). Il n'est pas utilisé ici.

### 2b — Trois helpers `_user_has_permission` qui court-circuitent le cache d'auth

La Phase 2 (`docs/PERFORMANCE_SQL_OPTIMIZATION_20260803.md`) a introduit un
contexte d'auth caché portant `permissions` et `service_ids`, et
`app/core/auth_user.py:57-77` expose `cached_permission_codes()` /
`cached_service_ids()` pour l'exploiter sans requête. **Le déploiement de cette
optimisation est incomplet.** Cinq helpers locaux dupliquent la décision ; deux
ont été convertis, trois ne l'ont pas été :

| Fichier:ligne | Utilise le contexte caché ? | SQL par appel | Sites d'appel |
|---|---|---:|---:|
| `app/services/service_access.py:57` (`user_has_permission`, partagé) | ✅ oui | 0 | — |
| `app/api/v1/endpoints/encaissements.py:456` | ✅ oui | 0 | 3 |
| `app/api/v1/endpoints/whatsapp.py:170` | ✅ oui | 0 | 1 |
| **`app/api/v1/endpoints/hr.py:108`** | ❌ **non** | **1 à 2** | **4** |
| **`app/api/v1/endpoints/sorties_fonds.py:276`** | ❌ **non** | **1** | **2** |
| **`app/api/v1/endpoints/ordres_decaissement.py:58`** | ❌ **non** | **1** | **2** |

`app/api/v1/endpoints/hr.py:108-122` est le pire des trois — il peut faire
**deux** requêtes, et il est appelé sur quatre listes RH :

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

Appelé en `hr.py:164`, `hr.py:297`, `hr.py:310`, `hr.py:333`. À comparer avec la
version déjà corrigée de `encaissements.py:456-471`, qui teste
`cached_permission_codes(user)` avant de tomber en base — les deux fonctions ont
le même contrat, l'une a été convertie, l'autre non.

`sorties_fonds.py:276` est incohérent avec lui-même : la même fonction appelle
`has_module_menu_access` (`sorties_fonds.py:588`), qui *passe* par le service
partagé et coûte 0 SQL, puis `_user_has_permission` (`sorties_fonds.py:597`),
qui coûte 1 SQL pour une décision de même nature.

### 2c — `get_system_settings` : 20 sites d'appel, aucun cache

`backend/app/services/system_settings_service.py:27-29` :

```python
async def get_system_settings(db: AsyncSession, organisation_id: int) -> SystemSettings | None:
    result = await db.execute(_settings_priority_query(organisation_id).limit(1))
    return result.scalar_one_or_none()
```

`_settings_priority_query` (`:9-24`) est un SELECT ORM avec **neuf clauses
`ORDER BY`** dont sept comparaisons de chaînes. 20 sites d'appel, notamment sur
les chemins de création (via `_notify_sortie_fonds_whatsapp`,
`sorties_fonds.py:210`). Réglages SMTP/WhatsApp d'organisation : ils changent
quelques fois par an.

### État du cache Redis dans l'application (point 8 du périmètre)

`cache_get`/`cache_set` ne sont appelés que dans **5 fichiers** :

| Fichier | Usage |
|---|---|
| `app/api/deps.py` (4) | contexte d'auth, statut SaaS |
| `app/core/tenant_resolver.py` (2) | résolution du tenant |
| `app/api/v1/endpoints/reports.py` (2) | `summary`, TTL 15 s |
| `app/api/v1/endpoints/dashboard.py` (2) | stats |

Manquent, de façon évidente et selon le critère du périmètre (« réglages
système, référentiels lus à chaque requête ») : `modules_config` (2a),
`SystemSettings` (2c), et le catalogue de permissions
(`admin.py:970 list_permissions`, non paginé).

### Requêtes SQL avant / après — `GET /api/v1/hr/contracts`

| Étape | Aujourd'hui | Après |
|---|---:|---:|
| `get_current_user` (cache auth chaud) | 0 | 0 |
| `require_module("rh")` — `deps.py:630` | **1** | 0 (cache) |
| `has_permission("rh.contracts.view")` (cache chaud) | 0 | 0 |
| **Sous-total avant handler** | **1** | **0** |
| Requête de liste — `hr.py:294` | 1 | 1 |
| `_user_has_permission("rh.salaries.view")` — `hr.py:297` | **1 à 2** | 0 (contexte) |
| **Total** | **3 à 4** | **1** |

Sur cache d'auth **froid** (TTL 30 s, `config.py:88`), ajouter les 4 SELECT ORM
de `_load_auth_context` (`deps.py:85-162` : user+org jointe, permissions,
services, commissions).

### Gain attendu

2 à 3 requêtes SQL en moins par appel sur `/hr/*`, 1 à 2 sur `/sorties-fonds` et
`/ordres-decaissement`, 1 sur `/secretariat/*` et `/comptabilite/*`. Chacune vaut
un aller-retour DB **plus** ~6,4 ms de CPU sur la machine de test (~1,8 ms
serveur), par le constat #1. Soit **de l'ordre de 5 à 18 ms de CPU par requête
sur les modules concernés**, sur des routeurs qui portent 45 routes et plus.

Effet secondaire notable : moins de requêtes = connexion rendue plus tôt au
pool. Les Phases 2 et 3 montrent que la saturation du pool est un symptôme de
détention longue, pas d'un manque de connexions.

### Coût / risque

**Faible.** Pour 2b, c'est le remplacement de trois fonctions locales par
`app/services/service_access.py:user_has_permission`, déjà en production et déjà
utilisée ailleurs — attention toutefois à `hr.py:108`, dont le second SELECT
(repli « le rôle est-il `admin` ? ») n'a pas d'équivalent exact dans la version
partagée : il faut vérifier que ce repli est bien couvert par le
court-circuit `role in {admin, super_admin}` avant de le supprimer.
Pour 2a et 2c, ajout d'un cache Redis court avec invalidation sur écriture des
réglages ; le risque est qu'un changement de configuration mette un TTL à
prendre effet.

**Risque déjà ouvert, hérité de la Phase 2 et non refermé :** le document
`PERFORMANCE_SQL_OPTIMIZATION_20260803.md` signale que
« l'invalidation explicite du cache d'authentification doit être raccordée aux
endpoints d'administration ». `invalidate_auth_context_cache()` existe bien
(`deps.py:73-83`) — je n'ai pas vérifié qu'elle est appelée depuis tous les
points de modification de rôles, permissions et affectations de service. Étendre
le cache à `modules_config` sans refermer ce point aggraverait le même risque.

---

# Fiche 3 — Listes RH non paginées et prédicats de date non-sargables

**Statut : DÉDUIT.** Aucun `EXPLAIN ANALYZE` n'a pu être exécuté.

### Endpoints touchés

**14 endpoints de liste RH sans aucun paramètre `limit`/`offset`**, renvoyant
l'intégralité de la table pour le tenant :

`hr.py:229` employees · `:287` contracts · `:346` leaves · `:411` documents ·
`:445` leave-allocations · `:488` leave-balance · **`:821` attendances** ·
**`:940` payroll-entries** · `:1086` entry-slips · `:1095` salary-slips ·
`:1436` evaluations · `:1498` sanctions ; plus
`hr_attendance_agent.py:932` unmapped-punches et `:914` attendance-devices.

`attendances`, `payroll-entries` et `salary-slips` croissent en
`agents × jours` — ce sont les seules tables du système dont j'ai identifié une
croissance non bornée par un cycle métier.

### Preuve

`backend/app/api/v1/endpoints/hr.py:821-836` — les deux défauts sur le même
endpoint :

```python
async def list_attendances(
    employee_id: int | None = None,
    mois: int | None = None,
    annee: int | None = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: int = Depends(get_current_tenant_id),
) -> list[HRAttendance]:
    stmt = select(HRAttendance).where(HRAttendance.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(HRAttendance.employee_id == employee_id)
    if mois:
        stmt = stmt.where(func.extract("month", HRAttendance.date_presence) == mois)
    if annee:
        stmt = stmt.where(func.extract("year", HRAttendance.date_presence) == annee)
    res = await db.execute(stmt.order_by(HRAttendance.date_presence.desc()))
    return list(res.scalars().all())
```

Ni `limit` ni `offset`. Et `func.extract("month", colonne) == valeur` est **non
sargable** : PostgreSQL ne peut utiliser aucun index B-tree ordinaire sur
`date_presence`, il balaie et évalue la fonction ligne à ligne.

**C'est exactement le motif que la migration
`alembic/versions/20260722d_perf_indexes.py` a corrigé ailleurs.** Cette
migration documente que les `CAST(date AS date)` / `func.date()` du dashboard et
des rapports provoquaient des balayages complets — « ~22 s, timeouts gunicorn » —
et les a réécrits en comparaisons de plage. **Le même motif est réapparu dans le
module RH, qui est postérieur.**

Les 13 occurrences de `func.extract`, toutes dans `hr.py` :
`:181`, `:182`, `:200`, `:201` (tableau de bord RH — donc sur le chemin
d'affichage principal du module), `:508`, `:832`, `:834`, `:877`, `:878`,
`:1588`, `:1594`, `:1596`, `:1659`.

### Requêtes SQL avant / après

Le nombre de requêtes ne change pas. Ce qui change, c'est leur plan et le volume
transporté : d'un `Seq Scan` sur toute la table de présences du tenant avec
matérialisation ORM de toutes les lignes, vers un `Index Scan` sur une plage de
dates avec un nombre de lignes borné.

### Gain attendu, et sur quoi je le fonde

Je ne peux pas le chiffrer : il dépend entièrement du volume, et le jeu de test
des campagnes (`load-test-20260803`) ne contient pas de données RH — les
campagnes des Phases 1 à 4 **n'ont jamais sollicité `/hr/*`**. Ce que je peux
dire :

- Le coût croît **linéairement avec l'historique de présences**, alors que tous
  les autres constats de ce rapport sont à coût constant par requête.
- Il n'est **pas couvert par le cache d'auth ni par le cache de rapports**.
- Il s'ajoute au constat #1 : chaque ligne matérialisée en entité ORM se paie en
  plus.
- C'est précisément la réserve n°1 laissée ouverte par la Phase 4 :
  « la linéarité tient tant que PostgreSQL est inactif. À volume de production,
  le coût SQL monte et ajouter des workers ne corrigera pas ce déplacement du
  goulot. C'est le risque principal et il n'est pas couvert par les mesures de
  cette phase. »

### Coût / risque

Réécrire `func.extract(...) == mois/annee` en plage
(`date_presence >= début AND date_presence < début_mois_suivant`) est mécanique
et sans risque, et rend un index `(tenant_id, date_presence)` utilisable.

Ajouter `limit`/`offset` est en revanche un **changement de contrat d'API** : il
faut vérifier ce que le frontend attend de ces 14 endpoints avant de borner les
réponses, sous peine de tronquer silencieusement des états de paie.

---

# Fiches courtes — constats 4 à 7

### 4 — Quatre agrégats séquentiels sur le même prédicat

`backend/app/api/v1/endpoints/sorties_fonds.py:719-761`. Sur
`GET /sorties-fonds?include_summary=true`, quatre requêtes parcourent
successivement le même ensemble de lignes, avec les mêmes `conditions` et la
même jointure `Requisition` :

```python
total_count = int((await db.execute(count_query)).scalar_one() or 0)
...
total_montant_paye        = (await db.execute(_sum_query())).scalar_one() or 0
total_transferts_internes = (await db.execute(_sum_query(SortieFonds.type_sortie.in_(transfert_types)))).scalar_one() or 0
total_depenses_reelles    = (await db.execute(_sum_query(SortieFonds.type_sortie.notin_(transfert_types)))).scalar_one() or 0
```

**4 requêtes → 1**, par agrégation conditionnelle
`SUM(...) FILTER (WHERE ...)` — exactement la technique déjà appliquée avec
succès à `experts-comptables` en Phase 2 (11 requêtes → 3), et déjà employée
ailleurs dans `reports.py` (cf. le commentaire de `reports.py:662-664` :
« chaque requête sépare *avant la période* et *dans la période* par agrégation
conditionnelle, pour ne pas doubler le nombre d'aller-retours »). Le motif est
connu de l'équipe, il n'a simplement pas été appliqué ici.

Gain : 3 SELECT ORM en moins, soit ~19 ms de CPU machine de test (~5 ms serveur)
plus 3 aller-retours DB, sur un endpoint de liste principal. **DÉDUIT.**

À noter en positif : le reste de cette fonction est un **bon** exemple. Les
utilisateurs et les remboursements sont chargés en une requête `IN (...)` avec
construction de `users_map` / `remboursements_map` (`sorties_fonds.py:679-700`),
puis consommés en compréhension. **Aucun N+1** dans la sérialisation.

### 5 — `verify-report` matérialise toute la période pour un `sum()` Python

`backend/app/api/v1/endpoints/requisitions.py:884-899` :

```python
query = select(Requisition).where(
    Requisition.organisation_id == tenant_id,
    Requisition.created_at.between(start, end),
    Requisition.is_deleted.is_(False),
)
res = await db.execute(query)
requisitions = res.scalars().all()
calc_total = sum(float(r.montant_total or 0) for r in requisitions)
calc_count = len(requisitions)
```

Aucun `limit`. Toutes les réquisitions de la période sont hydratées en entités
ORM complètes pour n'en tirer qu'une somme et un compte. C'est le motif visé par
le point 3 du périmètre (`len(...)` au lieu d'un `COUNT` SQL). Un seul
`select(func.count(), func.sum(...))` rend le même résultat en une ligne
transportée. **DÉDUIT**, mais le diagnostic ne demande aucune mesure.

### 6 — `/reports/summary` : 21 requêtes séquentielles à froid

`backend/app/api/v1/endpoints/reports.py:136-1010` — **21 `await db.execute`**
comptés, exécutés en série. Déjà identifié par la Phase 4, travail restant n°4 :
« `reports/summary` (16 requêtes séquentielles à froid, dont 4 comptages de
réquisitions qui tiennent dans une seule requête groupée) ». Les 4 comptages sont
à `reports.py:690`, `:709`, `:734`, `:759`.

**Correction utile au diagnostic :** cet endpoint est écrit en `text()` brut
(25 occurrences, ex. `reports.py:240-253`). Il **ne paie donc pas** le surcoût du
constat #1 — le listener sort sur `is_select` faux pour un `TextClause`. Son
coût est en aller-retours réseau et en temps PostgreSQL, pas en CPU Python. **Il
est donc de bien moindre priorité que ce que son nombre de requêtes suggère**, et
il est déjà couvert par un cache Redis de 15 s
(`config.py:89`, `services/report_cache.py`). Je le classe en 6e position et non
dans le trio de tête, contrairement à ce que recommandait la Phase 4.

Je note aussi que la parallélisation de ces 21 requêtes par `asyncio.gather`
serait une **fausse bonne idée** : une `AsyncSession` ne multiplexe pas, il
faudrait autant de connexions que de requêtes parallèles — c'est-à-dire
reproduire volontairement la saturation de pool des Phases 1 à 3. La bonne
direction est bien la fusion en 8 à 10 requêtes, comme indiqué.

### 7 — Deux exports construisent leurs lignes sur la boucle d'événements

`backend/app/api/v1/endpoints/audit_logs.py:265-294` et
`clotures.py:522-...` : `Workbook()` puis une boucle `ws.append(...)` exécutés
directement dans la coroutine. La sérialisation, elle, est bien déportée
(`audit_logs.py:296 await save_workbook(wb)`), avec un commentaire correct.

Le résidu est donc borné par le `limit` de la requête et reste modeste comparé au
`wb.save()` (mesuré à ~80 % du coût d'un export selon `app/utils/excel_io.py:3-5`).
Les 5 exports de `exports.py` font déjà mieux : ils enferment **toute** la
construction dans `_build_workbook()` passé à `anyio.to_thread.run_sync`.
Aligner ces deux-là sur ce motif est un alignement de cohérence, pas une urgence.
**DÉDUIT.**

---

## Points vérifiés qui se sont révélés sains

Je les liste pour éviter qu'ils soient réexaminés.

- **N+1 par accès à une relation dans une boucle de sérialisation : structurellement
  impossible ici.** Aucun `lazy=` n'est déclaré dans `app/models/*.py`, donc les
  relations sont en `lazy="select"` ; sous `AsyncSession`, un accès paresseux lève
  `MissingGreenlet` au lieu d'émettre une requête silencieuse. Le N+1 classique
  ne peut pas se cacher dans ce code — il ne pourrait apparaître que sous forme
  de requête explicite dans une boucle.
- **Requêtes explicites dans des boucles :** détecteur AST passé sur
  `app/api/v1/endpoints` (39 occurrences) et `app/services` (10). Après examen,
  **aucune sur un chemin de lecture à fort trafic**. Elles sont soit des faux
  positifs (`for row in (await db.execute(stmt)).all()`, ex.
  `dashboard.py:445`, `reports.py:1550`), soit des chemins d'import/écriture à
  faible fréquence : `budget.py:2427` (import de postes),
  `requisitions.py:1610` (import PDF), `hr_attendance_agent.py:560-620`
  (ingestion de pointages), `admin.py:989-1007` (mise à jour des permissions
  d'un rôle), `services.py:1350-1388` (affectation multiple).
  `budget.py:578-591` (`_refresh_parent_totals`, remontée de l'arbre) et
  `historical_snapshots.py:114` (un `SELECT User` par signataire) mériteraient un
  regroupement, mais ne sont pas sur le chemin chaud.
- **`len(res.scalars().all())` au lieu d'un COUNT :** une seule occurrence,
  `app/services/ai_chat.py:86`. Le motif du constat 5 en est la variante.
- **Sérialisation Pydantic :** 18 `model_validate`, tous en compréhension sur des
  listes déjà bornées. Rien d'alarmant. Le profil py-spy de la Phase 4 la crédite
  de 2,1 % du CPU — à comparer aux 46,1 % de SQLAlchemy.
- **`BackgroundTasks` :** correctement employé pour les e-mails
  (`auth.py:507`, `:557`) et la remise WhatsApp
  (`notifications/service.py:415-421`, avec la mise en file en base d'abord et le
  commentaire « à appeler après le `commit()` »). Les appels
  `await notify_whatsapp(...)` visibles dans les handlers
  (`sorties_fonds.py:1880`, `encaissements.py:1556`, `requisitions.py:2143`)
  n'envoient rien sur le réseau : ils écrivent en file et délèguent.
- **`with_for_update` :** aucune occurrence subsistante sur les séquences
  documentaires, la Phase 3 les a bien remplacées par un `INSERT … ON CONFLICT
  DO UPDATE … RETURNING`, et `test_document_sequences_concurrency.py` couvre le
  cas jusqu'à 100 réservations concurrentes.
- **Compression, dimensionnement du pool, nombre de workers :** hors périmètre
  sur consigne du coordinateur.

---

## Ce que je n'ai pas pu vérifier

1. **Tout temps de réponse HTTP.** Docker est arrêté, il n'y a ni API ni base.
   Les seules latences citées dans ce rapport proviennent de vos propres
   documents de campagne, jamais de moi. Aucun chiffre de ce rapport n'est une
   estimation de temps de réponse.
2. **Tout plan d'exécution PostgreSQL.** Aucun `EXPLAIN (ANALYZE, BUFFERS)` n'a
   pu être lancé. La fiche 3 (non-sargabilité de `func.extract`) repose sur une
   propriété connue du planificateur PostgreSQL et sur le précédent documenté
   dans `20260722d_perf_indexes.py`, **pas sur un plan observé sur cette base**.
3. **Le nombre réel de requêtes SQL par appel HTTP.** Je l'ai reconstitué par
   lecture des dépendances et des handlers. Vous avez déjà l'instrumentation
   qu'il faut pour le confirmer (compteur SQL par requête HTTP,
   `app/core/db_perf.py` + `app/middleware/timing.py`) : les tableaux « avant /
   après » des fiches 1 et 2 doivent être recoupés avec les logs `SLOW_REQUEST`
   d'une vraie campagne.
4. **Le gain du constat #1 sous charge réelle.** Ma mesure est un micro-benchmark
   mono-thread contre SQLite : elle isole proprement le coût CPU du listener et
   c'est ce qu'elle prétend mesurer, mais elle ne dit rien de l'effet sur le p95
   à 100 utilisateurs. Il faut rejouer `backend/scripts/load_campaign.py` avant /
   après. J'attends une amélioration franche du RPS par worker ; je ne peux pas
   la chiffrer.
5. **Que le ciblage par `all_mappers` préserve l'isolation multi-tenant sur les
   chargements secondaires** (`selectinload`/`joinedload`) et sur les requêtes
   corrélées. C'est le seul risque fonctionnel sérieux du correctif n°1 et il
   demande d'exécuter `test_multi_tenant_isolation.py` et
   `test_operation_visibility_scope.py` — impossible ici, `pytest` et les
   dépendances de test ne sont pas disponibles dans cet environnement.
6. **Le volume de données de production.** Aucune connexion à une base réelle.
   Toute la fiche 3 dépend de ce volume, et c'est aussi la réserve n°1 de la
   Phase 4, toujours ouverte.
7. **Le taux de hit réel du cache Redis** et la pertinence des TTL (30 s pour
   l'auth, 15 s pour `reports/summary`). Un TTL de 30 s signifie qu'un
   utilisateur espaçant ses actions de plus de 30 s ne bénéficie **jamais** du
   cache et repaie les 4 SELECT ORM de `_load_auth_context` — c'est mesurable en
   production et ça n'a pas été fait.
8. **Si `invalidate_auth_context_cache()` (`deps.py:73-83`) est appelée depuis
   tous les points de modification de rôles, permissions, affectations de service
   et désactivation d'utilisateur.** Le risque était déjà signalé comme ouvert
   par la Phase 2 ; je ne l'ai pas refermé, et il conditionne l'extension du
   cache proposée en fiche 2.
9. **Les modules `secretariat` et `comptabilite`** n'ont été examinés qu'au
   travers de `require_module` dans `router.py`. Leurs endpoints eux-mêmes n'ont
   pas été audités, faute de temps ; ils sont soumis aux mêmes constats #1 et #2a.
10. **Le temps de démarrage applicatif** (34 à 50 s selon la Phase 4, dominé par
    l'enregistrement de 530 routes) n'est pas réexaminé : non mesurable ici, et
    déjà diagnostiqué.
