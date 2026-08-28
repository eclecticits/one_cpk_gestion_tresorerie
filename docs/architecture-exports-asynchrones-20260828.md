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
  command: [arq, app.workers.exports.WorkerSettings]
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

### Phase 1 — Infrastructure du job, sans changer l'usage

4. Migration Alembic : table `export_jobs`. Ajout au cache du listener
   multi-tenant (`_tenant_loader_options`) — l'avertissement en tête de la
   fonction est explicite.
5. Endpoints de consultation : `GET /exports/jobs`, `GET /exports/jobs/{id}`,
   `GET /exports/jobs/{id}/download`. Pas encore de producteur.
6. Conteneur `exports-worker` + `arq`, healthcheck, limite mémoire, balayages
   (baux expirés, purge des artefacts périmés).
7. Un seul type branché, derrière un drapeau **désactivé par défaut** :
   `/exports/budget`, le plus petit (43 Ko, ~1 s). On valide la chaîne complète
   — file, contexte tenant, écriture du fichier, `X-Accel-Redirect` — sur
   l'export dont l'échec coûte le moins.

### Phase 2 — Bascule type par type

8. Deux réglages : `EXPORT_ASYNC_TYPES` (liste) et `EXPORT_ASYNC_ROW_THRESHOLD`.
   Sous le seuil, le chemin synchrone actuel est conservé — un export de 500
   lignes doit rester instantané, l'asynchrone y serait une régression d'usage.
   Au-dessus, `202` et un job.
9. `downloadExcel` gère 200 et 202.
10. Ordre de bascule, du plus coûteux au moins coûteux, pour que le premier
    gain soit le plus gros : `requisitions`, `encaissements`, `sorties-fonds`,
    `experts-comptables`, `budget`.

### Phase 3 — Retrait du chemin lourd

11. Après un mois d'usage réel : seuil abaissé, et suppression du code de
    construction synchrone pour les gros volumes. Le chemin direct ne subsiste
    que pour les exports petits et bornés.

### Phase 4 — Consolidation

12. Déplacer les ordonnanceurs (`weekly_report`, `monthly_report`,
    `billing_guard`) du backend HTTP vers le worker. Ils souffrent aujourd'hui
    du même défaut de nature — un rapport hebdomadaire s'exécute dans un worker
    qui sert des requêtes — et cela supprimerait le besoin de dédupliquer
    l'exécution entre les quatre workers gunicorn.
13. `write_only` pour openpyxl si la volumétrie l'impose.
14. Métriques par job (durée, lignes, mémoire) dans `/metrics`.

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

## 8. Décisions fonctionnelles à trancher avant l'implémentation

1. **Sémantique temporelle.** Un export asynchrone reflète les données au moment
   de sa *génération*, pas du clic. Aujourd'hui aucun classeur ne porte
   d'horodatage de génération (vérifié : aucun `Généré le…` dans les bandeaux).
   Il en faudra un.
2. **Rétention des artefacts.** Ces fichiers contiennent des données financières
   nominatives et restent sur disque. Combien de temps — 24 h, 7 jours ? Purge
   automatique, et suppression à la demande ?
3. **Notification.** Interrogation périodique seule (simple, suffisant), ou
   e-mail avec lien pour les exports de plusieurs minutes ?
4. **Quota par organisation.** Le plan d'abonnement est déjà connu du backend
   (`plan_type`, contrôlé dans `deps.py`). Faut-il en dériver un nombre d'exports
   par jour ?

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

## 10. Ce que je n'ai pas pu vérifier sur la phase 0

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
