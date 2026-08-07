# Procédure — Retour en caisse après une sortie de fonds

## 1. Contexte métier

Une **sortie de fonds** décaisse de l'argent (caisse ou banque) au profit d'un bénéficiaire.
Dans plusieurs situations, une partie de ces fonds revient dans les caisses de l'organisation :

- **Reliquat d'avance « à valoir »** (cas principal) : un agent reçoit une avance pour une
  mission ou un achat, en dépense une partie et **rend le solde non utilisé**. La dépense
  réelle est inférieure au montant décaissé.
- **Correction d'une sortie erronée** : une sortie enregistrée par erreur doit être
  rétablie alors que la fenêtre d'annulation directe (30 min) est dépassée.
- **Trop-perçu** : le bénéficiaire rembourse un excédent (montant versé supérieur au dû).

Avant ce lot, l'application ne disposait d'**aucun mécanisme dédié** : la seule réversion
possible était l'annulation d'une sortie (réversion **totale**, limitée à 30 minutes), ce
qui ne couvre ni un retour **partiel**, ni un retour survenant **plusieurs jours** après le
décaissement. Le module `Retour en caisse` comble ce manque.

## 2. Principe comptable et budgétaire

Un retour en caisse est la **contre-passation partielle** d'une sortie de fonds. Il ne
modifie jamais la sortie d'origine (piste d'audit préservée) mais enregistre une opération
distincte qui lui est rattachée (`sortie_fonds_id`).

| Effet | Sortie de fonds (caisse) | Retour en caisse (caisse) |
|-------|--------------------------|---------------------------|
| Trésorerie | Caisse **débitée** | Caisse **créditée** |
| Budget | Imputation `montant_paye` du poste **augmentée** | Imputation `montant_paye` **réduite** |
| Écriture (SYSCOHADA) | D Charge (poste) / C Trésorerie (571) | **D Trésorerie (571) / C Charge (poste)** |

La dépense **nette** du poste budgétaire reflète ainsi la consommation réelle
(`décaissé − rendu`). L'écriture inverse porte `module_origine = "retours_caisse"`,
`type_origine = "retour_caisse"` (clé d'idempotence dédiée) et n'est générée que si le
module Comptabilité est en **intégration automatique**.

## 3. Procédure fonctionnelle

1. **Ouvrir la caisse** (canal CAISSE) : un retour crédite la caisse, la session doit donc
   être ouverte, exactement comme pour enregistrer une sortie.
2. **Retrouver la sortie de fonds d'origine** (celle qui a servi l'avance ou le paiement).
3. **Enregistrer le retour** en indiquant au minimum la sortie et le **montant rendu**. Le
   canal, la devise, le compte bancaire et le poste budgétaire sont **hérités de la sortie**
   s'ils ne sont pas précisés.
4. Le système **crédite la trésorerie**, **réduit l'imputation budgétaire** et **génère
   l'écriture inverse** (si compta automatique), puis attribue un **numéro de pièce** `RET-…`.
5. Le **reste à justifier** de l'avance (`montant décaissé − Σ retours valides`) est calculé
   et consultable pour suivre le solde de l'avance.

Le montant cumulé des retours d'une sortie **ne peut pas dépasser le montant décaissé**.
Une pièce justificative et un motif peuvent être joints.

## 4. Implémentation technique

| Élément | Emplacement |
|---------|-------------|
| Modèle `RetourCaisse` (table `retours_caisse`) | `app/models/retour_caisse.py` |
| Migration | `alembic/versions/20260805_retours_caisse.py` (down_revision `20260804_compta_mode`) |
| Schémas Pydantic | `app/schemas/retour_caisse.py` |
| Écriture comptable inverse | `generer_ecriture_retour_caisse` dans `modules/comptabilite/services/generation_service.py` |
| Endpoints | `app/api/v1/endpoints/retours_caisse.py`, montés sur `/retours-caisse` |
| Tests | `tests/test_retours_caisse.py` |

Le modèle réutilise les conventions des sorties (contraintes `canal`, `devise`, montant
strictement positif, unicité `organisation_id + reference_numero`, champs d'annulation) et
les helpers de trésorerie/budget existants (`_get_or_create_caisse`, `_to_budget_currency`)
comme source unique de vérité. Permission requise : `sorties_fonds` (routeur) +
`can_execute_payment` (création / annulation), identiques à celles d'une sortie de fonds.

### Endpoints

- `POST /api/v1/retours-caisse` — enregistre un retour.
  Corps minimal : `{ "sortie_fonds_id": "...", "montant": 30 }`.
  Champs optionnels : `type_retour` (`reliquat_avance` | `correction` | `trop_percu`),
  `canal`, `compte_bancaire_id`, `budget_poste_id`, `ajuste_budget`, `mode`, `motif`,
  `reference`, `piece_justificative`, `date_retour`.
- `GET /api/v1/retours-caisse?sortie_fonds_id=…&include_summary=true` — liste les retours et
  renvoie le **résumé** `sortie_montant_paye` / `total_retourne` / `reste_a_justifier`.
- `PATCH /api/v1/retours-caisse/{id}/statut` — annule un retour (`{"statut":"ANNULEE"}`),
  fenêtre de 30 min, rétablit intégralement trésorerie + budget + comptabilité.

## 5. Garde-fous

- La sortie d'origine doit être **VALIDE** (une sortie annulée n'a rien à rendre).
- Les **transferts internes** (`versement_banque`, `approvisionnement_caisse`) ne sont pas
  des dépenses : ils sont refusés.
- La **devise** du retour est imposée par la sortie ; le **canal** hérite de la sortie par
  défaut (un retour BANQUE exige un `compte_bancaire_id`).
- Anti sur-remboursement : `Σ retours valides + montant ≤ montant décaissé`.
- Contraintes `solde ≥ 0` en base : les crédits augmentent les soldes ; l'annulation
  re-débite en bornant à 0 (avec journalisation) si des mouvements intermédiaires ont
  entre-temps réduit le solde.
- Multi-postes : pour une sortie répartie sur plusieurs postes (`budget_poste_id` nul),
  préciser `budget_poste_id` sur le retour ; en intégration automatique, l'écriture est
  sinon refusée avec un message explicite.

## 6. Limites connues / suites possibles

- **Reporting** : les états qui somment les sorties de fonds ne soustraient pas encore
  automatiquement les retours (la correction budgétaire, elle, est immédiate). Un lot
  ultérieur pourra exposer les retours dans les agrégats de dépenses nettes.
- **Frontend** : ce lot livre le socle backend (modèle, API, comptabilité, tests). L'écran
  de saisie « Retour en caisse » (bouton depuis la fiche d'une sortie, affichage du reliquat)
  reste à ajouter côté interface.
- **Tests d'intégration** : `tests/test_retours_caisse.py` requiert `TEST_DATABASE_URL`
  (PostgreSQL) comme le reste de la suite E2E.
