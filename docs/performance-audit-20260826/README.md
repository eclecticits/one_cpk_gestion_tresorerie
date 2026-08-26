# Audit de performance ONEC Smart — 26/08/2026

Sept audits parallèles, un par couche. Chaque rapport classe ses constats par
(gain attendu × confiance) et marque chacun **MESURÉ** ou **DÉDUIT**.

## Contrainte à connaître avant de lire

Le démon Docker était arrêté pendant tout l'audit. **Aucun temps de réponse
HTTP, aucun `EXPLAIN`, aucune statistique PostgreSQL n'a pu être relevé.**
Ce qui est marqué MESURÉ l'a été sur le bundle produit (`npm run build`) ou
par exécution directe de code Python. Le reste est du raisonnement sur le
code. Les rapports le disent en tête, chacun avec sa section « Ce que je n'ai
pas pu vérifier ».

## Les rapports

| Fichier | Couche | Constat de tête |
|---|---|---|
| `perf-backend.md` | FastAPI / SQLAlchemy | `db/session.py:478` reconstruit 78 `with_loader_criteria` à chaque SELECT ORM — 6,41 ms contre 0,84 ms sans listener (mesuré) |
| `perf-frontend.md` | React / Vite | six chunks de route tiraient jspdf/xlsx en import statique — **corrigé, commit 0b4c329** |
| `perf-postgres.md` | PostgreSQL | verrou `caisse_centrale` tenu sur toute la transaction ; ~24 index redondants ; inventaire de 425 index sur 116 tables |
| `perf-infra.md` | Docker / nginx | le dimensionnement pool/workers n'avait jamais atteint la production — **corrigé, commit 0b4c329** |
| `perf-reseau.md` | Réseau frontend ↔ API | 4 allers-retours séquentiels avant la première donnée utile ; 13 requêtes API pour se connecter |
| `perf-permissions.md` | Settings / permissions | le chemin d'autorisation est déjà optimisé (0 SQL par vérification) — l'hypothèse de départ était fausse |
| `perf-loadtest.md` | Tests de charge | scénarios k6 prêts à lancer, dans `backend/scripts/loadtest/` |

## Ce qui a déjà été appliqué

Commit `0b4c329` : allègement des six routes (jusqu'à −95 % du JS téléchargé),
`Settings.tsx` parallélisé, `docker-compose.prod.yml` aligné sur la
configuration validée sous charge, compression déplacée de Python vers nginx.

## Ce qui attend Docker, et pourquoi

1. **Le listener multi-tenant** (`perf-backend.md`, gain le plus élevé de tout
   l'audit) est la frontière d'isolation entre organisations. Le modifier sans
   faire passer `backend/tests/test_multi_tenant_isolation.py` risque une fuite
   de données inter-organisation. Non appliqué.
2. **La suppression des index redondants** (`perf-postgres.md`) exige de lire
   `pg_stat_user_indexes.idx_scan` en production d'abord. Un index supprimé sur
   la foi d'une lecture de code peut être celui qui tient une requête chaude.
3. **La validation chiffrée** de tout le reste : `backend/scripts/loadtest/`
   contient de quoi rejouer le palier 100 VU avant/après.
