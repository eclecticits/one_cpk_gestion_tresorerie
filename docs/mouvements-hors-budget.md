# Mouvements hors budget et fonds de tiers

## Le problème

Jusqu'ici, tout mouvement d'argent était supposé budgétaire. La conséquence
n'était pas une gêne d'affichage : un encaissement reçu pour le compte d'un
tiers gonflait les recettes budgétaires, et une dépense urgente payée sans
imputation décidée n'avait nulle part où aller. La trésorerie et le budget
étaient lus dans les mêmes chiffres alors qu'ils ne disent pas la même chose.

## Les quatre natures

Chaque encaissement et chaque sortie porte désormais une `nature_mouvement`,
qui décide d'une seule chose : le mouvement touche-t-il le budget ?

| Nature | Trésorerie | Budget | Cas typique |
|---|---|---|---|
| `BUDGETAIRE` | oui | oui | cotisation, dépense sur réquisition |
| `HORS_BUDGET_A_REGULARISER` | oui | non (pour l'instant) | recette imprévue, dépense urgente |
| `FONDS_DE_TIERS` | oui | jamais | argent encaissé pour un conseil provincial |
| `TRANSFERT_INTERNE` | non (déplacement) | non | versement banque, approvisionnement caisse |

`impact_budgetaire` en découle mécaniquement et une contrainte en base refuse
toute combinaison incohérente.

## Ce qui change à l'usage

- **Encaissements** : un sélecteur « Nature du mouvement » apparaît dans le
  formulaire. Hors budget et fonds de tiers masquent le poste budgétaire — il
  n'y a rien à imputer. Un fonds de tiers demande en plus le tiers concerné.
- **Sorties de fonds** : deux nouveaux types, « Reversement de fonds de tiers »
  (qui exige de désigner les fonds à rembourser, avec contrôle du solde) et
  « Dépense hors budget (à régulariser) ».
- **Affecter au budget** : sur toute ligne hors budget, une action ouvre la
  décision d'imputation — un ou plusieurs postes, une justification obligatoire,
  une affectation possiblement partielle. Réservée au droit `budget`.
- **Fonds de tiers** : un écran dédié liste ce qui reste à reverser, par tiers.
- **Tableau de bord** : deux blocs distincts, « Trésorerie » (tout ce qui a
  bougé) et « Exécution budgétaire » (ce qui a été imputé), plus un bandeau
  d'encours quand quelque chose attend une décision.
- **Exports** : une colonne « Nature budgétaire » dans les classeurs
  Encaissements et Sorties.

## Le journal des imputations

`mouvement_budget_imputations` enregistre chaque impact budgétaire produit par
un mouvement réel, avec sa source, son poste, son montant dans la devise du
mouvement et dans celle du budget. Une annulation reprend l'imputation
enregistrée au lieu de la recalculer : c'est ce qui garantit qu'on retire au
poste exactement ce qu'on lui avait ajouté, même après un changement de taux
ou une régularisation partielle.

## Mise en production

Deux migrations, dans cet ordre, avec un contrôle entre les deux.

### 1. Schéma (sans risque)

```bash
alembic upgrade 20260904_hors_budget_schema
```

Ajoute les colonnes (nullables), les tables et les contraintes. L'historique
n'est pas touché : les lignes existantes gardent `nature_mouvement` à NULL et
sont lues comme budgétaires, exactement comme avant.

### 2. Préflight (obligatoire)

```bash
DATABASE_URL=postgresql+asyncpg://... \
  python backend/scripts/audit_mouvements_hors_budget_preflight.py
```

Le script ne modifie rien. Il annonce comment chaque ligne sera classée et
s'arrête (code 1) s'il reste des sorties dont la conversion budgétaire est
indéterminée — typiquement une dépense en CDF sans taux de change ni snapshot.
Renseignez le taux de l'organisation avant de continuer.

Les sorties multi-postes anciennes sont signalées sans bloquer : leur
imputation n'est pas reconstructible, leur annulation restera sans reprise
budgétaire, comme aujourd'hui.

### 3. Backfill

```bash
alembic upgrade 20260905_hors_budget_backfill
```

Classe l'historique, reprend les imputations reconstructibles (sans jamais
toucher aux compteurs des postes : cet argent y est déjà), puis rend les deux
colonnes obligatoires. La migration est rejouable sans créer de doublon.

Le `downgrade` relâche les contraintes mais ne supprime pas les imputations
reprises : elles décrivent des faits exacts.
