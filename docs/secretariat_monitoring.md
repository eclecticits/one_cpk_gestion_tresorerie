# Secretariat Monitoring

## Events to monitor

- backend errors in Secretariat routes and services
- OAuth failures
- IA failures
- permission-denied actions
- rejected validations
- validations pending too long
- overdue Agenda items
- audit log anomalies
- cross-tenant access attempts
- Gmail draft creation failures

## Suggested signals

- count of 4xx/5xx on `/api/v1/secretariat/*`
- count of `approval_rejected`
- count of `approval_execution_blocked`
- count of `agenda_transition_blocked`
- count of `oauth` expired or disconnected states
- count of `OPENAI_API_KEY absent` responses
- count of cross-tenant 404s / 403s on Secretariat objects

## Notes

- keep logs free of secrets and object payloads
- alert on repeated validation failures
- alert on repeated OAuth reconnect prompts
- alert on Agenda overdue growth

