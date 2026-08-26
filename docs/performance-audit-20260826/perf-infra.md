# Audit de performance — infrastructure ONEC Smart

Date : 2026-08-26. Branche : `perf-write-contention-validation-20260803` (arbre propre).
Méthode : **lecture statique des fichiers du dépôt uniquement**. Le démon Docker est
inactif sur ce poste : aucune image n'a été construite, aucun conteneur lancé,
aucune mesure produite pour cet audit. Toute valeur chiffrée ci-dessous est soit
**MESURÉE** (reprise des campagnes documentées de `docs/PERFORMANCE_*`), soit
**DÉDUITE** (calcul à partir des fichiers, ou comportement documenté d'un logiciel).
Les deux étiquettes sont portées explicitement.

---

## 1. Le calcul central : workers × pool × `max_connections`

### 1.1 Les chiffres réels, par environnement

`max_connections` PostgreSQL — **MESURÉ** le 2026-08-03 :
`docs/PERFORMANCE_POOL_FIX_20260803.md:16` → `SHOW max_connections = 100`.
Cohérent avec le défaut de l'image `postgres:16-alpine`, qu'aucun fichier du dépôt
ne surcharge : `docker-compose.prod.yml:21-34` et `docker-compose.yml:13-26` ne
passent ni `command:`, ni `-c`, ni fichier `postgresql.conf` (recherche
`find … -name "postgresql.conf"` : aucun résultat). Sur ces 100, PostgreSQL réserve
`superuser_reserved_connections = 3` → **97 réellement disponibles à l'application**
(DÉDUIT, défaut PostgreSQL 16).

**Développement** (`docker-compose.yml`) :

| Terme | Valeur | Preuve |
|---|---|---|
| workers | 4 | `docker-compose.yml:33-41` (`gunicorn -w ${BACKEND_WORKERS:-4}`), `.env` local ne définit pas `BACKEND_WORKERS` |
| pool_size | 5 | `docker-compose.yml:65` |
| max_overflow | 5 | `docker-compose.yml:66` |
| pool_timeout | 5 s | `docker-compose.yml:67` |

→ budget = `4 × (5 + 5)` = **40 connexions** sur 97. Marge 57. Sain.
C'est exactement ce qu'annonce le commentaire `docker-compose.yml:63-64`.

**Production** (`docker-compose.prod.yml`) — c'est là que ça se joue :

| Terme | Valeur | Preuve |
|---|---|---|
| workers | **4, en dur, non configurable** | `docker-compose.prod.yml:37-83` ne contient **aucun `command:`** → le conteneur exécute le `CMD` de l'image : `backend/Dockerfile:27` → `gunicorn -w 4 …`. `BACKEND_WORKERS` n'est même pas dans l'environnement du service. |
| pool_size | **5** | non défini dans `docker-compose.prod.yml` → défaut applicatif `backend/app/core/config.py:77` |
| max_overflow | **10** | idem, `backend/app/core/config.py:78` |
| pool_timeout | **30 s** | idem, `backend/app/core/config.py:79` |
| gunicorn `--timeout` | **30 s (défaut)** | absent de `backend/Dockerfile:27` et de `docker-compose.prod.yml` |

→ budget = `4 × (5 + 10)` = **60 connexions potentielles** sur 97.
Ajouter les connexions hors pool : le moteur de sonde `NullPool` de
`backend/app/api/v1/endpoints/health.py:26` ouvre une connexion neuve par appel de
`/health/ready`, par worker (transitoire, non plafonnée), plus `alembic upgrade` au
démarrage (`backend/entrypoint.sh:12`) et les sessions d'exploitation (psql, dumps).
Ordre de grandeur réaliste en pointe : **60 à 70 sur 97**.

### 1.2 Verdict

**Le nombre de connexions n'est pas dangereux : 60/97, marge ~38 %. Ce n'est pas le
problème.** Le problème est ailleurs, et il est sérieux :

1. **La production n'a jamais reçu le travail de dimensionnement.**
   `git log -- docker-compose.prod.yml` → dernier commit `abecd7b`, **antérieur** à
   `8003109` (« Make DB pool configurable and validate load stages », qui n'a touché
   que `docker-compose.yml`, cf. `git show --stat 8003109`) et antérieur aux deux
   phases de `docs/PERFORMANCE_*`. Résultat : la prod tourne **exactement dans la
   configuration `size 5 / overflow 10 / timeout 30`** dont
   `docs/PERFORMANCE_LOAD_AUDIT_20260803.md:11` documente l'effondrement
   (`QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00`,
   100 % d'erreurs au palier 100). La prod a 4 fois plus de workers que ce test à
   1 worker, donc pas le même plafond — mais elle n'a **aucun** des réglages validés.

2. **`pool_timeout` = 30 s et `--timeout` gunicorn = 30 s sont égaux.** C'est la
   combinaison la plus toxique du lot (DÉDUIT, comportement documenté de gunicorn et
   de SQLAlchemy `QueuePool`) : une requête qui attend une connexion atteint la limite
   du pool au moment exact où l'arbitre gunicorn déclare le worker muet et l'envoie
   `SIGKILL`. Avec `UvicornWorker`, un worker async porte **toutes** ses requêtes
   concurrentes : sa mort en tue des dizaines d'un coup, la file bascule sur les
   workers restants, qui saturent à leur tour. C'est très précisément la « boucle de
   panne » décrite dans le commentaire de `docker-compose.yml:47-50`, dont le correctif
   (`--timeout 120 --graceful-timeout 30`) **n'existe qu'en dev**.

3. **Le démarrage peut ne pas tenir dans les 30 s de la prod.** MESURÉ :
   `docs/PERFORMANCE_WORKER_SCALING_20260817.md:152-159` — import de
   `app.api.v1.router` à 15 s (dont 6,5 s d'enregistrement de 517 routes), démarrage
   constaté de 34 à 50 s selon la charge machine. Un worker gunicorn qui ne notifie
   pas dans `--timeout` est tué **y compris pendant son boot** (DÉDUIT). Quatre workers
   qui importent en parallèle sur une petite instance sont un candidat sérieux à la
   boucle de redémarrage, que `restart: always` (`docker-compose.prod.yml:83`)
   masquera en la rejouant indéfiniment.

4. **`backend_workers` ne sert qu'au journal, et il ment potentiellement.**
   `backend/app/core/config.py:86` (défaut 4) alimente `log_pool_configuration()`
   (`backend/app/db/session.py:116`). En prod la valeur par défaut coïncide avec le
   `-w 4` de l'image, donc le journal est juste — **par accident**. Le jour où
   quelqu'un ajoute un `command:` avec `-w 6` sans toucher `BACKEND_WORKERS`, le
   budget journalisé restera faux, en silence.

5. **Trois sources de vérité divergentes pour le même pool.**
   `.env.example:20-22` et `backend/.env.example:6-8` disent `5 / 10 / 30` ;
   `docker-compose.yml:65-67` dit `5 / 5 / 5` ; `backend/app/core/config.py:77-79`
   dit `5 / 10 / 30`. Un opérateur qui part de `.env.example` obtient la configuration
   d'avant le correctif.

**Sur-dimensionné ou dangereux ?** Ni l'un ni l'autre côté PostgreSQL. Le pool est
**sous-dimensionné par worker** (15 max, alors que la campagne validante tournait à
20 par worker) et **mal temporisé** (30 s d'attente là où la campagne validante
utilisait 5 s). Le risque n'est pas « PostgreSQL refuse les connexions » ; c'est
« les workers meurent en cascade sous pointe ».

### 1.3 Réglages PostgreSQL : intégralement aux valeurs par défaut de l'image

Aucune surcharge nulle part (`docker-compose.prod.yml:21-34`). Donc, DÉDUIT des
défauts PostgreSQL 16 :

| Paramètre | Valeur effective | Commentaire |
|---|---|---|
| `max_connections` | 100 | MESURÉ, cf. ci-dessus |
| `shared_buffers` | 128 MB | ~1 % d'un hôte à 8 Go ; recommandé 25 % |
| `work_mem` | 4 MB | par nœud de tri/hachage, par requête |
| `effective_cache_size` | 4 GB | valeur arbitraire, non liée à l'hôte réel |
| `maintenance_work_mem` | 64 MB | VACUUM/CREATE INDEX lents |
| `random_page_cost` | 4.0 | calibré pour un disque rotatif ; sur EBS gp3 → 1.1 |
| `max_wal_size` | 1 GB | checkpoints fréquents en écriture soutenue |
| `/dev/shm` du conteneur | **64 MB** | défaut Docker, pas PostgreSQL : casse les requêtes parallèles (`could not resize shared memory segment`) |

Nuance importante, et elle vient des mesures existantes : le profil py-spy du
2026-08-17 (`docs/PERFORMANCE_WORKER_SCALING_20260817.md:59-78`) montre PostgreSQL
**quasi inactif** (0–63 % d'un cœur) pendant que le worker Python est collé à 100 %.
**Tuner PostgreSQL aujourd'hui ne rendra donc presque rien** sur le jeu de test
actuel. Ça devient rentable au volume de production, réserve n°1 explicitement
posée en `…20260817.md:199-203`. `random_page_cost` et `/dev/shm` sont les deux
exceptions : peu coûteux, effet direct sur le plan d'exécution et sur les
requêtes parallèles dès que le volume monte.

---

## 2. Les 3 changements les plus rentables

**Hiérarchie franche, dans l'ordre.**

1. **Aligner `docker-compose.prod.yml` sur le travail déjà validé** (timeouts,
   workers, pool). Coût : un bloc `command:` et huit variables. Supprime le mode de
   panne en cascade et fait bénéficier la prod de quatre semaines de mesures dont
   elle est aujourd'hui exclue. C'est le seul item qui protège d'un incident total.
2. **Déplacer la compression gzip de Python vers nginx sur le chemin API**, et
   ajouter `client_max_body_size` + `upstream keepalive`. Rend du CPU au processus
   qui est le goulot mesuré, sans toucher au code métier.
3. **Poser des limites mémoire (`deploy.resources`) et un healthcheck backend.**
   Ne rend pas la machine plus rapide ; l'empêche de tomber entièrement. Aujourd'hui,
   quatre workers à 355 Mo (MESURÉ, `…20260817.md:180-181`) + PostgreSQL + Redis sans
   `maxmemory` partagent la RAM de l'hôte sans aucun plafond.

---

## 3. Constats classés par (gain × confiance)

### C1 — La production tourne sans les timeouts correctifs [gain élevé × confiance élevée]

**Preuve.** `docker-compose.prod.yml:37-83` : aucun `command:`. `backend/Dockerfile:27` :
`CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8000"]`
— pas de `--timeout`, pas de `--graceful-timeout`, pas de `--max-requests`.
À comparer à `docker-compose.yml:33-54`, où le sujet a été traité et commenté.

**Correctif** (dans `docker-compose.prod.yml`, service `backend`) :

```yaml
    command:
      - gunicorn
      - -w
      - "${BACKEND_WORKERS:-3}"
      - -k
      - uvicorn.workers.UvicornWorker
      - app.main:app
      - --bind
      - 0.0.0.0:8000
      - --timeout
      - "${BACKEND_TIMEOUT:-120}"
      - --graceful-timeout
      - "30"
      - --keep-alive
      - "65"
      - --max-requests
      - "2000"
      - --max-requests-jitter
      - "200"
      - --worker-tmp-dir
      - /dev/shm
      - --access-logfile
      - "-"
      - --error-logfile
      - "-"
    environment:
      BACKEND_WORKERS: ${BACKEND_WORKERS:-3}
      DB_POOL_SIZE: ${DB_POOL_SIZE:-10}
      DB_MAX_OVERFLOW: ${DB_MAX_OVERFLOW:-10}
      DB_POOL_TIMEOUT: ${DB_POOL_TIMEOUT:-5}
      DB_POOL_RECYCLE: ${DB_POOL_RECYCLE:-1800}
      DB_POOL_PRE_PING: ${DB_POOL_PRE_PING:-true}
      DB_POOL_SLOW_CHECKOUT_SECONDS: ${DB_POOL_SLOW_CHECKOUT_SECONDS:-2}
      DB_SLOW_QUERY_MS: ${DB_SLOW_QUERY_MS:-500}
```

Budget résultant : `3 × (10 + 10)` = **60 connexions**, identique à la configuration
MESURÉE validante du 2026-08-17 (`…20260817.md:217`), marge 37 sur 97.
`--keep-alive 65` n'a d'effet qu'associé au correctif C4 (keepalive nginx).
`--worker-tmp-dir /dev/shm` évite que le fichier de battement gunicorn parte sur
l'overlayfs (cause classique de faux timeouts en conteneur).

**Gain attendu et fondement.** Suppression d'un mode de panne, pas d'une latence :
on ne « gagne » pas des millisecondes, on cesse de perdre des workers entiers.
Fondement : les paliers MESURÉS du 2026-08-17 (`…20260817.md:165-170`) ont tous été
obtenus en `10+10`/`timeout 5` ; la prod n'est pas dans cet état, donc aucune de ces
mesures ne la décrit. Le passage de 4 à 3 workers suit le point de fonctionnement
mesuré (0,26 % d'erreurs, p95 1,56 s à 100 utilisateurs) et libère ~355 Mo.

**Risque en production.** `--max-requests` recycle les workers : sur une instance
où le boot coûte 34–50 s (MESURÉ), un recyclage mal calé crée un trou de capacité —
d'où une valeur haute (2000) et un `jitter` pour désynchroniser. Passer de 4 à 3
workers réduit le débit théorique de ~19 RPS (MESURÉ, `…20260817.md:185`) : à ne
faire que si l'instance a moins de 4 vCPU réellement disponibles (**non vérifiable
depuis le dépôt** — voir §4). Si l'instance a 4 vCPU ou plus, garder 4 et retenir
seulement les timeouts.

### C2 — La compression gzip est faite par le processus CPU-bound [gain élevé × confiance moyenne-élevée]

**Preuve.** `backend/app/main.py:75` :
`app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)`.
Le commentaire de `main.py:72-74` justifie ce choix par « notre `location /api/` ne
fait que `proxy_pass` sans compression nginx propre » — c'est exact pour
`docs/nginx/backend-secure-uploads.conf`, qui ne contient **aucune** directive gzip,
et partiellement inexact pour `frontend/nginx.conf`, où `gzip on` (ligne 14) et
`gzip_proxied any` (ligne 18) s'appliquent aussi aux réponses proxifiées.
Or le goulot MESURÉ est le CPU d'un worker Python
(`…20260817.md:59-78` : backend 95–103 % d'un cœur, db 0–63 %).

**Correctif.** Retirer `GZipMiddleware` de `main.py` **et**, dans le même mouvement,
garantir la compression côté nginx sur les deux vhosts. Dans
`docs/nginx/backend-secure-uploads.conf` (aujourd'hui muet sur le sujet) :

```nginx
    gzip on;
    gzip_vary on;
    gzip_comp_level 5;
    gzip_min_length 1024;
    gzip_proxied any;
    gzip_types application/json application/problem+json text/plain text/csv;
```

**Gain attendu et fondement.** DÉDUIT, non mesuré : gzip niveau 6 en zlib CPython
coûte de l'ordre de quelques millisecondes de CPU par centaine de kilo-octets, et
ce CPU est prélevé sur la ressource dont le profil montre qu'elle est saturée à
100 %. Le même travail dans nginx est fait en C, hors du processus contraint, sur
un module dédié. Le gain se lit en RPS par worker, pas en poids transféré (identique).
**À mesurer avant d'y croire** : le profil py-spy existant ne ventile pas
explicitement le coût gzip (`…20260817.md:92-104`), il est probablement dilué dans
les postes non listés. C'est la seule raison pour laquelle ce point n'est pas classé
en confiance « élevée ».

**Risque en production.** Si le correctif nginx n'est pas déployé en même temps que
le retrait du middleware, les réponses JSON partent **non compressées** — régression
immédiate et visible sur les connexions lentes (contexte RDC : c'est un vrai sujet).
Les deux changements doivent être atomiques, ou faits dans l'ordre nginx-puis-Python.

### C3 — Aucune limite de ressources, aucun healthcheck applicatif [gain moyen × confiance élevée]

**Preuve.** `grep -n "deploy:\|mem_limit\|cpus\|logging:\|shm_size" docker-compose*.yml`
→ **aucun résultat**. Healthchecks présents uniquement sur `redis`
(`docker-compose.prod.yml:14-18`) et `db` (`:29-33`) ; **rien** sur `backend`
(`:37-83`) ni `frontend` (`:86-92`). `depends_on: - backend` (`:90`) sans
`condition:` → nginx démarre pendant que le backend importe encore ses 517 routes.
Redis sans `maxmemory` (`:6-18`).

**Correctif :**

```yaml
  backend:
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=3).status==200 else 1)\""]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 90s
    shm_size: "256mb"
    deploy:
      resources:
        limits:
          memory: 2g
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }

  db:
    shm_size: "256mb"
    deploy:
      resources:
        limits:
          memory: 2g

  redis:
    command: ["redis-server", "--maxmemory", "256mb", "--maxmemory-policy", "allkeys-lru"]
```

`start_period: 90s` est calibré sur le démarrage MESURÉ de 34–50 s
(`…20260817.md:159`). `/health/live` (`backend/app/api/v1/endpoints/health.py:35-39`)
ne touche ni PostgreSQL ni Redis : c'est le bon endpoint pour un healthcheck de
conteneur ; `/health/ready` ouvrirait une connexion PostgreSQL toutes les 30 s et
par worker.

**Gain attendu et fondement.** Aucun gain de latence. Confinement d'incident :
aujourd'hui, un pic mémoire du backend (imports Excel/PDF : `pandas` 57 Mo,
`pdfplumber` 10 Mo par worker — MESURÉ, `…20260817.md:132-144`) fait intervenir
l'OOM killer de l'hôte, qui vise le plus gros consommateur — potentiellement
**PostgreSQL**. Avec `restart: always` partout, la boucle est silencieuse.
Sur `deploy.resources` en Compose non-Swarm : `docker compose up` applique bien
`limits` (contrairement à `reservations`), mais si la version installée l'ignore,
utiliser `mem_limit: 2g` (syntaxe v2).

**Risque en production.** Une limite mémoire mal calibrée transforme une lenteur en
`OOMKilled`. Calibrer sur le RSS réel avant de poser le plafond ; 2 Go laisse ~2× la
marge des 1,069 Go MESURÉS pour 3 workers.

### C4 — nginx : pas de keepalive amont, pas de `client_max_body_size` [gain moyen × confiance élevée]

**Preuve.** `frontend/nginx.conf:55-63` : `proxy_http_version 1.1` est bien posé,
mais il n'y a **ni bloc `upstream`, ni `proxy_set_header Connection ""`**. Sans ce
couple, nginx envoie `Connection: close` à chaque requête proxifiée (DÉDUIT,
comportement documenté de nginx) : établissement TCP neuf vers `backend:8000` à
chaque appel d'API. Aucun `client_max_body_size` dans `frontend/nginx.conf` ni dans
`docs/nginx/backend-secure-uploads.conf` → plafond par défaut **1 Mo**, alors que
l'application accepte des annexes PDF (`backend/app/api/v1/endpoints/requisitions.py:1383`,
`file_size=len(contents)`) — un scan de justificatif dépasse couramment 1 Mo.

**Correctif** (`frontend/nginx.conf`, hors bloc `server`, puis dans `location /api/`) :

```nginx
upstream onec_backend {
    server backend:8000;
    keepalive 32;
    keepalive_timeout 60s;
}
```

```nginx
    location /api/ {
        proxy_pass http://onec_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        client_max_body_size 25m;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
        proxy_buffers 16 16k;
        proxy_busy_buffers_size 32k;
        # en-têtes existants inchangés
    }
```

**Gain attendu et fondement.** DÉDUIT : suppression d'un handshake TCP par requête
d'API (~1 RTT ; négligeable en boucle locale Docker, réel si backend et nginx sont
un jour séparés) et, surtout, suppression de la création/destruction de socket côté
worker Python — encore du CPU rendu au goulot. `client_max_body_size` ne relève pas
de la performance mais d'un 413 fonctionnel silencieux. `proxy_read_timeout` par
défaut est 60 s : à aligner sur le `--timeout` gunicorn de C1, sinon nginx coupe
avant que gunicorn n'ait tranché.

**Risque en production.** `client_max_body_size 25m` élargit la surface d'abus
(upload volumineux répété). L'application doit valider la taille côté serveur ;
aucune validation de taille n'a été trouvée dans le backend (`grep MAX_UPLOAD` :
aucun résultat) — à traiter en même temps.

### C5 — `X-Accel-Redirect` n'est branché sur aucun nginx du dépôt [gain moyen × confiance élevée]

**Preuve.** Le backend émet bien l'en-tête :
`backend/app/api/v1/endpoints/secure_uploads.py:55` →
`headers = {"X-Accel-Redirect": f"/_protected_uploads/{safe_rel}"}`, corps vide.
La `location internal` correspondante n'existe **que** dans
`docs/nginx/backend-secure-uploads.conf:12-15` — un fichier de documentation, qui
n'est copié dans aucune image (`frontend/Dockerfile:9` ne copie que
`frontend/nginx.conf`) et ne correspond à aucun service de `docker-compose.prod.yml`.
`frontend/nginx.conf` — le seul nginx réellement déployé par le compose — n'a
**aucune** `location /_protected_uploads/`, et le conteneur `frontend`
(`docker-compose.prod.yml:86-92`) **ne monte pas** le volume
`/var/www/onec_smart_data/uploads` que monte le backend (`:76-77`).

**Conséquence, DÉDUITE.** Si le trafic passe par le nginx du compose, une réponse
`X-Accel-Redirect` déclenche une redirection interne vers `/_protected_uploads/…`,
qui ne matche que `location /` (`frontend/nginx.conf:37-53`) et retombe sur
`try_files … /index.html` : le client reçoit **la page HTML de l'application, en 200**,
à la place de son PDF. Si le trafic passe par un nginx d'hôte calqué sur
`docs/nginx/backend-secure-uploads.conf`, tout fonctionne et les fichiers ne
transitent pas par Python — mais **ce fichier n'est pas déployé par le dépôt**, donc
son existence sur le serveur est une hypothèse, pas un fait.

S'ajoute un second désalignement : `frontend/.dockerignore:5` exclut `.env.*`
(`!.env.example` ligne 6 ne rattrape que l'exemple). `frontend/.env.production`
— qui contient `VITE_API_BASE_URL=https://api.onec-rdc.org/api/v1` et
`VITE_SECURE_UPLOADS=true` — **n'entre donc jamais dans le contexte de build Docker**.
Le bundle construit par `frontend/Dockerfile:6` retombe sur les défauts de
`frontend/src/lib/apiClient.ts:37` (`/api/v1`, même origine) et
`frontend/src/utils/uploads.ts:3` (`secureUploadsEnabled = false`), donc construit
des URL `/uploads/…` que `docker-compose.prod.yml:44` (`SERVE_UPLOADS_PUBLICLY: "false"`,
donc `backend/app/main.py:82-83` ne monte pas `/uploads`) ne sert pas.
**Conclusion : l'image frontend construite par ce dépôt n'affiche pas les pièces
jointes.** Le site en ligne fonctionne — donc son bundle a été construit autrement
(hors Docker, ou via un `dist/` déposé sur l'hôte). C'est une divergence
dépôt/production, et elle est structurelle.

**Correctif** (aligner le nginx déployé sur le mécanisme réel) — dans
`frontend/nginx.conf`, plus montage du volume en lecture seule côté `frontend` :

```nginx
    location /_protected_uploads/ {
        internal;
        alias /var/www/onec_smart_data/uploads/;
        expires 1h;
        add_header Cache-Control "private, max-age=3600" always;
        add_header X-Content-Type-Options "nosniff" always;
    }
```

```yaml
  frontend:
    volumes:
      - /var/www/onec_smart_data/uploads:/var/www/onec_smart_data/uploads:ro
```

et, pour le build : retirer `.env.production` de l'exclusion, ou passer les valeurs
en `build.args` explicites.

**Gain attendu et fondement.** DÉDUIT : un fichier servi par `sendfile()` nginx
n'occupe pas de worker Python pendant toute la durée du transfert. Sur une liaison
lente, un PDF de 5 Mo peut monopoliser une tâche async pendant plusieurs secondes ;
avec 3 workers CPU-bound c'est directement du débit perdu. Le mécanisme est déjà
codé côté Python — il ne manque que la moitié nginx.

**Risque en production.** `internal;` est ce qui empêche l'accès direct : un `alias`
posé sans `internal` exposerait publiquement **tous** les uploads de **tous** les
tenants. À ne pas manipuler à la légère ; le contrôle d'autorisation reste dans
`secure_uploads.py:118-129`.

### C6 — Image backend mono-stage avec la chaîne de compilation [gain faible en runtime × confiance élevée]

**Preuve.** `backend/Dockerfile:1-15` : un seul `FROM python:3.12-slim`, avec
`build-essential`, `libpq-dev` et `postgresql-client` **conservés dans l'image
finale**. Or les dépendances de `backend/requirements.txt` sont toutes disponibles en
roues manylinux (asyncpg 0.30, pandas 2.2.2, Pillow 10.4, reportlab 4.2.2) ; il n'y a
**pas** de `psycopg2` (asyncpg uniquement, `requirements.txt:10`), donc `libpq-dev`
n'a pas de justification. `postgresql-client` n'est utilisé par aucun script du
conteneur backend (`backend/entrypoint.sh` n'appelle qu'`alembic` ;
`scripts/backup_db.sh:45` s'exécute dans le conteneur **db**).

**Correctif :**

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .
RUN addgroup --system app && adduser --system --ingroup app app \
    && chmod +x /app/entrypoint.sh && chown -R app:app /app
USER app
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
```

**Gain attendu et fondement.** DÉDUIT, **taille non mesurée** (démon Docker
indisponible) : `build-essential` pèse à lui seul de l'ordre de 250–400 Mo décompressés.
Effet sur le temps de `docker pull`/déploiement et sur la surface d'attaque, **aucun
effet sur la latence runtime** — c'est ce que dit déjà `docs/ANALYSE_PERFORMANCE.md:30`,
et c'est pourquoi ce point est classé bas malgré une confiance élevée.

**Risque en production.** Si une dépendance future n'a pas de roue, le build échoue
au lieu de compiler silencieusement. C'est un risque de chaîne de build, pas de
production. Vérifier `pip install` en CI avant bascule.

### C7 — Front : compression et cache déjà bien traités, deux angles morts [gain faible × confiance élevée]

**Acquis, à ne pas retoucher.** `frontend/nginx.conf:14-35` : gzip actif, niveau 6,
`gzip_min_length 256`, `gzip_proxied any`, liste MIME complète (JS, CSS, JSON, SVG,
wasm, woff/woff2). `:65-78` : `/assets/` en `expires 1y` + `Cache-Control: public,
no-transform, immutable` — exactement ce qu'appellent les noms hashés de Vite —
avec les en-têtes de sécurité correctement répétés (le piège `add_header` de nginx
est documenté aux lignes 72-74). `:52` : `expires -1` sur `index.html`. Côté build,
`frontend/vite.config.ts:16-73` découpe des chunks vendor stables et documente
pourquoi. **Ce volet est fait, et bien fait.**

**Angle mort 1 — brotli absent.** L'image `nginx:stable-alpine`
(`frontend/Dockerfile:8`) n'embarque pas `ngx_brotli`. Brotli niveau 5 rend
typiquement 15–20 % de plus que gzip 6 sur du JS (DÉDUIT, ordre de grandeur usuel ;
non mesuré ici). Le chemin sans recompiler nginx est la **pré-compression au build** :

```dockerfile
RUN npm run build \
    && find dist -type f \( -name '*.js' -o -name '*.css' -o -name '*.svg' -o -name '*.json' \) \
       -exec gzip -9 -k {} \;
```

```nginx
    gzip_static on;
```

`gzip_static` est inclus dans nginx standard : nginx sert le `.gz` déjà présent au
lieu de compresser à chaque requête. Gain double — meilleur ratio (niveau 9 au lieu
de 6) et zéro CPU nginx par requête.

**Angle mort 2 — HTTP/2 absent, mais hors du dépôt.** `frontend/nginx.conf:1` :
`listen 80;` uniquement. Aucun `listen 443 ssl`, aucun certificat, aucun `http2`
nulle part dans le dépôt. HTTP/1.1 sans TLS dans le conteneur : la terminaison TLS
se fait donc **ailleurs** (reverse proxy d'hôte, ALB, CDN) — sur un composant qui
n'existe pas dans le dépôt. Impossible de dire si le public est servi en HTTP/2 :
voir §5.

### C8 — Redis : réellement utilisé, persistance à laisser désactivée [constat, pas de correctif majeur]

**Preuve d'usage réel** (pas une déclaration à vide) : `backend/app/core/cache.py`
expose `cache_get/set/delete/delete_pattern` ; les appelants sont
`backend/app/api/deps.py:199-214` (statut SaaS du tenant, avec cache négatif),
`backend/app/api/deps.py:244-255` (contexte d'authentification, TTL 30 s —
c'est la recommandation n°2 de `docs/PERFORMANCE_POOL_FIX_20260803.md:146-150`,
effectivement implémentée), `app/services/report_cache.py` (invalidé depuis
`encaissements.py:1501,1826`), plus le résolveur de tenant et le dashboard.
`cache_delete_pattern` utilise **SCAN et non KEYS** (`cache.py:83-99`) — le piège
classique est évité, et documenté.

**Persistance AOF désactivée** (`docker-compose.prod.yml:11-13`, commentée) :
**acceptable, et c'est le bon choix.** Tout ce qui est stocké est reconstructible à
la lecture suivante et porte un TTL court (30 s pour l'auth, 15 s pour les rapports,
300 s par défaut via `REDIS_DEFAULT_TTL`, `docker-compose.prod.yml:53`). Aucun état
métier — ni session, ni file de travail, ni verrou distribué — n'y transite
(vérifié : le refresh token est un cookie HttpOnly signé, pas une session Redis).
Un redémarrage Redis coûte une vague de reconstruction de cache de quelques
secondes, pas une perte de données. Activer l'AOF ajouterait des `fsync` pour rien.

**Le vrai manque est ailleurs : aucun `maxmemory`.** Sans plafond ni politique
d'éviction, Redis grossit jusqu'à la RAM de l'hôte, et comme il n'a pas non plus de
limite conteneur (C3), c'est l'OOM killer qui arbitre. Correctif dans C3.

### C9 — Volumes et uploads : disque local, pas de stockage objet [constat]

**Preuve.** `docker-compose.prod.yml:76-77` : bind mount
`/var/www/onec_smart_data/uploads:/var/www/onec_smart_data/uploads`, aligné sur
`UPLOAD_DIR` (`:45`). Base : volume nommé `postgres_data` (`:23-24`, `:94-95`),
pilote `local`. Aucune dépendance S3 (`boto3` absent de `backend/requirements.txt`),
aucun client objet dans le code.

**Lecture.** Les uploads **survivent** au redéploiement : le bind mount pointe le
disque de l'hôte, pas la couche du conteneur — c'est correct et volontaire
(`README.md:84-90`). En revanche : un seul hôte, donc **pas de scale-out possible**
du backend (deux instances ne partageraient pas le répertoire), sauvegarde des
fichiers non couverte (`scripts/backup_db.sh` ne sauvegarde que la base, et vers
`/mnt/d/Projet_dev_ck/…` — un chemin WSL du poste de développement, ligne 37, donc
inutilisable tel quel sur le serveur), et le disque de l'instance devient une
ressource à surveiller. Migrer vers S3 est un chantier applicatif, pas un réglage
d'infrastructure : hors périmètre de cet audit, mais c'est le préalable à toute
horizontalisation.

### C10 — Chemin AWS : esquissé, pas outillé [constat]

Ce qui **existe réellement** dans le dépôt :

- `.github/workflows/ci.yml` — **tests uniquement** : pytest backend sur services
  PostgreSQL 16 + Redis 7 (`:9-57`), typecheck + build frontend (`:59-76`).
  **Aucun job de build d'image, aucun push de registre, aucun déploiement.**
  Il n'existe qu'un seul fichier dans `.github/workflows/`.
- `reinstall_onec_rdc/` — n'a **rien** à voir avec AWS : c'est un runbook de remise à
  zéro de base (`RUNBOOK_onec_rdc.md`), des scripts SQL de purge et un seed
  d'organes. Toutes ses commandes sont des `docker compose exec` lancés depuis
  `D:\Projet_dev_ck\onec_smart`, c'est-à-dire **depuis le poste de développement**.
- `scripts/` — `backup_db.sh` (chemin WSL en dur), `backup_db_cron.txt`, `health.sh`
  (qui interroge `localhost:8000` puis l'IP hôte Windows lue dans
  `/etc/resolv.conf`, lignes 23-28 : c'est un script de **dev WSL**), et deux
  simulateurs de webhook.
- Mentions AWS dans la documentation : **une seule ligne réelle**, `README.md:84`
  (« Production (AWS/EC2) »), qui se contente de dire d'utiliser
  `docker-compose.prod.yml`. `docs/ANALYSE_PERFORMANCE.md:28` évoque « l'instance EC2
  réelle » sans jamais la caractériser.

**Verdict.** Il n'y a **aucune** infrastructure AWS dans ce dépôt : ni RDS (la base
est un conteneur `postgres:16-alpine` du compose), ni S3, ni Terraform/CloudFormation,
ni ALB, ni ASG, ni pipeline de déploiement. Le modèle réel est **un hôte unique,
probablement une EC2, sur lequel on lance `docker compose -f docker-compose.prod.yml
up --build -d` à la main** (`README.md:86-88`). Toute recommandation qui présuppose
RDS (et donc un `max_connections` différent, un pgbouncer, des Performance Insights)
serait hors sol. **Conséquence directe sur le §1 : `max_connections = 100` est bien
le défaut de l'image conteneurisée, pas un paramètre RDS.**

Corollaire pratique : `--build` sur l'hôte de production signifie que **le serveur
compile le bundle frontend et installe les dépendances Python à chaque déploiement**,
avec `npm install` (et non `npm ci`, `frontend/Dockerfile:4`) — donc sans
verrouillage du `package-lock.json` : deux déploiements successifs peuvent produire
deux bundles différents. Correctif trivial et rentable :

```dockerfile
COPY package*.json ./
RUN npm ci
```

---

## 4. Ce que je n'ai pas pu vérifier

- **Aucune mesure produite pour cet audit.** Démon Docker inactif : pas de build,
  pas de `docker image ls`, pas de conteneur, pas de `SHOW max_connections` en
  direct, pas de campagne de charge. Tout ce qui est chiffré vient soit des
  documents de mesure existants (étiqueté MESURÉ, avec leur date et leur machine),
  soit d'un calcul sur fichiers (étiqueté DÉDUIT).
- **La taille réelle des images** backend et frontend. L'argument « mono-stage
  lourd » repose sur le contenu du `Dockerfile`, pas sur un `docker image ls`.
- **Le contenu du `.env` de production.** Le `.env` présent ici est un fichier de
  développement (30 lignes, `POSTGRES_USER=christian`, `ENABLE_DEBUG_ENDPOINTS=true`,
  `SAAS_CONSOLE_BASE_URL=http://localhost:8000`). Il ne définit **ni** `BACKEND_WORKERS`
  **ni** aucun `DB_POOL_*`. Si le `.env` du serveur définit ces variables, le calcul
  du §1.1 change — mais `BACKEND_WORKERS` resterait sans effet en prod, puisque
  aucun `command:` ne le consomme (C1).
- **Le taux de hit du cache Redis.** L'usage est prouvé par le code ; son efficacité
  ne l'est pas. Aucune métrique de hit/miss n'est exposée (`core/cache.py` ne
  compte rien).
- **Le comportement réel de `X-Accel-Redirect` en production.** Le dépôt contient
  les deux moitiés du mécanisme dans deux fichiers qui ne se rencontrent pas
  (C5). Laquelle est déployée est indéterminable ici.
- **Si le bundle frontend en ligne a été construit par `frontend/Dockerfile`.**
  L'exclusion de `.env.production` par `.dockerignore` rend le résultat du build
  Docker incompatible avec le site tel qu'il est décrit (CSP pointant
  `api.onec-rdc.org`). Une des deux choses n'est pas ce qu'elle paraît.
- **HTTP/2 et TLS.** Terminés par un composant absent du dépôt.
- **`docs/PERFORMANCE_SQL_OPTIMIZATION_20260803.md` et
  `PERFORMANCE_WRITE_CONTENTION_20260803.md`** n'ont pas été dépouillés en détail :
  ils portent sur le coût SQL applicatif, hors du périmètre infrastructure demandé.

## 5. Ce qui exigerait un accès au serveur de production

1. **Le nombre de vCPU et la RAM de l'instance.** C'est le paramètre manquant le
   plus structurant : il décide seul entre 3 et 4 workers (C1), et il conditionne
   la valeur des limites mémoire (C3). Les projections de
   `…20260817.md:186-195` (3 workers pour 100 utilisateurs, ~6 pour 200) supposent
   « autant de cœurs réellement disponibles que de workers » — supposition
   invérifiable d'ici. `nproc`, `free -m`, `docker stats`.
2. **Quel nginx sert réellement `api.onec-rdc.org`**, et s'il contient
   `location /_protected_uploads/` (C5) et des directives gzip (C2). `nginx -T` sur
   l'hôte. Sans cette réponse, C2 et C5 restent des correctifs conditionnels.
3. **Les paramètres PostgreSQL effectifs et le comportement au volume réel.**
   `SHOW ALL`, puis `pg_stat_statements` et `pg_stat_activity` sous charge réelle.
   C'est la réserve n°1 de `…20260817.md:199-203` : la linéarité workers/débit
   MESURÉE tenait sur 299 réquisitions et 245 encaissements. Au volume de
   production, le goulot peut avoir migré vers la base — auquel cas C1 (pool) monte
   d'un cran en priorité et le tuning PostgreSQL cesse d'être secondaire.
4. **La présence effective de redémarrages de workers.** `docker compose logs backend
   | grep -c "WORKER TIMEOUT"` tranche en une commande si le mode de panne décrit en
   C1 est théorique ou déjà en cours. **À faire en premier** : c'est le test le moins
   cher de tout ce rapport.
5. **La consommation mémoire réelle par worker sur l'instance de production**, pour
   calibrer les limites de C3 plutôt que de les poser au jugé.
6. **Le RTT et la bande passante réels des utilisateurs** (contexte RDC), qui
   décident si l'effort compression (C2, C7) vaut plus que l'effort CPU serveur.
7. **La procédure de déploiement réellement pratiquée** (`--build` sur l'hôte ?
   image pré-construite ? `dist/` déposé à la main ?). Elle détermine si les
   correctifs de `Dockerfile` et de `.dockerignore` ont le moindre effet.
