# Phase 2 - Optimisation SQL et detention des connexions

Date: 2026-08-03

## Cadre de test

- Backend: 1 worker
- Pool SQLAlchemy: `pool_size=10`, `max_overflow=10`, `pool_timeout=5`
- Budget PostgreSQL potentiel: `workers * (pool_size + max_overflow) = 1 * (10 + 10) = 20 connexions`
- Donnees de test isolees: organisation `load-test-20260803`
- Regle de phase: ne pas augmenter le pool, ne pas ajouter de worker, ne pas tester 500 utilisateurs avant stabilisation a 100.

## Classement initial des endpoints

Mesure initiale: `backend/scripts/onec_load_phase2_baseline_25.json`, 25 utilisateurs, 20 s de charge, 5 s d'echauffement, 226 requetes, 0 % d'erreurs.

Les donnees SQL proviennent des logs enrichis `SLOW_REQUEST`; les endpoints tres rapides peuvent donc etre sous-representes dans les statistiques SQL. Ce classement sert a identifier les chemins qui gardent le plus longtemps les connexions et qui depassent les budgets de requetes.

| Rang | Endpoint | Appels | Moyen | p95 | p99 | SQL moy. | SQL max | SQL cumule moy. | Connexion tenue moy. | Connexion tenue max | JSON moy. | Erreurs | Requete la plus lente observee |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | `/api/v1/experts-comptables` | 40 | 1179 ms | 2619 ms | 2854 ms | 11.0 | 11 | 1014 ms | 1238 ms | 2921 ms | 13496 o | 0.00 % | `SELECT experts_comptables.id ...` |
| 2 | `/api/v1/encaissements` | 36 | 1032 ms | 2421 ms | 2596 ms | 10.6 | 25 | 961 ms | 1372 ms | 2541 ms | 6658 o | 0.00 % | `SELECT users.id ...` |
| 3 | `/api/v1/requisitions` | 33 | 1012 ms | 2323 ms | 2744 ms | 11.9 | 20 | 790 ms | 1166 ms | 3171 ms | 13285 o | 0.00 % | `SELECT users.id ...` |
| 4 | `/api/v1/reports/summary` | 22 | 1176 ms | 2286 ms | 2488 ms | 17.6 | 18 | 1019 ms | 1079 ms | 3526 ms | 1229 o | 0.00 % | `SELECT mode_paiement ...` |
| 5 | `/api/v1/budget/postes/tree` | 44 | 953 ms | 2274 ms | 2565 ms | 4.8 | 5 | 934 ms | 1034 ms | 2613 ms | 341 o | 0.00 % | `SELECT budget_exercices.id ...` |
| 6 | `/api/v1/dashboard/stats` | 37 | 809 ms | 2150 ms | 2217 ms | 6.1 | 18 | 934 ms | 1302 ms | 3526 ms | 907 o | 0.00 % | `SELECT organisations.id ...` |

## Budget SQL par endpoint

| Type d'endpoint | Budget retenu |
|---|---:|
| Liste simple | 3 a 5 requetes SQL |
| Detail | 3 a 6 requetes SQL |
| Dashboard | 5 a 8 requetes SQL |
| Rapport de synthese | 5 a 10 requetes SQL |
| Authentification courante | 0 a 1 requete SQL apres cache chaud |

Ecarts initiaux:

- `/api/v1/experts-comptables`: 11 requetes SQL, au-dessus du budget liste.
- `/api/v1/encaissements`: jusqu'a 25 requetes SQL, au-dessus du budget liste.
- `/api/v1/requisitions`: jusqu'a 20 requetes SQL, au-dessus du budget liste.
- `/api/v1/reports/summary`: 17 a 18 requetes SQL, au-dessus du budget rapport.
- `/api/v1/dashboard/stats`: moyenne acceptable, mais pics a 18 requetes et detention longue.
- `/api/v1/budget/postes/tree`: nombre de requetes acceptable, mais detention de connexion trop longue.

## Audit de get_current_user

Observation initiale:

- Avant cache, chaque requete protegee recharge le contexte utilisateur et contribue aux requetes repetees visibles dans les listes, notamment `SELECT users.id ...`.
- Le cout d'authentification s'ajoute a presque tous les endpoints de charge.

Optimisation appliquee:

