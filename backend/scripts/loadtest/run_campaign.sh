#!/usr/bin/env bash
# Campagne de charge ONEC Smart : enchaine les paliers, attend la disponibilite
# du backend entre chaque, et archive les sorties brutes.
#
# LE GENERATEUR NE TOURNE PAS DANS LE CONTENEUR BACKEND.
# C'est le principal biais releve dans docs/PERFORMANCE_WORKER_SCALING_20260817.md :
# « Le generateur de charge tourne DANS le conteneur backend et dispute le CPU
# au serveur teste ». Ce script lance k6 depuis l'hote (binaire natif) ou depuis
# un conteneur separe, jamais depuis `backend`.
#
# Usage :
#   ./run_campaign.sh                       # paliers 10,25,50,100
#   STAGES="10,25,50,100,200" ./run_campaign.sh
#   DURATION=15m STAGES=100 ./run_campaign.sh
#   K6=docker ./run_campaign.sh             # k6 via l'image grafana/k6

set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_URL="${BASE_URL:-http://localhost:8000/api/v1}"
STAGES="${STAGES:-10,25,50,100}"
DURATION="${DURATION:-10m}"
RAMP="${RAMP:-1m}"
PAUSE_ENTRE_PALIERS="${PAUSE_ENTRE_PALIERS:-60}"
K6="${K6:-natif}"                 # natif | docker
DOCKER_NETWORK="${DOCKER_NETWORK:-onec_smart_default}"
RESULTATS="${RESULTATS:-$ICI/resultats/$(date +%Y%m%d_%H%M%S)}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
COLLECTE_SERVEUR="${COLLECTE_SERVEUR:-1}"

mkdir -p "$RESULTATS"
echo "Resultats -> $RESULTATS"

if [ ! -f "$ICI/k6/context.json" ]; then
  echo "ERREUR : $ICI/k6/context.json absent. Executez d'abord seed/mint_tokens.py (voir README.md)." >&2
  exit 1
fi

# --- Attente de disponibilite ------------------------------------------------
# Le demarrage applicatif est long (34 a 50 s mesures en Phase 4, section
# « Le temps de demarrage n'est pas du a ces imports »). Un palier lance trop
# tot mesure le cold start : c'est l'anomalie corrigee en Phase 3.
attendre_backend() {
  local limite=$((SECONDS + ${1:-180}))
  echo -n "Attente de $BASE_URL/health/ready "
  while [ $SECONDS -lt $limite ]; do
    if curl -fsS -m 5 "$BASE_URL/health/ready" >/dev/null 2>&1; then
      echo " pret."
      return 0
    fi
    echo -n "."
    sleep 3
  done
  echo " ECHEC : backend non pret." >&2
  return 1
}

lancer_k6() {
  local script="$1"; shift
  if [ "$K6" = "docker" ]; then
    docker run --rm -i \
      --network "$DOCKER_NETWORK" \
      -v "$ICI/k6:/scripts" \
      -w /scripts \
      grafana/k6 run "$@" "$(basename "$script")"
  else
    ( cd "$ICI/k6" && k6 run "$@" "$(basename "$script")" )
  fi
}

# --- Boucle des paliers ------------------------------------------------------
IFS=',' read -ra PALIERS <<< "$STAGES"
for VUS in "${PALIERS[@]}"; do
  VUS="$(echo "$VUS" | tr -d ' ')"
  [ -z "$VUS" ] && continue
  PREFIXE="$RESULTATS/palier_${VUS}vu"
  echo
  echo "=============================================================="
  echo " PALIER $VUS utilisateurs virtuels - duree $DURATION"
  if [ "$VUS" = "100" ]; then
    echo " (palier de non-regression : c'est celui qui saturait la"
    echo "  configuration de production avant correction de"
    echo "  docker-compose.prod.yml - voir perf-loadtest.md, section 8)"
  fi
  echo "=============================================================="

  attendre_backend 240

  if [ "$COLLECTE_SERVEUR" = "1" ]; then
    COMPOSE_FILE="$COMPOSE_FILE" "$ICI/observe/server_metrics.sh" "$PREFIXE" &
    METRIQUES_PID=$!
  fi

  set +e
  lancer_k6 "$ICI/k6/journeys.js" \
    -e "BASE_URL=$BASE_URL" -e "VUS=$VUS" -e "DURATION=$DURATION" -e "RAMP=$RAMP" \
    --out "json=$(basename "$PREFIXE")_raw.json" \
    2>&1 | tee "${PREFIXE}_summary.txt"
  CODE=${PIPESTATUS[0]}
  set -e

  if [ "${COLLECTE_SERVEUR:-0}" = "1" ]; then
    kill "$METRIQUES_PID" 2>/dev/null || true
    wait "$METRIQUES_PID" 2>/dev/null || true
  fi

  # Journaux backend du palier : c'est la qu'on lit DB_POOL_AT_CAPACITY,
  # DB_POOL_SLOW_USAGE, DB_SLOW_QUERY, SLOW_REQUEST et les WORKER TIMEOUT.
  docker compose -f "$COMPOSE_FILE" logs --since "$DURATION" backend \
    > "${PREFIXE}_backend.log" 2>&1 || true
  grep -c "QueuePool limit" "${PREFIXE}_backend.log" 2>/dev/null \
    | xargs -I{} echo "  saturations de pool signalees dans les logs : {}" || true
  grep -c "WORKER TIMEOUT" "${PREFIXE}_backend.log" 2>/dev/null \
    | xargs -I{} echo "  workers tues par l'arbitre gunicorn : {}" || true

  if [ "$CODE" -ne 0 ]; then
    echo "  >> SEUILS NON TENUS a $VUS VU (code k6 $CODE). La campagne continue."
  else
    echo "  >> Tous les seuils tenus a $VUS VU."
  fi

  echo "  pause de stabilisation ${PAUSE_ENTRE_PALIERS}s"
  sleep "$PAUSE_ENTRE_PALIERS"
done

echo
echo "Campagne terminee. Sorties dans $RESULTATS"
echo "Etape suivante : observe/pg_after.sql (unicite des numeros, pg_stat_statements)."
