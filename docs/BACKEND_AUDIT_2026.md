# Audit technique backend - 2026-08-10

## 1. Resume executif

Le backend est fonctionnel et couvre un perimetre large : finances, tresorerie, budget, requisitions, comptabilite, administration, SaaS, RH et secretariat. Il contient des garde-fous importants pour une application multi-tenant : JWT avec issuer/audience, refresh tokens hashes et rotatifs, limitation de debit sur l'authentification, contexte tenant, filtre ORM global sur les SELECT, validations inter-tenant au flush, journalisation d'audit, verrous `FOR UPDATE` sur plusieurs mouvements financiers et des types `Numeric`/`Decimal` largement utilises.

La maturite generale est intermediaire a avancee sur les fondations, mais insuffisante pour une exploitation financiere critique sans durcissement. Le principal probleme n'est pas l'absence de logique metier : c'est son emplacement. Plusieurs endpoints de plus de 2 000 lignes melangent validation HTTP, calculs financiers, requetes SQL, mutations de soldes, generation comptable, notifications, cache et audit. Cette concentration rend les garanties d'integrite difficiles a prouver.

Les risques principaux sont :

- fuite multi-tenant via endpoints debug si l'environnement est configure avec `ENV=prod` au lieu de `ENV=production` ;
- divergence entre tresorerie, budget et comptabilite sur les paiements partiels ;
- incoherence financiere possible par soft-delete/restauration d'encaissements actifs ;
- annulations qui corrigent les soldes en les ramenant a zero au lieu de bloquer ou de creer une ecriture d'ecart explicite ;
- permissions trop larges sur des operations sensibles comme cloturer/rouvrir/importer/remplacer un budget ;
- performance fragile sur rapports/exports volumineux.

Conclusion : le backend n'a pas besoin d'une reecriture totale. Il faut une refactorisation progressive centree sur l'integrite financiere, les transactions, les permissions fines et l'extraction de services metier reutilisables.

## 2. Top 10 problemes

### 1. Debug finance expose des agregats multi-tenant si `ENV=prod`

Constat : les routes `/debug` sont montees sauf si `settings.env.lower() == "production"`, alors que la configuration traite `prod` comme un environnement de production pour d'autres controles. L'endpoint `finance-sanity` utilise du SQL brut sans filtre `organisation_id`.

Fichiers :

- `backend/app/api/v1/router.py:74`
- `backend/app/api/v1/endpoints/debug.py:17`
- `backend/app/api/v1/endpoints/debug.py:68`

Fonction : `finance_sanity`.

Impact : fuite de totaux financiers et metadonnees globales entre organisations si l'application est lancee avec `ENV=prod`. C'est aussi un precedent dangereux : SQL brut hors tenant scope sur un endpoint de diagnostic.

Gravite : CRITIQUE.

Cause racine : definition non centralisee de "production" et endpoint debug non tenant-safe.

Correction recommandee : creer une propriete unique `is_production`, desactiver strictement `/debug` hors dev/test, exiger `super_admin` explicite pour tout diagnostic, supprimer les agregats multi-tenant ou les filtrer par tenant selectionne.

### 2. Soft-delete/restauration des encaissements peut casser la coherence financiere

Constat : `soft_delete_encaissement` et `restore_encaissement` changent uniquement `is_deleted`. Le chemin financier correct existe avec `cancel_encaissement_operation`, mais le soft-delete peut masquer un encaissement actif des rapports/exports sans inverser caisse, banque, budget ni comptabilite.

Fichiers :

- `backend/app/api/v1/endpoints/encaissements.py:1863`
- `backend/app/api/v1/endpoints/encaissements.py:1895`
- `backend/app/api/v1/endpoints/encaissements.py:1959`

Fonctions : `soft_delete_encaissement`, `restore_encaissement`, `cancel_encaissement_operation`.

Impact : ecarts entre solde bancaire/caisse, budget execute, comptabilite et rapports filtrant `is_deleted = false`.

Gravite : CRITIQUE.

Cause racine : coexistence d'un mecanisme CRUD generique et d'un workflow financier d'annulation.

Correction recommandee : interdire le soft-delete des operations payees/actives, ou le transformer en annulation financiere auditee avec contrepassation. Restreindre la restauration aux proformas/brouillons non comptabilises.

Dette technique ouverte apres correctif 2 :

