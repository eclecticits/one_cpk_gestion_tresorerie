# Architecture détaillée (SaaS)

```
   Utilisateurs (cpk.onecmind.cd, cn.onecmind.cd, ...)             Super Admin (console SaaS)
   ┌───────────────────────────────────────────────┐             ┌────────────────────────┐
   │  Web / Mobile                                 │             │ Monitoring / Reporting │
   └──────────────┬────────────────────────────────┘             └────────────┬───────────┘
                  │                                                        │
                  ▼                                                        ▼
         ┌────────────────────┐                                  ┌───────────────────────┐
         │  Nginx (wildcard)  │                                  │   FastAPI (admin)     │
         │  *.onecmind.cd     │                                  │   /super-admin/*      │
         └───────┬────────────┘                                  └───────────┬───────────┘
                 │                                                       APIs
                 │                                     ┌────────────────────┴────────────────────┐
                 ▼                                     ▼                                         ▼
      ┌─────────────────────┐              ┌───────────────────────┐                 ┌────────────────────┐
      │ Frontend React/Vite │              │ FastAPI (tenant)       │                 │  Scheduler Jobs    │
      │ - détecte slug       │────────────▶│ - JWT org_id/org_uuid  │                 │  - Monthly report  │
      │ - branding pré-login │             │ - hard enforcement 402 │                 │  - Weekly report   │
      └─────────┬───────────┘              └───────────┬───────────┘                 └────────────────────┘
                │                                      │
                │                                      ▼
                │                           ┌───────────────────────┐
                │                           │ PostgreSQL            │
                │                           │ - organisations       │
                │                           │ - tables métier       │
                │                           │   + organisation_id   │
                │                           │ - system_events       │
                │                           │ - saas_platform_metrics (MV)
                │                           └───────────────────────┘
                │
                ▼
      ┌─────────────────────┐
      │ Storage local        │
      │ uploads/tenants/{uuid}
      └─────────────────────┘
```

## Flux principaux

1) **Pré‑login (white‑label)**
- Le frontend détecte le slug via sous‑domaine.
- Appel public: `/api/v1/organisation/public/{slug}`
- Affichage logo + nom tenant.

2) **Isolation multi‑tenant**
- JWT contient `org_id` + `org_uuid`.
- Filtrage automatique ORM + org_id sur toutes les tables métier.

3) **Console Super Admin**
- KPI globaux et anomalies.
- Vue matérialisée `saas_platform_metrics` + refresh.
- Impersonation journalisée dans `system_events`.

4) **Reporting**
- Génération PDF mensuelle consolidée.
- Scheduler (cron) + envoi email.
