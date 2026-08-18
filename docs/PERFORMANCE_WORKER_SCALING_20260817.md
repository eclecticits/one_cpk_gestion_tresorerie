# Phase 4 - Le goulot n'etait pas la base de donnees

Date: 2026-08-17

Reprise de PERF-001, suspendu le 2026-08-03 a la fin de la Phase 3.

## Resultat principal

Le palier 100 utilisateurs passe desormais les criteres d'entree, avec 3 workers:

- Erreurs: 0.26 % (critere: < 1 %)
- p95: 1.56 s (critere: < 3 s)
- p99: 2.05 s
- p50: 115 ms
- RPS completes: 57.4

La Phase 3 concluait qu'il ne fallait pas ajouter de worker avant d'avoir
stabilise un worker. Cette regle reposait sur une hypothese fausse, corrigee
par la mesure ci-dessous: la contention n'etait pas dans PostgreSQL.

## Environnement de mesure

Machine de test, a prendre en compte pour toute comparaison:

- 12 coeurs
- 3.7 Go de RAM totale, ~1.2 Go disponible, swap actif (28 546 pages sorties)
- Charge moyenne ~7 AU REPOS: la machine execute d'autres piles (frontend,
  WordPress) pendant les tests
- Le generateur de charge tourne DANS le conteneur backend et dispute le CPU
  au serveur teste

Les valeurs absolues ne sont donc pas comparables a une machine de production.
Les rapports entre configurations, mesures dans la meme session et sur la meme
machine, sont eux exploitables.

Jeu de donnees: organisation `load-test-20260803`, tenant 18, soit 299
requisitions, 245 encaissements, 1000 utilisateurs, 1584 experts. Volume faible,
point traite en fin de document.

## Re-baseline: regression constatee

Deux semaines de developpement metier (RH, agent de presence, paiement mixte,
budget) ont ete livrees depuis la Phase 3. Premiere action: rejouer la campagne
dans la configuration exacte de la Phase 3 (1 worker, pool 10+10).

| Palier | Phase 3 (2026-08-03) | Re-baseline (2026-08-17) |
|---|---|---|
| 10 users | 0 % err, p95 495 ms | 0 % err, p95 588 ms |
| 25 users | 0 % err, p95 1.10 s | 0.22 % err, p95 1.55 s |
| 50 users | 0 % err, p95 3.36 s | 0.31 % err, p95 10.38 s |
| 100 users | 0.22 % err, p95 7.27 s | 36.51 % err, p95 20.01 s |

Le palier 100 s'effondre: 164 `QueuePool limit of size 10 overflow 10 reached`.

Une partie de cet ecart vient de la machine elle-meme (voir environnement
ci-dessus), qui n'etait pas dans le meme etat le 2026-08-03. La suite du
diagnostic ne depend pas de cet ecart.

## Diagnostic: le worker est limite par le CPU, pas par PostgreSQL

Echantillonnage de la consommation CPU pendant un palier 50 utilisateurs isole,
1 worker:

```
T+6s   backend=102.03%   db=0.06%
T+14s  backend=102.93%   db=0.00%
T+18s  backend= 97.48%   db=62.88%
T+30s  backend= 98.89%   db=0.01%
T+40s  backend= 95.84%   db=0.00%
```

Le worker est colle a 100 % d'UN coeur pendant toute la duree du palier.
PostgreSQL est majoritairement inactif, avec des pointes a 60 % d'un coeur.

Les timeouts de pool sont donc un SYMPTOME et non la cause: une requete garde sa
connexion pendant qu'elle attend du temps CPU Python. Augmenter le pool n'aurait
rien corrige; le reduire non plus.

Verification complementaire: a vide, le cout unitaire des endpoints est intact
par rapport a la Phase 3 (budget_tree 181-235 ms contre 196-225 ms en Phase 3).
La regression est donc concurrentielle, pas algorithmique.

## Profil CPU du worker (py-spy)

Note de methode: un premier enregistrement en mode `--nonblocking` attribuait
93.8 % du temps a une seule ligne (`langhelpers.py:1429`, le compteur d'ID de
session SQLAlchemy). C'est un artefact: en mode non bloquant, py-spy lit la pile
sans figer le processus et produit des piles incoherentes. Un lock non contendu
ne peut pas consommer 94 % du CPU. Seul le releve en mode bloquant, ci-dessous,
est retenu.