| Anomalie | Fichier | Priorite | Raison |
|---|---|---|---|
| Filtre `Encaissement.is_deleted = false` manquant dans des agregats dashboard | `backend/app/api/v1/endpoints/dashboard.py:163` | Moyenne | Risque latent de divergence d'affichage si une operation non financiere est soft-supprimee. |
| Filtre `Encaissement.is_deleted = false` manquant dans des agregats rapports | `backend/app/api/v1/endpoints/reports.py:202` | Moyenne | Risque latent de divergence entre rapports et liste encaissements. |
| Filtre `Encaissement.is_deleted = false` manquant dans l'export encaissements | `backend/app/api/v1/endpoints/exports.py:879` | Moyenne | Risque latent d'export de lignes masquees logiquement. |

Ces anomalies ne doivent pas etre corrigees dans le correctif 2. Elles confirment que les operations financieres validees ne doivent plus passer par le soft-delete : le chemin autorise est l'annulation financiere auditee.

### 3. Paiements partiels sans generation comptable automatique

Constat : `POST /payment-history` ajoute un paiement, met a jour l'encaissement, le budget, la caisse ou la banque, puis commit. Contrairement a la creation/conversion d'encaissement, il n'appelle pas la generation d'ecriture comptable en mode automatique.

Fichiers :

- `backend/app/api/v1/endpoints/payments.py:82`
- `backend/app/api/v1/endpoints/encaissements.py:1243`
- `backend/app/api/v1/endpoints/encaissements.py:1451`

Fonction : `create_payment`.

Impact : un paiement partiel peut exister dans la tresorerie et le budget sans piece comptable correspondante.

Gravite : CRITIQUE.

Cause racine : workflow de paiement separe du workflow d'encaissement principal.

Correction recommandee : creer un service metier unique `record_encaissement_payment` qui gere atomiquement historique, soldes, budget, comptabilite, audit et notifications.

### 4. Annulations avec soldes tronques a zero

Constat : lors de certaines annulations, si le solde destination est insuffisant, le code journalise un avertissement et applique `max(0, solde - montant)` au lieu de bloquer l'operation ou de creer une regularisation formelle.

Fichiers :

- `backend/app/api/v1/endpoints/encaissements.py:1990`
- `backend/app/api/v1/endpoints/sorties_fonds.py:1909`
- `backend/app/api/v1/endpoints/sorties_fonds.py:1924`

Fonctions : `cancel_encaissement_operation`, `update_sortie_statut`.

Impact : incoherence mathematique du solde, ecarts non materialises comptablement, perte de tracabilite financiere exploitable.

Gravite : CRITIQUE.

Cause racine : logique "best effort" appliquee a une operation comptable critique.

Correction recommandee : bloquer l'annulation en cas de solde insuffisant, ou generer une regularisation/creance d'ecart validee et comptabilisee.

### 5. God modules financiers

Constat : les plus gros endpoints portent directement des responsabilites metier lourdes.

Fichiers principaux :

| Fichier | Lignes | Fonctions | Responsabilites actuelles | Complexite |
|---|---:|---:|---|---|
| `backend/app/api/v1/endpoints/budget.py` | 2255 | 39 | exercices, postes, import, cloture, reouverture, exports de structure | Tres elevee |
| `backend/app/api/v1/endpoints/requisitions.py` | 2213 | 49 | creation, workflow, validation, dossiers, statuts | Tres elevee |
| `backend/app/api/v1/endpoints/sorties_fonds.py` | 2130 | 25 | paiement, budget, caisse, banque, comptabilite, annulation | Tres elevee |
| `backend/app/api/v1/endpoints/encaissements.py` | 2094 | 31 | proforma, encaissement, paiement initial, pieces, annulation | Tres elevee |
| `backend/app/api/v1/endpoints/exports.py` | 1577 | 20 | exports Excel/PDF de plusieurs domaines | Elevee |
| `backend/app/api/v1/endpoints/services.py` | 1518 | 48 | unites, rubriques, membres, commissions | Elevee |
| `backend/app/api/v1/endpoints/admin.py` | 1438 | 48 | users, roles, settings, notifications, approbateurs | Elevee |
| `backend/app/api/v1/endpoints/reports.py` | 1373 | 10 | tableaux financiers, journaux, agregats | Elevee |
| `backend/app/api/v1/endpoints/hr.py` | 1362 | 60 | RH complete dans un seul routeur | Elevee |
| `backend/app/services/requisition_service.py` | 1211 | 28 | workflow requisition, permissions, montants, statuts | Elevee |

Impact : regression probable a chaque changement, transactions difficiles a auditer, tests longs a ecrire.

Gravite : ELEVEE.

