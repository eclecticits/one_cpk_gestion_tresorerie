# Isoler les exports lourds du trafic HTTP — proposition d'architecture

28/08/2026. Fait suite à `docs/performance-audit-20260826/perf-charge-20260828.md`,
qui a établi la mesure : **quatre exports par minute suffisent à consommer toute
la capacité du service.** Sans eux, les mêmes 25 utilisateurs simultanés sont
servis avec une médiane de 88 ms et zéro erreur serveur ; avec eux, 5,13 s de
médiane et 18 % d'échecs.

Ce document propose une cible, justifie le choix, et donne un plan de bascule
progressif. **Aucun code n'est écrit à ce stade.**

---

## 1. Ce que fait l'application aujourd'hui

Les cinq exports (`budget`, `encaissements`, `sorties-fonds`, `requisitions`,
`experts-comptables`) suivent tous le même motif dans
`app/api/v1/endpoints/exports.py` :

```
GET /exports/<type>
  → requêtes SQL (async)
  → _build_workbook() dans anyio.to_thread.run_sync()   ← CPU openpyxl
  → save_workbook() → BytesIO
  → StreamingResponse
```

Le passage en thread (`app/utils/excel_io.py`) empêche le gel de la boucle
d'événements, ce qui était le bon réflexe. **Mais il ne rend pas le worker
disponible** : openpyxl est du CPU Python, il tient le GIL. Un worker gunicorn
qui construit un classeur ne sert plus rien d'autre, du premier SELECT à la
dernière cellule.

### Les murs déjà atteints, mesurés

| Fait | Mesure | Source |
|---|---|---|
| Coût d'un export d'exercice | 75 s serveur pour 60 000 lignes (1,25 ms/ligne) | `perf-exports-20260827.md` |
| Mémoire d'un export | **+310 Mo de RSS** (1,52 → 1,83 Gio) pour un seul export de réquisitions sur un an, et non rendus à la fin | mesuré le 28/08 (`docker stats` pendant l'appel, 38,6 s, fichier de 1,97 Mo) |
| Un worker reste pris après abandon du client | export tracé à `duration_ms=168496` alors que le client avait renoncé à 120 s | `perf-charge-20260828.md` §3 |
| Timeout nginx | `frontend/nginx.conf` ne fixe aucun `proxy_read_timeout` → **60 s par défaut** | lecture du fichier |
| Arbitre gunicorn | `--timeout 120` : au-delà, le worker est tué avec toutes ses requêtes en cours | `docker-compose*.yml` |

> **En production, un export qui dépasse 60 s est déjà cassé** — nginx coupe
> avant que le backend n'ait fini, et le travail continue quand même côté
> serveur. Ce n'est pas un risque futur, c'est l'état actuel.

### Ce qui existe déjà et qu'on va réutiliser

| Brique | Où | Ce qu'elle apporte |
|---|---|---|
| Redis asyncio | `app/core/cache.py`, `redis[asyncio]==5.2.1` | connexion déjà configurée, service déjà déployé (dev et prod) |
| Contexte tenant hors HTTP | `app/services/weekly_report.py` appelle `set_current_tenant_id()` | précédent d'un traitement multi-tenant hors requête |
| Livraison de fichier sans occuper Python | `app/api/v1/endpoints/secure_uploads.py` → `X-Accel-Redirect` | le téléchargement de l'artefact ne coûtera pas un worker |
| Arborescence par tenant | `uploads/tenants/<uuid>/…`, contrôle d'appartenance dans `secure_uploads.py` | emplacement et contrôle d'accès des artefacts |
| Traçabilité d'artefacts générés | table `generated_documents` | modèle de table éprouvé (snapshot, version, chemin fichier) |
| Ordonnanceur | APScheduler dans `app/utils/scheduler.py` | à déplacer, cf. §7 |

### Le piège à ne pas manquer

`app/db/session.py:590` :

```python
tenant_id = get_current_tenant_id()
if tenant_id is None:
    return          # ← aucun filtre appliqué
```

En HTTP, `deps.py` pose toujours le contexte : l'absence est impossible. **Hors
HTTP, un oubli ne lève rien — il produit des requêtes non filtrées.** Un export
généré sans contexte tenant contiendrait les données de toutes les
organisations, silencieusement, dans un fichier téléchargeable. C'est le risque
numéro un de cette migration, avant toute considération de performance, et le
§4 lui consacre une garde dédiée.

---

## 2. La décision : file Redis + worker dédié, vérité en base

**Recommandation : `arq` pour la file, PostgreSQL pour l'état des jobs.**

### Pourquoi pas Celery

Celery est synchrone par conception. Le code d'export est intégralement `async`
(`await db.execute`, `AsyncSession`, `anyio.to_thread`) : il faudrait soit un
second moteur SQLAlchemy synchrone (psycopg) avec son propre pool et sa propre
configuration multi-tenant, soit un `asyncio.run()` par tâche dans un worker
préfork. Beaucoup de surface — broker, backend de résultats, sérialisation,
deux configurations de pool à tenir cohérentes — pour cinq tâches. Le jour où
il y aura vingt tâches hétérogènes et plusieurs machines, la question se
reposera ; aujourd'hui c'est du poids sans contrepartie.

