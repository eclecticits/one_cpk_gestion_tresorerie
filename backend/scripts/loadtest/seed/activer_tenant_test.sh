#!/usr/bin/env bash
# Reouvre le chemin d'ECRITURE sur l'organisation de test de charge.
#
#   ./activer_tenant_test.sh [slug]        # defaut : load-test-20260803
#
# Pourquoi : la campagne du 27/08 n'a execute AUCUNE ecriture. L'organisation
# etait `status_abonnement = SUSPENDED` / `is_active = false`, et
# app/api/deps.py:352 refuse alors tout POST/PUT/PATCH/DELETE avec un 402. Les
# 402 se lisaient comme des echecs de charge : 36 des 129 echecs du palier
# 10 VU venaient de la.
#
# GARDE-FOU : ce script n'agit QUE sur un slug commencant par « load-test ».
# Il refuse tout autre tenant, et refuse de tourner si la base ne ressemble pas
# a un environnement de test. Il n'a rien a faire en production.
#
# Idempotent : le rejouer sur un tenant deja actif ne change rien.

set -euo pipefail

SLUG="${1:-load-test-20260803}"
CONTENEUR_DB="${CONTENEUR_DB:-onec_smart-db-1}"
CONTENEUR_REDIS="${CONTENEUR_REDIS:-onec_smart-redis-1}"

if [[ "$SLUG" != load-test* ]]; then
  echo "REFUS : « $SLUG » n'est pas un tenant de test (prefixe attendu : load-test)." >&2
  echo "Ce script ne doit jamais reactiver un abonnement reel." >&2
  exit 1
fi

psql_test() {
  docker exec "$CONTENEUR_DB" sh -c "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -At -c \"$1\""
}

# Deuxieme garde-fou : une base de production contient d'autres organisations
# actives que celles de test. On refuse d'agir si le tenant vise n'existe pas.
ID_ORG="$(psql_test "SELECT id FROM organisations WHERE slug = '$SLUG'")"
if [ -z "$ID_ORG" ]; then
  echo "REFUS : aucune organisation de slug « $SLUG » dans cette base." >&2
  exit 1
fi

echo "Organisation « $SLUG » (id $ID_ORG)"
echo "--- avant ---"
psql_test "SELECT status_abonnement || ' / is_active=' || is_active FROM organisations WHERE id = $ID_ORG"

# L'expiration est repoussee loin : sans cela, si une ligne `subscriptions`
# venait a exister, app/services/billing_guard.py resuspendrait l'organisation
# au prochain passage et la campagne suivante rebasculerait en 402 en silence.
psql_test "UPDATE organisations
           SET status_abonnement = 'ACTIVE',
               is_active = true,
               date_expiration_abonnement = now() + interval '10 years',
               updated_at = now()
           WHERE id = $ID_ORG" > /dev/null

psql_test "UPDATE subscriptions
           SET status = 'ACTIVE',
               current_period_end = now() + interval '10 years',
               updated_at = now()
           WHERE organisation_id = $ID_ORG" > /dev/null

echo "--- apres ---"
psql_test "SELECT status_abonnement || ' / is_active=' || is_active FROM organisations WHERE id = $ID_ORG"

# Le statut est mis en cache dans Redis (app/api/deps.py:190,
# saas_status_cache_ttl_seconds, minimum 30 s). Sans invalidation, le garde
# continue de lire SUSPENDED et les 402 persistent apres la correction.
if docker exec "$CONTENEUR_REDIS" redis-cli DEL "saas:status:$ID_ORG" > /dev/null 2>&1; then
  echo "Cache Redis saas:status:$ID_ORG invalide."
else
  echo "AVERTISSEMENT : cache Redis non invalide — attendre le TTL avant de mesurer." >&2
fi

# DEUXIEME cache, celui qui compte reellement : le contexte d'authentification
# (app/api/deps.py:66, prefixe authctx) embarque `plan_status` PAR UTILISATEUR.
# Tant qu'il n'est pas purge, le garde d'ecriture continue de lire SUSPENDED
# pour chaque utilisateur deja vu, et les 402 persistent apres la correction en
# base — symptome observe le 27/08.
PURGES="$(docker exec "$CONTENEUR_REDIS" sh -c \
  "redis-cli --scan --pattern 'authctx:*' | xargs -r redis-cli DEL" 2>/dev/null || echo 0)"
echo "Contextes d'authentification purges : ${PURGES:-0}"

echo
echo "Verifier avec : observe/sonde_ecriture.sh (201 ou 409 attendu)."

# ATTENTION — troisieme couche, la plus silencieuse : `plan_status` est FIGE
# DANS LE JETON JWT au moment de la frappe (seed/mint_tokens.py:143). Un
# context.json produit alors que le tenant etait suspendu porte
# `plan_status: SUSPENDED` et continue de provoquer des 402 apres cette
# correction — base a jour, Redis vide, et pourtant 402. Il FAUT refrapper :
#
#   docker compose cp seed/mint_tokens.py backend:/app/mint_tokens.py
#   docker compose exec -T backend python /app/mint_tokens.py --out /app/context.json
#   docker compose cp backend:/app/context.json k6/context.json
echo
echo "IMPORTANT : refrapper les jetons — plan_status est fige dans le JWT."
echo "  docker compose exec -T backend python /app/mint_tokens.py --out /app/context.json"
