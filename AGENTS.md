# Repository Guidelines

## Project Structure & Module Organization
- `backend/` contains the FastAPI service, SQLAlchemy models, and Alembic migrations (`backend/app`, `backend/alembic`).
- `frontend/` is a Vite + React app with source in `frontend/src` and static assets in `frontend/public`.
- `dist/` and `frontend/dist/` contain built assets; treat them as build outputs unless explicitly updating generated artifacts.
- `docker-compose.yml` defines the local Postgres database and API container wiring.
- `docker-compose.prod.yml` defines the production Docker setup with persistent uploads.

## Build, Test, and Development Commands
- `docker compose up --build` launches Postgres and the API using the settings in `docker-compose.yml`.
- `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` runs the API locally from `backend/` (virtualenv required).
- `npm install` (run in `frontend/`) installs UI dependencies.
- `npm run dev` starts the Vite dev server on port 5173.
- `npm run build` builds the production frontend to `frontend/dist`.
- `npm run preview` serves the production build for local smoke tests.

## Coding Style & Naming Conventions
- Python: follow PEP 8, use type hints where practical, and keep modules organized by feature (`app/api`, `app/models`, `app/schemas`).
- TypeScript/React: 2-space indentation, PascalCase for components (`UserRoleManager.tsx`), camelCase for hooks/utilities (`usePermissions.ts`, `encaissementHelpers.ts`).
- CSS Modules use `ComponentName.module.css` and class names scoped per component.

## Testing Guidelines

### Tests unitaires / intégration (existants)
```bash
# Depuis backend/ avec un virtualenv activé
pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/onec_cpk_test pytest
```

### Tests E2E Phase 1 — via Docker (recommandé)
Les tests E2E utilisent httpx + ASGITransport pour tester la pile FastAPI complète,
avec la vraie base de données (TEST_DATABASE_URL) et Redis mocké.

```bash
# 1. S'assurer que les conteneurs sont démarrés
docker compose up -d

# 2. Lancer les tests E2E dans le conteneur backend
docker compose exec backend sh -c \
  "pip install pytest pytest-asyncio httpx -q && \
   TEST_DATABASE_URL='postgresql+asyncpg://USER:PASS@db:5432/onec_cpk_test' \
   python -m pytest tests/test_health_e2e.py tests/test_auth_flow_e2e.py -v"
```

> Remplacer `USER:PASS` par les vraies valeurs (`POSTGRES_USER`/`POSTGRES_PASSWORD` du `.env`).

### Fichiers de tests E2E (Phase 1)
| Fichier | Couverture |
|---|---|
| `tests/test_health_e2e.py` | `/health`, `/health/live`, `/health/ready` |
| `tests/test_auth_flow_e2e.py` | Login, `/auth/me`, dashboard protégé, refresh token |
| `tests/test_auth_e2e.py` | Cas d'erreur auth (401, 422, 404) |

### Vérifications finales après modification
```bash
docker compose config          # valider la syntaxe docker-compose
docker compose up -d --build   # reconstruire et démarrer
docker compose ps              # vérifier que tous les services sont healthy
curl http://localhost:8000/api/v1/health/ready  # sonde readiness
```

## Commit & Pull Request Guidelines
- This repository does not include Git history in the current workspace, so no commit message convention is available. If contributing, use clear, imperative commit subjects and keep PRs scoped.
- PRs should include a short summary, steps to validate, and screenshots for UI changes.

## Database Migrations
- Alembic migrations in `backend/alembic/versions` are the source of truth for schema changes.
- Keep Alembic revision IDs under 32 characters to satisfy database limits.

## Security & Configuration Tips
- Configure API secrets via environment variables (see `docker-compose.yml`): `DATABASE_URL`, `JWT_SECRET`, and related auth settings.
- Avoid committing real credentials; update placeholders like `CHANGE_ME_SUPER_LONG_RANDOM` and `CHANGE_ME_ONE_TIME` in your local environment.
- Uploads: use `UPLOAD_DIR` to control storage location. For secured serving in production, set `SERVE_UPLOADS_PUBLICLY=false`, set `VITE_SECURE_UPLOADS=true`, and serve files through `GET /api/v1/secure-uploads/...` with Nginx `X-Accel-Redirect` (see `docs/nginx/backend-secure-uploads.conf`).