### Pourquoi pas RQ

Même remarque en plus léger : RQ est synchrone et fork un processus par job.
Ça marcherait (`asyncio.run(export(...))`), mais chaque fork recrée un moteur
et un pool, et le code applicatif devrait être appelé depuis un contexte
étranger à celui pour lequel il a été écrit.

### Pourquoi arq

- **Asyncio natif** : la tâche est une coroutine. Les services d'export, le
  `SessionLocal` existant, le listener multi-tenant, `anyio.to_thread` —
  tout est réutilisé tel quel. C'est le seul choix qui ne demande **aucune**
  réécriture du code métier.
- **Redis seul comme dépendance d'infrastructure** : le service est déjà là,
  déjà dans les deux `docker-compose`, déjà avec un healthcheck.
- **Une dépendance Python, pas un écosystème.**
- Reprise sur incident, réessais, tâches périodiques : fournis.

### Pourquoi l'état des jobs va en base, pas dans Redis

`app/core/cache.py` traite Redis comme faillible **par conception** : toutes les
opérations avalent `RedisError` et retournent `None`. C'est le bon choix pour un
cache. Ça interdit d'en faire la source de vérité d'un job : un `FLUSHALL`, un
redémarrage sans persistance, et l'historique des exports d'une organisation
disparaît.

Répartition :

- **PostgreSQL = la vérité.** Table `export_jobs`, portée par `organisation_id`,
  soumise au cloisonnement multi-tenant comme le reste, auditable, sauvegardée.
- **Redis = le signal.** La file transporte un identifiant de job, rien d'autre.

Si Redis perd un message, rien n'est perdu : un balayage de réconciliation
reprend les jobs `QUEUED` plus vieux que N minutes. La criticité de Redis reste
donc celle qu'elle a aujourd'hui — dégradation, pas perte.

### La variante sans nouvelle dépendance

Si l'ajout d'`arq` est jugé indésirable, la même architecture fonctionne avec
une file dans PostgreSQL (`SELECT … FOR UPDATE SKIP LOCKED` sur `export_jobs`,
boucle de polling toutes les 2 s dans le conteneur worker). On perd la latence
de prise en charge (secondes au lieu de millisecondes — sans importance pour un
export) et on écrit soi-même une soixantaine de lignes de boucle ; on gagne une
seule source de vérité et zéro dépendance.

