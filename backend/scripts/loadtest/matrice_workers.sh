#!/usr/bin/env bash
# Matrice workers x paliers : 1, 2 puis 4 workers, chacun sur 10/25/50/100 VU.
#
#   ./matrice_workers.sh                       # matrice complete
#   WORKERS="1,2,4" STAGES="10,25,50,100" ./matrice_workers.sh
#
# Ce script existe parce que le nombre de workers ne se change pas a chaud : il
# faut recreer le conteneur backend entre deux groupes. Enchainer a la main
# expose a deux erreurs qui invalident la comparaison — mesurer un palier sur
# une configuration qu'on croit changee, et mesurer un demarrage a froid.
#
# Duree : 12 paliers x (10 min + 1 min de montee) + pauses ~= 2 h 30.
#
# PREALABLES, verifies avant de lancer (chacun a deja invalide une campagne) :
#   seed/activer_tenant_test.sh    tenant ACTIVE, sinon 402 sur toute ecriture
#   seed/resync_sequences.sh       compteurs a jour, sinon 500 sur les creations
#   seed/recharger_budget_test.sh  marge budgetaire, sinon 400 metier
#   observe/sonde_ecriture.sh      doit repondre 201/200 sur les deux operations
#
# Le contexte k6 doit avoir ete refrappe APRES l'activation du tenant :
# `plan_status` est fige dans le JWT.

set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RACINE_DEPOT="${RACINE_DEPOT:-$(cd "$ICI/../../.." && pwd)}"
WORKERS="${WORKERS:-1,2,4}"
STAGES="${STAGES:-10,25,50,100}"
DUREE="${DUREE:-10m}"
RAMPE="${RAMPE:-1m}"
RACINE_RESULTATS="${RACINE_RESULTATS:-$ICI/resultats/matrice_$(date +%Y%m%d_%H%M%S)}"
# Le pool suit les workers : chaque worker a son propre pool_size + max_overflow.
# On epingle les deux pour que la seule variable de la matrice soit le nombre de
# workers — sinon le defaut du code (max_overflow=10) s'appliquerait si .env
# changeait, et 4 workers donneraient 60 connexions au lieu de 40.
POOL_SIZE="${POOL_SIZE:-5}"
MAX_OVERFLOW="${MAX_OVERFLOW:-5}"

mkdir -p "$RACINE_RESULTATS"
echo "Matrice -> $RACINE_RESULTATS"
echo "  workers : $WORKERS"
echo "  paliers : $STAGES  (duree $DUREE, montee $RAMPE)"
echo

# --- Verification des prealables ---------------------------------------------
echo "Verification du chemin d'ecriture avant de commencer..."
SONDE="$("$ICI/observe/sonde_ecriture.sh" 2>&1 || true)"
if echo "$SONDE" | grep -qE "BLOQUE|REFUSE"; then
  echo "$SONDE"
  echo >&2
  echo "ARRET : le chemin d'ecriture est ferme. Une matrice lancee maintenant" >&2
  echo "mesurerait des refus metier, pas de la contention. Voir les prealables" >&2
  echo "en tete de ce script." >&2
  exit 1
fi
echo "$SONDE" | grep -E "encaissement|requisition"
echo

for N in ${WORKERS//,/ }; do
  echo "=============================================================="
  echo " GROUPE $N WORKER(S)"
  echo "=============================================================="

  # Recreation du conteneur : `docker compose up -d` ne suffit pas si seule une
  # variable d'environnement change et que l'image est identique, d'ou --force-recreate.
  BACKEND_WORKERS="$N" DB_POOL_SIZE="$POOL_SIZE" DB_MAX_OVERFLOW="$MAX_OVERFLOW" \
    docker compose -f "$RACINE_DEPOT/docker-compose.yml" up -d --force-recreate backend

  echo -n "Attente du backend "
  LIMITE=$((SECONDS + 300))
  while [ $SECONDS -lt $LIMITE ]; do
    curl -fsS -m 5 http://localhost:8000/api/v1/health/ready >/dev/null 2>&1 && break
    echo -n "."
    sleep 5
  done
  echo " pret."

  # Trace de la configuration reellement appliquee : c'est cette ligne, et non
  # la variable passee, qui fait foi dans le rapport.
  CONFIG="$(docker compose -f "$RACINE_DEPOT/docker-compose.yml" logs backend 2>/dev/null \
            | grep -m1 DB_POOL_CONFIG || echo 'DB_POOL_CONFIG introuvable')"
  echo "  $CONFIG"
  echo "$CONFIG" > "$RACINE_RESULTATS/w${N}_config.txt"

  # Chauffe : le premier acces paie le cache froid (mesure : requisitions
  # 13 411 ms a froid contre 31 ms a chaud). Sans elle, le palier 10 VU de
  # chaque groupe mesurerait surtout un demarrage.
  echo "  chauffe des chemins froids..."
  "$ICI/observe/cout_unitaire.sh" 2 > "$RACINE_RESULTATS/w${N}_chauffe.txt" 2>&1 || true

  K6=docker \
  BASE_URL=http://backend:8000/api/v1 \
  HEALTH_URL=http://localhost:8000/api/v1/health/ready \
  STAGES="$STAGES" DURATION="$DUREE" RAMP="$RAMPE" \
  RESULTATS="$RACINE_RESULTATS/w${N}" \
    "$ICI/run_campaign.sh"

  echo
done

echo
echo "Matrice terminee. Sorties dans $RACINE_RESULTATS"
echo "Analyse : observe/matrice_tableau.py $RACINE_RESULTATS"
