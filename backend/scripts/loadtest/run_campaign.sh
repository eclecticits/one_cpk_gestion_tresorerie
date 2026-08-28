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
# La sonde de disponibilite tourne sur l'HOTE, k6 dans un conteneur : les deux
# n'ont pas la meme vue du reseau. Avec K6=docker sur le reseau compose,
# BASE_URL vaut http://backend:8000/... — un nom que l'hote ne resout pas.
# HEALTH_URL permet de sonder par le port publie sans changer la cible de k6.
HEALTH_URL="${HEALTH_URL:-$BASE_URL/health/ready}"
STAGES="${STAGES:-10,25,50,100}"
DURATION="${DURATION:-10m}"
RAMP="${RAMP:-1m}"
PAUSE_ENTRE_PALIERS="${PAUSE_ENTRE_PALIERS:-60}"
K6="${K6:-natif}"                 # natif | docker
DOCKER_NETWORK="${DOCKER_NETWORK:-onec_smart_default}"
RESULTATS="${RESULTATS:-$ICI/resultats/$(date +%Y%m%d_%H%M%S)}"
# Chemin ABSOLU : le script tourne depuis loadtest/, pas depuis la racine du
# depot. Avec un chemin relatif, la capture des journaux backend echouait en
# silence (`|| true`) et les fichiers palier_*_backend.log restaient vides —
# or c'est la qu'on lit DB_POOL_AT_CAPACITY, QueuePool limit et WORKER TIMEOUT.
RACINE_DEPOT="${RACINE_DEPOT:-$(cd "$ICI/../../.." && pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-$RACINE_DEPOT/docker-compose.yml}"
COLLECTE_SERVEUR="${COLLECTE_SERVEUR:-1}"
# FLUX_BRUT=0 desactive `--out json=`. Ce flux serialise CHAQUE echantillon k6
# (1,76 Mo au palier 25 VU) et k6 le bufferise en memoire. Sur un hote a la
# memoire courte, c'est ce qui a tue le generateur : SIGKILL, code de sortie
# 137, palier perdu a 40 s. Le summary suffit pour comparer les paliers ; le
# flux brut ne sert qu'a une analyse echantillon par echantillon.
FLUX_BRUT="${FLUX_BRUT:-1}"

mkdir -p "$RESULTATS"
echo "Resultats -> $RESULTATS"

if [ ! -f "$ICI/k6/context.json" ]; then
  echo "ERREUR : $ICI/k6/context.json absent. Executez d'abord seed/mint_tokens.py (voir README.md)." >&2
  exit 1
fi

# --- Peremption des jetons ---------------------------------------------------
# Les JWT du contexte ont une duree de vie fixee a la frappe
# (mint_tokens.py --ttl-minutes, reportee dans `jetons_valides_minutes`). Passee
# cette limite, TOUTES les requetes repondent 401 « Invalid token » : la
# campagne tourne, produit des chiffres, et ne mesure plus rien. C'est arrive le
# 27/08 a 23h09, sur des jetons frappes a 15h00 avec 480 minutes de validite.
# Le controle coute une seconde ; la campagne perdue coutait dix minutes.
AGE_MIN=$(( ( $(date +%s) - $(date -r "$ICI/k6/context.json" +%s) ) / 60 ))
TTL_MIN=$(sed -n 's/.*"jetons_valides_minutes"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' "$ICI/k6/context.json" | head -1)
TTL_MIN="${TTL_MIN:-0}"
if [ "$TTL_MIN" -gt 0 ] && [ "$AGE_MIN" -ge "$TTL_MIN" ]; then
  echo "ERREUR : jetons perimes — context.json a $AGE_MIN min, validite $TTL_MIN min." >&2
  echo "         Refrappez-les (seed/mint_tokens.py) avant de relancer, sinon la" >&2
  echo "         campagne ne mesurera que des 401." >&2
  exit 1
fi
RESTANT=$(( TTL_MIN - AGE_MIN ))
if [ "$TTL_MIN" -gt 0 ] && [ "$RESTANT" -lt 60 ]; then
  echo "AVERTISSEMENT : les jetons expirent dans $RESTANT min. Une campagne longue les depassera."
fi

# --- Attente de disponibilite ------------------------------------------------
# Le demarrage applicatif est long (34 a 50 s mesures en Phase 4, section
# « Le temps de demarrage n'est pas du a ces imports »). Un palier lance trop
# tot mesure le cold start : c'est l'anomalie corrigee en Phase 3.
attendre_backend() {
  local limite=$((SECONDS + ${1:-180}))
  echo -n "Attente de $HEALTH_URL "
  while [ $SECONDS -lt $limite ]; do
    if curl -fsS -m 5 "$HEALTH_URL" >/dev/null 2>&1; then
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

  OPTIONS_SORTIE=()
  if [ "$FLUX_BRUT" = "1" ]; then
    OPTIONS_SORTIE=(--out "json=$(basename "$PREFIXE")_raw.json")
  else
    echo "  (flux brut desactive : FLUX_BRUT=0)"
  fi

  # EXPORT_RATE n'est transmis que s'il est pose : sans lui, journeys.js garde
  # son defaut de 4/min. C'est la variable qui separe « l'application sature »
  # de « les exports saturent l'application ».
  OPTIONS_ENV=()
  if [ -n "${EXPORT_RATE:-}" ]; then
    OPTIONS_ENV=(-e "EXPORT_RATE=$EXPORT_RATE")
    echo "  (debit d'export force a $EXPORT_RATE/min)"
  fi

  set +e
  lancer_k6 "$ICI/k6/journeys.js" \
    -e "BASE_URL=$BASE_URL" -e "VUS=$VUS" -e "DURATION=$DURATION" -e "RAMP=$RAMP" \
    "${OPTIONS_ENV[@]}" "${OPTIONS_SORTIE[@]}" \
    2>&1 | tee "${PREFIXE}_summary.txt"
  CODE=${PIPESTATUS[0]}
  set -e

  # 137 = 128 + SIGKILL. Le generateur a ete tue, pas l'application : le palier
  # ne mesure rien. A distinguer d'un depassement de seuils (99), sinon on lit
  # un effondrement applicatif la ou il n'y a qu'un banc a court de memoire.
  if [ "$CODE" -eq 137 ]; then
    echo "  >> GENERATEUR TUE (SIGKILL) a $VUS VU — palier NON MESURE, pas un echec applicatif."
  fi

  if [ "${COLLECTE_SERVEUR:-0}" = "1" ]; then
    kill "$METRIQUES_PID" 2>/dev/null || true
    wait "$METRIQUES_PID" 2>/dev/null || true
  fi

  # --out json= est resolu depuis le repertoire de travail de k6, soit k6/ en
  # natif, soit /scripts (= k6/ monte) en conteneur : un chemin absolu de l'hote
  # ne marcherait pas dans les deux cas. Le flux brut atterrissait donc dans k6/
  # et chaque campagne ecrasait la precedente. On l'archive apres coup, dans le
  # repertoire du palier, la ou vivent deja summary/stats/pg_activity.
  BRUT="$ICI/k6/$(basename "$PREFIXE")_raw.json"
  if [ -f "$BRUT" ]; then
    mv "$BRUT" "${PREFIXE}_raw.json"
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
