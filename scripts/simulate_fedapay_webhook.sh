#!/usr/bin/env bash
set -euo pipefail

SLUG="${1:-}"
ADMIN_EMAIL="${2:-}"
BILLING_MONTHS="${3:-1}"
REFERENCE="${4:-}"

if [[ -z "${SLUG}" || -z "${ADMIN_EMAIL}" ]]; then
  echo "Usage: $0 <slug> <admin_email> [billing_months] [reference]" >&2
  exit 1
fi

if [[ -z "${REFERENCE}" ]]; then
  REFERENCE="TEST-${SLUG}-$(date +%s)"
fi

ORG_NAME="Conseil Provincial ${SLUG}"

docker compose exec -T db psql -U app -d onec_cpk <<SQL
WITH upsert_org AS (
  INSERT INTO organisations (nom, slug, email_contact, status_abonnement, is_active, plan_type, limite_utilisateurs, devise_preferee)
  SELECT '${ORG_NAME}', '${SLUG}', '${ADMIN_EMAIL}', 'PENDING_ACTIVATION', false, 'PENDING', 10, 'CDF'
  WHERE NOT EXISTS (SELECT 1 FROM organisations WHERE slug='${SLUG}')
  RETURNING id
)
SELECT id FROM upsert_org
UNION ALL
SELECT id FROM organisations WHERE slug='${SLUG}'
LIMIT 1;
SQL

docker compose exec -T db psql -U app -d onec_cpk <<SQL
INSERT INTO organisation_settings (organisation_id, max_users, storage_quota_mb, is_ai_enabled, is_mobile_money_enabled, is_audit_logs_enabled, fiscal_year_start, currency_code)
SELECT id, 10, 1024, true, true, true, 1, 'CDF'
FROM organisations
WHERE slug='${SLUG}'
  AND NOT EXISTS (
    SELECT 1 FROM organisation_settings
    WHERE organisation_id = (SELECT id FROM organisations WHERE slug='${SLUG}')
  );
SQL

docker compose exec -T db psql -U app -d onec_cpk <<SQL
INSERT INTO tenant_signups (organisation_name, slug, admin_email, plan_id, organisation_id, billing_months, status, reference)
SELECT '${ORG_NAME}', '${SLUG}', '${ADMIN_EMAIL}', (SELECT id FROM plans ORDER BY id LIMIT 1),
       (SELECT id FROM organisations WHERE slug='${SLUG}'),
       ${BILLING_MONTHS}, 'pending_payment', '${REFERENCE}'
WHERE NOT EXISTS (SELECT 1 FROM tenant_signups WHERE reference='${REFERENCE}');
SQL

docker compose exec -T api curl -sS -X POST http://localhost:8000/api/v1/webhooks/fedapay \
  -H "Content-Type: application/json" \
  -d "{\"event\":\"transaction.approved\",\"entity\":{\"id\":\"SIM-${REFERENCE}\",\"amount\":500000,\"customer\":{\"email\":\"${ADMIN_EMAIL}\"},\"metadata\":{\"reference\":\"${REFERENCE}\"}}}"

echo ""
echo "Référence: ${REFERENCE}"
echo "Admin: ${ADMIN_EMAIL}"
TEMP_PASSWORD="$(docker compose exec -T db psql -U app -d onec_cpk -t -c "select hashed_password from users where email='${ADMIN_EMAIL}' order by created_at desc limit 1;" | tr -d '[:space:]')"
if [[ -n "${TEMP_PASSWORD}" ]]; then
  echo "Mot de passe temporaire: (généré dans le webhook UI uniquement)"
else
  echo "Mot de passe temporaire: introuvable"
fi