- Ajout de `AUTH_CONTEXT_CACHE_ENABLED=true`.
- Ajout de `AUTH_CONTEXT_CACHE_TTL_SECONDS=30`.
- Ajout de `REPORT_SUMMARY_CACHE_TTL_SECONDS=15`.
- Cache court d'un contexte serialise: `user_id`, `tenant_id`, `antenne_id`, `role_ids`, `permissions`, `is_active`, `token_version`.
- Aucun objet ORM n'est stocke en cache.
- La cle est separee par utilisateur, tenant et version de token.

Validation courte apres cache:

- Fichier: `backend/scripts/onec_load_auth_cache_10.json`
- 10 utilisateurs, 104 requetes, 0 % d'erreurs, p95 884 ms.

Risque ouvert:

- L'invalidation explicite lors des changements de roles, permissions ou desactivation utilisateur doit etre raccordee aux endpoints d'administration correspondants avant une validation multi-worker.

## Optimisations prevues dans cette phase

1. Reduire le cout d'authentification sur les requetes courantes. Fait.
2. Optimiser les trois chemins les plus couteux mesures: experts-comptables, encaissements et requisitions. Fait.
3. Optimiser ensuite les aggregations lourdes de rapports si elles restent au-dessus du budget. Cache court ajoute.
4. Rejouer 10, 25, 50 puis 100 utilisateurs avec la meme configuration. Fait.

## Resultats apres optimisation

### Campagne apres optimisation SQL des listes

Fichier: `backend/scripts/onec_load_phase2_after_sql.json`

| Utilisateurs | Requetes | Erreurs | p95 | p99 | RPS terminees |
|---:|---:|---:|---:|---:|---:|
| 10 | 159 | 0.63 % | 426 ms | 535 ms | 7.33 |
| 25 | 337 | 0.30 % | 1.35 s | 2.22 s | 14.83 |
| 50 | 381 | 1.05 % | 3.15 s | 5.44 s | 16.53 |
| 100 | 446 | 4.04 % | 7.50 s | 9.47 s | 17.59 |

### Campagne apres cache court de reports/summary

Fichier: `backend/scripts/onec_load_phase2_after_report_cache.json`

| Utilisateurs | Requetes | Erreurs | p95 | p99 | RPS terminees |
|---:|---:|---:|---:|---:|---:|
| 10 | 148 | 0.00 % | 387 ms | 788 ms | 7.06 |
| 25 | 316 | 0.00 % | 1.54 s | 1.84 s | 14.21 |
| 50 | 450 | 0.22 % | 2.47 s | 3.42 s | 19.36 |
| 100 | 480 | 1.25 % | 7.52 s | 11.64 s | 18.32 |

Comparaison avec le baseline connu:

| Palier | Avant Phase 2 | Apres Phase 2 |
|---:|---|---|
| 25 utilisateurs | 0 % erreurs, p95 2.78 s | 0 % erreurs, p95 1.54 s |
| 50 utilisateurs | 0 % erreurs, p95 8.06 s | 0.22 % erreurs, p95 2.47 s |
| 100 utilisateurs | 34.27 % erreurs, p95 9.41 s | 1.25 % erreurs, p95 7.52 s |

Le palier 50 s'ameliore fortement mais ne respecte pas encore le critere p95 < 2 s. Le palier 100 reste hors acceptation: erreurs > 1 %, p95 > 3 s et timeouts de pool encore observes.

## Requetes SQL avant/apres

| Endpoint | SQL avant | SQL apres observe | Changement |
|---|---:|---:|---|
| `/api/v1/experts-comptables` | 11 moy. | 3 sur requetes lentes | Synthese passee de plusieurs `COUNT` a une aggregation unique `FILTER`. |
| `/api/v1/encaissements` | 10.6 moy., max 25 | 1 a 2 sur listes lentes, plus sur cache auth froid | Suppression du `selectinload(articles)` par defaut et permissions lues depuis le contexte auth. |
| `/api/v1/requisitions` | 11.9 moy., max 20 | 1 sur liste standard | Annexes, montants payes, compteurs de lignes et transport charges uniquement via `include`. |
| `/api/v1/reports/summary` | 17.6 moy. | 0 sur cache chaud, 14-15 sur cache froid | Cache court tenant/periode/canal ajoute, mais la requete froide reste trop couteuse. |
| `/api/v1/budget/postes/tree` | 4.8 moy. | 2 sur cache auth chaud, 6 sur cache auth froid | Non optimise dans cette phase, reste implique dans les erreurs 500 a 100 utilisateurs. |

