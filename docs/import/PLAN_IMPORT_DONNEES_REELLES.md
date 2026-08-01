# Plan d'import des données réelles — ONEC Smart

**Date :** 31/07/2026 · **Périmètre :** exercice 2026, journaux arrêtés au 3 juin 2026
**Sources :** journal de caisse, banques Equity et TMB, 31 réquisitions, budget 2026

---

## 1. Ce qui a été analysé

| Source | Volume | État |
|---|---|---|
| Journal CAISSE | 545 mouvements | Codes budgétaires 2025 (à remapper), 31 lignes sans code |
| BANQUE EQUITY | 86 mouvements | **Aucun code budgétaire renseigné** |
| BANQUE TMB | 12 mouvements | **Aucun code** + écart de rapprochement 30 000 USD |
| Réquisitions | 31 documents (22 docx, 7 xlsx, 2 pdf) | 26 exploitées, 6 numéros manquants |
| Budget 2026 | 103 postes dont **82 lignes terminales** | Nomenclature renumérotée vs 2025 |

**Totaux de contrôle à retrouver après import :**

| Indicateur | Montant USD |
|---|---|
| Entrées totales des 3 journaux | 131 482,67 |
| — dont mouvements internes (à ne PAS compter en recettes) | 34 623,35 |
| **Recettes budgétaires à importer** | **96 859,32** |
| Sorties totales des 3 journaux | 239 067,58 |
| — dont prêts (créances, hors budget) | 23 000,00 |
| **Dépenses budgétaires à importer** | **216 067,58** |

---

## 2. Anomalies à traiter AVANT l'import

### Bloquantes

**A. Écart de rapprochement TMB : 30 000 USD.** Le solde du journal dépasse le relevé bancaire de 30 000 USD, à l'identique en janvier, février et mars 2026. Tant que l'origine n'est pas élucidée, le solde d'ouverture TMB est faux — et l'importer ferait de cette erreur le point de départ officiel du nouveau système.
*Piste : rechercher une opération de 30 000 enregistrée en décembre 2025 mais jamais dénouée à la banque.*

**B. Double emploi probable sur les salaires.** La réquisition n°9 (salaires février, 20 000 USD) n'est décaissée qu'à 0,5 %, alors que les salaires ont bien été payés — mais rattachés aux réquisitions mensuelles couvrant la même période. Deux approbations pourraient couvrir la même dépense. À arbitrer avant d'importer les réquisitions.

### Majeures

**C. Nomenclature budgétaire.** Les journaux utilisent les codes 2025 alors que le budget applicable est 2026, avec une **permutation en cascade** (II.2.10.5 « collation » devient « frais bancaires » en 2026, etc.). La table de correspondance validée doit être appliquée à l'import. *Sans cela, la quasi-totalité des montants serait mal classée, silencieusement.*

**D. Prêts comptabilisés comme dépenses : 23 000 USD.** 15 000 au Conseil National (caisse) et 8 000 au Secrétaire exécutif (TMB). Ce sont des **créances**, pas des charges. À enregistrer au bilan.

**E. Mouvements internes comptés en recettes : 34 623 USD.** Retours en caisse, approvisionnements, dépôts en banque. À importer en **transferts internes**, jamais en encaissements.

### À clarifier

- **Réquisitions 19, 20, 28, 29, 30, 32 absentes** ; numéros 06, 22, 25 et 26 dupliqués avec des incohérences entre nom de fichier et contenu.
- **Entités CPK et CN mêlées** dans les journaux. Décider : périmètre CPK seul, ou CN traité comme tiers (ce que suggèrent déjà les prêts et remboursements).
- **Codes déduits** : 31 lignes de caisse et 98 lignes bancaires sans code budgétaire ont été classées par analyse des libellés — à valider par sondage.

---

## 3. Ordre d'import (impératif)

Les dépendances imposent cette séquence. Chaque étape se valide avant de passer à la suivante.

