# Export et suppression de compte (RGPD) — spécification à implémenter

**Statut :** conception à valider avant implémentation.
**Pourquoi une spec et pas directement du code :** la suppression **modifie/altère des données** (droit à l'effacement) et, dans un SaaS financier, se heurte aux **obligations légales de conservation** des écritures comptables. L'approche retenue doit donc être l'**anonymisation** (dissociation identité ↔ écritures), pas la suppression physique. Deux points requièrent votre validation avant que j'écrive le code :
1. **Durées de conservation légales** applicables aux écritures financières et RH dans votre juridiction.
2. **Qui déclenche** la suppression (l'utilisateur lui-même en self-service ? un administrateur ? sur demande à un contact ?).

---

## 1. Export des données personnelles (droit d'accès + portabilité) — SÛR, lecture seule

**Endpoint proposé :** `GET /api/v1/users/me/export`
**Auth :** utilisateur authentifié (`get_current_user`).
**Réponse :** JSON téléchargeable rassemblant les données personnelles **du demandeur**, scopé à son organisation.

Contenu suggéré :
```json
{
  "compte": {
    "id", "email", "nom", "prenom", "role",
    "organisation_id", "created_at", "updated_at",
    "is_email_verified", "active"
  },
  "activite": {
    "requisitions_creees": [ { "numero", "objet", "montant_total", "statut", "created_at" } ],
    "sorties_creees":       [ { "reference_numero", "montant_paye", "beneficiaire", "date_paiement" } ],
    "encaissements_saisis": [ … ],
    "ordres_autorises":     [ … ],
    "connexions_recentes":  [ { "date", "ip" } ]  // depuis audit_logs
  },
  "genere_le": "…", "format": "json", "version": 1
}
```
Notes :
- **Ne jamais** inclure le mot de passe haché, les OTP, les jetons.
- Filtrer strictement par `created_by == user.id` et `organisation_id == tenant`.
- Fournir aussi un export CSV optionnel pour la lisibilité.
- Cet endpoint peut être implémenté immédiatement (aucune écriture). Effort : S.

## 2. Suppression de compte (droit à l'effacement) — via ANONYMISATION

**Principe :** on ne supprime pas physiquement l'utilisateur s'il est lié à des écritures financières à conserver. On **anonymise** les données personnelles et on désactive le compte. Les écritures restent, mais ne sont plus rattachables à une personne identifiable.

**Endpoint proposé :** `POST /api/v1/users/me/delete-request` (self-service) **ou** `POST /api/v1/admin/users/{id}/anonymize` (par un admin).
**Auth :** l'utilisateur pour son propre compte, ou un administrateur de l'organisation.
**Workflow recommandé :**
1. Vérification d'identité (mot de passe + OTP) pour une action irréversible.
2. Passage du compte à `active = false`, `is_deleted = true` (soft-delete).
3. **Anonymisation des champs personnels** de `users` :
   - `email` → `deleted-<uuid>@anonymized.local`
   - `nom`, `prenom` → `"Utilisateur supprimé"` / `null`
   - `hashed_password` → `null` ; `otp_code` → `null`
4. **Conservation** des écritures financières liées (`created_by` reste l'UUID, mais l'UUID ne pointe plus vers une identité). Option : remplacer les noms de bénéficiaires libres uniquement si ce sont des données personnelles de l'utilisateur, jamais les montants/références comptables.
5. Écriture d'une entrée d'audit `USER_ANONYMIZED` (le journal étant append-only).
6. Révocation de toutes les sessions/refresh tokens de l'utilisateur, et **révocation des jetons Google OAuth** côté Google si une connexion existait (`https://oauth2.googleapis.com/revoke`).

**À NE PAS supprimer** (obligation légale) : les écritures comptables (réquisitions, sorties, encaissements) et les journaux d'audit. Elles sont conservées de façon anonymisée pour la durée légale [À COMPLÉTER].

**Points de vigilance :**
- Contrainte d'unicité sur `email` : l'anonymisation doit produire une valeur unique (d'où le suffixe `<uuid>`).
- Si l'utilisateur est le **dernier administrateur** d'une organisation, bloquer la suppression (sinon l'organisation devient ingérable).
- Cette opération **modifie des données** : à tester sur une copie, avec sauvegarde préalable.

## 3. Révocation OAuth Google (complément conformité)

Aujourd'hui, la déconnexion Google efface les jetons **locaux** mais n'appelle pas l'endpoint de révocation Google. À ajouter dans la déconnexion **et** dans l'anonymisation :
```
POST https://oauth2.googleapis.com/revoke  (body: token=<refresh_or_access_token>)
```
Effort : S.

## 4. Ce que je peux faire ensuite

- **Immédiat, sûr :** implémenter l'endpoint d'**export** (§1) — lecture seule.
- **Après vos réponses (rétention + déclencheur) :** implémenter l'**anonymisation** (§2) et la **révocation OAuth** (§3), avec tests, sur validation et sauvegarde.

Merci de préciser :
1. Durée(s) légale(s) de conservation des écritures financières/RH.
2. Suppression en self-service par l'utilisateur, ou par un administrateur uniquement ?
