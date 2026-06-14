# Secretariat Preproduction Checklist

## Database and migrations

- [ ] Alembic head unique
- [ ] Migrations applied on target environment
- [ ] PostgreSQL real tests pass

## Backend tests

- [ ] `pytest -q tests/test_secretariat_module.py -rs`
- [ ] `pytest -q -rs`
- [ ] No unexpected failures

## Frontend

- [ ] `npm run build` passes
- [ ] Secretariat pages load
- [ ] No broken routes or missing permissions

## Permissions and roles

- [ ] Secretariat permissions seeded
- [ ] Secretariat roles created
- [ ] Users assigned to roles
- [ ] Operational roles have no admin permissions

## OAuth and IA

- [ ] Gmail OAuth configured or intentionally disabled
- [ ] `gmail.readonly` and `gmail.compose` are the only scopes used
- [ ] `OPENAI_API_KEY` configured or IA disabled cleanly

## Data security

- [ ] Audit logs verified
- [ ] `file_path` not exposed
- [ ] No `gmail.send`
- [ ] No public file download endpoint
- [ ] No external document sharing

## Operational readiness

- [ ] Backup and restore procedure validated
- [ ] Monitoring thresholds defined
- [ ] Alerts configured for OAuth, IA, approvals, overdue tasks, and tenant access anomalies

