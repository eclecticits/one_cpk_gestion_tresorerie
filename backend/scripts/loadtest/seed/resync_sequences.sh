#!/usr/bin/env bash
# Resynchronise les compteurs de numeros de documents avec le volume deja seme.
#
#   ./resync_sequences.sh [slug]           # defaut : load-test-20260803
#
# Pourquoi : seed_volume.py insere les requisitions/encaissements en masse avec
# leurs numeros, mais n'avance pas `document_sequences`. Resultat mesure sur le
# tenant de charge :
#
#   service LOAD    compteur 574   alors que le numero 3057 est deja pris
#   services LOAD01..LOAD07        AUCUNE ligne de sequence, ~2400 numeros pris
#
# La premiere creation repart donc sur un numero existant et echoue :
#
#   UniqueViolationError: duplicate key value violates unique constraint
#   "uq_requisitions_org_numero"
#
# Consequence pour la campagne : `requisition_create` renvoie 500 quoi qu'il
# arrive, et le chemin d'ecriture — objet de la branche — n'est jamais mesure.
#
# GARDE-FOU : n'agit que sur un slug commencant par « load-test ».
# Idempotent : rejouable sans effet si les compteurs sont deja au-dela.

set -euo pipefail

SLUG="${1:-load-test-20260803}"
CONTENEUR_DB="${CONTENEUR_DB:-onec_smart-db-1}"

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

echo "Organisation « $SLUG » (id $ID_ORG)"
echo
echo "--- compteurs REQ avant ---"
psql_t -c "\"
SELECT s.code AS service,
       COALESCE(ds.counter::text, 'ABSENT') AS compteur,
       COALESCE(MAX(split_part(r.numero_requisition, '-', 4))::int, 0) AS max_utilise
FROM services s
LEFT JOIN document_sequences ds
       ON ds.service_id = s.id AND ds.doc_type = 'REQ'
      AND ds.year = EXTRACT(year FROM now())::int AND ds.tenant_id = $ID_ORG
LEFT JOIN requisitions r
       ON r.service_id = s.id AND r.organisation_id = $ID_ORG
      AND r.numero_requisition LIKE 'REQ-%-' || EXTRACT(year FROM now())::int || '-%'
WHERE s.organisation_id = $ID_ORG
GROUP BY s.code, ds.counter ORDER BY s.code\""

# Deux cas a couvrir, et le second est celui qui casse le plus discretement :
#   1. la ligne existe mais son compteur est en retard  -> UPDATE
#   2. la ligne n'existe pas du tout                    -> INSERT
# Un simple UPDATE ne traiterait que le premier ; les services LOAD01..LOAD07
# resteraient sans sequence et repartiraient de 1 a la premiere ecriture.
psql_t -c "\"
WITH utilises AS (
  SELECT r.service_id,
         EXTRACT(year FROM now())::int AS annee,
         MAX(split_part(r.numero_requisition, '-', 4))::int AS max_num
  FROM requisitions r
  WHERE r.organisation_id = $ID_ORG
    AND r.numero_requisition LIKE 'REQ-%-' || EXTRACT(year FROM now())::int || '-%'
    AND r.service_id IS NOT NULL
  GROUP BY r.service_id
)
INSERT INTO document_sequences (tenant_id, doc_type, year, service_id, counter)
SELECT $ID_ORG, 'REQ', u.annee, u.service_id, u.max_num
FROM utilises u
-- Index unique PARTIEL (uq_docseq_service ... WHERE service_id IS NOT NULL) :
-- l'inference ON CONFLICT doit reprendre la clause WHERE, sinon PostgreSQL
-- repond « no unique or exclusion constraint matching ».
ON CONFLICT (doc_type, year, tenant_id, service_id) WHERE service_id IS NOT NULL
DO UPDATE SET counter = GREATEST(document_sequences.counter, EXCLUDED.counter)\"" > /dev/null

echo
echo "--- compteurs REQ apres ---"
psql_t -c "\"
SELECT s.code AS service,
       COALESCE(ds.counter::text, 'ABSENT') AS compteur,
       COALESCE(MAX(split_part(r.numero_requisition, '-', 4))::int, 0) AS max_utilise
FROM services s
LEFT JOIN document_sequences ds
       ON ds.service_id = s.id AND ds.doc_type = 'REQ'
      AND ds.year = EXTRACT(year FROM now())::int AND ds.tenant_id = $ID_ORG
LEFT JOIN requisitions r
       ON r.service_id = s.id AND r.organisation_id = $ID_ORG
      AND r.numero_requisition LIKE 'REQ-%-' || EXTRACT(year FROM now())::int || '-%'
WHERE s.organisation_id = $ID_ORG
GROUP BY s.code, ds.counter ORDER BY s.code\""

echo
echo "Verifier avec : observe/sonde_ecriture.sh (201 attendu sur requisition)."
