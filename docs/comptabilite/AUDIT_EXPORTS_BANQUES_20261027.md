# Audit — exports comptables et gestion bancaire

Date de l'audit : 27 octobre 2026  
Périmètre : module **Ma Comptabilité**, trésorerie et comptes bancaires ONEC Smart.

## 1. Classeur de référence

Source analysée avant modification du code :

`D:\iComptabilité\Importation Octobre 2026.xlsx`

Empreinte SHA-256 :

`db688659436873eb2ff0ae4513a7909ad82dcc77fa3da3b6ff1c6f1943e46183`

Constats techniques :

- une feuille `Journal`, plage utilisée `A1:M202` ;
- la table d'import exploitable se trouve en `A1:F99` ;
- en-têtes exacts : `Date>` | `Pièce` | `Compte` | `Libellé` | `Débit` | `Crédit` ;
- dates Excel natives, format `mm-dd-yy` ;
- comptes Excel numériques, format `0` ;
- débits et crédits numériques, format `0.00`, côté nul laissé vide ;
- les lignes 2 à 99 sont équilibrées : débit = crédit = `18 320,36` ;
- la colonne `Pièce` est vide dans le modèle, mais ONEC Smart l'alimente car la
  référence est indispensable à la traçabilité demandée ;
- les lignes 100 à 202 et la zone H:M constituent une zone de travail partielle,
  sans comptes et non équilibrée : elles ne définissent pas le contrat d'import.

Décision : conserver provisoirement l'en-tête inhabituel `Date>` à l'identique.
Il ne pourra être remplacé par `Date` qu'après confirmation écrite de l'éditeur
du logiciel comptable ou test d'import validé par le comptable.

## 2. Éléments existants réutilisés

- `ComptaEcriture` et `ComptaLigneEcriture` : partie double, statut, devise,
  taux figé, origine métier, validation et contre-passation ;
- journaux typés `CA` et `BQ`, plan comptable et exercices ;
- mappings paramétrables des postes budgétaires, rubriques techniques, caisses
  et comptes bancaires ;
- génération comptable idempotente depuis les encaissements, sorties et
  transferts internes ; les réquisitions et fonds de tiers passent par ces flux
  financiers lors de leur paiement ou reversement ;
- statuts `A_COMPTABILISER_MANUELLEMENT`, exposés dans l'interface sous le nom
  métier **À imputer** ;
- séparation tenant CN/CPK via `organisation_id`, filtres SQLAlchemy et RBAC ;
- journal de trésorerie existant, réutilisé pour les mouvements et le contrôle
  bancaire afin d'éviter un second calcul de solde divergent.

## 3. Lacunes corrigées

- absence de fichier conforme au contrat Excel du logiciel cible ;
- exports de trésorerie qui ne constituaient pas des écritures en partie double ;
- absence de prévalidation centralisée avant export et de blocage des comptes
  manquants, écritures déséquilibrées, devises incohérentes et doublons ;
- absence d'historique liant un export aux écritures exactes qu'il contient ;
- comptes bancaires dispersés entre paramétrage et rapports ;
- pointage bancaire manuel sans import déterministe, empreinte anti-doublon ni
  propositions soumises à validation humaine ;
- droit `compta.export` non accordé aux rôles opérationnels comptables.

## 4. Solution mise en œuvre

### Export logiciel comptable

- sélection par période, journal, compte bancaire et devise ;
- seules les écritures `VALIDEE` ou `CLOTUREE` sont retenues ;
- les écritures `BROUILLON` et `ANNULEE` ne sont jamais exportées comme actives ;
- contrôle par écriture et global : date, pièce, libellé, compte, devise,
  montants, équilibre et unicité de l'origine ;
- fichier `.xlsx` à six colonnes exactes, avec types Excel natifs ;
- export bloqué en présence d'une anomalie ; aucun montant source n'est modifié ;
- verrou transactionnel contre deux exports simultanés ;
- réexport bloqué par défaut, puis possible uniquement après confirmation
  explicite, avec lien vers l'export précédent.

### Contrôle et rapprochement bancaires

- vue centralisée des comptes, soldes, entrées, sorties, frais et transferts ;
- affichage du compte comptable associé à chaque banque ;
- USD et CDF traités séparément, sans conversion implicite ;
- import CSV/XLSX à colonnes Débit et Crédit distinctes ;
- normalisation des dates et nombres, conservation d'un solde négatif ;
- empreinte du fichier et de chaque ligne, doublons conservés mais non pointables ;
- rapprochement proposé selon sens, montant exact, date à ±7 jours, référence
  et similarité du libellé ;
- aucune proposition, même à 100 %, n'est confirmée automatiquement ;
- les propositions ambiguës sont signalées `INCERTAIN` ;
- confirmation ou rejet réservé au droit `compta.validation`.

Le journal de contrôle bancaire reste distinct du fichier destiné au logiciel
comptable. Aucun ordre de virement bancaire n'est produit.

## 5. Données et API ajoutées

- `compta_exports` et `compta_export_ecritures` ;
- `compta_releves_bancaires` et `compta_releve_bancaire_lignes` ;
- aperçu, génération et historique des exports ;
- mouvements bancaires, import/listage/détail des relevés et décision de
  rapprochement ;
- permission `compta.export` accordée par migration aux rôles `comptable`,
  `chef_comptable` et `daf`.

## 6. Validation avant mise en production

La migration a été jouée jusqu'à la tête sur une base PostgreSQL temporaire.
Les tests couvrent le contrat Excel, l'équilibre, les mappings absents, USD/CDF,
les virements internes, les annulations/contrepassations, l'idempotence et les
réexportations.

Avant déploiement réel :

1. faire tester un fichier généré dans une copie ou un bac à sable du logiciel
   comptable et confirmer notamment `Date>` ;
2. faire valider les mappings par le comptable, sans compte créé implicitement ;
3. tester un relevé réel de chaque banque et, si nécessaire, ajouter ses noms
   de colonnes au dictionnaire d'import ;
4. sauvegarder la base, appliquer la migration avec `make migrate`, contrôler
   les rôles, puis réaliser un export pilote sur une courte période ;
5. conserver le déploiement en attente tant que ces validations humaines ne
   sont pas signées.
