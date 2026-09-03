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

### Via Docker (recommandé)

Un service dédié, `backend-tests`, porte la suite. Il n'est pas démarré par
`docker compose up` : il vit sous le profil `test` et ne tourne que le temps
d'une exécution.

```bash
# Toute la suite
docker compose --profile test run --rm backend-tests

# Un fichier, un test, n'importe quel argument pytest
docker compose --profile test run --rm backend-tests pytest tests/test_encaissements.py -q
docker compose --profile test run --rm backend-tests pytest -k fractionnement -q
```

`TEST_DATABASE_URL` est déjà posée par le service, vers une base **dédiée**
(`${POSTGRES_DB}_test`) : le harnais fait `DROP SCHEMA` à chaque session, il ne
doit jamais viser la base applicative. Aucun identifiant à recopier à la main.

Le code et les tests sont montés en direct : éditer puis relancer suffit,
sans rebuild. Un `docker compose --profile test build backend-tests` n'est
nécessaire que si `requirements-dev.txt` change.

Pourquoi un conteneur à part plutôt qu'un `exec` dans `backend` :

- le backend fait tourner 4 workers gunicorn ; y lancer la suite mettait les
  deux en concurrence mémoire et l'OOM-killer emportait le conteneur (code
  137), qui redémarrait aussitôt en emportant pytest avec lui ;
- `tests/` est exclu de l'image applicative (`.dockerignore`) : il fallait l'y
  copier à la main avant chaque exécution ;
- pytest devait être réinstallé après chaque redémarrage, sans garantie de
  version. L'image `tests` les embarque, **épinglées** — `pytest-asyncio` n'est
  pas interchangeable, une version trop ancienne ignore
  `asyncio_default_test_loop_scope` et met tous les teardowns en erreur.

Deux modules ne se collectent pas dans ce conteneur
(`test_attendance_agent_local_queue.py`, `test_hr_attendance_agent_ingestion.py`) :
ils importent `onec_attendance_agent`, qui vit dans `attendance-agent/`, hors de
l'image backend. Les écarter explicitement :

```bash
docker compose --profile test run --rm backend-tests pytest tests/ -q \
  --ignore=tests/test_attendance_agent_local_queue.py \
  --ignore=tests/test_hr_attendance_agent_ingestion.py
```

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
