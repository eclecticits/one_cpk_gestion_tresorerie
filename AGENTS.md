# Repository Guidelines

## Project Structure & Module Organization
- `backend/` contains the FastAPI service, SQLAlchemy models, and Alembic migrations (`backend/app`, `backend/alembic`).
- `frontend/` is a Vite + React app with source in `frontend/src` and static assets in `frontend/public`.
- `dist/` and `frontend/dist/` contain built assets; treat them as build outputs unless explicitly updating generated artifacts.
- `docker-compose.yml` defines the local Postgres database and API container wiring.

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
- No project-specific test framework or test directories are present. If adding tests, place them alongside features (e.g., `backend/tests/` or `frontend/src/__tests__/`) and document the runner in this file.

## Commit & Pull Request Guidelines
- This repository does not include Git history in the current workspace, so no commit message convention is available. If contributing, use clear, imperative commit subjects and keep PRs scoped.
- PRs should include a short summary, steps to validate, and screenshots for UI changes.

## Database Migrations
- Alembic migrations in `backend/alembic/versions` are the source of truth for schema changes.
- Keep Alembic revision IDs under 32 characters to satisfy database limits.

## Security & Configuration Tips
- Configure API secrets via environment variables (see `docker-compose.yml`): `DATABASE_URL`, `JWT_SECRET`, and related auth settings.
- Avoid committing real credentials; update placeholders like `CHANGE_ME_SUPER_LONG_RANDOM` and `CHANGE_ME_ONE_TIME` in your local environment.
