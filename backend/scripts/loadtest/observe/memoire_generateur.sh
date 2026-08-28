#!/usr/bin/env bash
# Empreinte memoire du GENERATEUR k6, isolee du systeme teste.
#
#   ./memoire_generateur.sh [VUS] [DUREE]      # defaut : 25 30s
#
# Pourquoi : le 27/08, k6 a ete tue deux fois par l'OOM-killer (anon-rss ~600 Mo)
# alors que gunicorn reclamait de la memoire sur une VM de 3,7 Go. Le palier
# 25 VU etait perdu avant la premiere iteration. Avant de rejouer une campagne,
# il faut savoir ce que coute le generateur — sinon on impute a l'application
# un palier que le banc n'a jamais pu porter.
#
# La mesure porte sur l'INITIALISATION autant que sur le tir : c'est la que k6
# alloue le contexte pour chaque VU, et c'est la qu'il mourait.

set -uo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VUS="${1:-25}"
DUREE="${2:-30s}"
BASE_URL="${BASE_URL:-http://backend:8000/api/v1}"
RESEAU="${RESEAU:-onec_smart_default}"
NOM="k6-mesure-memoire-$$"

echo "Generateur k6 — $VUS VU pendant $DUREE (flux brut desactive)"
echo

docker run --rm -d --name "$NOM" \
  --network "$RESEAU" \
  -v "$ICI/../k6:/scripts" -w /scripts \
  grafana/k6 run \
  -e "BASE_URL=$BASE_URL" -e "VUS=$VUS" -e "DURATION=$DUREE" -e "RAMP=5s" \
  journeys.js > /dev/null 2>&1

MAX_MO=0
ECHANTILLONS=0
while docker ps --format '{{.Names}}' | grep -q "^${NOM}$"; do
  BRUT="$(docker stats --no-stream --format '{{.MemUsage}}' "$NOM" 2>/dev/null | awk '{print $1}')"
  if [ -n "$BRUT" ]; then
    MO="$(python3 -c "
v = '$BRUT'.strip()
u = ''.join(c for c in v if c.isalpha())
n = float(''.join(c for c in v if c.isdigit() or c == '.') or 0)
print(int(n * {'GiB': 1024, 'MiB': 1, 'KiB': 1/1024, 'B': 1/1048576}.get(u, 1)))
" 2>/dev/null || echo 0)"
    if [ "${MO:-0}" -gt "$MAX_MO" ]; then MAX_MO="$MO"; fi
    ECHANTILLONS=$((ECHANTILLONS + 1))
    printf '\r  echantillon %-4s  courant %-6s Mo  pic %s Mo   ' "$ECHANTILLONS" "$MO" "$MAX_MO"
  fi
done

echo
echo
echo "  Pic memoire du generateur : ${MAX_MO} Mo  ($ECHANTILLONS echantillons)"
echo
echo "  Rappel : la VM dispose de $(free -m | awk '/^Mem:/{print $2}') Mo au total,"
echo "  dont $(free -m | awk '/^Mem:/{print $7}') Mo disponibles a l'instant."
echo "  Le backend seul en occupe ~1500 Mo a 4 workers."
