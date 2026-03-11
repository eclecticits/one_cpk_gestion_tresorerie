# Architecture ONEC-Mind SaaS

```
                    ┌────────────────────────────┐
                    │        Utilisateurs        │
                    │  cpk.onecmind.cd / cn...   │
                    └─────────────┬──────────────┘
                                  │
                                  ▼
                         ┌────────────────┐
                         │     Nginx      │
                         │ wildcard DNS   │
                         └──────┬─────────┘
                                │
               ┌────────────────┴────────────────┐
               │                                 │
               ▼                                 ▼
     ┌────────────────────┐              ┌────────────────────┐
     │      Frontend      │              │      Backend       │
     │  React + Vite      │              │   FastAPI + JWT    │
     │  Subdomain detect  │              │  Multi-tenant ORM  │
     └─────────┬──────────┘              └─────────┬──────────┘
               │                                  │
               ▼                                  ▼
     ┌────────────────────┐              ┌────────────────────┐
     │  White-label UI    │              │   PostgreSQL       │
     │  logos/devise      │              │ organisations +    │
     └────────────────────┘              │ organisation_id    │
                                         └─────────┬──────────┘
                                                   │
                                                   ▼
                                         ┌────────────────────┐
                                         │  Monitoring SaaS    │
                                         │  View matérialisée  │
                                         │  SystemEvents       │
                                         └────────────────────┘
```

## Flux clés

1) **Connexion**
- Le frontend détecte le tenant via le sous-domaine.
- `/api/v1/organisation/public/{slug}` fournit le nom + logo.
- Login retourne JWT avec `org_id`, `org_uuid`, `plan_status`.

2) **Séparation des données**
- `organisation_id` présent dans toutes les tables métier.
- Filtrage automatique côté ORM + sécurisation JWT.

3) **Super Admin**
- Console SaaS multi-tenant (monitoring, impersonation, reporting).
- Vue matérialisée `saas_platform_metrics`.

4) **Fichiers**
- Stockage local : `uploads/tenants/{org_uuid}/...`.

## Points de sécurité
- Hard enforcement des plans : write = 402 si plan expiré.
- Super Admin invisible des admins tenants.
- Impersonation journalisée (SystemEvents).