Cause racine : logique metier concentree dans les routes au lieu de services specialises.

Correction recommandee : extraire progressivement des services transactionnels par cas d'usage : `EncaissementPaymentService`, `TreasuryLedgerService`, `BudgetExecutionService`, `FinancialCancellationService`, `BudgetImportService`.

### 6. Permissions trop larges sur operations sensibles

Constat : des operations de budget utilisent une permission large `budget`, incluant cloture, reouverture et import/remplacement. `has_any_permission` donne aussi un bypass aux roles `admin` et `super_admin`.

Fichiers :

- `backend/app/api/v1/router.py:125`
- `backend/app/api/v1/endpoints/budget.py:552`
- `backend/app/api/v1/endpoints/budget.py:577`
- `backend/app/api/deps.py:478`

Impact : un utilisateur trop largement autorise peut rouvrir un exercice ou remplacer des donnees budgetaires.

Gravite : ELEVEE.

Cause racine : RBAC organise par module plutot que par action critique.

Correction recommandee : permissions fines : `budget.close_exercise`, `budget.reopen_exercise`, `budget.import`, `budget.replace`, `budget.delete`, avec confirmation et audit trail obligatoire.

### 7. Tenant scope robuste mais fragile par contournement

Constat : un filtre ORM global protege les SELECT et une validation `before_flush` controle de nombreuses relations inter-tenant. Mais les requetes SQL brutes, bulk UPDATE/DELETE, endpoints `super_admin` avec `skip_tenant_scope`, et les nouveaux modeles non ajoutes a la liste peuvent contourner ce mecanisme.

Fichiers :

- `backend/app/db/session.py:462`
- `backend/app/db/session.py:533`
- `backend/app/db/session.py:555`
- `backend/app/api/v1/endpoints/super_admin.py:111`

Impact : risque d'exposition ou modification inter-tenant lors d'une evolution future ou d'un endpoint brut.

Gravite : ELEVEE.

Cause racine : isolation tenant partiellement implicite et liste de modeles maintenue manuellement.

Correction recommandee : imposer `organisation_id` explicite dans les repositories, tester chaque endpoint critique avec deux tenants, ajouter des guards sur SQL brut et bulk operations.

### 8. Exports et rapports non bornes

Constat : plusieurs exports chargent tous les resultats en memoire avec `.all()` et construisent des workbooks/PDF dans la requete HTTP. Des rapports executent plusieurs agregats sequentiels.

Fichiers :

- `backend/app/api/v1/endpoints/exports.py:413`
- `backend/app/api/v1/endpoints/exports.py:879`
- `backend/app/api/v1/endpoints/exports.py:1072`
- `backend/app/api/v1/endpoints/reports.py:917`

Impact : latence, consommation memoire, timeouts et saturation DB avec 100-500 utilisateurs ou de gros historiques.

Gravite : ELEVEE.

Cause racine : exports synchrones et absence de pagination/streaming/limites fortes.

Correction recommandee : imposer limites de periode, streaming, jobs asynchrones pour gros exports, index composes, vues/materialisations pour rapports lourds.

### 9. Gestion d'erreurs qui masque certains echecs financiers/reporting

Constat : certains blocs `except Exception` rollback puis continuent avec des valeurs par defaut, par exemple des soldes de rapport a zero si une requete echoue.

Fichiers :

- `backend/app/api/v1/endpoints/reports.py:178`
- `backend/app/services/weekly_report.py:44`
- `backend/app/middleware/timing.py:49`

Impact : le frontend peut afficher des chiffres faux sans signaler une erreur critique.

Gravite : ELEVEE.

Cause racine : traitement d'erreur optimise pour disponibilite visuelle plutot que pour exactitude financiere.

Correction recommandee : differencier erreurs non critiques et erreurs de calcul financier ; retourner une erreur explicite ou un statut "donnees indisponibles" pour les rapports financiers.

### 10. Suite de tests large mais trous sur les scenarios critiques identifies

Constat : 541 tests collectes. Execution locale : 206 passes, 334 skips, 1 echec environnemental (`OSError: [Errno 30] Read-only file system: '/data'` lors de `os.makedirs(UPLOAD_DIR)` dans `app.main`). Les tests couvrent beaucoup de domaines, mais les risques trouves ne semblent pas verrouilles par tests dedies.

Fichiers :

- `backend/tests/test_auth_e2e.py:38`
- `backend/app/main.py:67`

Impact : de bonnes defenses existantes peuvent regresser sans alerte sur les flux les plus critiques.

Gravite : ELEVEE.

