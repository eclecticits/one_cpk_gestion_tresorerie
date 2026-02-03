# Import Experts Comptables

## Colonnes attendues (Excel)
Les colonnes doivent correspondre aux modèles existants dans l'UI d'import :

- N° d'ordre
- Dénomination (SEC)
- Noms (EC)
- Raison sociale (SEC)
- N° de téléphone
- E-mail
- Associé gérant (SEC)
- Sexe (EC)
- Cabinet d'attache (en cabinet)
- Nom de l'employeur (salarié)
- NIF (indépendant)

## Normalisation appliquée (backend)
- Toutes les valeurs sont converties en `str(...).strip()`.
- Téléphone (RDC) :
  - "(+243)829000113" -> "+243829000113"
  - "+243829000113" -> "+243829000113"
  - "0829000113" -> "+243829000113" (si longueur 10 et commence par 0)
  - "829000113" -> "+243829000113" (si longueur 9)
  - sinon : téléphone ignoré (None) + erreur douce.
- E-mail : trim + lower. Si format invalide, il est ignoré (None) + erreur douce.

## UPSERT par numero_ordre
- Si `numero_ordre` existe : mise à jour.
- Sinon : création.
- Si `numero_ordre` est vide : ligne ignorée + erreur douce.

## Réponse API (POST /api/v1/experts-comptables/import)
Exemple :

```
{
  "success": true,
  "imported": 12,
  "updated": 3,
  "skipped": 1,
  "total_lignes": 16,
  "errors": [
    {"ligne": 2, "champ": "telephone", "message": "Téléphone invalide (ignoré)"},
    {"ligne": 5, "champ": "email", "message": "Format e-mail invalide"}
  ],
  "import_id": "...",
  "message": "12 expert(s)-comptable(s) importé(s) avec succès | Téléphones invalides ignorés: 1 (ex: 001)"
}
```

## Notes
- Les erreurs "douces" n'empêchent pas l'import. Les champs invalides sont ignorés.
