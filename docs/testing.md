# Testing

This repository uses a dedicated PostgreSQL database for backend tests.

## Test database

Create a separate database and user, then point the test runner to it with `TEST_DATABASE_URL`.
In the current Docker Compose setup, the PostgreSQL service is reached from the backend container as `db:5432`.
Run the DB-backed tests inside the backend container.

Never use `onec_cpk` as `TEST_DATABASE_URL`.
`TEST_DATABASE_URL` is destructive by design: the pytest fixtures may drop and recreate the `public` schema.
The test database must be separate from the legitimate development database.

```bash
docker compose exec -T db psql -U christian -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='onec_tresorerie_test';"
docker compose exec -T db psql -U christian -d postgres -c "CREATE DATABASE onec_tresorerie_test OWNER christian;" 
docker compose exec -T db psql -U christian -d onec_tresorerie_test -c "select current_database(), current_user;"
export TEST_DATABASE_URL="postgresql+asyncpg://christian:kncd@db:5432/onec_tresorerie_test"
```

If the first command returns `1`, the database already exists and the `CREATE DATABASE` command should be skipped.

You can also copy `backend/.env.test.example` and adapt it to your local environment.

## Migrations

The test fixtures create the schema from SQLAlchemy metadata after dropping the `public` schema.
If you want to verify the Alembic state on the test database first, run:

```bash
cd backend
python -m alembic upgrade head
python -m alembic heads
```

## Run tests

### ⚠️ The `backend` container does not mount the source tree

`docker-compose.yml` gives the `backend` service a single volume, for uploads.
Its `/app` is therefore the **copy baked into the image at build time**, not the
working tree. `docker compose exec backend python -m pytest` runs whatever the
image contains — it can report a green suite while the code you just edited is
broken, and it can report failures that no longer exist in your files. It also
depends on `pip install pytest` having been run by hand inside the live
container, which the image itself does not carry.

Bind-mount the working tree instead. Build a test image once (the backend image
plus the dev requirements):

```bash
printf 'FROM onec_smart-backend\nUSER root\nCOPY requirements-dev.txt /tmp/requirements-dev.txt\nENV HOME=/tmp\nRUN pip install --no-cache-dir -r /tmp/requirements-dev.txt\n' > /tmp/Dockerfile.test
docker build -f /tmp/Dockerfile.test -t onec_smart-backend-test backend
```

Then run the suite against the files on disk:

```bash
docker run --rm --network onec_smart_default --env-file .env \
  -v "$PWD/backend:/app" -v "$PWD/attendance-agent:/attendance-agent" \
  -e TEST_DATABASE_URL="postgresql+asyncpg://christian:kncd@db:5432/onec_tresorerie_test" \
  -e HOME=/tmp -w /app --entrypoint python onec_smart-backend-test -m pytest -q
```

`--entrypoint python` matters: the image's entrypoint runs `alembic upgrade` on
`DATABASE_URL` — the development database — before starting the API. A test run
has no business migrating it.

`attendance-agent` is mounted because `tests/conftest.py` puts it on
`sys.path`; without it, two test files fail to collect.

Rebuild the test image whenever `requirements-dev.txt` changes.

### Inside the running container (stale code — see the warning above)

Run the Secretariat backend tests:

```bash
cd backend
docker compose exec -T backend env TEST_DATABASE_URL="postgresql+asyncpg://christian:kncd@db:5432/onec_tresorerie_test" python -m pytest -q tests/test_secretariat_module.py
```

Run the full backend suite:

```bash
cd backend
docker compose exec -T backend env TEST_DATABASE_URL="postgresql+asyncpg://christian:kncd@db:5432/onec_tresorerie_test" python -m pytest -q
```

## Notes

- Do not point `TEST_DATABASE_URL` to `onec_cpk`.
- Do not point `TEST_DATABASE_URL` to the production database.
- Keep `DATABASE_URL` on the legitimate development database `onec_cpk` outside the test profile.
- The test database is destructive by design: the fixture drops and recreates the `public` schema at session start.
- If `TEST_DATABASE_URL` is missing, the suite skips the DB-backed tests with a clear message from `backend/tests/conftest.py`.
- If PostgreSQL is not reachable from the backend container, the expected host in Docker Compose is `db:5432`.
- If you run tests from the host instead of Docker, use the exposed port configured in `docker-compose.yml` instead of `db:5432`.