Cause racine : tests nombreux mais pas assez axes invariants financiers/multi-tenant de bout en bout.

Correction recommandee : ajouter tests invariants : paiement partiel => compta, soft-delete interdit sur operation active, debug non monte en `prod`, annulation avec solde insuffisant, isolation inter-tenant sur exports/rapports.

## 3. Cartographie de l'architecture actuelle

### Structure backend

- `backend/app/main.py` : creation FastAPI, CORS, middlewares, montage uploads/static, demarrage schedulers.
- `backend/app/api/v1/router.py` : composition des routeurs API v1.
- `backend/app/api/v1/endpoints/` : couche HTTP principale. 468 declarations de routes detectees.
- `backend/app/api/deps.py` : authentification, resolution tenant, controle subscription, permissions.
- `backend/app/core/` : configuration, securite JWT/mots de passe, contexte audit, chiffrement, observabilite.
- `backend/app/db/` : session SQLAlchemy async, moteur, filtres tenant, audit DB.
- `backend/app/models/` : modeles SQLAlchemy des domaines financiers, SaaS, RBAC, RH, secretariat.
- `backend/app/schemas/` : schemas Pydantic.
- `backend/app/services/` : services transverses et quelques services metier.
- `backend/app/modules/comptabilite/` : module mieux separe avec routers, schemas et services.
- `backend/app/modules/secretariat/` : module fonctionnel separe par routers/services/tableau.
- `backend/alembic/versions/` : 212 migrations.
- `backend/tests/` : 42 fichiers de tests, 541 tests collectes.

### Routes API principales

Les routeurs couvrent notamment : auth, admin, super-admin, dashboard, encaissements, payment-history, sorties de fonds, requisitions, lignes de requisition, budget, clotures, treasury, transferts, retours caisse, banques, projets/activites, rapports, exports, experts, imports, HR, secretariat, comptabilite, billing, webhooks, uploads securises.

Les plus gros fichiers de routes indiquent que la logique metier est souvent dans la couche HTTP, surtout finances/budget/requisitions.

### Modeles et donnees

Les modeles critiques utilisent majoritairement `Numeric` :

- `Encaissement` : montants `Numeric(15,2)`, taux `Numeric(12,4)`, contraintes de statut/canal/devise, unique `organisation_id + numero_recu`.
- `SortieFonds` : montants `Numeric(14,2)`, taux `Numeric(12,4)`, unique `organisation_id + reference_numero`.
- `BudgetExercice` / `BudgetPoste` : unique par organisation/exercice/code, index sur organisation/exercice/code/parent.
- `CaisseCentrale`, `CompteBancaire`, `PaymentHistory`, `PaymentTransaction`, `ClotureCaisse`, `RegularisationCaisse` structurent la tresorerie.
- `EcritureComptable`, journaux, comptes et mappages comptables sont isoles dans le module comptabilite.

### Authentification et securite

Points positifs :

- access tokens JWT signes HS256 avec issuer/audience ;
- refresh tokens separes, hashes en base, rotation a chaque refresh ;
- cookies refresh HttpOnly, Secure effectif hors dev/test, SameSite configure ;
- rate limit login/reset ;
- validation du secret JWT en production ;
- uploads non publics par defaut ;
- restriction subscription sur ecritures.

Points a durcir :

- bootstrap admin pas explicitement desactive en production ;
- Swagger/OpenAPI non desactives explicitement dans `main.py` ;
- route debug dependante d'une comparaison d'environnement incomplete ;
- admin et super_admin bypassent largement les permissions fines.

### Middlewares et observabilite

Middlewares detectes : rate limit SlowAPI, slow request, error tracking, reset contexte audit/tenant. La DB trace les requetes lentes et loggue la configuration de pool. Les logs incluent parfois tenant/user mais pas un schema structure uniforme avec request id obligatoire.

### Migrations

212 migrations Alembic. Plusieurs migrations effectuent des `op.execute`, seed de donnees, migrations tenant, drops en downgrade et suppressions de permissions. Le volume est normal pour un produit vivant, mais demande une discipline de revue stricte avant production.

### Tests

42 fichiers de tests, 541 tests collectes. Execution observee :

- 206 passes ;
- 334 skipped ;
- 1 failed ;
- 248 warnings ;
- duree : 77,79 s.

L'echec est environnemental : `app.main` tente de creer `/data` alors que le filesystem de test est en lecture seule.

## 4. Separation des responsabilites

### Etat actuel

La separation est heterogene.

Bonne separation :