Repartition inclusive, 1418 echantillons, palier 25 utilisateurs:

| Poste | Part du CPU |
|---|---|
| SQLAlchemy (construction / execution / materialisation) | 46.1 % |
| Sonde `/health/ready` | 11.9 % |
| threadpool inactif | 8.3 % |
| event loop inactif | 6.8 % |
| slowapi (rate limiting) | 6.6 % |
| connexion DB + handshake SSL | 5.1 % |
| JWT / crypto | 4.1 % |
| prometheus | 3.3 % |
| pydantic (validation / serialisation) | 2.1 % |

Lecture: 46 % du CPU part dans SQLAlchemy alors que la base de donnees est
inactive. Ce n'est pas de l'attente de reponse SQL, c'est du cout Python de
construction de requetes et de materialisation ORM. C'est le gisement principal.

Le middleware par requete (slowapi + prometheus, ~10 %) est le second poste
evitable: `slowapi/middleware.py:23` fait un balayage lineaire des routes a
chaque appel.

## Correctifs appliques

### 1. La sonde de readiness reconstruisait un moteur SQLAlchemy a chaque appel

`app/api/v1/endpoints/health.py` appelait `create_async_engine` a chaque
requete, puis `dispose()`. Chaque appel payait la construction du moteur
(parsing d'URL, dialecte, enregistrement des events) et un handshake SSL neuf.
Sous charge, un appel a ete mesure a 8.0 s, un autre a 3.4 s.

Le moteur est desormais construit une seule fois, en initialisation paresseuse.
`NullPool` est conserve: la garantie d'origine tient toujours (aucune connexion
gardee entre deux appels, resultat frais, pas de conflit d'event-loop en test).

Mesure a vide, 4 workers, mediane sur 16 appels apres rechauffement:

- Avant: 281 ms
- Apres: 117 ms

### 2. pandas et pdfplumber charges par chaque worker au demarrage

`treasury.py` importait `ExcelParser` (donc pandas, 57 Mo de RSS, 1.3 s
d'import) et `requisitions.py` importait `parse_requisition_pdf` (donc
pdfplumber, 10 Mo) au niveau module, pour un endpoint chacun. Les deux imports
sont deplaces dans la vue.

Mesure, conteneur a 4 workers:

- Avant: 1.605 Go de RSS
- Apres: 1.421 Go de RSS, soit -46 Mo par worker

Sur cette machine, c'est ce qui rend possible un worker supplementaire.

`openpyxl` (8 Mo, 321 ms) n'a pas ete traite: il est utilise en plusieurs points
de `exports.py`, `clotures.py` et `audit_logs.py`, et le rapport
effort / gain ne le justifie pas.

### 3. Le temps de demarrage n'est pas du a ces imports

Diagnostic `-X importtime` sur `app.api.v1.router`: 15 s au total, dont 6.5 s
dans le corps de `router.py` lui-meme, c'est-a-dire l'enregistrement des 517
routes par FastAPI. pandas et openpyxl ne pesent que ~1.6 s.

La recommandation de la Phase 3 ("supprimer les imports lourds au demarrage")
ne corrige donc qu'environ 10 % du temps de demarrage. Le reste est intrinseque
a FastAPI et au nombre de routes. Demarrage constate apres correctifs: 34 a 50 s
selon la charge de la machine.

## Scaling par worker

Toutes les mesures ci-dessous: pool 10+10 par worker, campagne identique.

| Config | 50 users | 100 users | RPS a 100 users |
|---|---|---|---|
| 1 worker | 0 % err, p95 4.30 s | 12.82 % err, p95 9.77 s | 12.7 |
| 2 workers | 0 % err, p95 1.80 s | 0.23 % err, p95 9.45 s | 23.7 |
| 3 workers | 0 % err, p95 4.00 s (*) | 0.25 % err, p95 2.09 s | 48.1 |
| 3 workers + correctifs | 0 % err, p95 1.34 s | 0.26 % err, p95 1.56 s | 57.4 |

(*) Le palier 50 de cette serie est le premier execute apres redemarrage et
absorbe le rechauffement des caches malgre le warmup de 5 s. L'ordre des paliers
influence le resultat: a interpreter avec prudence.

Le debit croit de facon quasi lineaire avec le nombre de workers (12.7, 23.7,
48.1), ce qui confirme le diagnostic: le systeme est limite par le CPU d'un
processus Python, et PostgreSQL a de la marge.

Cout memoire mesure: environ 355 Mo par worker apres correctifs (1.069 Go pour
3 workers, 1.421 Go pour 4).

## Projection

Base de calcul, mesuree: environ 19 RPS par worker, et 0.57 req/s par
utilisateur virtuel au profil realiste (think time 0.5-2 s).

| Cible | Debit requis | Workers necessaires | RAM backend |
|---|---|---|---|
| 100 users | ~57 RPS | 3 | ~1.1 Go |
| 200 users | ~115 RPS | ~6 | ~2.1 Go |
| 500 users | ~285 RPS | ~15 | ~5.3 Go |

Ces chiffres supposent autant de coeurs reellement disponibles que de workers,
et une base de donnees qui garde sa marge.

Deux reserves majeures pesent sur cette projection:

1. **Le volume de donnees.** La linearite tient tant que PostgreSQL est
   inactif. Le jeu de test compte 299 requisitions et 245 encaissements. A
   volume de production, le cout SQL monte et ajouter des workers ne corrigera
   pas ce deplacement du goulot. C'est le risque principal et il n'est pas
   couvert par les mesures de cette phase.
2. **La marge de latence.** A 100 utilisateurs et 3 workers, le p95 est a
   1.56 s pour un budget de 3 s. Doubler le nombre d'utilisateurs impose de
   doubler la capacite pour simplement conserver le meme p95.

Point favorable non compte: le generateur de charge occupait le CPU de la
machine testee. En production, les utilisateurs sont externes et le backend
recupere cette capacite.

## Coordination pool / workers

Le budget de connexions vaut `workers x (pool_size + max_overflow)`:

- Configuration par defaut du depot: 4 x (5 + 5) = 40
- Configuration des tests de cette phase: 3 x (10 + 10) = 60
- 4 workers en 10+10 donneraient 80, pour un `max_connections` PostgreSQL de 100

Toute augmentation du nombre de workers doit etre verifiee contre
`max_connections`, sans quoi la saturation se deplace vers un refus de connexion
cote PostgreSQL.

## Travaux restants, par valeur decroissante

1. Reduire le cout CPU Python par requete, principalement les 46 % SQLAlchemy:
   projections de colonnes a la place du chargement d'entites ORM sur les
   endpoints de liste, sur le modele de ce qui a ete fait pour `budget_tree` en
   Phase 3 (cet endpoint ne pese plus que 0.4 % du profil).
2. Rejouer la campagne sur un volume de donnees representatif de la production.
   Sans cela, la projection ci-dessus n'est pas validee.
3. Reduire le middleware par requete (~10 %): balayage lineaire des routes par
   slowapi, instrumentation prometheus.
4. Reduire le nombre de requetes des endpoints de creation:
   `encaissement_create` (19-20 requetes) et `requisition_create` (13), et
   `reports/summary` (16 requetes sequentielles a froid, dont 4 comptages de
   requisitions qui tiennent dans une seule requete groupee).
5. Valider 200 utilisateurs sur la machine cible, generateur de charge sur une
   machine SEPAREE.
6. Test d'endurance, imports/exports concurrents, monitoring de production.

## Fichiers modifies

- `backend/app/api/v1/endpoints/health.py`
- `backend/app/api/v1/endpoints/treasury.py`
- `backend/app/api/v1/endpoints/requisitions.py`

Tests: `6 passed, 11 skipped` sur `test_treasury_readonly.py`,
`test_treasury_flows.py`, `test_requisitions_list_filters.py`.
`test_health_e2e.py`: 5 tests passes en skip (serveur live requis).

## Conclusion

Le critere d'entree de la Phase 4 est atteint: 100 utilisateurs simultanes,
0.26 % d'erreurs, p95 1.56 s, avec 3 workers.

500 utilisateurs reste non valide. La voie est identifiee et chiffree, mais elle
depend d'une verification a volume de donnees reel, qui n'a pas ete faite.
