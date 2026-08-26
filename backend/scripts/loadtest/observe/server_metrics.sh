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
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
INTERVALLE="${INTERVALLE:-5}"

DC="docker compose -f $COMPOSE_FILE"

echo "horodatage,conteneur,cpu_pct,mem_usage,mem_pct,net_io,block_io" > "${PREFIXE}_docker_stats.csv"
echo "horodatage,etat,connexions" > "${PREFIXE}_pg_activity.csv"
: > "${PREFIXE}_pool.log"

nettoyer() { echo; echo "Collecte arretee."; exit 0; }
trap nettoyer INT TERM

while true; do
  TS="$(date -Is)"

  docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}}' 2>/dev/null \
    | sed "s|^|${TS},|" >> "${PREFIXE}_docker_stats.csv"

  $DC exec -T db psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}" -At -F',' -c \
    "SELECT state, count(*) FROM pg_stat_activity WHERE datname = current_database() GROUP BY state" 2>/dev/null \
    | sed "s|^|${TS},|" >> "${PREFIXE}_pg_activity.csv"

  sleep "$INTERVALLE"
done