- `app/core/security.py` concentre JWT, hash, validation mot de passe.
- `app/api/deps.py` concentre auth, tenant, permissions.
- `modules/comptabilite` possede une structure routers/schemas/services plus saine.
- `modules/secretariat` est mieux module que les anciens endpoints monolithiques.

Separation faible :

- `encaissements.py` gere HTTP, validation, clients, budget, caisse/banque, pieces, comptabilite, emails et audit.
- `sorties_fonds.py` gere paiement, requisition, budget, tresorerie, comptabilite, annulation et statut.
- `budget.py` gere exercices, postes, import, backup, suppression, cloture, reouverture et calculs.
- `admin.py` melange utilisateurs, roles, parametres, notifications, impression, approbateurs.
- `services.py` melange unites organisationnelles, rubriques budgetaires, membres et commissions.

### Fonctions candidates a refactorisation

- `create_sortie_fonds` dans `sorties_fonds.py` : candidat prioritaire, fonction de paiement transactionnel multi-domaines.
- `update_sortie_statut` dans `sorties_fonds.py` : candidat pour un service d'annulation/contrepassation.
- `create_encaissement` dans `encaissements.py` : candidat pour un service d'encaissement.
- `convertir_proforma` dans `encaissements.py` : candidat pour reutiliser le meme service de paiement.
- `create_payment` dans `payments.py` : candidat prioritaire, doit rejoindre le service d'encaissement.
- `import_budget_postes` dans `budget.py` : candidat pour `BudgetImportService`.
- routes reports/exports : candidats pour services read-only optimises.

## 5. Fichiers trop volumineux

Seuils detectes :

- plus de 2 000 lignes : `budget.py`, `requisitions.py`, `sorties_fonds.py`, `encaissements.py`, `test_secretariat_module.py`.
- plus de 1 500 lignes : ajouter `exports.py`, `services.py`.
- plus de 1 000 lignes : ajouter `admin.py`, `reports.py`, `hr.py`, `requisition_service.py`, `clotures.py`, `super_admin.py`.
- plus de 500 lignes : de nombreux endpoints/services/schemas/modeles.

Decoupage recommande :

- routes fines gardant seulement validation HTTP et appels services ;
- services transactionnels par cas d'usage ;
- repositories explicites avec `organisation_id` obligatoire ;
- helpers financiers centralises ;
- generation document/export deplacee hors endpoints.

## 6. Duplications metier

### Argent et arrondis

Fonctions similaires :

- `_clean_money` dans `encaissements.py` ;
- `_clean_money` dans `payments.py` ;
- helpers equivalents dans `exports.py`, `clotures.py`, `hr_payroll_calc.py`, `modules/comptabilite/services/change_service.py`, `modules/comptabilite/services/ecriture_service.py`.

Source de verite recommandee : `app/core/money.py` avec `Money`, `quantize_money`, `parse_money`, `compare_money`, politique d'arrondi documentee.

### Caisse centrale

Fonctions similaires :

- `_get_or_create_caisse` dans `encaissements.py` ;
- `_get_or_create_caisse` dans `sorties_fonds.py` ;
- logique proche dans `transferts.py`.

Source de verite recommandee : `TreasuryAccountService.get_or_create_cash_account(tenant_id, devise, lock=True)`.

### Permissions

Fonctions similaires :

- `_user_has_permission` dans `encaissements.py` ;
- `_user_has_permission` dans `sorties_fonds.py` ;
- variantes dans `ordres_decaissement.py`, `hr.py`.

Source de verite recommandee : reutiliser uniquement `app/api/deps.py` ou un service RBAC commun.

### Resolution service/unite

Fonctions similaires :

- `_resolve_service` dans `encaissements.py` ;
- `_resolve_service` dans `sorties_fonds.py` ;
- logique proche dans `requisitions.py`.

Source de verite recommandee : `OrganisationUnitService.resolve_for_user()`.

### Conversion devises

Fonctions similaires :

- `_to_budget_currency` / `_assert_budget_rate` dans `sorties_fonds.py` ;
- conversion CDF/EUR/XOF dans `encaissements.py` ;
- `_pivot_amount` et taux en float dans `requisition_service.py`.

Source de verite recommandee : `ExchangeRateService.convert(amount, from_currency, to_currency, date, tenant_id)`, en `Decimal` uniquement.

### Numerotation

Fonctions proches :

- numerotation encaissement ;
- references sorties ;
- sequences documents/requisitions ;
- migrations SQL de sequences.

Source de verite recommandee : `DocumentSequenceService` unique, avec verrouillage transactionnel.

