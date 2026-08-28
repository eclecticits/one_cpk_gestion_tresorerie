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

## Suites de l'audit

| Fichier | Date | Constat de tête |
|---|---|---|
| `perf-validation-20260827.md` | 27/08 | la campagne ne mesurait pas ce qu'on croyait : tenant suspendu, jeu de test invalide, générateur tué par l'OOM |
| `perf-exports-20260827.md` | 27/08 | trois défauts des exports Excel : clause `IN` non bornée (échec fonctionnel), styles re-hachés par openpyxl, connexion retenue toute la génération |
| `perf-charge-20260828.md` | 28/08 | **le scénario d'export du banc consomme à lui seul toute la machine** : sans lui, 25 VU sont servis à 88 ms de médiane et zéro 5xx. Et `/exports/budget` écrivait 76 lignes dans un GET |

## Ce qui a déjà été appliqué

Commit `0b4c329` : allègement des six routes (jusqu'à −95 % du JS téléchargé),
`Settings.tsx` parallélisé, `docker-compose.prod.yml` aligné sur la
configuration validée sous charge, compression déplacée de Python vers nginx.

**Exports, phase 0 (28/08, non commité)** — le préalable à la génération
asynchrone, livrable et utile seul :

- clause `IN` découpée en lots de 10 000 : au-delà de 32 767 paramètres de bind,
  l'export répondait 500 avec un seul utilisateur. Défaut fonctionnel, pas de
  performance ;
- cache de styles openpyxl : 14,9 s des 18 s de construction de 4 800 lignes
  étaient du re-hachage d'objets de style identiques ;
- `/exports/budget` n'écrit plus dans un GET (76 `UPDATE budget_postes` par
  appel, dont un relevé à 11,5 s sous charge) et rend sa connexion au pool avant
  la construction du classeur, comme les deux autres exports lourds ;
- `proxy_read_timeout` à 130 s sur les deux nginx : un export de 112 s était
  coupé à 60 s, et le worker continuait de générer un fichier que personne ne
  recevrait ;
- `location internal /_protected_uploads/` et montage du volume d'uploads côté
  `frontend` : le constat C5 de `perf-infra.md` est levé ;
- plafond de lignes (`EXPORT_MAX_ROWS`, 60 000) : un export qui ne peut pas
  aboutir est refusé en `413` avec sa raison, plutôt que de tenir un worker
  jusqu'à ce que l'arbitre gunicorn le tue.

Détail, mesures et limites de vérification : `docs/architecture-exports-asynchrones-20260828.md`.

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
