#!/usr/bin/env bash
# Cout d'UNE requete, sans concurrence, a volume reel.
#
#   ./cout_unitaire.sh [repetitions]
#
# Pourquoi cette mesure existe : les campagnes k6 melangent deux effets, le
# cout intrinseque d'une requete et la contention entre requetes. Quand le banc
# lui-meme sature (OOM du generateur, CPU partage), on ne sait plus lequel on
# regarde. Ici il n'y a qu'un seul appel a la fois : ce qui reste est le cout
# incompressible de l'endpoint sur le volume actuel.
#
# La lecture qui compte : un endpoint deja hors budget A UN SEUL UTILISATEUR ne
# sera sauve par aucun reglage de workers ni de pool. C'est ce qui separe « il
# faut optimiser la requete » de « il faut dimensionner le service ».
#
# La premiere repetition est ignoree (cache froid : PostgreSQL, cache d'auth,
# cache de permissions). Les suivantes mesurent le regime chaud.

set -uo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_URL="${BASE_URL:-http://localhost:8000/api/v1}"
CONTEXTE="${CONTEXTE:-$ICI/../k6/context.json}"
REPETITIONS="${1:-4}"

if [ ! -f "$CONTEXTE" ]; then
  echo "ERREUR : $CONTEXTE absent. Executez seed/mint_tokens.py." >&2
  exit 1
fi

lire_contexte() {
  python3 -c "
import json, sys
d = json.load(open('$CONTEXTE'))
u = [x for x in d['utilisateurs'] if x.get('plein_droit')] or d['utilisateurs']
print(u[0]['token'])
print(d['organisation_id'])
print(d['annee'])
"
}

mapfile -t CTX < <(lire_contexte)
JETON="${CTX[0]}"
ORG="${CTX[1]}"
ANNEE="${CTX[2]}"

# Les routes du parcours k6 qui pesent le plus, plus l'authentification qui est
# sur le chemin de 100 % du trafic.
ROUTES=(
  "auth_me|/auth/me"
  "permissions_menu|/permissions/menu"
  "dashboard_stats|/dashboard/stats?annee=$ANNEE&devise=USD"
  "budget_summary|/budget/summary"
  "tresorerie_soldes|/tresorerie/soldes"
  "encaissements_p1|/encaissements?page=1&page_size=25"
  "requisitions_p1|/requisitions?page=1&page_size=25"
  "sorties_fonds_p1|/sorties-fonds?page=1&page_size=25"
  "experts_liste|/experts-comptables?page=1&page_size=25"
  "budget_postes_tree|/budget/postes/tree?annee=$ANNEE"
  "reports_summary|/reports/summary?annee=$ANNEE"
)

printf '%-24s %10s %10s %10s %8s\n' "route" "froid" "chaud_moy" "chaud_max" "statut"
printf '%s\n' "--------------------------------------------------------------------"

for entree in "${ROUTES[@]}"; do
  nom="${entree%%|*}"
  chemin="${entree#*|}"
  froid=""
  chauds=()
  statut=""
  for ((i = 0; i <= REPETITIONS; i++)); do
    reponse="$(curl -s -o /dev/null -w '%{time_total} %{http_code}' -m 120 \
      -H "Authorization: Bearer $JETON" \
      -H "X-Tenant-ID: $ORG" \
      "$BASE_URL$chemin" 2>/dev/null)"
    duree="${reponse%% *}"
    statut="${reponse##* }"
    ms="$(python3 -c "print(f'{float(\"$duree\")*1000:.0f}')" 2>/dev/null || echo 0)"
    if [ "$i" -eq 0 ]; then
      froid="$ms"
    else
      chauds+=("$ms")
    fi
  done
  moy="$(printf '%s\n' "${chauds[@]}" | python3 -c "
import sys
v=[int(x) for x in sys.stdin.read().split()]
print(sum(v)//len(v) if v else 0)")"
  max="$(printf '%s\n' "${chauds[@]}" | sort -n | tail -1)"
  printf '%-24s %9sms %9sms %9sms %8s\n' "$nom" "$froid" "$moy" "$max" "$statut"
done

echo
echo "Aucune concurrence : un seul appel a la fois. Un chiffre eleve ici est un"
echo "cout intrinseque, que ni les workers ni le pool ne peuvent corriger."
