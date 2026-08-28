#!/usr/bin/env bash
# Redonne de la marge budgetaire aux postes de depense du tenant de charge.
#
#   ./recharger_budget_test.sh [slug]      # defaut : load-test-20260803
#
# Pourquoi : seed_volume.py seme 60 000 requisitions qui ENGAGENT du budget,
# sans augmenter `montant_prevu` en face. Etat mesure sur le tenant de charge :
#
#   DEPENSE : 226 postes, prevu moyen 253 319, engage moyen 715 950
#             -> 225 postes sur 226 saturés
#
# Toute creation de requisition est alors refusee par la regle metier :
#
#   400 {"detail":"Dépassement budgétaire: disponible -438390.65, demandé 2000.00"}
#
# Ce 400 est un comportement CORRECT de l'application. Mais il rend le chemin
# d'ecriture intestable : la campagne mesure un refus metier, pas de la
# contention. On ne desactive pas la regle — on donne au jeu de test le budget
# qu'il aurait du avoir.
#
# GARDE-FOU : n'agit que sur un slug commencant par « load-test ».
# Idempotent : recalcule la marge a partir de l'engage courant.

set -euo pipefail

SLUG="${1:-load-test-20260803}"
CONTENEUR_DB="${CONTENEUR_DB:-onec_smart-db-1}"
# Marge visee par poste. Large devant ce qu'une campagne peut engager : a
# 25 VU pendant 10 min, le scenario requisition cree au plus quelques centaines
# de lignes a ~20 000 l'unite.
MARGE="${MARGE:-100000000}"

if [[ "$SLUG" != load-test* ]]; then
  echo "REFUS : « $SLUG » n'est pas un tenant de test." >&2
  exit 1
fi

psql_t() {
  docker exec "$CONTENEUR_DB" sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" $*"
}

ID_ORG="$(psql_t -At -c "\"SELECT id FROM organisations WHERE slug = '$SLUG'\"")"
if [ -z "$ID_ORG" ]; then
  echo "REFUS : aucune organisation de slug « $SLUG »." >&2
  exit 1
fi

echo "Organisation « $SLUG » (id $ID_ORG) — marge visee par poste : $MARGE"
echo
echo "--- avant ---"
psql_t -c "\"
SELECT type,
       count(*) AS postes,
       count(*) FILTER (WHERE montant_prevu - montant_engage <= 0) AS satures
FROM budget_postes WHERE organisation_id = $ID_ORG GROUP BY type ORDER BY type\""

# On releve le prevu au niveau de l'engage constate PLUS la marge : partir de
# l'engage (et non d'une valeur fixe) rend le script rejouable quel que soit ce
# que les campagnes precedentes ont consomme.
psql_t -c "\"
UPDATE budget_postes
SET montant_prevu = COALESCE(montant_engage, 0) + $MARGE
WHERE organisation_id = $ID_ORG
  AND type = 'DEPENSE'
  AND montant_prevu - COALESCE(montant_engage, 0) < $MARGE\"" > /dev/null

echo
echo "--- apres ---"
psql_t -c "\"
SELECT type,
       count(*) AS postes,
       count(*) FILTER (WHERE montant_prevu - montant_engage <= 0) AS satures,
       round(min(montant_prevu - montant_engage)) AS marge_min
FROM budget_postes WHERE organisation_id = $ID_ORG GROUP BY type ORDER BY type\""

echo
echo "Verifier avec : observe/sonde_ecriture.sh (201 attendu sur requisition)."
