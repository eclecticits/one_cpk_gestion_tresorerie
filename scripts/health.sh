#!/usr/bin/env sh
set -e

API_URL=${API_URL:-http://localhost:8000}
HEALTH_PATH="/api/v1/health"

check_url() {
  url="$1$HEALTH_PATH"
  status=$(curl -s -o /dev/null -w "%{http_code}" "$url" || true)
  if [ "$status" = "200" ]; then
    echo "[health] OK: $url (status $status)"
    return 0
  fi
  echo "[health] FAIL: $url (status $status)"
  return 1
}

echo "[health] Checking localhost first..."
if check_url "$API_URL"; then
  exit 0
fi

echo "[health] localhost failed, trying Windows host IP from /etc/resolv.conf"
WIN_IP=$(grep -m1 nameserver /etc/resolv.conf | awk '{print $2}')
if [ -n "$WIN_IP" ]; then
  if check_url "http://$WIN_IP:8000"; then
    exit 0
  fi
fi

echo "[health] FAIL: could not reach API health endpoint" >&2
exit 1
