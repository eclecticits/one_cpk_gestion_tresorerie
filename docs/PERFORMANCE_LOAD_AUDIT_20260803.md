# Audit de charge ONEC Smart - 2026-08-03

## Résumé exécutif

Campagne exécutée sur le stack Docker local `onec_smart` contre le backend actif `http://backend:8000/api/v1` et la base PostgreSQL `onec_cpk`.

Conclusion: la configuration actuelle n'est pas prête pour 500 utilisateurs simultanés. Le palier 100 utilisateurs échoue déjà avec 100% de timeouts côté client. La cause racine observée dans les logs backend est la saturation du pool SQLAlchemy:

```text
QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00
```

Capacité maximale actuelle validée: inférieure à 100 utilisateurs simultanés sur cette configuration locale.

## Méthode

Script reproductible: `backend/scripts/load_campaign.py`

Jeu de charge créé automatiquement:

- 1 000 utilisateurs de test sous l'organisation `load-test-20260803`
- profils représentés: `super_admin`, `admin`, `comptable`, `caissier`, `valideur`, `expert_comptable`, `utilisateur`
- 1 000 experts-comptables de test
- 1 service `LOAD`
- 1 exercice budgétaire 2026
- 1 poste recette et 1 poste dépense
- 1 caisse
- 1 banque et 1 compte bancaire
- autorisations service-rubrique nécessaires aux encaissements

Mode d'authentification de la charge: `direct-token`.

Justification: `/auth/login` est limité à `5/minute` par IP. Simuler 500 connexions depuis un seul générateur local mesurerait surtout l'anti-bruteforce, pas la capacité métier du backend.

## Résultats

| Utilisateurs | RPS | Erreurs | Latence moyenne | Latence max | Statuts |
|---:|---:|---:|---:|---:|---|
| 100 | 6.67 | 100.00% | 22 810 ms | 26 270 ms | `0:100` |
| 250 | 16.67 | 89.20% | 29 793 ms | 36 723 ms | `0:223`, `200:27` |
| 500 | 33.33 | 59.00% | 26 159 ms | 37 858 ms | `0:295`, `200:203`, `201:2` |
| 750 | 50.00 | 73.73% | 35 446 ms | 46 735 ms | `0:553`, `200:197` |
| 1 000 | 66.67 | 89.10% | 33 510 ms | 44 048 ms | `0:891`, `200:109` |

`status 0` signifie timeout/erreur réseau côté générateur avant réception d'une réponse HTTP.

## Métriques système

Avant charge:

- backend: 0.70% CPU, 416.6 MiB
- PostgreSQL: 0.08% CPU, 73.14 MiB
- Redis: 14.45% CPU, 8.812 MiB

Après charge:

- backend: 2.63% CPU, 553.1 MiB
- PostgreSQL: 50.39% CPU, 83.21 MiB
- Redis: 2.25% CPU, 8.992 MiB

PostgreSQL après charge:

```text
active connections: 2
idle connections: 5
xact_commit: 2334
xact_rollback: 3463
blks_read: 1032
blks_hit: 657481
tup_returned: 3835094
tup_fetched: 427347
```

## Goulots d'étranglement

Critique:

- Pool SQLAlchemy trop petit: `pool_size=5`, `max_overflow=10`, timeout 30 s.
- Saturation dès l'authentification applicative interne: chaque requête appelle `get_current_user`, qui ouvre une connexion DB.
- Les timeouts du pool remontent en exceptions non maîtrisées et peuvent produire des erreurs 500.
- Requêtes lentes observées dans les logs: `/requisitions`, `/experts-comptables`, `/reports/summary`, `/dashboard/stats`, `/budget/postes/tree`, `/encaissements`.

Élevée:

- Trop de requêtes DB par requête API, notamment dans les dépendances tenant/RBAC.
- Rollbacks élevés après charge: `3463`, supérieur aux commits.
- Absence de garde de concurrence côté API: le backend accepte plus de requêtes qu'il ne peut servir avec son pool actuel.

Moyenne:

- Le test frontend Chrome/Edge n'a pas encore été exécuté. Cette campagne a couvert le backend et PostgreSQL.
- Les exports PDF/Excel et imports Excel simultanés ne sont pas encore couverts dans le script.

## Recommandations

1. Dimensionner le pool DB par environnement.
   - Ajouter des variables explicites: `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`.
   - Point de départ pour test local/prod pilote: `pool_size=20`, `max_overflow=40`, `pool_timeout=10`.
   - Gain attendu: réduction forte des timeouts de connexion, mais à valider avec `max_connections` PostgreSQL.

2. Ajouter plusieurs workers backend.
   - La charge actuelle repose sur un seul conteneur backend.
   - Tester Gunicorn/Uvicorn avec 2 à 4 workers selon CPU disponible.
   - Gain attendu: meilleure utilisation CPU et débit plus stable.

3. Optimiser `get_current_user` et la résolution tenant/RBAC.
   - Cache court des utilisateurs actifs et permissions par token/user.
   - Éviter une requête DB complète sur chaque appel si le JWT contient déjà des claims fiables.
   - Gain attendu: baisse du nombre de connexions et latence sur tous les endpoints.

4. Profiler les endpoints lents.
   - Activer logs SQL lents ou `pg_stat_statements`.
   - Priorité: dashboard, rapports, experts, budget tree, listes réquisitions/encaissements.
   - Gain attendu: identifier N+1, agrégations coûteuses et index manquants.

5. Ajouter backpressure.
   - Limiter la concurrence applicative ou retourner `503` contrôlé au lieu d'attendre 30 secondes.
   - Gain attendu: meilleure stabilité sous surcharge.

6. Compléter la campagne frontend et fichiers.
   - Ajouter scénarios Playwright/Lighthouse pour Chrome et Edge.
   - Ajouter import Excel, export PDF et export Excel concurrents.

## Fichiers générés

- `backend/scripts/load_campaign.py`
- `backend/scripts/onec_load_validation.json`
- `backend/scripts/onec_load_report.json`
- `docs/PERFORMANCE_LOAD_AUDIT_20260803.md`

## Validation finale

ONEC Smart n'est pas validé pour 500 utilisateurs simultanés sur la configuration testée le 2026-08-03.

Blocage principal avant production: saturation du pool de connexions PostgreSQL côté SQLAlchemy.
