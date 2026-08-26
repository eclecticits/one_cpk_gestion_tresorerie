#!/usr/bin/env bash
# Validation A/B du correctif de docker-compose.prod.yml.
#
# CE QUI A ETE CORRIGE (etat du depot au 2026-08-26)
#   Avant : le service `backend` de docker-compose.prod.yml n'avait ni
#   `command:` ni variables DB_POOL_*. Le conteneur executait donc le CMD de
#   l'image (backend/Dockerfile:27 : `gunicorn -w 4 ...`, sans --timeout, donc
#   arbitre a 30 s) et le pool prenait les defauts du code
#   (backend/app/core/config.py:77-79 : pool_size=5, max_overflow=10,
#   pool_timeout=30). Consequence : pool_timeout == timeout gunicorn. Une
#   requete atteignait la limite du pool a l'instant meme ou l'arbitre tuait le
#   worker — et un UvicornWorker tue emporte toutes ses requetes en cours.
#   Apres : `command:` gunicorn explicite avec --timeout 120 et
#   DB_POOL_TIMEOUT=5, soit un rapport de 24 entre les deux.
#
# COMMENT ON LE PROUVE
#   Le meme palier, celui qui saturait (100 VU), joue deux fois : une fois avec
#   les valeurs de l'ancienne configuration forcees par variables
#   d'environnement (aucun fichier n'est modifie), une fois avec les valeurs
#   corrigees. On compare taux d'erreur, p95, 502/504, `QueuePool limit` et
#   `WORKER TIMEOUT` dans les logs.
#
# Usage :
#   COMPOSE_FILE=docker-compose.prod.yml ./validate_prod_fix.sh
#
# ATTENTION : ce script recree le conteneur backend deux fois. A ne lancer que
# sur un environnement de test, jamais sur une production vivante.

set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPOT="${DEPOT:-/mnt/d/Projet_dev_ck/onec_smart}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BASE_URL="${BASE_URL:-http://localhost:8000/api/v1}"
VUS="${VUS:-100}"
DURATION="${DURATION:-10m}"
SORTIE="${SORTIE:-$ICI/resultats/prod_fix_$(date +%Y%m%d_%H%M%S)}"

mkdir -p "$SORTIE"
cd "$DEPOT"

echo "Ce script va recreer le conteneur backend ($COMPOSE_FILE) deux fois."
echo "Ctrl-C dans les 10 secondes pour annuler."
sleep 10

signaux() {
  local nom="$1"
  local fichier="$SORTIE/${nom}_signaux.txt"
  {
    echo "--- Signaux d'infrastructure ($nom) ---"
    echo -n "saturations de pool (QueuePool limit) : "
    docker compose -f "$COMPOSE_FILE" logs backend 2>&1 | grep -c "QueuePool limit" || true
    echo -n "workers tues par l'arbitre (WORKER TIMEOUT) : "
    docker compose -f "$COMPOSE_FILE" logs backend 2>&1 | grep -c "WORKER TIMEOUT" || true
    echo -n "pool a capacite (DB_POOL_AT_CAPACITY) : "
    docker compose -f "$COMPOSE_FILE" logs backend 2>&1 | grep -c "DB_POOL_AT_CAPACITY" || true
    echo -n "requetes lentes (SLOW_REQUEST) : "
    docker compose -f "$COMPOSE_FILE" logs backend 2>&1 | grep -c "SLOW_REQUEST" || true
  } | tee "$fichier"
}

jouer_palier() {
  local nom="$1"
  shift
  echo
  echo "############ CONFIGURATION : $nom ############"
  env "$@" docker compose -f "$COMPOSE_FILE" up -d --force-recreate backend
  # Le demarrage applicatif prend 34 a 50 s (Phase 4) : run_campaign.sh attend
  # /health/ready avant de tirer.
  BASE_URL="$BASE_URL" STAGES="$VUS" DURATION="$DURATION" \
    COMPOSE_FILE="$COMPOSE_FILE" RESULTATS="$SORTIE/$nom" \
    "$ICI/run_campaign.sh"
  signaux "$nom"
}

# A) Reproduction de l'ANCIENNE configuration de production, par variables
#    d'environnement uniquement : docker-compose.prod.yml utilise partout la
#    forme ${VAR:-defaut}, donc rien n'est modifie sur disque.
jouer_palier "avant_correctif" \
  BACKEND_WORKERS=4 BACKEND_TIMEOUT=30 \
  DB_POOL_SIZE=5 DB_MAX_OVERFLOW=10 DB_POOL_TIMEOUT=30

# B) Configuration corrigee, telle qu'elle est desormais dans le fichier.
jouer_palier "apres_correctif" \
  BACKEND_WORKERS=4 BACKEND_TIMEOUT=120 \
  DB_POOL_SIZE=5 DB_MAX_OVERFLOW=5 DB_POOL_TIMEOUT=5

echo
echo "Comparez : $SORTIE/avant_correctif  vs  $SORTIE/apres_correctif"
echo "Le correctif est valide si, a $VUS VU, la configuration corrigee tient"
echo "les seuils la ou l'ancienne produisait des 502/504, des WORKER TIMEOUT"
echo "ou des messages QueuePool limit."