## 7. Audit des calculs financiers

Points positifs :

- les colonnes financieres principales utilisent `Numeric` ;
- les calculs critiques utilisent souvent `Decimal(str(value))` ;
- plusieurs operations emploient `with_for_update()` pour verrouiller budget/caisse/banque ;
- les taux sont stockes avec precision `Numeric(12,4)`.

Points faibles :

- `float()` reste present dans des services financiers ou proches finance : `requisition_service.py`, `workflow_config.py`, `weekly_report.py`, notifications SaaS ;
- les exports/PDF convertissent souvent en float, acceptable pour affichage mais risqué si reutilise pour calcul ;
- politique d'arrondi non centralisee ;
- plusieurs comparaisons de montants utilisent une tolerance float (`0.01`) au lieu d'une comparaison Decimal explicite ;
- certains taux sont transformes en `float` avant stockage snapshot dans sorties.

Risque : erreurs d'arrondi, divergence subtile entre budget/tresorerie/comptabilite, surtout sur devises et paiements partiels.

## 8. Base de donnees

Points positifs :

- relations SQLAlchemy nombreuses et explicites ;
- contraintes d'unicite sur references par organisation ;
- contraintes CHECK sur plusieurs statuts/canaux/devises ;
- validations inter-tenant au flush ;
- pool configure et observable.

Points a corriger :

- index manquants probables sur `Encaissement.date_encaissement`, `Encaissement.created_at`, `Encaissement.reference`, `Encaissement.statut_paiement` ;
- index manquants probables sur `SortieFonds.date_paiement`, `SortieFonds.created_at`, `SortieFonds.statut` ;
- rapports/exports beneficieraient d'index composes `organisation_id + date`, `organisation_id + statut + date`, `organisation_id + canal + date` ;
- l'isolation par tenant sur SELECT est implicite ; les requetes brutes doivent rester explicitement filtrees ;
- bulk UPDATE/DELETE doivent etre encadres par repositories ou validations dediees.

## 9. Transactions financieres

Les transactions principales de creation d'encaissement et de sortie sont plutot bien regroupees : elles creent l'objet, mettent a jour budget/caisse/banque, generent la comptabilite et commitent a la fin.

Risques :

- absence d'unite de travail explicite ; chaque endpoint gere lui-meme commit/rollback ;
- `create_payment` ne synchronise pas la comptabilite ;
- soft-delete contourne les inversions financieres ;
- annulations avec solde insuffisant produisent des soldes tronques ;
- notifications et cache sont hors transaction, ce qui est acceptable, mais doit etre documente.

## 10. Securite

Points solides :

- JWT et refresh tokens raisonnablement securises ;
- secrets JWT refuses en production s'ils sont faibles ;
- cookies refresh correctement configures hors dev/test ;
- rate limiting auth ;
- uploads validates sur taille/type/extension/signature dans les pieces d'encaissement ;
- multi-tenant applique globalement en lecture.

Risques :

- debug active si `ENV=prod` ;
- bootstrap admin disponible sans garde explicite de production ;
- CORS permissif sur methodes/headers, acceptable si origins stricts mais a documenter ;
- Swagger/OpenAPI visibles par defaut ;
- absence de scan antivirus/quarantaine sur uploads ;
- identifiants de migration/demo presents via variables de config, a garantir absents en prod ;
- logs debug/tenant utiles mais doivent etre structures et verifies pour absence de tokens/secrets.

## 11. Multi-tenant

L'application dispose d'une protection avancée :

- contexte tenant par requete ;
- `with_loader_criteria` global sur SELECT ;
- assignation `organisation_id`/`tenant_id` au flush ;
- validation inter-tenant de relations sensibles ;
- resolution tenant depuis host/header/utilisateur.

Mais le modele reste fragile :

- nouveaux modeles doivent etre ajoutes manuellement a la liste du filtre global ;
- SQL brut non filtre peut fuiter ;
- `skip_tenant_scope` est necessaire pour super-admin mais dangereux ;
- exports/rapports doivent etre audites route par route ;
- les tests multi-tenant doivent couvrir SELECT, UPDATE, DELETE, SUM, COUNT, exports et rapports.

## 12. API et endpoints dangereux

Endpoints sensibles identifies :

