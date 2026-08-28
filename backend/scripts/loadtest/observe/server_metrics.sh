#!/usr/bin/env bash
# Collecte des metriques SERVEUR pendant un tir. A lancer en parallele de k6.
#
#   ./server_metrics.sh /chemin/prefixe        # Ctrl-C ou kill pour arreter
#
# Produit :
#   <prefixe>_docker_stats.csv   CPU / RAM par conteneur, toutes les 5 s
#   <prefixe>_pg_activity.csv    connexions PostgreSQL par etat, toutes les 5 s
#   <prefixe>_pool.log           echantillons du pool SQLAlchemy vus dans les logs
#
# Pourquoi ces trois-la : la Phase 4 a montre que le goulot etait le CPU d'un
# worker Python et non PostgreSQL (docs/PERFORMANCE_WORKER_SCALING_20260817.md,
# section « Diagnostic »). Sans le CPU par conteneur cote a cote avec les
# connexions actives, on reprend le mauvais diagnostic de la Phase 3.

set -uo pipefail

PREFIXE="${1:-./metriques}"
ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Chemin ABSOLU : ce script est appele depuis loadtest/, pas depuis la racine.
# Avec un chemin relatif, tous les `docker compose` echouaient en silence
# (2>/dev/null) et les trois fichiers de sortie restaient vides.
RACINE_DEPOT="${RACINE_DEPOT:-$(cd "$ICI/../../../.." && pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-$RACINE_DEPOT/docker-compose.yml}"
INTERVALLE="${INTERVALLE:-5}"

DC="docker compose -f $COMPOSE_FILE"

echo "horodatage,conteneur,cpu_pct,mem_usage,mem_pct,net_io,block_io" > "${PREFIXE}_docker_stats.csv"
echo "horodatage,etat,connexions" > "${PREFIXE}_pg_activity.csv"
: > "${PREFIXE}_pool.log"

# Le fichier _pool.log etait cree puis jamais alimente : aucune ligne de code ne
# l'ecrivait, il ressortait a 0 octet a chaque tir. Ces marqueurs sont emis par
# app/db/session.py (DB_POOL_AT_CAPACITY, DB_POOL_SLOW_USAGE, DB_SLOW_QUERY) et
# app/middleware/timing.py (SLOW_REQUEST) : c'est la qu'on lit la saturation du
# pool. On suit le flux en continu plutot que de relire les logs apres coup,
# pour horodater les evenements pendant le palier.
$DC logs -f --since 10s backend 2>/dev/null \
  | grep --line-buffered -E "DB_POOL_AT_CAPACITY|DB_POOL_SLOW_USAGE|DB_SLOW_QUERY|SLOW_REQUEST|QueuePool limit|WORKER TIMEOUT|too many clients|FATAL" \
  >> "${PREFIXE}_pool.log" &
SUIVI_LOGS_PID=$!

nettoyer() {
  kill "$SUIVI_LOGS_PID" 2>/dev/null || true
  echo; echo "Collecte arretee."
  exit 0
}
trap nettoyer INT TERM

while true; do
  TS="$(date -Is)"

  docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}}' 2>/dev/null \
    | sed "s|^|${TS},|" >> "${PREFIXE}_docker_stats.csv"

  # Les identifiants sont lus DANS le conteneur : POSTGRES_USER vient de .env,
  # que compose injecte dans le service db mais que ce script n'a jamais eu
  # dans son environnement. Le repli "postgres" designait un role inexistant,
  # donc chaque appel echouait et _pg_activity.csv ne contenait que l'en-tete.
  $DC exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F"," -c \
    "SELECT state, count(*) FROM pg_stat_activity WHERE datname = current_database() GROUP BY state"' 2>/dev/null \
    | sed "s|^|${TS},|" >> "${PREFIXE}_pg_activity.csv"

  sleep "$INTERVALLE"
done
