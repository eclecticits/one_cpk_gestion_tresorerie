# Validation sous charge du 27/08/2026 — ce que la campagne mesurait réellement

Suite de l'audit du 26/08. Objectif initial : valider sous charge les deux
correctifs qui attendaient Docker (cache du listener multi-tenant, index
couvrant des recettes), puis chiffrer le gain.

**Le résultat principal n'est pas un gain de performance.** C'est que la
campagne ne mesurait pas ce qu'on croyait. Cinq défauts de méthode et de
données ont été identifiés, chacun reproduit hors charge. Tant qu'ils tiennent,
aucun chiffre de cette campagne ne peut servir de référence.

Tout ce qui suit est **mesuré**, jamais déduit. Les commandes de reproduction
sont données pour chaque constat.

---

## 1. La référence historique ne s'applique pas

Les benchmarks d'août (`PERFORMANCE_SQL_OPTIMIZATION_20260803.md`) donnaient
10 VU → p95 387 ms, 0 % d'erreur. La campagne du 27/08 donne, au même palier,
un p95 en minutes et 34 % d'erreurs. L'écart est d'un facteur ~250.

Il ne s'agit pas d'une régression : **les deux campagnes ne mesurent pas la
même chose.**

| | Août (`load_campaign.py`) | 27/08 (k6 `journeys.js`) |
|---|---|---|
| durée par palier | **30 s** (dont 5 s de chauffe) | **11 min** |
| encaissements dans le tenant | **~0** | **120 000** |
| réquisitions | ~0 | 60 000 |
| sorties de fonds | ~0 | 20 731 |
| experts | 1 000 | 6 000 |

Les deux visent pourtant la **même organisation** (`load-test-20260803`, id 18).
Entre les deux, `seed/seed_volume.py --preset production` l'a remplie.

Le seed d'août (`load_campaign.py:163`, `seed_data`) ne crée qu'utilisateurs,
experts et structures budgétaires : **aucun volume transactionnel**. Les 148
requêtes du palier 10 VU à 7,06 RPS confirment la durée — environ 21 secondes
de mesure effective.

> **Le p95 de 387 ms décrit une base vide observée pendant 30 secondes.**
> Il ne peut pas servir de référence à volume réel, et son dépassement
> aujourd'hui n'est pas une régression.

Reproduction :

```bash
docker exec onec_smart-db-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT organisation_id, count(*) FROM encaissements GROUP BY 1"'
```

---

## 2. Aucune écriture n'a été exécutée

C'est le constat le plus lourd, et il touche l'objet même de la branche
`perf-write-contention-validation`.

L'organisation de test est suspendue :

```
 id |        slug        | plan_type | status_abonnement | is_active
----+--------------------+-----------+-------------------+-----------
 18 | load-test-20260803 | STANDARD  | SUSPENDED         | f
```

Or `app/api/deps.py:352` refuse toute écriture dans cet état :

```python
if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
    ...
    if not (admin_host and is_super_admin) and plan_status not in {"ACTIVE", "TRIAL"}:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, ...)
```

Conséquence mesurée sur le palier 10 VU : `encaissement_create` 10/10 en **402**,
`requisition_create` 12/12 en **402**, `sortie_create` 4/4 en **402**.

> **La contention en écriture n'a jamais été mise à l'épreuve.**
> Le seed d'août créait l'organisation en `ACTIVE` ; elle est passée à
> `SUSPENDED` depuis. La cause du basculement n'a pas été recherchée.

---

## 3. Le taux d'échec annoncé est très majoritairement un artefact

Ventilation des 129 échecs du palier 10 VU (4 workers), par requête :

| requête | total | échecs | taux | cause |
|---|---:|---:|---:|---|
| `auth_me` | 27 | 27 | 100 % | 500 — `EmailStr` |
| `print_settings` | 27 | 27 | 100 % | 403 — permission |
| `requisition_create` | 14 | 14 | 100 % | 402 — abonnement |
| `encaissement_create` | 10 | 10 | 100 % | 402 — abonnement |
| `export_encaissements` | 6 | 6 | 100 % | timeout > 60 s |
| `sortie_create` | 6 | 6 | 100 % | 402 — abonnement |
| `export_requisitions` | 5 | 5 | 100 % | 500 — 32 767 paramètres |
| `auth_login` | 4 | 4 | 100 % | 422 — `EmailStr` |
| `reports_journal_caisse` | 4 | 4 | 100 % | timeout — 13,5 s hors charge |