| Endpoint | Impact | Protection observee | Appel frontend |
|---|---|---|---|
| `/debug/finance-sanity` | Agregats financiers multi-tenant | Admin role, monte hors `production` seulement | Non trouve |
| `/auth/bootstrap-admin` | Creation premier admin | Mot de passe bootstrap, seulement si aucun admin | Non trouve |
| `/budget/exercices/{annee}/cloture` | Cloture budget | Permission large `budget` | Oui |
| `/budget/exercices/{annee}/ouvrir` | Reouverture budget | Permission large `budget` | Oui |
| `/budget/postes/import` | Import/remplacement budget | Permission large `budget`, confirmation sur replace | Oui |
| `/payment-history` POST | Paiement partiel | Utilisateur courant/tenant, permission a verifier selon route | Oui |
| `/encaissements/{id}/soft-delete` | Masquage operation | Protection specifique insuffisante a durcir | Non trouve pour encaissements |
| `/encaissements/{id}/restore` | Restauration operation | Protection specifique insuffisante a durcir | Non trouve |
| `/encaissements/{id}/cancel-operation` | Annulation financiere | Permission `cancel_encaissement` | Oui |
| sortie statut/annulation | Annulation/reversal tresorerie | Permission `cancel_sortie_fonds`, limite 30 min | Oui |
| `/super-admin/organisations/{id}/simulate-payment` | Simulation paiement abonnement | Super-admin | Oui, API super-admin |

Routes inutilisees : une recherche statique frontend ne prouve pas l'absence d'usage externe. Les candidats a revue d'usage sont `/debug/*`, `/auth/bootstrap-admin`, soft-delete/restore encaissements, anciens endpoints desactives comme `change-password`.

## 13. Gestion des erreurs

Problemes observes :

- `except Exception` nombreux ;
- certains echecs de reporting sont transformes en valeurs `0` ;
- erreurs critiques parfois journalisees puis traitement poursuivi ;
- rollback manuel disperse.

Recommandation : classifier les erreurs finance en "bloquantes", "degradees", "non critiques", et interdire les valeurs de remplacement silencieuses pour les chiffres officiels.

## 14. Logs et observabilite

Existant :

- slow query logging ;
- slow request middleware ;
- audit logs metier ;
- logs tenant/user sur resolution tenant ;
- metrics conditionnelles avec protection en production.

A ajouter :

- request ID propage partout ;
- logs structures JSON en production ;
- user_id, organisation_id, route, duree, statut HTTP ;
- audit trail obligatoire pour cloture/reouverture/import/annulation/regularisation ;
- alerte sur divergence budget/tresorerie/comptabilite ;
- masquage systematique token, mot de passe, cookie, secret.

## 15. Performance

Risques a 50 utilisateurs :

- endpoints monolithiques difficiles a profiler ;
- exports volumineux lents mais probablement supportables sur petits historiques.

Risques a 100 utilisateurs :

- pool par defaut `5 + 10 overflow` peut devenir limite ;
- rapports avec agregats multiples et exports `.all()` peuvent bloquer ;
- generation PDF/Excel synchrone consomme CPU/memoire.

Risques a 500 utilisateurs :

- besoin de workers multiples, jobs async, file storage dedie, cache par tenant ;
- exports doivent etre asynchrones ;
- index composes deviennent obligatoires ;
- rapports financiers devraient utiliser vues/materialisations ou tables de synthese.

## 16. Tests

Etat mesure :

- collecte : 541 tests ;
- execution : 206 passes, 334 skipped, 1 failed ;
- echec : creation `/data` dans un environnement en lecture seule pendant l'import de `app.main`.

Couverture visible :

- auth, billing, budget imports, comptabilite, multi-tenant, tresorerie, regularisation, sorties partielles, secretariat.

Tests prioritaires manquants ou a renforcer :

- paiement partiel avec comptabilite automatique ;
- interdiction soft-delete operation active/payee ;
- debug non monte en `ENV=prod` ;
- annulation avec solde insuffisant ;
- exports/rapports entre deux tenants ;
- arrondis devises CDF/EUR/XOF ;
- cloture/reouverture budget avec permissions fines ;
- isolation multi-tenant sur SUM/COUNT/exports.

## 17. Code mort ou obsolete apparent

Candidats a revue, sans suppression :

- endpoint `change_password` desactive ;
- endpoints `/debug/*` ;
- anciens chemins de soft-delete/restauration pour operations financieres ;
- scripts de reset/backfill a separer clairement de l'application runtime ;
- fichiers `.pyc` et `.pytest_cache` presents dans l'arborescence ;
- migrations de seed/demo a verifier pour production.

## 18. Configuration

Points positifs :

- validation du JWT secret en prod ;
- cookies refresh securises hors dev/test ;
- uploads prives par defaut ;
- metrics token exige en prod si metrics active.

