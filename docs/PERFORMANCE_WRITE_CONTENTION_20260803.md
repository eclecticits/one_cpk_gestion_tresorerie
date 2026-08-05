# Phase 3 - Suppression des contentions d'ecriture

Date: 2026-08-03

## Perimetre

Configuration conservee pour la validation:

- Backend: 1 worker
- SQLAlchemy: `pool_size=10`, `max_overflow=10`, `pool_timeout=5`
- Budget de connexions potentiel: `1 x (10 + 10) = 20`
- Organisation de test: `load-test-20260803`, tenant `18`
- Aucun test 250/500 utilisateurs execute dans cette phase.

## Protection du workspace

Sauvegardes creees avant modification:

- `backups/workspace_before_perf_phase3_20260803.patch`
- `backups/workspace_staged_before_perf_phase3_20260803.patch`
- `backups/workspace_untracked_before_perf_phase3_20260803.tar.gz`

Branche de travail:

- `perf-write-contention-validation-20260803`

Le workspace contient des changements metier, UI et performance preexistants. Aucun commit global n'a ete cree pour eviter d'inclure des modifications sans rapport.

## document_sequences

### Fonctionnement initial

La generation utilisait:

1. `INSERT ... ON CONFLICT DO NOTHING`
2. `SELECT ... FROM document_sequences ... FOR UPDATE`
3. Incrementation ORM de `counter`
4. `flush()`
5. Lecture optionnelle du code service

Cle fonctionnelle reelle:

- Centrale: `(doc_type, year, tenant_id)` avec `service_id IS NULL`
- Service: `(doc_type, year, tenant_id, service_id)` avec `service_id IS NOT NULL`

Les contraintes/index partiels existent deja:

- `uq_docseq_central`
- `uq_docseq_service`

### Correction appliquee

Le verrou explicite `FOR UPDATE` a ete remplace par une reservation atomique courte:

- `INSERT ... ON CONFLICT ... DO UPDATE`
- `counter = document_sequences.counter + 1`
- `RETURNING counter`

La reservation reste dans PostgreSQL et retourne directement le numero reserve. Aucun remplacement par sequence PostgreSQL native n'a ete fait, car le modele actuel exige une numerotation separee par type, annee, tenant et service. Une sequence native serait plus rapide mais accepte naturellement des trous apres rollback.

Garantie conservee:

- unicite par cle fonctionnelle
- ordre croissant
- isolation tenant/service/annee/type

Garantie non revendiquee:

- absence absolue de trous

## Tests de concurrence

Nouveau fichier:

- `backend/tests/test_document_sequences_concurrency.py`

Scenarios testes:

- 10, 25, 50 et 100 reservations concurrentes
- `REQ` par service
- `PAY` par service
- `ND` central
- `OD` central

Resultat:

- `16 passed`
- Aucun doublon
- Formats valides
- Series ordonnees `1..N`

Suite ciblee apres changements:

- `25 passed, 242 warnings`

Compilation:

- `python -m compileall -q app`: OK

## Optimisation budget/postes/tree

Avant:

- Chargement ORM complet de `BudgetPoste`
- Mutation des objets ORM pour les vues par service
- Construction de l'arbre depuis des instances ORM

Apres:

- Projection stricte des colonnes necessaires
- Structure legere `_BudgetTreeLine`
- Construction de l'arbre hors ORM

Smoke test tenant 18:

- Appel 1: 555 ms, 637 octets
- Appel 2: 225 ms, 637 octets
- Appel 3: 196 ms, 637 octets

Sous charge 25 utilisateurs:

- `budget_tree`: p95 892 ms

Sous charge 50 utilisateurs:

- `budget_tree`: p95 2.95 s

Sous charge 100 utilisateurs:

- `budget_tree`: p95 6.61 s

Conclusion: la projection corrige le cout local de l'endpoint, mais a 100 utilisateurs l'endpoint subit encore la saturation globale du pool.

## EXPLAIN ANALYZE

### document_sequences ancien acces FOR UPDATE representatif

Tenant 18, service 23, `REQ`, 2026:

- Plan: `Seq Scan` sur 13 lignes, puis `LockRows`
- Execution: 0.084 ms
- Buffers: shared hit=3

Le Seq Scan est normal sur cette table minuscule. La contention vient de la concurrence sur la meme ligne, pas d'un index manquant.

### budget_postes tree representatif

Tenant 18, exercice 2026, type DEPENSE:

