# Procédure de lancement — campagne de charge ONEC Smart

Rien ici n'a été exécuté : le démon Docker est arrêté sur le poste de rédaction.
Ces scripts sont prêts à lancer tels quels une fois Docker redémarré.
Aucun fichier du dépôt n'est modifié par cette procédure.

## Prérequis

- Le stack `onec_smart` démarré (`docker-compose.yml` en dev, `docker-compose.prod.yml` en préprod).
- `k6` sur la machine du générateur — **jamais dans le conteneur `backend`**
  (binaire natif, ou `K6=docker` pour passer par l'image `grafana/k6`).
- `curl`, `jq` facultatif.

## 1. Semer les données (une seule fois par base)

```bash
cd /mnt/d/Projet_dev_ck/onec_smart
# a) ossature : organisation, service, exercice, caisse, banque, comptes, users, experts
docker compose exec backend python scripts/load_campaign.py --stages "" --seed-users 400 --seed-experts 1000
# b) volume métier (60 k réquisitions, 120 k encaissements, 40 k sorties, 300 postes, 8 services)
docker compose cp <LOADTEST>/seed/seed_volume.py backend:/app/seed_volume.py
docker compose exec backend python /app/seed_volume.py --preset production
```

`--preset smoke` (≈2 min) pour valider la mécanique, `--preset pilote` intermédiaire.

## 2. Fabriquer les jetons

```bash
docker compose cp <LOADTEST>/seed/mint_tokens.py backend:/app/mint_tokens.py
docker compose exec backend python /app/mint_tokens.py --out /app/context.json --users 400 --ttl-minutes 480
docker compose cp backend:/app/context.json <LOADTEST>/k6/context.json
```

## 3. Armer l'observation serveur

```bash
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f - < <LOADTEST>/observe/pg_before.sql
```

(`pg_stat_statements` demande `shared_preload_libraries` : le bloc à ajouter dans
un override local est donné en tête de `observe/pg_before.sql`.)

## 4. Tirer

```bash
cd <LOADTEST>
BASE_URL=http://localhost:8000/api/v1 STAGES="10,25,50,100" DURATION=10m ./run_campaign.sh
```

Le script attend `/health/ready` avant chaque palier, lance la collecte
`docker stats` + `pg_stat_activity` en parallèle, archive le résumé k6, le flux
JSON brut et les journaux backend du palier dans `resultats/<horodatage>/`.

## 5. Contention ciblée

```bash
cd <LOADTEST>/k6
k6 run -e BASE_URL=http://localhost:8000/api/v1 -e MODE=nd  -e VUS=100 -e DURATION=3m contention.js
k6 run -e BASE_URL=http://localhost:8000/api/v1 -e MODE=req -e VUS=100 -e DURATION=3m contention.js
k6 run -e BASE_URL=http://localhost:8000/api/v1 -e MODE=pay -e VUS=50  -e DURATION=3m contention.js
```

## 6. Dépouiller

```bash
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f - < <LOADTEST>/observe/pg_after.sql \
  > <LOADTEST>/resultats/<horodatage>/pg_after.txt
```

La section 6 de `pg_after.sql` est le **contrat de numérotation** : elle doit
renvoyer zéro ligne. Une seule ligne = doublon de numéro sous concurrence.

## 7. Valider le correctif de `docker-compose.prod.yml`

```bash
cd <LOADTEST>
COMPOSE_FILE=docker-compose.prod.yml VUS=100 DURATION=10m ./validate_prod_fix.sh
```

Rejoue le palier 100 VU d'abord avec les valeurs de l'ancienne configuration
(forcées par variables d'environnement, aucun fichier touché), puis avec la
configuration corrigée, et compare les signaux d'infrastructure.

## 8. Nettoyer

```bash
docker compose exec backend python scripts/cleanup_load_test_org.py \
  --slug load-test-20260803 --org-id <ID> --confirm
```

Script déjà présent dans le dépôt (commit 8003109).

---

`<LOADTEST>` = le répertoire contenant ce fichier.
