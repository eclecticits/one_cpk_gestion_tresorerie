# Audit & Contrats API (Dashboard + Reports)

Date: 2026-01-31

## Schéma final (standard)

### Dashboard
Endpoint: `GET /api/v1/dashboard/stats`

Réponse (unique) :
```json
{
  "stats": {
    "total_encaissements_period": 0,
    "total_encaissements_jour": 0,
    "total_sorties_period": 0,
    "total_sorties_jour": 0,
    "solde_period": 0,
    "solde_actuel": 0,
    "solde_jour": 0,
    "requisitions_en_attente": 0,
    "note": "Migration mode: returns zeros if tables are missing"
  },
  "daily_stats": [
    { "date": "2026-01-25", "encaissements": 0, "sorties": 0, "solde": 0 }
  ],
  "period": {
    "start": "2026-01-01",
    "end": "2026-01-31",
    "label": "month"
  }
}
```

### Reports
Endpoint: `GET /api/v1/reports/summary`

Réponse (unique) :
```json
{
  "stats": {
    "totals": { "encaissements_total": 0, "sorties_total": 0, "solde": 0 },
    "breakdowns": {
      "par_statut_paiement": [ { "key": "complet", "count": 0, "total": 0 } ],
      "par_mode_paiement": {
        "encaissements": [ { "key": "cash", "count": 0, "total": 0 } ],
        "sorties": [ { "key": "cash", "count": 0, "total": 0 } ]
      },
      "par_type_operation": [ { "key": "formation", "count": 0, "total": 0 } ],
      "par_statut_requisition": [ { "key": "EN_ATTENTE", "count": 0 } ],
      "requisitions": { "total": 0, "en_attente": 0, "approuvees": 0 }
    },
    "availability": { "encaissements": true, "sorties": true, "requisitions": true }
  },
  "daily_stats": [
    { "date": "2026-01-25", "encaissements": 0, "sorties": 0, "solde": 0 }
  ],
  "period": {
    "start": "2026-01-25",
    "end": "2026-01-31",
    "label": "custom"
  }
}
```

## Endpoints concernés
- `GET /api/v1/dashboard/stats`
- `GET /api/v1/reports/summary`

## Fichiers modifiés
Backend:
- `backend/app/schemas/dashboard.py`
- `backend/app/schemas/reports.py`
- `backend/app/api/v1/endpoints/dashboard.py`
- `backend/app/api/v1/endpoints/reports.py`

Frontend:
- `frontend/src/types/dashboard.ts`
- `frontend/src/types/reports.ts`
- `frontend/src/api/dashboard.ts`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/Dashboard.module.css`
- `frontend/src/pages/Rapports.tsx`

## Compat legacy (temporaire)
- Dashboard: fallback si l’API renvoie l’ancien format (champs racines).
- Reports: fallback si l’API renvoie `totals/breakdowns` sans wrapper `stats`.

TODO: supprimer ces fallbacks après validation prod.

## Tests rapides
### Curl
```bash
# Dashboard
curl -s "http://localhost:8000/api/v1/dashboard/stats?period_type=month&date_debut=2026-01-01&date_fin=2026-01-31" | jq .

# Reports
curl -s "http://localhost:8000/api/v1/reports/summary?date_debut=2026-01-01&date_fin=2026-01-31" | jq .
```

### UI
1) Login admin.
2) Ouvrir “Tableau de bord” : vérifier stats + graphique 7 jours.
3) Ouvrir “Rapports” : générer rapport, vérifier totaux et tableaux.
4) Simuler une erreur API (arrêter backend) : vérifier bannière d’erreur + bouton “Réessayer”.
