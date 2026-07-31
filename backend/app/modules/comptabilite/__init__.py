"""Module Comptabilité — ONEC Smart.

Comptabilité en partie double, paramétrable et multi-référentiel
(SYSCOHADA révisé, SYSCEBNL, PCG, ONG, plan personnalisé).

Principes structurants :
- Aucun numéro de compte codé en dur : tout passe par le paramétrage en base.
- Aucune suppression physique : annulation / contre-passation / historisation.
- Les écritures générées automatiquement le sont dans la MÊME transaction que
  l'opération métier d'origine (cohérence ACID).
"""
