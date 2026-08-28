#!/usr/bin/env bash
# Sonde du chemin d'ECRITURE : un POST de chaque type, hors charge.
#
#   ./sonde_ecriture.sh
#
# Pourquoi elle existe : la campagne du 27/08 a mesure 0 ecriture reussie sans
# que rien ne le signale — les 402 se noyaient dans un taux d'echec global lu
# comme de la saturation. Cette sonde repond a une seule question, avant toute
# campagne : le chemin d'ecriture est-il seulement ouvert ?
#
# 201 ou 409 = ouvert (409 = doublon, comportement metier attendu).
# 402         = abonnement du tenant inactif, AUCUNE ecriture ne passera.
# 403         = permission manquante sur l'utilisateur de test.
# 422         = charge utile refusee (souvent le jeu de donnees, pas l'appli).

set -uo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_URL="${BASE_URL:-http://localhost:8000/api/v1}"
CONTEXTE="${CONTEXTE:-$ICI/../k6/context.json}"

if [ ! -f "$CONTEXTE" ]; then
  echo "ERREUR : $CONTEXTE absent. Executez seed/mint_tokens.py." >&2
  exit 1
fi

mapfile -t CTX < <(python3 -c "
import json
d = json.load(open('$CONTEXTE'))
u = [x for x in d['utilisateurs'] if x.get('plein_droit')] or d['utilisateurs']
print(u[0]['token'])
print(d['organisation_id'])
print((d['postes_recette'] or [{}])[0].get('id', ''))
print((d['services'] or [{}])[0].get('id', ''))
")
JETON="${CTX[0]}"; ORG="${CTX[1]}"; POSTE="${CTX[2]}"; SERVICE="${CTX[3]}"
MARQUE="sonde-$(date +%s)-$RANDOM"

appel() {
  local nom="$1" chemin="$2" corps="$3"
  local out
  out="$(curl -s -o /tmp/sonde_corps.$$ -w '%{http_code}' -m 60 -X POST \
    -H "Authorization: Bearer $JETON" -H "X-Tenant-ID: $ORG" \
    -H "Content-Type: application/json" \
    -d "$corps" "$BASE_URL$chemin" 2>/dev/null)"
  local verdict
  case "$out" in
    201|200|409) verdict="OUVERT" ;;
    402) verdict="BLOQUE — abonnement du tenant" ;;
    403) verdict="BLOQUE — permission" ;;
    422) verdict="REFUSE — charge utile" ;;
    *)   verdict="?" ;;
  esac
  printf '%-22s %-5s %s\n' "$nom" "$out" "$verdict"
  if [ "$out" != "201" ] && [ "$out" != "409" ] && [ "$out" != "200" ]; then
    sed -e 's/^/                             /' -e 's/\(.\{150\}\).*/\1…/' /tmp/sonde_corps.$$ 2>/dev/null | head -2
  fi
  rm -f /tmp/sonde_corps.$$
}

echo "Tenant $ORG — sonde d'ecriture (aucune concurrence)"
printf '%-22s %-5s %s\n' "operation" "code" "verdict"
echo "----------------------------------------------------------------"

appel "encaissement" "/encaissements" "{
  \"type_client\": \"autre\",
  \"client_nom\": \"Client $MARQUE\",
  \"libelle\": \"Encaissement sonde\",
  \"montant\": 1234.00,
  \"montant_total\": 1234.00,
  \"mode_paiement\": \"cash\",
  \"canal\": \"CAISSE\",
  \"montant_paye\": 1234.00,
  \"montant_percu\": 1234.00,
  \"devise_perception\": \"USD\",
  \"statut_paiement\": \"complet\",
  \"budget_poste_id\": \"$POSTE\",
  \"service_id\": \"$SERVICE\"
}"

POSTE_DEP="$(python3 -c "
import json
d = json.load(open('$CONTEXTE'))
print((d['postes_depense'] or [{}])[0].get('id', ''))
")"

appel "requisition" "/requisitions" "{
  \"objet\": \"Depense sonde $MARQUE\",
  \"mode_paiement\": \"cash\",
  \"type_requisition\": \"classique\",
  \"montant_total\": \"2000.00\",
  \"devise\": \"USD\",
  \"service_id\": \"$SERVICE\",
  \"a_valoir\": false,
  \"decaissement_progressif\": false,
  \"lignes\": [
    {\"budget_poste_id\": \"$POSTE_DEP\", \"rubrique\": \"Sonde\",
     \"description\": \"Ligne sonde $MARQUE\", \"quantite\": 1,
     \"montant_unitaire\": \"2000.00\", \"montant_total\": \"2000.00\",
     \"devise\": \"USD\"}
  ]
}"

echo
echo "201/409 = le chemin d'ecriture est ouvert. Tout autre code : la campagne"
echo "mesurera des echecs qui n'ont rien a voir avec la charge."