Un taux de 100 % ne dépend pas de la charge : c'est la signature d'un défaut
systématique. Ces neuf requêtes totalisent **103 des 129 échecs, soit 80 %**.

> **Taux d'échec réellement imputable à la charge : 26/374 ≈ 7 %**, et non
> 34,6 %.

---

## 4. Les endpoints ne sont pas intrinsèquement lents à volume réel

Mesure sans aucune concurrence, un seul appel à la fois, sur les 120 000
encaissements (`observe/cout_unitaire.sh`) :

| route | à froid | à chaud (moy.) |
|---|---:|---:|
| `requisitions?page=1` | **13 411 ms** | **31 ms** |
| `dashboard/stats` | 4 326 ms | **20 ms** |
| `reports/summary` | 1 429 ms | **8 ms** |
| `budget/postes/tree` | 348 ms | 46 ms |
| `encaissements?page=1` | 254 ms | 47 ms |
| `tresorerie/soldes` | 120 ms | 82 ms |
| `permissions/menu` | 56 ms | 20 ms |

> **À chaud, tout tient entre 8 et 82 ms.** Le coût n'est pas dans la requête,
> il est dans le **premier accès**. Aucun réglage de workers ou de pool ne
> corrige un coût intrinsèque — mais ici il n'y en a pas.

Cela réoriente l'audit : le sujet est le chemin froid (cache d'authentification,
cache de permissions, cache PostgreSQL), pas l'optimisation des requêtes de
liste.

---

## 5. Deux défauts applicatifs réels, reproduits hors charge

Les seuls constats de cette campagne qui soient des défauts de l'application,
et non du banc ou du jeu de test.

### 5a. `/exports/requisitions` — échec fonctionnel au-delà de ~32 767 lignes

```
sqlalchemy.exc.InterfaceError: (asyncpg.exceptions._base.InterfaceError):
the number of query arguments cannot exceed 32767
```

`app/api/v1/endpoints/exports.py:1841` :

```python
req_ids = [req.id for req, _ in rows]
if req_ids:
    sortie_res = await db.execute(
        select(...).where(SortieFonds.requisition_id.in_(req_ids))
    )
```

`req_ids` n'est pas borné. Avec 60 000 réquisitions, la clause `IN` dépasse la
limite de paramètres du protocole PostgreSQL. **Ce n'est pas un problème de
performance : l'export est impossible**, quelle que soit la charge, dès que le
tenant dépasse ce seuil.

Correctif attendu : découper `req_ids` en lots, ou remplacer le `IN` par une
jointure/agrégat corrélé sur la requête principale.

### 5b. `/exports/encaissements` — dépasse 60 s sans concurrence

Timeout client à 60 s avec **un seul utilisateur**. Non root-causé à ce stade.
Ces deux exports tiennent un worker plusieurs dizaines de secondes ; c'est un
facteur direct de la file d'attente observée sous charge.

---

## 6. Le banc ne peut pas porter la campagne

Preuve dans le journal du noyau :

```
Out of memory: Killed process (k6) anon-rss:606056kB
gunicorn invoked oom-killer: ... task=k6
Out of memory: Killed process (k6) anon-rss:610752kB
```

Deux OOM kills, tous deux sur **k6**. Le second est explicite : c'est gunicorn
qui déclenche l'OOM-killer, et le noyau choisit le générateur comme victime.

| | RAM |
|---|---:|
| machine (VM WSL) | 3,7 Go |
| backend, 4 workers | 1,5 Go |
| backend, 8 workers | 2,1 Go |
| k6 à 25 VU | ~0,6 Go |

À 4 workers le palier 25 VU passe ; à 8 workers il est tué. Le générateur
partage la mémoire du système testé.

---

## 7. L'expérience 8 workers : impasse mesurée

Test A/B, palier 10 VU, seul palier où la mesure est valide des deux côtés :

| | 4 workers | 8 workers |
|---|---:|---:|
| taux d'échec | 34,6 % | **86,6 %** |
| requêtes servies | 373 | **149** |
| itérations complètes | 87 | 47 |
| workers tués (gunicorn) | 12 | 17 |
| CPU backend (moy.) | 264 % | **587 %** |

Le CPU consommé double pendant que le débit chute de 60 % : le surcroît n'est
pas du travail utile, c'est de la contention.