| # | Étape | Contenu | Contrôle |
|---|---|---|---|
| 1 | **Référentiels** | Services, 82 postes budgétaires 2026, comptes (Caisse, Equity, TMB) | Les 82 lignes terminales existent |
| 2 | **Soldes d'ouverture** | Caisse 1 511,99 · Equity 97 565,35 · TMB 124 932,32 *(sous réserve de l'anomalie A)* | Soldes conformes aux reports |
| 3 | **Réquisitions** | 26 réquisitions + leurs lignes, avec `import_source` | Montants approuvés cohérents |
| 4 | **Encaissements** | 296 entrées, hors mouvements internes | Total = 96 859,32 |
| 5 | **Sorties de fonds** | 346 sorties, rattachées aux réquisitions quand identifiées | Total = 216 067,58 |
| 6 | **Transferts internes** | Mouvements caisse ↔ banque | Neutres sur le résultat |
| 7 | **Prêts / créances** | 23 000 USD | Au bilan, hors budget |

---

## 4. Le piège central : ne pas rejouer la trésorerie

**C'est la règle la plus importante de ce plan.**

Si les 346 sorties sont importées via le circuit normal de l'application, celle-ci **débitera la caisse 346 fois** et incrémentera les compteurs budgétaires d'autant. Le solde deviendrait massivement négatif et les budgets seraient consommés deux fois.

**Méthode retenue :** importer les opérations en mode **historique** — écriture des enregistrements sans déclencher les mouvements de trésorerie ni la consommation budgétaire — puis **fixer les soldes** aux montants réels constatés au 3 juin 2026.

---

## 5. Sécurité de l'opération

1. **Sauvegarde vérifiée** (`pg_dump`) immédiatement avant, et test de restauration.
2. **Mode simulation d'abord** : le script analyse, produit un rapport d'anomalies, et n'écrit rien.
3. **Marquage** de chaque enregistrement (`import_source`) pour permettre l'annulation complète d'un lot.
4. **Import par étape**, avec vérification des totaux de contrôle après chacune.
5. **SEC-01 à traiter au préalable** : la clé SSH exposée dans l'historique git doit être révoquée avant que des données financières et personnelles réelles soient chargées.

---

## 6. Rapprochement dépenses ↔ réquisitions

Deux méthodes ont été testées :

| Méthode | Dépenses rattachées | Montant |
|---|---|---|
| Montant exact | 10 | 87 544 $ |
| **Par enveloppe** (cumul sur période + catégorie) | **108** | **120 908 $** |

L'approche par enveloppe est retenue : elle correspond au fonctionnement réel (une réquisition approuvée, puis des décaissements successifs) et au module de **décaissement progressif** de l'application. Sept réquisitions ressortent soldées à 100 %.

Les 118 160 $ restants sans rattachement se concentrent sur : per capita (25 106), loyers (21 533), transport (18 210), salaires (16 146) et prêts (15 000 — sans réquisition par nature).

---

## 7. Fichiers de travail

| Fichier | Contenu |
|---|---|
| `PLAN_IMPORT_ONEC_SMART.xlsx` | Totaux de contrôle, anomalies, soldes, postes 2026, données prêtes par catégorie |
| `MAPPING_LIGNE_A_LIGNE_CAISSE_2026.xlsx` | 545 lignes de caisse avec code 2026 proposé |
| `MAPPING_BANQUES_2026.xlsx` | 98 lignes bancaires classées + alerte rapprochement |
| `MAPPING_BUDGET_2026_COMPLETE.xlsx` | Correspondance des codes 2025 → 2026 |
| `RAPPROCHEMENT_ENVELOPPE.xlsx` | Suivi des enveloppes par réquisition |

---

## 8. Décisions attendues avant développement du script

1. Origine de l'écart TMB de 30 000 USD.
2. Arbitrage sur le double emploi salaires (réq. n°9).
3. Périmètre : CPK seul, ou CPK + CN ?
4. Validation de la table de correspondance budgétaire.
5. Récupération des réquisitions manquantes (19, 20, 28, 29, 30, 32).

*Le script d'import sera développé une fois ces points tranchés. Il comportera un mode simulation obligatoire avant tout écriture.*