Points faibles :

- distinction `prod`/`production` incoherente sur debug ;
- Swagger non conditionne explicitement ;
- creation de repertoire upload au demarrage peut casser les tests si `UPLOAD_DIR=/data` non ecrivable ;
- variables bootstrap/default/migration password doivent etre interdites en production effective.

## 19. Migrations

Constats :

- 212 migrations ;
- plusieurs migrations seedent des permissions/roles ;
- plusieurs downgrades suppriment tables/colonnes ;
- migrations de tenant backfill mettent parfois `organisation_id = 1` pour donnees historiques.

Risques :

- rollback destructif ;
- donnees historiques mal rattachees si migration rejouee hors contexte attendu ;
- derives entre modeles et schema si migrations manuelles non testees.

Recommandations :

- test `alembic upgrade head` sur base vide et copie anonymisee ;
- revue des downgrades destructifs ;
- procedure de backup pre-migration ;
- migration contractuelle pour nouvelles tables tenant : index `organisation_id`, FK, test d'isolation.

## 20. Documentation

Documentation presente :

- `docs/ARCHITECTURE.md`
- `docs/ARCHITECTURE_DETAILED.md`
- docs performance 2026-08-03 ;
- docs comptabilite ;
- docs secretariat ;
- docs nginx uploads securises ;
- docs testing ;
- roadmap.

Manques :

- runbook incident financier ;
- procedure de reconciliation budget/tresorerie/comptabilite ;
- matrice permissions par endpoint critique ;
- politique d'arrondi officielle ;
- politique retention/audit logs ;
- checklist production env.

## 21. Architecture cible recommandee

Architecture cible progressive :

```text
app/
  api/
    v1/endpoints/          # HTTP uniquement : validation, auth, appel service
  services/
    finance/
      encaissement_service.py
      payment_service.py
      sortie_service.py
      cancellation_service.py
      treasury_ledger.py
      budget_execution.py
      exchange_rate.py
    budget/
      import_service.py
      exercise_service.py
    auth/
      rbac_service.py
  repositories/
    encaissements.py       # toutes les requetes avec tenant_id explicite
    sorties.py
    budget.py
    treasury.py
  core/
    money.py               # Decimal, arrondis, comparaisons
    unit_of_work.py        # transaction explicite
  modules/
    comptabilite/
    secretariat/
```

Principes :

- chaque operation financiere publique appelle un service transactionnel unique ;
- aucune mutation de solde directement dans un endpoint ;
- chaque repository exige `organisation_id` ;
- chaque operation critique ecrit un audit trail ;
- chaque recalcul/reouverture/remplacement demande permission fine + confirmation ;
- les exports lourds deviennent des jobs.

## 22. Roadmap

### Phase 1 - Securite et integrite financiere

1. Corriger l'exposition debug `prod`/`production`.
2. Bloquer soft-delete/restore des encaissements actifs/payes.
3. Brancher la comptabilite automatique sur `POST /payment-history`.
4. Remplacer les annulations `max(0, ...)` par blocage ou regularisation auditee.
5. Ajouter tests invariants critiques multi-tenant/finance.

### Phase 2 - Architecture

1. Extraire les services transactionnels encaissement, sortie, paiement, annulation.
2. Creer `core/money.py`.
3. Creer repositories avec `organisation_id` obligatoire.
4. Decouper `budget.py`, `encaissements.py`, `sorties_fonds.py`, `requisitions.py`.
5. Mettre en place une unite de travail.

### Phase 3 - Performance

1. Ajouter index composes sur dates/statuts/references par organisation.
2. Paginer ou streamer exports.
3. Passer gros PDF/Excel en jobs async.
4. Optimiser rapports avec agregats consolides.
5. Dimensionner pool/workers selon charge.

### Phase 4 - Tests

1. Tests E2E finance : encaissement, paiement partiel, sortie, annulation, cloture.
2. Tests multi-tenant sur SELECT/UPDATE/DELETE/SUM/COUNT/export.
3. Tests arrondis et conversion devises.
4. Tests permissions fines.
5. Tests migration `upgrade head`.

### Phase 5 - Nettoyage

1. Supprimer ou isoler endpoints debug et anciens endpoints desactives.
2. Retirer duplications `_clean_money`, `_get_or_create_caisse`, permissions locales.
3. Nettoyer caches `.pyc`/`.pytest_cache` hors livrable.
4. Completer runbooks production.
5. Documenter la matrice de risques et d'audit.
