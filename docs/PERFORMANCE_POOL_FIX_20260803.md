# Correction progressive du pool DB - 2026-08-03

## Sauvegarde et isolation

- Branche dédiée: `perf-pool-load-validation-20260803`
- Commit de référence avant optimisation: `a67b5ec`
- Dump PostgreSQL créé avant modification: `backups/onec_cpk_before_perf_pool_20260803.dump`
- Organisation de test isolée: `load-test-20260803`, id `18`
- Aucun nettoyage automatique exécuté.

## Budget de connexions

PostgreSQL:

```text
SHOW max_connections = 100
```

Configuration testée:

```text
workers = 1
DB_POOL_SIZE = 10
DB_MAX_OVERFLOW = 10
DB_POOL_TIMEOUT = 5
DB_POOL_RECYCLE = 1800
DB_POOL_PRE_PING = true
```

Formule:

```text
connexions potentielles = workers x (pool_size + max_overflow)
```

Budget actuel:

```text
1 x (10 + 10) = 20 connexions
```

Marge conservée:

```text
100 - 20 = 80 connexions
```

## Correction appliquée

Le pool SQLAlchemy async est maintenant configurable via:

- `DB_POOL_SIZE`
- `DB_MAX_OVERFLOW`
- `DB_POOL_TIMEOUT`
- `DB_POOL_RECYCLE`
- `DB_POOL_PRE_PING`
- `DB_POOL_SLOW_CHECKOUT_SECONDS`
- `DB_SLOW_QUERY_MS`
- `BACKEND_WORKERS`

Instrumentation ajoutée:

- log de configuration du pool;
- alerte lorsque le pool atteint sa capacité;
- alerte lorsqu'une connexion est gardée trop longtemps;
- compteur SQL par requête HTTP;
- temps SQL cumulé par requête HTTP;
- requête SQL la plus lente par requête HTTP;
- log des requêtes SQL dépassant `DB_SLOW_QUERY_MS`.

## Correction méthodologique du test

Le script `backend/scripts/load_campaign.py` a été corrigé:

- paliers exécutés avec nouveaux clients HTTP;
- warmup non mesuré;
- pause de stabilisation entre paliers;
- temps de réflexion réaliste;
- p50, p90, p95, p99, max;
- taux d'erreur par endpoint;
- distinction `ReadTimeout`, 4xx, 5xx;
- RPS basé sur durée théorique et RPS réellement complété.

## Résultats comparatifs

Avant correction, palier 100:

```text
100 utilisateurs
100% erreurs
p95: 25.9 s
cause: QueuePool size 5 overflow 10 timeout 30 s
```

Après correction `10+10`, un worker:

| Utilisateurs | Requêtes | RPS complété | Erreurs | p50 | p90 | p95 | p99 | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 198 | 6.26 | 0.00% | 186 ms | 801 ms | 903 ms | 1 303 ms | 1 548 ms |
| 25 | 351 | 11.00 | 0.00% | 607 ms | 2 367 ms | 2 777 ms | 3 974 ms | 4 243 ms |
| 50 | 315 | 9.29 | 0.00% | 3 463 ms | 6 262 ms | 8 056 ms | 11 873 ms | 17 278 ms |
| 100 | 429 | 11.17 | 34.27% | 6 512 ms | 8 587 ms | 9 414 ms | 14 419 ms | 21 161 ms |

Résultat: le pool `10+10` améliore fortement le palier 10 et évite les erreurs à 25/50, mais le palier 100 échoue encore.

## Preuves applicatives

À 100 utilisateurs, les logs backend confirment encore une saturation, mais avec la nouvelle limite:

```text
QueuePool limit of size 10 overflow 10 reached, connection timed out, timeout 5.00
DB_POOL_AT_CAPACITY snapshot={'size': 10, 'checked_in': 0, 'checked_out': 20, 'overflow': 10}
```

Les logs enrichis montrent des coûts élevés:

- `/api/v1/reports/summary`: environ 18 requêtes SQL par appel;
- `/api/v1/experts-comptables`: environ 11 requêtes SQL par appel;
- `/api/v1/requisitions`: environ 6 à 9 requêtes SQL par appel;
- création réquisition: jusqu'à 18 à 20 requêtes SQL;
- création encaissement: jusqu'à 24 requêtes SQL;
- `get_current_user` apparaît fréquemment comme requête la plus lente sous contention;
- les permissions et services sont relus très souvent;
- les écritures déclenchent des appels internes `GET /api/v1/tenants/18/status` qui retournent `404`.

## Goulots restants

Critique:

- 100 utilisateurs simultanés échoue encore avec 34.27% d'erreurs.
- La saturation se produit maintenant à 20 connexions potentielles, ce qui prouve que l'application garde trop longtemps les connexions ou fait trop d'allers-retours SQL.

Élevé:

- Un seul worker atteint environ 100% CPU dès 25 utilisateurs.
- Les endpoints de rapports et experts font trop de requêtes SQL par appel.
- Les créations de réquisitions/encaissements gardent des connexions plusieurs secondes.
- Les requêtes d'authentification/RBAC sont répétées à haute fréquence.

## Prochaines corrections recommandées

1. Ne pas augmenter encore le pool.
   - Le palier 100 échoue déjà avec 20 connexions potentielles.
   - Augmenter sans réduire le coût SQL déplacerait le problème vers PostgreSQL.

2. Optimiser `get_current_user`, permissions et services.
   - Cache Redis court 30 à 60 secondes pour données sérialisées: user_id, tenant_id, role, role_id, permissions, service_ids, is_active.
   - Ne pas cacher d'objet ORM.
   - Invalidation lors des changements de rôle/permissions.

3. Corriger les appels SaaS internes sur les écritures.
   - Éviter l'appel HTTP interne à `/api/v1/tenants/{id}/status` si la console SaaS n'est pas disponible.
   - Mettre en cache négatif court les 404.
   - Ne pas garder une session DB ouverte pendant un appel réseau.

4. Réduire les agrégations des rapports.
   - Regrouper les agrégats.
   - Ajouter cache court avec invalidation après opération financière validée.
   - Étudier les index uniquement avec `EXPLAIN ANALYZE`.

5. Optimiser les créations de documents.
   - La génération de numéros utilise `document_sequences ... FOR UPDATE`.
   - Vérifier les verrous et l'idempotence sous concurrence.

## Conclusion

Non prêt pour 500 utilisateurs simultanés.

La première correction progressive est utile mais insuffisante. Le prochain travail doit réduire le nombre de requêtes SQL par endpoint et la durée de détention des connexions avant de tester deux workers ou un pool plus grand.