- Plan: `Seq Scan` sur 127 lignes
- Execution: 0.364 ms
- Buffers: shared hit=7

Aucun index ajoute: le volume du jeu de test ne justifie pas un index supplementaire ici. Un index composite devra etre reconsidere avec un volume de production reel.

## Correction du script de charge

Fichier modifie:

- `backend/scripts/load_campaign.py`

Corrections:

- attente explicite de `/health/ready` avant chaque palier
- resume du warmup inclus dans le rapport
- taille moyenne des reponses JSON par endpoint

Anomalie confirmee avant correction:

- Palier 10: 100 % `ReadTimeout`
- Palier 25 juste apres: 0 % erreur

Cause: effet cold start / backend pas encore stabilise et warmup non visible dans le rapport.

## Resultats de charge valides

### 10 utilisateurs

- Erreurs: 0 %
- p50: 60 ms
- p90: 270 ms
- p95: 495 ms
- p99: 715 ms
- RPS completes: 7.25

### 25 utilisateurs

- Erreurs: 0 %
- p50: 137 ms
- p90: 908 ms
- p95: 1.10 s
- p99: 1.38 s
- RPS completes: 15.09

### 50 utilisateurs

- Erreurs: 0 %
- p50: 976 ms
- p90: 2.96 s
- p95: 3.36 s
- p99: 4.34 s
- RPS completes: 17.45

Ce palier ne respecte pas le critere demande `p95 < 2 s`.

### 100 utilisateurs

- Erreurs: 0.22 %
- p50: 3.23 s
- p90: 5.65 s
- p95: 7.27 s
- p99: 11.93 s
- RPS completes: 18.63
- Erreur 500: `GET /api/v1/encaissements`

Cause de l'erreur 500:

- `QueuePool limit of size 10 overflow 10 reached, connection timed out, timeout 5.00`
- Snapshot: `checked_out=20`, `overflow=10`

## Endpoints encore couteux

A 100 utilisateurs:

- `requisition_create`: p95 12.93 s, 13 requetes SQL, sequence documentaire encore lente sous contention
- `encaissement_create`: p95 12.34 s, 19-20 requetes SQL
- `reports_summary`: p95 7.30 s, 15 requetes SQL a froid/cache miss
- `budget_tree`: p95 6.61 s sous saturation globale
- `experts_list`: p95 5.73 s
- `encaissements_list`: 1 erreur 500 par timeout de pool

## Demarrage applicatif

Risque ouvert important:

- Le worker Gunicorn met environ 1 min 50 s a atteindre `Application startup complete` apres rebuild.
- Diagnostic `-X importtime`: `app.api.v1.router` atteint environ 60 s d'import cumule.
- Imports lourds observes: `openpyxl`, `pdfplumber`, `pandas`, modules secretariat, treasury, requisitions.

Ce point fausse les premiers paliers si le test demarre trop tot et doit etre corrige avant une vraie campagne production.

## Comparaison un worker / deux workers

Deux workers n'ont pas ete testes.

Raison:

- Le critere d'entree n'est pas atteint avec un worker.
- 50 utilisateurs depasse deja le p95 cible.
- 100 utilisateurs sature encore le pool et produit une erreur 500.

Tester deux workers maintenant doublerait le budget potentiel a `2 x (10 + 10) = 40` connexions et risquerait d'amplifier la contention documentaire sans corriger la cause applicative.

## Fichiers Phase 3

- `backend/app/services/document_sequences.py`
- `backend/tests/test_document_sequences_concurrency.py`
- `backend/app/api/v1/endpoints/budget.py`
- `backend/scripts/load_campaign.py`
- `docs/PERFORMANCE_WRITE_CONTENTION_20260803.md`

## Conclusion

Non pret pour 500 utilisateurs simultanes.

Le prochain objectif reste:

- stabiliser 100 utilisateurs
- erreurs < 1 %
- p95 < 3 s
- aucune saturation durable du pool
- aucune erreur 500 liee a PostgreSQL

Actions recommandees avant de tester deux workers:

- reduire `reports/summary` froid de 15 requetes vers 5-8 requetes
- reduire `encaissement_create` de 19-20 requetes vers 8-12
- reduire `requisition_create` de 13 requetes et raccourcir la transaction
- supprimer les imports lourds au demarrage ou les charger paresseusement
- analyser les traitements non SQL qui occupent le worker pendant que les connexions restent rares