## Cause restante

Les logs backend confirment encore:

- `QueuePool limit of size 10 overflow 10 reached, connection timed out, timeout 5.00`.
- `DB_POOL_AT_CAPACITY checked_out=20 overflow=10`.
- `reports/summary` froid conserve encore 14 a 15 requetes SQL.
- Les creations `POST /api/v1/requisitions` et `POST /api/v1/encaissements` executent 16 a 22 requetes SQL et gardent parfois une connexion plusieurs secondes.
- Les sequences de documents utilisent `FOR UPDATE` et deviennent un point de contention sous ecriture concurrente.

## Requetes SQL optimises

- `experts_comptables`: remplacement de compteurs separes par:
  - `COUNT(*)`
  - `COUNT(*) FILTER (WHERE active = true)`
  - `COUNT(*) FILTER (WHERE active = false)`
  - `COUNT(*) FILTER (WHERE type_ec = 'SEC')`
  - `COUNT(*) FILTER (...)` pour les categories.
- `encaissements`: chargement des articles uniquement avec `include=articles`.
- `requisitions`: chargement optionnel des enrichissements couteux uniquement avec `include=annexe,montant_paye,lignes_count,remboursement_transport`.
- `reports/summary`: cache Redis court par tenant, periode et canal.

## Index ajoutes

Aucun index ajoute dans cette phase. Les index restent a justifier par `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)` avant application.

## Fichiers modifies

- `backend/app/api/deps.py`
- `backend/app/services/service_access.py`
- `backend/app/api/v1/endpoints/experts.py`
- `backend/app/api/v1/endpoints/encaissements.py`
- `backend/app/api/v1/endpoints/requisitions.py`
- `backend/app/api/v1/endpoints/reports.py`
- `backend/app/core/config.py`
- `backend/app/core/db_perf.py`
- `backend/app/db/session.py`
- `backend/app/middleware/timing.py`
- `backend/scripts/load_campaign.py`
- `backend/scripts/onec_load_phase2_after_sql.json`
- `backend/scripts/onec_load_phase2_after_report_cache.json`
- `docker-compose.yml`
- `docs/PERFORMANCE_SQL_OPTIMIZATION_20260803.md`

## Verifications executees

- Compilation Python ciblee:
  - `app/api/deps.py`
  - `app/api/v1/endpoints/experts.py`
  - `app/api/v1/endpoints/encaissements.py`
  - `app/api/v1/endpoints/requisitions.py`
  - `app/api/v1/endpoints/reports.py`
  - `app/services/service_access.py`
  - `app/core/config.py`
- Smoke test API direct:
  - `/api/v1/experts-comptables?include_summary=true&limit=25&offset=0`: 200
  - `/api/v1/encaissements?limit=20&offset=0`: 200
  - `/api/v1/requisitions?limit=20&offset=0`: 200
- Campagnes progressives 10/25/50/100 executees dans le conteneur backend avec la base PostgreSQL du compose.

Test non execute:

- `pytest`: le conteneur backend courant ne contient pas `pytest`.

## Risques ouverts

- Invalidation explicite du cache d'authentification a raccorder aux changements de roles, permissions et desactivation utilisateur.
- `reports/summary` doit encore etre reduit en requetes froides, pas seulement masque par cache court.
- Creations encaissements/requisitions trop couteuses: 16 a 22 requetes SQL et contention `document_sequences ... FOR UPDATE`.
- Les listes restent sensibles au volume parce que les schemas retournent encore beaucoup de colonnes; des schemas de liste plus legers sont encore necessaires.
- Le palier 100 reste au-dessus des criteres, donc il ne faut pas passer a deux workers ni a 500 utilisateurs.

## Etape suivante recommandee

1. Optimiser la generation de numeros de documents pour reduire la contention `FOR UPDATE`.
2. Regrouper les validations et lectures de creation encaissements/requisitions.
3. Recrire `reports/summary` froid en 3 a 5 aggregations SQL au lieu de 14 a 15.
4. Ajouter des tests automatises de nombre de requetes SQL.
5. Rejouer 10/25/50/100 avant toute augmentation de workers ou pool.

## Conclusion

Non pret pour 500 utilisateurs simultanes.
