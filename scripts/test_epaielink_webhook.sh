#!/usr/bin/env bash
set -euo pipefail

API_BASE="http://localhost:8000/api/v1"
INTERNAL_KEY="CHANGE_ME_INTERNAL_KEY"
EPAIELINK_SECRET="CHANGE_ME_WEBHOOK_SECRET"

TENANT_ID="cpk-lualaba"
AMOUNT="150.0"
CURRENCY="USD"

# 1) Créer la session
session_json=$(curl -s -X POST "$API_BASE/payments/create-session" \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: $INTERNAL_KEY" \
  -d "{\"tenant_id\":\"$TENANT_ID\",\"amount\":$AMOUNT,\"currency\":\"$CURRENCY\",\"success_url\":\"http://localhost:5173/settings?status=success\",\"cancel_url\":\"http://localhost:5173/settings?status=cancel\"}")

session_id=$(echo "$session_json" | python - <<'PY'
import json,sys
print(json.load(sys.stdin)["transaction_id"])
PY
)

echo "Session ID: $session_id"

# 2) Payload webhook
payload=$(cat <<JSON
{"status":"SUCCESS","amount":$AMOUNT,"currency":"$CURRENCY","fees":0.5,"payment_method":"VISA","operator_reference":"EP-TEST-123","external_reference":"$session_id","reference":"$session_id","phone":"+243812345678"}
JSON
)

# 3) Signature HMAC
signature=$(printf "%s" "$payload" | openssl dgst -sha256 -hmac "$EPAIELINK_SECRET" -hex | sed 's/^.* //')

# 4) Appel webhook
curl -i -X POST "$API_BASE/payments/webhook/epaielink" \
  -H "Content-Type: application/json" \
  -H "x-epaielink-signature: $signature" \
  -d "$payload"

echo ""
echo "Attente de confirmation..."
sleep 2

# 5) Vérifier le statut côté session
status_json=$(curl -s "$API_BASE/payments/session/$session_id")
status=$(echo "$status_json" | python - <<'PY'
import json,sys
data=json.load(sys.stdin)
print((data.get("status") or "").lower())
PY
)

echo "Statut session: ${status:-inconnu}"
if [ "$status" = "success" ]; then
  echo "OK: paiement confirmé"
else
  echo "KO: paiement non confirmé"
fi