**Critère de choix** : si le worker doit un jour porter autre chose que des
exports (envois d'e-mails, imports, rapports planifiés), prendre `arq`. Si les
exports restent le seul usage, la file PostgreSQL est défendable.

---

## 3. L'architecture cible

```
Navigateur                Backend HTTP (4 workers)         Worker exports (1-2)
    │                            │                                  │
    │ POST /exports/requisitions │                                  │
    ├───────────────────────────►│ permissions, abonnement,         │
    │                            │ quota, déduplication             │
    │                            │ INSERT export_jobs (QUEUED)      │
    │                            │ enqueue(job_id) ──── Redis ─────►│
    │  202 { job_id }            │                                  │ set_current_tenant_id()
    │◄───────────────────────────┤                                  │ SELECT … (async)
    │                            │                                  │ openpyxl (thread)
    │ GET /exports/jobs/{id}     │                                  │ écrit le fichier
    ├───────────────────────────►│ SELECT export_jobs               │ UPDATE job = DONE
    │  { status, progress }      │                                  │
    │◄───────────────────────────┤                                  │
    │ GET …/{id}/download        │                                  │
    ├───────────────────────────►│ contrôle tenant                  │
    │◄─── X-Accel-Redirect ──────┤ (nginx sert le fichier)          │
```

### La table `export_jobs`

Colonnes structurantes (le détail se décidera à l'implémentation) :

| Champ | Rôle |
|---|---|
| `id` (uuid) | identifiant public du job, et nom du fichier produit |
| `organisation_id` | cloisonnement — indexé, filtré par le listener |
| `requested_by` | qui a demandé, pour l'affichage et l'audit |
| `type`, `params` (JSONB) | quoi exporter, avec quels filtres |
| `params_hash` | déduplication (§4) |
| `status` | `QUEUED` / `RUNNING` / `DONE` / `FAILED` / `EXPIRED` / `CANCELLED` |
| `progress`, `row_count` | retour à l'utilisateur pendant l'attente |
| `file_path`, `file_size` | artefact produit, relatif à `UPLOAD_DIR` |
| `error_code`, `error_message` | échec exploitable côté UI, sans trace technique |
| `attempts`, `lease_until`, `worker_id` | reprise après mort du worker (§4) |
| `created_at`, `started_at`, `finished_at`, `expires_at` | durée de vie et métriques |

### Le conteneur worker

Même image que le backend, commande différente — c'est ce qui garantit que le
code métier ne diverge jamais entre les deux.

```yaml
exports-worker:
  build: ./backend
  command: [arq, app.workers.arq_worker.WorkerSettings]
  env_file: .env
  environment:
    BACKEND_WORKERS: "1"
    DB_POOL_SIZE: "2"
    DB_MAX_OVERFLOW: "2"
    EXPORT_WORKER_CONCURRENCY: "1"
  volumes: [ … même volume d'uploads que le backend … ]
  mem_limit: 1g          # mesuré : +310 Mo pour un seul export
  restart: always
```

Budget de connexions à recalculer : 4 × (5 + 5) + 1 × (2 + 2) = **44**, à
comparer aux 97 utilisables de PostgreSQL. Le worker ne peut pas manger le pool
du service HTTP — c'est une propriété du dimensionnement, pas une convention.

### Les artefacts

`${UPLOAD_DIR}/tenants/<organisation_uuid>/exports/<job_id>.xlsx`, servis par
l'endpoint de téléchargement qui vérifie l'appartenance puis délègue à nginx par
`X-Accel-Redirect` — exactement le mécanisme de `secure_uploads.py`.

**Prérequis d'infrastructure — levé le 28/08.** `frontend/nginx.conf` n'avait
aucune `location internal` (constat C5 de `perf-infra.md`) : la redirection
interne retombait sur `try_files … /index.html`, et le client recevait la page
HTML de l'application en 200 à la place de son fichier. La `location
/_protected_uploads/` existe désormais, et les deux `docker-compose` montent le
répertoire d'uploads dans le conteneur `frontend` en lecture seule. Le
téléchargement des artefacts n'occupera donc aucun worker Python. **Non vérifié
en exécution** : ni `nginx -t` ni Docker n'étaient disponibles (cf. §10).

---

## 4. Les garde-fous, et pourquoi chacun existe

### 4.1 Cloisonnement multi-tenant — le point dur

Trois barrières, parce qu'une seule ne suffit pas quand l'échec est silencieux :

1. **Contexte obligatoire.** Le worker ouvre ses sessions par une fabrique
   dédiée qui **refuse de démarrer sans contexte tenant** (exception, pas repli).
   La lecture de `session.py:590` est sans ambiguïté : contexte vide = aucun
   filtre. Hors HTTP, l'absence doit devenir une erreur bruyante.
2. **Le job porte son tenant.** `organisation_id` est lu depuis la ligne
   `export_jobs`, jamais depuis les paramètres du client.
3. **Vérification a posteriori.** Avant de marquer `DONE`, contrôle que les
   entités rassemblées appartiennent toutes à l'organisation du job. Coût
   négligeable devant la génération, et c'est la barrière qui attrape une
   requête ajoutée plus tard sans filtre.

À doubler d'un test : *un job dont le contexte tenant a été omis doit échouer,
jamais produire un fichier.*

### 4.2 Équité entre organisations

Un worker unique traite une file unique : sans règle, une organisation qui lance
dix exports fait attendre toutes les autres. Donc **un job en cours au maximum
par organisation**, et une profondeur de file bornée par organisation (au-delà,
refus explicite à la soumission plutôt qu'une attente muette).

### 4.3 Déduplication

`hash(type + params + organisation)` : si un artefact `DONE` existe et date de
moins de N minutes, le rendre au lieu de relancer. Le motif « l'utilisateur
clique cinq fois parce que rien ne se passe » est précisément ce qui a été
observé dans les tirs de charge — et il coûte cinq fois le prix.

### 4.4 Reprise après mort du worker

Le générateur a déjà été tué par l'OOM-killer pendant cette campagne. Un job en
`RUNNING` dont le worker meurt resterait bloqué. D'où `lease_until` renouvelé
pendant le traitement, et un balayage qui remet en file les jobs dont le bail a
expiré — deux tentatives, puis `FAILED` avec un message exploitable.

### 4.5 Mémoire

310 Mo pour un seul export, mesurés, non rendus à la fin par l'allocateur. Sur la VM actuelle (3,7 Go, partagés avec PostgreSQL et le
backend), cela impose **concurrence 1** et une limite mémoire au conteneur.
Monter à 2 suppose de mesurer d'abord. Le mode `write_only` d'openpyxl reste le
levier de fond si la volumétrie double, avec le coût de refonte décrit dans
`perf-exports-20260827.md`.

---

## 5. Ce que ça change pour le frontend

Une seule fonction est concernée : `frontend/src/utils/download.ts`
(`downloadExcel`), appelée par les six écrans qui exportent. Elle peut gérer les
deux régimes sans qu'aucune page ne change :

- réponse **200** → comportement actuel (blob, téléchargement immédiat) ;
- réponse **202** → interrogation périodique du job, puis téléchargement.

C'est ce qui rend la bascule réversible type par type : le serveur décide, le
client s'adapte. Un panneau « Mes exports » (liste des jobs, état, lien) est
souhaitable mais n'est pas nécessaire à la bascule — il peut venir après.

---

## 6. Plan de migration progressif

Chaque phase est livrable seule, mesurable, et réversible.

### Phase 0 — Prérequis (aucune file, aucun worker) — **livrée le 28/08**

1. ✅ `frontend/nginx.conf` et `docs/nginx/backend-secure-uploads.conf` :
   `proxy_read_timeout` / `proxy_send_timeout` à 130 s, soit le `--timeout`
   gunicorn (120 s) plus une marge — c'est l'arbitre gunicorn qui doit trancher
   le sort d'une requête trop longue, pas nginx. Plus la `location internal`
   `/_protected_uploads/` et le montage du volume d'uploads dans le conteneur
   `frontend`, en lecture seule (§3).
2. ✅ Relâchement de la connexion sur `/exports/budget`, par `commit()` et non
   `rollback()` — `expire_on_commit=False` ne couvre que le premier, et un
   rollback expirait les entités, provoquant un `MissingGreenlet` à la première
   lecture d'attribut dans le thread. L'export ne salit plus la session depuis
   que la surcharge d'affichage des recettes passe par un dictionnaire local :
   il n'y a plus rien à écrire (76 `UPDATE budget_postes` par appel avant, 0
   après, pour un classeur identique).
3. ✅ `_compter_lignes()` : un `COUNT` sur les mêmes filtres, exécuté **avant**
   la requête elle-même — donc avant de ramener 120 000 entités ORM en mémoire.
   Au-delà de `EXPORT_MAX_ROWS` (60 000 par défaut), refus `413` portant les
   deux nombres et l'action qui débloque, au lieu d'un worker tenu deux minutes
   pour un fichier que le client ne recevra pas. `downloadExcel` remonte
   désormais le `detail` du serveur : sans cela l'utilisateur ne lisait que
   « Export failed (HTTP 413) », et le réflexe est de recliquer à l'identique.
   Le plafond est conservateur — la mesure de 1,25 ms/ligne est antérieure au
   cache de styles openpyxl (−14,9 s sur les 18 s de construction de 4 800
   lignes) — et sera réévalué à la première mesure post-correctif.

La trace `EXPORT_COUNT export=… lignes=… plafond=…` et son pendant aval
`EXPORT_WORKBOOK feuilles=… lignes=… octets=… serialisation_ms=…` donnent, par
type d'export, la volumétrie d'entrée et de sortie. C'est ce qui permettra de
placer `EXPORT_ASYNC_ROW_THRESHOLD` (phase 2) sur une distribution réelle plutôt
que sur une intuition.

*Valeur livrée sans file ni worker : les exports cessent d'être coupés par nginx
à 60 s, ceux qui ne peuvent pas aboutir sont refusés en une seconde avec une
raison, et la connexion PostgreSQL n'est plus retenue pendant la construction du
classeur.*

**Effet de bord à connaître avant le prochain tir de charge** : le tenant de
charge porte 60 000 réquisitions. Un export d'exercice complet frôle donc le
plafond par défaut, et le franchira dès que le jeu grossira — le scénario
d'export du banc rendra alors des `413` au lieu de classeurs. C'est le
comportement voulu, mais il faut le savoir pour ne pas le lire comme une
régression : `EXPORT_MAX_ROWS` permet de le désactiver (valeur `0`) le temps
d'une campagne de comparaison avant/après.

### Phase 1 — Infrastructure du job, sans changer l'usage — **livrée le 28/08**

4. ✅ Migration `20260828_export_jobs` : table `export_jobs`, cinq index et pas
   un de plus (deux d'entre eux partiels, pour les balayages qui tournent en
   boucle). `ExportJob` est ajouté à `_tenant_loader_options` : sans ce
   critère, `GET /exports/jobs` rendrait les jobs de toutes les organisations.
5. ✅ `GET /exports/jobs`, `GET /exports/jobs/{id}`,
   `GET /exports/jobs/{id}/download` (`app/api/v1/endpoints/export_jobs.py`).
   Le téléchargement rend un corps vide et un `X-Accel-Redirect` : le fichier ne
   traverse pas la mémoire de Python. Une table `PERMISSION_PAR_TYPE` rattache
   chaque type d'export à la permission de la route synchrone correspondante —
   sans elle, un utilisateur sans le menu Encaissements téléchargerait l'export
   d'un collègue. Le cloisonnement multi-tenant ne couvre pas ce cas : il sépare
   les organisations, pas les rôles.
6. ✅ Service `exports-worker` (même image, commande `arq`), limite mémoire à
   1 Go, sonde de vitalité par `arq --check`, pool de 2 connexions, et les deux
   balayages : baux expirés à la minute, purge des artefacts à l'heure.
7. ✅ `/exports/budget` bascule quand `EXPORT_ASYNC_TYPES` le nomme —
   **vide par défaut**, donc rien ne change tant qu'on ne l'ouvre pas.

**Ce qui a été tiré de la phase 2, et pourquoi.** `downloadExcel` gère
désormais le `202` (item 9). Sans lui, ouvrir le drapeau donnait un résultat
pire que l'ancien comportement : `202` est un statut « ok », donc le JSON du job
aurait été téléchargé tel quel sous un nom en `.xlsx`, et l'utilisateur aurait
ouvert un fichier illisible en croyant à un bug d'Excel. Livrer la phase 1 sans
cela, c'était livrer un piège.

**Deux choix d'implémentation qui ne sont pas dans le plan initial.**

- *La reprise ne se fait qu'au balayage.* Une exception attrapée pendant la
  génération marque le job `FAILED` immédiatement, sans réessai : le worker est
  vivant et c'est le code qui a échoué (paramètres, données, plafond). Rejouer
  produirait la même erreur, trois fois plus vite. La reprise ne concerne que la
  mort du worker — qui, par définition, ne passe pas par un bloc `except`.
- *`max_tries = 1` côté arq.* Le bail et le balayage portent déjà la reprise ;
  laisser arq réessayer en plus produirait deux exécutions concurrentes du même
  job.

### Phase 2 — Bascule type par type — **livrée le 29/08**

8. ✅ `EXPORT_ASYNC_TYPES` (déjà là) et `EXPORT_ASYNC_ROW_THRESHOLD` (5 000).
   Sous le seuil, le chemin direct est conservé même pour un type ouvert.
9. ✅ Livré par anticipation en phase 1.
10. ✅ Les cinq types sont portés dans le worker. L'ordre de bascule
    recommandé — `requisitions`, `encaissements`, `sorties-fonds`,
    `experts-comptables`, `budget` — est inscrit dans l'ordre de
    `TYPES_SUPPORTES` : sans effet technique, mais lisible depuis le code.

**Comment la décision est prise, et pourquoi là.** Le nombre de lignes n'est
connu qu'après construction de la requête, laquelle vit dans le constructeur
avec ses quinze filtres. Faire remonter la décision jusqu'à l'endpoint aurait
supposé de dupliquer cette construction — deux endroits où se tromper, pour
cinq exports — ou de scinder chaque constructeur en deux. C'est donc
`_compter_lignes` qui lève `BasculeAsynchroneRequise`, rattrapée par les cinq
endpoints. Le signal part **avant** le chargement des entités et la
construction du classeur : rien de coûteux n'a été payé. Dans le worker,
`seuil_bascule` vaut `None` et l'exception ne peut pas être levée — c'est ce
qui empêche un job de se remettre en file lui-même, indéfiniment.

**Trois régimes, dans cet ordre**, et l'ordre est ce qui les rend cohérents :

| Volume | Régime |
|---|---|
| ≤ `EXPORT_ASYNC_ROW_THRESHOLD` (5 000) | chemin direct, inchangé |
| entre le seuil et `EXPORT_MAX_ROWS` | `202` et un job |
| > `EXPORT_MAX_ROWS` (60 000) | `413` **à la soumission** |

Le plafond est évalué avant le seuil. C'est ce qui corrige le défaut relevé à
la revue de la phase 1 : sans cet ordre, un export au-delà du plafond était
accepté en `202` puis échoué par le worker, pour une raison qu'on connaissait
déjà au moment du clic.

`EXPORT_ASYNC_ROW_THRESHOLD=0` fait basculer tout ce qui est ouvert, quelle que
soit la taille : c'est le réglage qui permet de valider la chaîne complète sur
un petit export, `budget` par exemple.

**Filtres vérifiés avant d'être transmis.** Le worker refuse un job dont les
paramètres stockés ne correspondent plus à la signature du constructeur, au
lieu de les ignorer. Un filtre silencieusement perdu produirait un classeur
faux — plus de lignes que demandé, et dans le cas d'un filtre de service, des
données que le demandeur n'avait pas le droit de voir. Le cas se présente dès
qu'un job survit à un déploiement qui change une signature.

**Contrôle d'accès d'`experts-comptables`.** Ce type n'est pas gardé par une
permission mais par un rôle (`require_expert_admin`). Il ne pouvait donc pas
entrer dans `PERMISSION_PAR_TYPE`, dont les valeurs sont des codes de
permission : une seconde table, `VERIFICATEUR_PAR_TYPE`, renvoie vers la
fonction que déclare déjà la route synchrone. Un test vérifie que les deux
tables ne se recouvrent pas — un type présent dans les deux aurait deux
contrôles dont un seul s'appliquerait, et lequel dépendrait de l'ordre du code.

### Phase 3 — Retrait du chemin lourd

11. Après un mois d'usage réel : seuil abaissé, et suppression du code de
    construction synchrone pour les gros volumes. Le chemin direct ne subsiste
    que pour les exports petits et bornés.

### Phase 4 — Consolidation

12. ✅ **Fait le 29/08.** Les trois ordonnanceurs (`weekly_report`,
    `monthly_report`, `billing_guard`) peuvent désormais être portés par le
    conteneur worker, sous le réglage `SCHEDULERS_IN_WORKER` — **`false` par
    défaut, donc rien ne change**. Le backend et le worker se déterminent sur ce
    seul réglage et concluent à l'inverse l'un de l'autre ; un test verrouille
    cet invariant, parce qu'une divergence entre les deux ne produirait aucune
    erreur : soit des rapports en double, soit — bien pire — plus aucun rapport,
    en silence.

    **APScheduler est conservé, il n'est pas réécrit en `cron()` arq.** Les trois
    planifications sont réglées en heure locale (ici `Africa/Kinshasa`) et les
    crons d'arq suivent l'horloge du processus, sans notion de fuseau. Les
    retranscrire aurait signifié réimplémenter la conversion, donc décaler des
    envois d'e-mails réels d'une heure une ou deux fois par an, au changement
    d'heure. Seul le PROCESSUS hôte change, pas la sémantique.

    Le verrou consultatif PostgreSQL de `weekly_report` est gardé : il ne
    départage plus quatre workers gunicorn, mais il protège encore d'un worker
    déployé en double.

    ⚠️ **Le code et le déploiement deviennent solidaires.** Passer le réglage à
    `true` sans déployer le conteneur worker arrête purement et simplement les
    rapports et la garde de facturation. D'où le défaut fermé : ce doit être une
    décision, jamais un effet de bord de mise à jour.

    *Limite assumée* : quand les ordonnanceurs sont délégués, `GET` du statut
    côté admin ne peut plus savoir s'ils tournent — l'API et le worker sont deux
    processus. La réponse porte donc un champ `host` et n'affirme plus
    « arrêté », ce qui serait faux. Publier une pulsation du worker dans Redis
    lèverait cette limite ; ce n'est pas fait.
13. `write_only` pour openpyxl si la volumétrie l'impose.
14. ✅ **Fait le 29/08.** Métriques d'export sur `/metrics`, **dérivées de la
    base** et non de la mémoire : les jobs sont produits par le conteneur
    worker, `/metrics` est servi par le backend — deux processus, donc aucun
    compteur en mémoire de l'un ne peut décrire l'autre. `export_jobs` porte
    déjà durée, volumétrie, taille et statut : un agrégat au moment du scrape
    suffit, sans serveur HTTP supplémentaire ni pushgateway.

    *Effet de bord heureux* : des valeurs lues en base sont identiques dans les
    quatre workers gunicorn. Le défaut classique du scrape multi-processus —
    Prometheus tombe sur un worker au hasard et lit ses compteurs à lui — ne
    s'applique pas à ces séries.

    Séries publiées : `onec_export_jobs{type,etat}`,
    `onec_export_attente_max_secondes`, `onec_export_duree_moyenne_secondes` et
    `_max` par type, `onec_export_lignes_moyennes` par type (sur 24 h, de quoi
    régler `EXPORT_ASYNC_ROW_THRESHOLD` sur une distribution réelle), et
    `onec_export_artefacts_octets` (de quoi vérifier que la purge de rétention
    travaille). **Le couple à surveiller est profondeur de file + âge du plus
    ancien job en attente** : c'est lui qui distingue « beaucoup de demandes »
    de « plus personne ne les traite ».

    ⚠️ **La mémoire par job n'est pas livrée.** Rien ne l'échantillonne pendant
    la génération, et publier une valeur inventée serait pire que son absence.
    Le seul chiffre dont on dispose (+310 Mo de RSS) est global et appartient au
    conteneur, pas au job.

---

## 7. Comment on saura que c'est réussi

Le harnais de charge existant fournit déjà la mesure de référence. Critères, à
tirer avec `EXPORT_RATE=4` et 25 VU (le tir du 28/08 sert de « avant ») :

| Métrique | Avant (mesuré, 28/08) | Cible |
|---|---:|---:|
| p50 HTTP pendant que des exports tournent | 5,13 s | **≤ 150 ms** |
| erreurs 5xx | 12 | **0** |
| débit | 1,21 req/s | **≥ 8 req/s** |
| `WORKER TIMEOUT` gunicorn | 6 | **0** |

Plus trois tests qui ne sont pas des mesures de performance :

- un job sans contexte tenant **échoue** et ne produit aucun fichier ;
- un worker tué en plein job : le job repart et finit ;
- l'artefact produit en asynchrone est **identique** à celui du chemin
  synchrone (`observe/comparer_classeurs.py`, déjà écrit pour ça).

---

## 8. Décisions fonctionnelles — tranchées le 28/08

| Question | Décision | Où elle vit |
|---|---|---|
| File | **arq**, et non une file PostgreSQL | `arq==0.26.3`, `app/workers/arq_worker.py` |
| Rétention des artefacts | **7 jours**, purge automatique horaire | `EXPORT_JOB_RETENTION_DAYS` |
| Notification | **Interrogation seule**, pas d'e-mail | `downloadExcel`, intervalles 0,8 s puis 5 s |
| Quota par organisation | **Aucun en phase 1** | un job actif par organisation et file bornée (`EXPORT_MAX_QUEUED_PER_ORG`) suffisent à l'équité |

Le choix d'`arq` suit le critère posé au §2 : la phase 4 prévoit d'y déplacer
les ordonnanceurs, donc le worker portera autre chose que des exports.

### Tranchée le 29/08 : la sémantique temporelle

**Les classeurs portent désormais « Généré le … ».** Un export asynchrone
reflète les données au moment de sa *génération*, pas du clic : le job peut
démarrer plusieurs minutes après la demande, et la déduplication peut rendre un
artefact produit une demi-heure plus tôt. Sans cette mention, un classeur
imprimé ne dit pas à quel instant ses chiffres étaient vrais — sur des pièces
comptables, c'est une ambiguïté que la bascule introduirait sans le dire.

La mention vaut pour les **deux** régimes. Deux chemins qui horodatent
différemment seraient pires que deux chemins qui n'horodatent pas.

Elle est écrite par `_write_banner`, donc une seule fois pour les cinq exports
et toutes leurs feuilles. Elle rejoint le sous-titre (ligne 3) plutôt que
d'occuper une quatrième ligne : les lignes 1 à 3 sont réservées au bandeau et
l'en-tête des données commence en ligne 4 — une ligne de plus aurait décalé
toutes les références de plage.

Le fuseau vient de `DOCUMENT_TIMEZONE`, **vide par défaut, auquel cas on reprend
`WEEKLY_REPORT_TIMEZONE`** — déjà réglé sur le fuseau local du déploiement
(`Africa/Kinshasa`). Un défaut à UTC aurait horodaté chaque document d'une heure
d'écart avec l'horloge de celui qui le lit, sans que rien ne le signale ; et à
23 h 30 UTC, c'est la *date* qui aurait été fausse. Aucune configuration
nouvelle n'est nécessaire pour que la date soit juste.

**L'objection soulevée en phase 1 est traitée, pas contournée.** La mention fait
diverger deux classeurs par ailleurs identiques, donc
`observe/comparer_classeurs.py` — dont la raison d'être est de prouver que le
chemin asynchrone produit le même fichier que le chemin direct — aurait déclaré
un écart à chaque comparaison. Il neutralise désormais l'horodatage, mais
étroitement : les **deux** cellules doivent porter la mention. Un classeur
horodaté comparé à un classeur qui ne l'est pas reste un écart, et doit le
rester — c'est le signe de deux versions du code, pas de deux instants. La
mention est dupliquée entre l'application et le script (qui tourne depuis
l'hôte, sans le paquet applicatif), et un test verrouille leur égalité : si
l'une bouge sans l'autre, la neutralisation cesse d'opérer en silence.

---

## 9. Ce que je ne recommande pas

- **Relever seulement les timeouts** (nginx, gunicorn) : déplace le mur sans le
  supprimer. Le worker reste tenu pendant toute la génération, et la mesure du
  28/08 montre que c'est *ça* le problème, pas la coupure.
- **Générer côté navigateur** : 120 000 lignes dans l'onglet de l'utilisateur, et
  duplication des règles de calcul métier. Non.
- **Redis comme source de vérité des jobs** : incompatible avec la posture
  « faillible » assumée de `cache.py`, et perte d'historique au premier flush.
- **Passer à 8 workers gunicorn pour absorber les exports** : mesuré
  contre-productif dès le 27/08 (échecs 34,6 % → 86,6 %), et sans effet sur la
  cause.

---

## 10. Ce que je n'ai pas pu vérifier (phases 0 à 2)

> **La séquence de validation est écrite et prête** :
> `backend/scripts/loadtest/observe/valider_exports_asynchrones.sh`, en trois
> cas — `reference` (capture le classeur du chemin direct), `asynchrone`
> (soumet, suit le job, télécharge l'artefact, le compare au précédent avec
> `comparer_classeurs.py`, et vérifie que le job apparaît bien dans la liste de
> son organisation), `reprise` (tue le conteneur worker en plein job et attend
> que le balayage le remette en route). Le script ne bascule pas le drapeau
> lui-même — `EXPORT_ASYNC_TYPES` est lu au démarrage par le backend *et* par
> le worker — mais il détecte le régime au code HTTP reçu et dit quoi régler.
> C'est ce qui doit être déroulé en premier le jour où la pile redémarre.


Le démon Docker n'était pas joignable depuis ce poste (« docker could not be
found in this WSL 2 distro »), et aucune base de test n'était accessible — le
PostgreSQL qui écoute sur `localhost:5432` n'est pas celui du projet (ses
identifiants diffèrent de ceux du `.env`). Ce qui a donc été vérifié, et
comment :

| Vérifié | Comment |
|---|---|
| Les cinq `COUNT` compilent, sans `ORDER BY` résiduel, avec les jointures et le filtre d'organisation de chaque export | compilation SQLAlchemy hors connexion, dialecte PostgreSQL |
| Décision du plafond, message de refus, `EXPORT_MAX_ROWS=0`, forme du SQL produit | `backend/tests/test_export_plafond_lignes.py`, 5 tests, sans base |
| Aucune régression d'import sur le paquet | `pytest --collect-only` : 704 tests collectés |
| Le frontend compile | `tsc --noEmit` |
| Équilibre des blocs de `frontend/nginx.conf`, validité YAML des deux `docker-compose` | analyse statique |

Restent **non vérifiés en exécution**, et à reprendre dès que Docker est
disponible :

1. `nginx -t` sur `frontend/nginx.conf`, et un téléchargement réel passant par
   `X-Accel-Redirect` (le seul test qui prouve que l'`alias` pointe au bon
   endroit dans le conteneur `frontend`).
2. Le coût réel du `COUNT` ajouté, sur le tenant de charge (attendu :
   négligeable devant la construction, à confirmer par `EXPORT_COUNT` et le
   `SLOW_REQUEST` correspondant).
3. La suite `pytest` complète, notamment `test_multi_tenant_isolation.py`.
4. Le tir de charge avant/après, qui seul dira ce que la phase 0 a rendu — en
   pensant à neutraliser le plafond (`EXPORT_MAX_ROWS=0`) si le scénario
   d'export du banc dépasse 60 000 lignes.

### Phase 2

Vérifié sans base : les trois régimes de volume et leur ordre (plafond avant
seuil), l'impossibilité pour le worker de déclencher une bascule, la
correspondance entre les types déclarés supportés et le dispatch du worker,
la non-intersection des deux tables de contrôle d'accès, et le fait qu'un type
fermé n'a pas de seuil — 38 tests sans base au total (28 avant).

L'extraction des quatre constructeurs restants a été faite mécaniquement, par
génération des signatures depuis celles des endpoints plutôt que par recopie.

Reste non exécuté, en plus de tout ce qui suit : **aucun des cinq types n'a
jamais été produit par le worker**, et la comparaison
`observe/comparer_classeurs.py` entre chemin direct et chemin asynchrone n'a
toujours pas eu lieu.

### Phase 1

Vérifié sans base ni Redis : le refus d'une session hors HTTP sans organisation,
la forme du chemin d'artefact (contrôlée en appelant le vrai
`secure_uploads._extract_tenant_uuid`), la stabilité de l'empreinte de
déduplication, la fermeture du drapeau par défaut, la présence du lien de
téléchargement au bon moment, et **la concordance colonne par colonne entre le
modèle et la migration** — 12 tests dans `backend/tests/test_export_jobs.py`.
Plus : `alembic heads` rend une tête unique, `app.openapi()` expose bien les
trois routes, 716 tests collectés, `tsc --noEmit` passe.

Restent **non exécutés**, faute de Docker et de base :

1. **La chaîne complète, de bout en bout** — soumettre, voir le job passer
   `QUEUED → RUNNING → DONE`, télécharger l'artefact via `X-Accel-Redirect`.
   C'est l'objet même de la phase 1 : tant que ce chemin n'a pas tourné une
   fois, l'infrastructure est écrite, pas validée.
2. **Les deux balayages** (bail expiré, purge des artefacts) : ils demandent des
   lignes en base et une horloge qu'on avance.
3. **Le test « un worker tué en plein job repart et finit »** du §7, qui suppose
   de tuer un conteneur.
4. **`comparer_classeurs.py`** entre le classeur synchrone et l'asynchrone : la
   preuve que les deux chemins produisent le même fichier. Le code la rend
   *structurellement* probable — une seule fonction, appelée par les deux — mais
   ce n'est pas une mesure.
5. **La migration** n'a jamais été appliquée : `alembic upgrade head` n'a pas
   tourné.

> ⚠️ **Chaînage de la migration.** `20260828_export_jobs` a pour parent
> `20260827_perf_budget_recettes`, seule tête au moment de l'écrire — mais ce
> fichier d'index n'est **pas encore commité** (il attend une fenêtre de
> maintenance, son `CREATE INDEX` verrouille les écritures sur une table de
> 37 Mo). Déployer la phase 1 impose donc de déployer cet index d'abord.
> L'alternative — brancher la phase 1 sur `20260823_whatsapp_notifs` — créerait
> deux têtes, et `alembic upgrade head` échouerait au démarrage du backend
> (`entrypoint.sh`). Ce n'est pas un choix : c'est une conséquence de l'ordre
> dans lequel les deux migrations ont été écrites.
