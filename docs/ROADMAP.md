# Roadmap technique

## PERF-001 - Validation de la capacite a 500 utilisateurs simultanes

Statut: Suspendu temporairement

Priorite: Elevee avant deploiement a grande echelle

Contexte:

- Phase 3 cloturee temporairement le 2026-08-03.
- Configuration validee: 1 worker, pool SQLAlchemy `10 + 10`.
- Capacite actuelle mesuree: charge interne moderee, jusqu'a 25 utilisateurs avec p95 inferieur a 2 secondes dans la campagne Phase 3.
- Conclusion officielle: ONEC Smart n'est pas encore pret pour 500 utilisateurs simultanes.

Travaux restant a realiser:

- Optimiser les endpoints de creation.
- Reduire encore le nombre de requetes SQL.
- Reduire le temps de detention des connexions.
- Optimiser les rapports a froid.
- Completer l'analyse avec `EXPLAIN ANALYZE`.
- Ajouter uniquement des index justifies par les plans.
- Tester avec deux workers apres stabilisation a un worker.
- Tester les imports et exports concurrents.
- Tester le frontend sur Chrome et Edge.
- Executer un test d'endurance.
- Reprendre la montee progressive jusqu'a 500 utilisateurs.
- Mettre en place le monitoring de production.
