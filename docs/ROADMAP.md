# Roadmap technique

## PERF-001 - Validation de la capacite a 500 utilisateurs simultanes

Statut: En cours

Priorite: Elevee avant deploiement a grande echelle

Contexte:

- Phase 3 cloturee temporairement le 2026-08-03.
- Phase 4 executee le 2026-08-17, voir
  `docs/PERFORMANCE_WORKER_SCALING_20260817.md`.
- Capacite actuelle mesuree: 100 utilisateurs simultanes avec 3 workers,
  0.26 % d'erreurs et p95 a 1.56 s. Le critere d'entree de la Phase 4 est
  atteint.
- Cause racine identifiee: le worker est limite par le CPU Python, pas par
  PostgreSQL, qui reste inactif sous charge. La regle "ne pas ajouter de worker"
  de la Phase 3 reposait sur une hypothese fausse et a ete levee.
- Debit mesure: environ 19 RPS par worker, croissance quasi lineaire jusqu'a
  3 workers.
- Conclusion officielle: ONEC Smart n'est pas encore valide pour 500
  utilisateurs simultanes.

Travaux restant a realiser, par valeur decroissante:

- Reduire le cout CPU Python par requete, en priorite les 46 % passes dans
  SQLAlchemy (projections de colonnes plutot que chargement d'entites ORM sur
  les endpoints de liste).
- Rejouer la campagne sur un volume de donnees representatif de la production:
  sans cela la projection de capacite n'est pas validee, et c'est le risque
  principal.
- Reduire le middleware par requete (~10 % du CPU): balayage lineaire des
  routes par slowapi, instrumentation prometheus.
- Reduire le nombre de requetes des endpoints de creation et de
  `reports/summary`.
- Valider 200 utilisateurs sur la machine cible, avec le generateur de charge
  sur une machine separee.
- Verifier le budget de connexions `workers x (pool_size + max_overflow)`
  contre `max_connections` de PostgreSQL a chaque changement du nombre de
  workers.
- Tester les imports et exports concurrents.
- Tester le frontend sur Chrome et Edge.
- Executer un test d'endurance.
- Reprendre la montee progressive jusqu'a 500 utilisateurs.
- Mettre en place le monitoring de production.