Le dashboard donne le mécanisme : requêtes tentées 189 → **63**, et **aucune**
n'apparaît plus dans `SLOW_REQUEST`. Elles ne sont pas lentes *dans*
l'application — elles n'y entrent jamais.

Plafond de connexions vérifié : **80** (8 × (pool_size 5 + max_overflow 5)),
confirmé au runtime par `DB_POOL_CONFIG max_potential_connections=80`. À noter :
le défaut du code est `max_overflow = 10` (`app/core/config.py:78`) ; seul
`docker-compose.yml` l'épingle à 5. Sans cet épinglage, 8 workers donneraient
120 connexions pour **97 utilisables** (`max_connections` 100 − 3 réservées
superuser), donc des `FATAL: too many clients`.

**PostgreSQL n'a jamais été la contrainte** : 16 connexions en pic sur 80
autorisées, aucun refus, CPU à 28 %.

---

## 8. Ce qui a tenu

L'index couvrant `ix_enc_org_poste_actif`
(`alembic/versions/20260827_perf_budget_recettes_index.py`) : l'agrégat des
recettes par poste, relevé à **194 s** lors de la campagne précédente, a
disparu du classement des requêtes lentes. Machine au repos, il passait de
448 ms / 4 782 buffers à 26,9 ms / 533 buffers.

Le cache du listener multi-tenant est en place et verrouillé par
`tests/test_tenant_loader_options_cache.py`. **Son gain n'est pas chiffré** :
il est noyé dans les défauts ci-dessus. Il n'a pas été touché depuis.

---

## 9. Correctifs apportés au harnais

La collecte de métriques était aveugle sur les campagnes précédentes — trois
fichiers sur quatre ressortaient vides.

| Fichier | Défaut | Correctif |
|---|---|---|
| `observe/server_metrics.sh` | `_pg_activity.csv` vide : connexion en tant que rôle `postgres`, inexistant | identifiants lus dans le conteneur |
| `observe/server_metrics.sh` | `_pool.log` à 0 octet : **créé mais jamais alimenté** | branché sur le flux des journaux backend |
| `observe/server_metrics.sh` | `COMPOSE_FILE` relatif → tout échouait en silence | chemin absolu |
| `run_campaign.sh` | `_backend.log` vide, même cause | chemin absolu |
| `run_campaign.sh` | flux bruts k6 écrasés d'une campagne à l'autre | archivés par palier |
| `run_campaign.sh` | code 137 lu comme un échec applicatif | distingué : « GÉNÉRATEUR TUÉ — palier NON MESURÉ » |

Deux outils d'analyse ajoutés :

- `observe/comparer_paliers.py` — comparatif avant/après par palier, avec seuils
- `observe/analyser_palier.py` — répartition SQL / hors SQL, état PostgreSQL, CPU
- `observe/cout_unitaire.sh` — coût d'une requête sans concurrence

---

## 10. Ordre de traitement proposé

Les trois premiers points sont des **prérequis** : sans eux, toute campagne
ultérieure reproduira les mêmes chiffres ininterprétables.

1. **Réactiver l'organisation de test** (`status_abonnement`, `is_active`) —
   sans quoi le chemin d'écriture reste inaccessible. Comprendre au passage
   pourquoi elle est passée en `SUSPENDED`.
2. **Corriger le jeu de test** : domaine d'adresses valide à la place de
   `.test` (`auth_me` 500, `auth_login` 422), permission de `print-settings`.
3. **Sortir le générateur de la machine testée**, ou augmenter la RAM de la VM
   WSL. Tant que k6 et gunicorn se disputent 3,7 Go, les chiffres absolus ne
   valent rien.
4. **Corriger `/exports/requisitions`** (lots sur `req_ids`) — défaut
   fonctionnel, indépendant de la charge.
5. **Instruire `/exports/encaissements`** (> 60 s sans concurrence).
6. **Puis seulement** rejouer la campagne pour établir une référence à volume
   réel, et chiffrer le gain du listener.

Ce qu'il ne faut **pas** faire tout de suite : augmenter le nombre de workers
(mesuré contre-productif), supprimer des index (le relevé `idx_scan` en
production reste le prérequis posé par `perf-postgres.md`), ou optimiser les
requêtes de liste (8 à 82 ms à chaud, elles ne sont pas le sujet).
