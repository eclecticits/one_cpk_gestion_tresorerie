# Dev Notes

## WSL <-> Docker Desktop (Windows host loopback)

If the API works in the Windows browser (example: http://127.0.0.1:8000/api/v1/health) but fails from WSL with:

```
curl: (7) Failed to connect to localhost port 8000
```

That is expected: WSL localhost is not the same as Windows localhost when Docker Desktop runs on Windows.

Use the Windows host IP from WSL:

```sh
WIN_IP=$(grep -m1 nameserver /etc/resolv.conf | awk '{print $2}')
curl -i "http://$WIN_IP:8000/api/v1/health"
```

Quick port test:

```sh
nc -vz "$WIN_IP" 8000
```

Notes:
- Keep `VITE_API_BASE_URL=http://localhost:8000/api/v1` for the browser (Windows) if it already works.
- Avoid `host.docker.internal` in WSL (often not resolved by default).
- If needed, add a manual mapping in `/etc/hosts` using the `WIN_IP` above.

Optional helper script:

```sh
./scripts/health.sh
```

It tries `localhost` first, then falls back to the Windows host IP.

## DEV: Vite proxy + relative API base

To avoid localhost/127.0.0.1/WIN_IP cookie issues in dev, use same-origin:

- Browser -> Vite on `http://localhost:5173`
- Vite proxies `/api` -> backend `http://localhost:8000`

Config:
- `frontend/vite.config.ts` proxy `/api`
- `frontend/.env.local` uses `VITE_API_BASE_URL=/api/v1`

This keeps cookies same-origin and avoids CORS in development.
