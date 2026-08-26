# Scénarios de tests de charge ONEC Smart

Date de rédaction : 2026-08-26
Branche : `perf-write-contention-validation-20260803`

**Aucune campagne n'a été exécutée pour produire ce document.** Le démon Docker
est arrêté sur ce poste. Tous les nombres qui suivent sont soit des **cibles à
valider**, soit des **volumes à semer**, soit des **mesures déjà publiées dans
les rapports du dépôt**, et sont alors explicitement attribués à leur source.
Aucun temps de réponse, aucun débit n'est inventé ici.

Livrables :

- ce rapport ;
- les scripts dans `loadtest/` (voir §9 pour l'inventaire) ;
- la procédure de lancement dans `loadtest/README.md`.

Aucun fichier du dépôt n'a été modifié.

---

## 1. Inventaire de l'existant

Un travail de charge sérieux a déjà été fait. Trois phases, quatre documents,
un harnais complet.

### 1.1 Ce qui est en place dans le dépôt

| Artefact | Emplacement | Origine | Réutilisable tel quel ? |
|---|---|---|---|
| Harnais de charge asyncio/httpx | `backend/scripts/load_campaign.py` (675 lignes) | commit a67b5ec, étendu par 8003109 | **Oui pour le semis**, non pour le tir (voir §2) |
| Semis d'ossature | `load_campaign.py:163-434` (`seed_data`) | a67b5ec | Oui, réutilisé tel quel |
| Frappe de jetons directs | `load_campaign.py:451-462` (`direct_token`) | a67b5ec | Oui, principe repris |
| Nettoyage du tenant de charge | `backend/scripts/cleanup_load_test_org.py` | 8003109 | Oui |
| Pool DB paramétrable | `backend/app/core/config.py:77-79`, `backend/app/db/session.py:90-97` | 8003109 | Oui, c'est le levier à faire varier |
| Instrumentation pool (logs) | `backend/app/db/session.py:129-176` | 8003109 | Oui : `DB_POOL_AT_CAPACITY`, `DB_POOL_SLOW_USAGE`, `DB_SLOW_QUERY` |
| Compteurs SQL par requête HTTP | `backend/app/core/db_perf.py`, `backend/app/middleware/timing.py:64-91` | 8003109 | Oui : ligne `SLOW_REQUEST` avec `db_queries`, `db_conn_max_ms` |
| Endpoint Prometheus | `backend/app/core/metrics.py:34-61` | antérieur | Oui, `ENABLE_METRICS=true` |
| Test de concurrence des séquences | `backend/tests/test_document_sequences_concurrency.py` | Phase 3 | Oui, mais **hors HTTP** (voir §4) |
| 14 rapports JSON de campagnes passées | `backend/scripts/onec_load_*.json` | Phases 1 à 4 | Oui, comme base de comparaison historique |

### 1.2 Paliers déjà joués et résultats déjà publiés

Ces chiffres **sont des mesures existantes du dépôt**, pas les miennes :

- Phase 1 (`docs/PERFORMANCE_LOAD_AUDIT_20260803.md`) : paliers 100 / 250 / 500 /
  750 / 1000, tous en échec massif, cause racine `QueuePool limit of size 5
  overflow 10 reached`.
- Phase 3 (`docs/PERFORMANCE_WRITE_CONTENTION_20260803.md`) : paliers 10 / 25 /
  50 / 100, 1 worker, pool 10+10. Le palier 50 dépasse déjà la cible p95 < 2 s ;
  le palier 100 produit une erreur 500 par saturation de pool.
- Phase 4 (`docs/PERFORMANCE_WORKER_SCALING_20260817.md`) : le palier 100 passe
  le critère d'entrée avec 3 workers (0,26 % d'erreurs, p95 1,56 s). Diagnostic
  clé : **le goulot est le CPU d'un worker Python, pas PostgreSQL** — 46 % du
  temps CPU dans SQLAlchemy pendant que la base est inactive.

### 1.3 Ce que l'existant ne couvre pas — et que j'ajoute

Les manques ne sont pas de mon invention : ce sont les « travaux restants » de
la Phase 4 (section « Travaux restants, par valeur décroissante ») et la
« reserve n°1 » de sa Projection.

| Manque | Constat au dépôt | Ce que j'ajoute |
|---|---|---|
| **Volume de données** | Le tenant de charge compte 299 réquisitions et 245 encaissements (Phase 4, § « Environnement de mesure »). « À volume de production, le coût SQL monte et ajouter des workers ne corrigera pas ce déplacement du goulot. C'est le risque principal et il n'est pas couvert. » | `loadtest/seed/seed_volume.py` — voir §5 |
| **Générateur sur la même machine** | « Le générateur de charge tourne DANS le conteneur backend et dispute le CPU au serveur testé » (Phase 4) | Bascule sur k6, exécuté hors du conteneur — voir §2 |
| **Parcours d'écriture en chaîne** | `load_campaign.py:508-524` ne fait que `POST /requisitions` en brouillon et `POST /encaissements`. Aucun `validate`, aucun `vise`, aucune sortie de fonds, aucun export | 4 parcours d'écriture nouveaux — voir §3 |
| **Contention délibérée** | Les séquences ne sont testées qu'en appel direct au service Python (`test_document_sequences_concurrency.py:67-77`), jamais à travers la pile HTTP | `loadtest/k6/contention.js` — voir §4 |
| **Exports concurrents** | « Les exports PDF/Excel et imports Excel simultanés ne sont pas encore couverts dans le script » (Phase 1, § Goulots, priorité moyenne) | Parcours `export_excel` — voir §3.7 |
| **Seuils déclaratifs** | `load_campaign.py` calcule des percentiles mais ne juge rien : le pass/fail est fait à la main en lisant le JSON | Seuils k6 exécutables — voir §6 |
| **Validation du correctif prod** | `docker-compose.prod.yml` vient d'être corrigé, jamais rejoué sous charge | `loadtest/validate_prod_fix.sh` — voir §8 |

---

## 2. Choix de l'outil : k6

**Recommandation : k6 pour le tir, `load_campaign.py` conservé pour le semis et
la frappe des jetons.** Une seule variante est livrée.

Le raisonnement tient en un point, et ce point vient de la mesure déjà faite
dans le dépôt. La Phase 4 a établi que le système est limité par le CPU d'un
processus Python et que le générateur, tournant dans le conteneur backend, lui
disputait ce CPU. Continuer avec un générateur asyncio/httpx — donc Python,
donc GIL, donc coûteux par VU — c'est reconduire le biais que le rapport
lui-même désigne comme le principal défaut de méthode. k6 est un binaire Go :
son coût par utilisateur virtuel est d'un ordre de grandeur inférieur, il
s'exécute depuis une machine ou un conteneur séparé sans dépendance Python, et
il apporte nativement ce qui manque à `load_campaign.py` : des **seuils
exécutables** (`thresholds`) qui font échouer le tir quand p95 ou le taux
d'erreur dépasse la cible, au lieu d'un JSON à interpréter à la main.

Ce qui reste en Python, et pourquoi : le semis et la frappe des jetons ont
besoin des modèles SQLAlchemy et du `JWT_SECRET` de l'application. Les réécrire
en JavaScript serait un doublon fragile. `load_campaign.py --stages ""` sème
sans tirer, et `mint_tokens.py` réutilise `create_access_token`
(`backend/app/core/security.py:52`). La frontière est nette : Python prépare
l'état, k6 mesure.

Locust a été écarté pour la raison qui disqualifie `load_campaign.py` : c'est
du Python, avec le même coût par VU sur la machine de test.

### 2.1 Pourquoi les jetons sont pré-frappés

`POST /auth/login` est limité à **3 appels par 3 minutes et par IP**
(`backend/app/api/v1/endpoints/auth.py:307`, clé IP dans
`backend/app/core/limiter.py:33`), doublé d'un verrou Redis par
(IP, tenant, email) (`auth.py:67-99`). Depuis un générateur unique, tout
scénario qui se connecte mesure l'anti-bruteforce. C'est déjà la conclusion de
la Phase 1 (« Mode d'authentification de la charge : `direct-token` »).

Le parcours de connexion n'est pas abandonné pour autant : il est mesuré par un
scénario dédié à très bas débit (`login_probe`, 2 itérations par 3 minutes),
qui accepte `429` comme réponse informative et non comme échec.

---

## 3. Parcours couverts

Fichier : `loadtest/k6/journeys.js`. Chaque séquence est relevée dans le code,
avec la référence.

Répartition du parc de VU (proportions dérivées du mix de
`load_campaign.py:489-524`, complété par les écritures manquantes) :
dashboard 25 %, listes 25 %, rapports/budget 20 %, encaissement 12 %,
cycle de réquisition 8 %, sortie de fonds 5 %, export à débit fixe,
connexion à 2 itérations / 3 min.

### 3.1 Connexion puis tableau de bord — chemin critique

Connexion (`parcoursConnexion`) :

| # | Méthode | Chemin | Charge utile | Référence |
|---|---|---|---|---|
| 1 | POST | `/auth/login` | `{email, password, tenant_id}` + en-tête `X-Tenant-ID` | `auth.py:306` |
| 2 | GET | `/auth/me` | — | `auth.py:794`, appelé par `frontend/src/api/auth.ts:115` |
| 3 | GET | `/permissions/menu` | — | `permissions.py:17`, `frontend/src/api/permissions.ts:4` |

Tableau de bord (`parcoursDashboard`) — le front lance **cinq appels en
parallèle** dans un unique `Promise.all` (`frontend/src/pages/Dashboard.tsx:279-288`),
reproduit à l'identique par `http.batch` :

| # | Méthode | Chemin | Référence |
|---|---|---|---|
| 1 | GET | `/auth/me` | `auth.py:794` |
| 2 | GET | `/permissions/menu` | `permissions.py:17` |
| 3 | GET | `/dashboard/stats?period_type=month&date_debut=…&date_fin=…&devise=USD` | `dashboard.py:77` |
| 4 | GET | `/dashboard/stats?…&devise=CDF` | idem, seconde devise |
| 5 | GET | `/budget/summary` | `budget.py:985` |
| 6 | GET | `/tresorerie/soldes` | `treasury.py:35` |
| 7 | GET | `/print-settings` | `frontend/src/api/settings.ts:67` |

Point d'attention : `/dashboard/stats` a un cache Redis de 60 s
(`dashboard.py:33`, lecture en `dashboard.py:104`, écriture en `dashboard.py:519`) et `/reports/summary` un cache de 15 s
(`REPORT_SUMMARY_CACHE_TTL_SECONDS`, `docker-compose.yml:74`). Les scénarios
font **varier les bornes de dates** pour ne pas mesurer le cache à la place de
la base.

### 3.2 Consultation et filtrage d'une grosse liste

`parcoursListes` :

| # | Méthode | Chemin | Pourquoi ce cas |
|---|---|---|---|
| 1 | GET | `/encaissements?limit=50&offset=0&include_summary=true&include=expert_comptable&date_debut=…&date_fin=…` | ouverture d'écran, `encaissements.py:773` |
| 2 | GET | `/encaissements?…&statut_paiement=complet&canal=CAISSE&budget_poste_id=…` | filtrage combiné |
| 3 | GET | `/encaissements?limit=50&offset=1000..5000&order=date_encaissement.desc` | pagination profonde : tri sur un gros ensemble |
| 4 | GET | `/requisitions?include=demandeur,validateur,approbateur,examinateur,caissier&type_requisition=classique&date_debut=…&date_fin=…&limit=5000&offset=0` | **le pire cas de lecture de l'application** |
| 5 | GET | `/requisitions?service_id=…&status=APPROUVEE&limit=200` | filtrage par service |
| 6 | GET | `/requisitions?search=charge&limit=200` | recherche `ILIKE` sur trois colonnes + sous-requête utilisateurs (`requisitions.py:1005-1020`) |
| 7 | GET | `/experts-comptables?include_summary=true&limit=50` | endpoint listé comme coûteux en Phase 3 |

Le cas 4 n'est pas une exagération de ma part : le front demande réellement
`limit: 5000` avec cinq relations jointes, la liste n'étant pas paginée côté
client (`frontend/src/pages/Requisitions.tsx:293-308`). L'endpoint accepte
jusqu'à 5000 (`requisitions.py:950`). Sur une base à 60 000 réquisitions, c'est
là que se joue la tenue en charge des lectures.

### 3.3 Saisie d'un encaissement (écriture)

`parcoursEncaissement` :

| # | Méthode | Chemin | Charge utile | Référence |
|---|---|---|---|---|
| 1 | GET | `/comptes-bancaires?active=true` | — | `banques.py:277`, chargé par `frontend/src/pages/Encaissements.tsx:279` |
| 2 | POST | `/encaissements` | `{type_client, client_nom, libelle, montant, montant_total, montant_paye, montant_percu, mode_paiement:"cash", canal:"CAISSE", devise_perception:"USD", statut_paiement:"complet", budget_poste_id, service_id}` | `encaissements.py:1239` |

`409` est accepté comme réponse métier (détection d'opération en double,
`encaissements.py:1428-1430`), pas comptabilisé en erreur.

### 3.4 Cycle de réquisition : création → validation technique → visa

`parcoursCycleRequisition`. **Attention au vocabulaire** : dans ce code, le
« visa » (`/vise`) est la validation **finale**, et la validation technique
(`/validate`) la précède. La chaîne réelle est donc création → `validate` →
`vise` :

| # | Méthode | Chemin | Charge utile / permission | Référence |
|---|---|---|---|---|
| 1 | GET | `/budget/lines/autorisees?type=DEPENSE&active=true&service_id=…` | — | `budget.py:1886`, appelé à chaque changement de service (`frontend/src/pages/Requisitions.tsx:345`) |
| 2 | POST | `/requisitions` | `{objet, mode_paiement:"cash", type_requisition:"classique", montant_total, devise:"USD", service_id, a_valoir:false, decaissement_progressif:false, lignes:[{budget_poste_id, rubrique, description, quantite, montant_unitaire, montant_total, devise}]}` — permission `can_create_requisition` | `requisitions.py:1825` |
| 3 | POST | `/requisitions/{id}/validate` | corps vide — permission `can_verify_technical` | `requisitions.py:2007` |
| 4 | POST | `/requisitions/{id}/vise` | corps vide — permission `can_validate_final` | `requisitions.py:2071` |

Trois contraintes fonctionnelles que le scénario doit respecter, sous peine de
mesurer des `400` au lieu de la charge réelle :

1. **Deux comptes distincts sont obligatoires.** `vise_requisition_logic` refuse
   le viseur qui a déjà validé : « Une autre personne doit viser cette
   réquisition » (`backend/app/services/requisition_service.py:923-927`). Le
   scénario prend `adminToken(0)` pour créer et valider, `adminToken(1)` pour
   viser.
2. **Le circuit de validation doit être réduit.** Le préréglage par défaut est
   `complet` (`backend/app/services/workflow_config.py:52`) : la réquisition
   naît alors en `BROUILLON` et exige signature de service puis examen avant
   d'atteindre `EN_ATTENTE`. `seed_volume.py` force le tenant de charge sur le
   préréglage `simplifie` (`workflow_config.py:40`), ce qui rend la chaîne
   jouable en trois appels : `EN_ATTENTE` → `AUTORISEE` → `APPROUVEE`
   (`workflow_config.py:123-129`).
3. **Le montant compte.** Si un seuil est posé sur `validation_2`, la seconde
   validation peut être sautée (`workflow_config.py:163-166`). Aucun seuil n'est
   posé sur le tenant de charge.

### 3.5 Sortie de fonds

`parcoursSortieFonds` :

| # | Méthode | Chemin | Charge utile | Référence |
|---|---|---|---|---|
| 1 | GET | `/sorties-fonds/requisitions/{id}/solde` | — | `sorties_fonds.py:804` |
| 2 | POST | `/sorties-fonds` | `{type_sortie:"requisition", requisition_id, service_id, budget_poste_id, montant_paye, mode_paiement:"cash", devise:"USD", canal:"CAISSE", motif, beneficiaire}` — permission `can_execute_payment` | `sorties_fonds.py:1040` |

La réquisition visée doit être en `APPROUVEE` ou `EN_DECAISSEMENT`
(`sorties_fonds.py:1260-1263`). `mint_tokens.py` exporte un stock de
réquisitions `APPROUVEE` ; chaque itération en consomme **une seule**, indexée
par `exec.scenario.iterationInTest` (unique sur tout le tir), pour que deux VU
ne se disputent jamais la même réquisition — sinon le second reçoit un `400`
« montant déjà payé » et le taux d'erreur ne veut plus rien dire.

### 3.6 Consultation budget et rapports (lectures lourdes)

`parcoursRapports` :

| # | Méthode | Chemin | Référence |
|---|---|---|---|
| 1 | GET | `/budget/postes/tree?annee=…&type=DEPENSE` | `budget.py:1738` (optimisé en Phase 3, projection de colonnes) |
| 2 | GET | `/budget/postes/tree?annee=…&type=RECETTE` | idem |
| 3 | GET | `/budget/lines/autorisees?type=DEPENSE&active=true&service_id=…` | `budget.py:1886` |
| 4 | GET | `/budget/lines/tree?annee=…` | `budget.py:2008` |
| 5 | GET | `/reports/summary?date_debut=…&date_fin=…` | `reports.py:135` — 15-16 requêtes SQL à froid (Phase 3) |
| 6 | GET | `/reports/synthese-annuelle?year=…&devise=USD&canal=ALL` | `reports.py:1043` — SQL brut avec `EXTRACT(MONTH …)` |
| 7 | GET | `/reports/top-depenses?date_debut=…&date_fin=…` | `reports.py:1195` |
| 8 | GET | `/reports/journal-tresorerie?canal=CAISSE&devise=USD&date_debut=…&date_fin=…` | `reports.py:1245` |

### 3.7 Export (chemin coûteux en CPU)

`parcoursExport`, en `constant-arrival-rate` (4 exports/minute par défaut) et
non proportionnel aux VU : un export est un pic, pas un geste répété par tous.

| Chemin | Référence |
|---|---|
| `GET /exports/encaissements?date_debut=…&date_fin=…&est_proforma=false` | `exports.py:1165` |
| `GET /exports/requisitions?date_debut=…&date_fin=…&type_requisition=classique` | `exports.py:1764` |
| `GET /exports/budget?annee=…` | `exports.py:488` |

C'est le parcours le plus directement branché sur le goulot identifié en
Phase 4 : le rendu `openpyxl` s'exécute **dans le worker**, occupe un cœur
Python pendant toute la génération, et `openpyxl` est justement le seul import
lourd que la Phase 4 a décidé de ne pas traiter. Sur une base à 120 000
encaissements, un export sur un an n'est plus une opération anodine.

---

## 4. Points de contention ciblés explicitement

Fichier dédié : `loadtest/k6/contention.js`, trois modes (`MODE=nd|req|pay`).
Le principe est l'inverse du scénario métier : là où `journeys.js` répartit les
écritures sur 8 services et 300 postes, `contention.js` fait viser **la même
ligne de base** par tous les VU.

### 4.1 Séquence `ND` — la plus dure

`_generate_numero_recu` appelle `generate_document_number(db, "ND", tenant_id,
service_id=None)` (`backend/app/api/v1/endpoints/encaissements.py:690`). Le
`service_id` est `None`, donc la clé fonctionnelle est
`(doc_type, year, tenant_id)` : **une seule ligne de `document_sequences` pour
tout le tenant**. Chaque `POST /encaissements` de toute l'organisation passe par
cette ligne. C'est le point de sérialisation le plus dur de l'application, et il
n'est couvert par aucun test existant à travers HTTP.

Le mécanisme actuel est la réservation atomique
`INSERT … ON CONFLICT DO UPDATE … RETURNING counter`
(`backend/app/services/document_sequences.py:23-52`), qui a remplacé en Phase 3
un `SELECT … FOR UPDATE`. Le contrat revendiqué est l'unicité et l'ordre
croissant ; l'absence de trous **n'est pas** revendiquée
(`docs/PERFORMANCE_WRITE_CONTENTION_20260803.md`, § « Garantie non
revendiquée »). Le dépouillement SQL en tient compte : la section 7 de
`observe/pg_after.sql` compare compteur et documents réels sans en faire un
échec, tandis que la section 6 (doublons) doit renvoyer **zéro ligne**.

Le même appel empile trois autres foyers sur la même transaction :

- boucle de **50 tentatives** en cas de collision de numéro
  (`encaissements.py:1437-1439`) — sous contention, chaque tentative refait un
  aller-retour SQL ;
- `SELECT … FOR UPDATE` sur `budget_postes` pour cumuler `montant_paye`
  (`encaissements.py:309-315`) : en mode contention, tous les VU pointent le
  **même poste**, donc la mise à jour est sérialisée ;
- `SELECT … FOR UPDATE` sur `caisse_centrale`, ligne unique par organisation.

### 4.2 Séquence `REQ` — par service

`create_requisition_logic` réserve le numéro avec le `service_id` de la
réquisition (`backend/app/services/requisition_service.py:463`), donc la clé est
`(doc_type, year, tenant_id, service_id)`. En pointant **un seul service**,
`MODE=req` reproduit exactement le scénario de
`backend/tests/test_document_sequences_concurrency.py:67-77` (10 / 25 / 50 /
100 réservations concurrentes) — mais à travers la pile HTTP complète, avec le
JWT, le RBAC, le pool et la transaction métier, au lieu d'un appel direct au
service Python. C'est la différence qui compte : le test unitaire prouve la
correction de l'algorithme, il ne dit rien de son coût sous charge réelle.

Le mode enchaîne ensuite `validate` puis `vise` sur la réquisition qui vient
d'être créée, ce qui exerce en plus :

- le `SELECT … with_for_update()` de `vise_requisition_logic`
  (`requisition_service.py:912-916`) et de `update_requisition_logic`
  (`requisition_service.py:657-672`) ;
- le recalcul de `montant_engage` par `UPDATE budget_postes … SET
  montant_engage = (sous-requête corrélée)`
  (`backend/app/services/budget_engagement.py:97-103`), tous les VU visant le
  **même poste** ;
- le trigger `trg_requisitions_immutable_after_final`
  (`alembic/versions/20260723b_historical_document_snapshots.py:145`), qui
  s'exécute à chaque `UPDATE` de réquisition.

### 4.3 Séquence `PAY` + verrou caisse

`POST /sorties-fonds` réserve un numéro `PAY` par service
(`sorties_fonds.py:1603`) puis verrouille `caisse_centrale` en `FOR UPDATE`
(`sorties_fonds.py:1564-1566`). Toutes les sorties en canal `CAISSE` d'une même
organisation frappent **la même ligne**. `MODE=pay` provoque cette collision
délibérément.

### 4.4 Ce que le tir de contention doit prouver

- Zéro doublon de numéro (`observe/pg_after.sql`, section 6) — c'est un contrat
  fonctionnel, pas une métrique de performance.
- Zéro `5xx` : le compteur `erreurs_5xx` est un seuil dans `contention.js`.
- Aucun `deadlock` (`pg_stat_database.deadlocks`, section 5).
- Une latence qui se dégrade de façon **prévisible** avec la concurrence, et non
  en falaise. C'est le seul indicateur qui distingue une file d'attente saine
  d'un effondrement.

---

## 5. Jeu de données

Un test sur une base vide ne mesure rien : c'est la réserve n°1 de la Phase 4,
formulée par le dépôt lui-même. Le tenant de charge actuel compte 299
réquisitions et 245 encaissements.

Script : `loadtest/seed/seed_volume.py`, préréglage `production` par défaut.

### 5.1 Volumes cibles

| Table | Cible `production` | Justification |
|---|---|---|
| `organisations` | 1 (`load-test-20260803`) | tenant existant, réutilisé |
| `services` | 8 | fait travailler 8 lignes de séquence `REQ` et `PAY` en parallèle ; le mode contention en pointe une seule |
| `users` | 400 (semés par `load_campaign.py`) | ≥ 1 compte par VU pour que le cache d'auth (TTL 30 s) se comporte comme en production |
| `budget_postes` | 300, arbre à 2 niveaux (1 parent / 10 enfants) | `budget/postes/tree` doit construire un arbre réel ; la Phase 3 mesurait sur 127 postes à plat |
| `service_rubriques` | 8 × 300 = 2 400 | autorise chaque service sur chaque poste : sans cela, `build_ligne_requisition` refuse les lignes |
| `requisitions` | 60 000, réparties sur 24 mois | la liste front demande `limit=5000` : il faut de quoi la remplir |
| `lignes_requisition` | ≈ 120 000 (1 à 3 par réquisition) | alimente le recalcul d'engagement et l'export |
| `encaissements` | 120 000 | table la plus lue et la plus écrite |
| `sorties_fonds` | 40 000 | adossées aux réquisitions `PAYEE` |
| `experts_comptables` | 6 000 | `experts_list` était à p95 5,73 s en Phase 3 sur 1 584 experts |
| `document_sequences` | repositionnées | sinon la première écriture de l'API régénère un numéro déjà pris |

Répartition des statuts de réquisition : ≈ 35 % `PAYEE`, 20 % `APPROUVEE`,
10 % `AUTORISEE`, 25 % `EN_ATTENTE`, 10 % `REJETEE`. Les `APPROUVEE` constituent
le stock consommé par le parcours sortie de fonds ; les `EN_ATTENTE` donnent du
travail réel aux filtres.

Préréglages plus légers : `--preset smoke` (≈2 min, pour valider le script) et
`--preset pilote` (intermédiaire).

### 5.2 Contraintes que le semis doit respecter

Ce ne sont pas des détails d'implémentation : les ignorer donne une base
incohérente qui fait échouer le tir pour de mauvaises raisons.

1. **Ordre d'insertion imposé par un trigger.**
   `trg_lignes_requisition_immutable_after_final`
   (`alembic/versions/20260723b_historical_document_snapshots.py:171`) refuse
   toute insertion de ligne sur une réquisition `APPROUVEE`, `PAYEE` ou
   `EN_DECAISSEMENT`. Le semis insère donc les réquisitions en `EN_ATTENTE`,
   puis les lignes, puis met les statuts à jour — l'`UPDATE` passe parce que le
   trigger de réquisition ne bloque que si `OLD.status` est déjà final
   (`…:104`).
2. **Séquences repositionnées.** Les numéros semés respectent exactement le
   format de `document_sequences.py:55-66` (`REQ-{CODE}-{année}-{5 chiffres}`,
   `ND-{année}-{6 chiffres}`), et les compteurs sont remis au maximum utilisé,
   par type / année / service.
3. **Provision de trésorerie.** Les scénarios d'écriture décaissent réellement.
   Sans provision, la caisse tombe à zéro et les `POST /sorties-fonds`
   répondent `400 Fonds insuffisants` (`sorties_fonds.py:1591-1595`). Le semis
   provisionne `caisse_centrale` et les comptes bancaires.
4. **Circuit de validation.** Préréglage `simplifie` posé sur
   `organisation_settings.workflow_config` (voir §3.4).
5. **`ANALYZE`** sur les tables chargées : sans statistiques à jour, le
   planificateur PostgreSQL choisit des plans qui ne seront jamais ceux de la
   production.

### 5.3 Nettoyage

`backend/scripts/cleanup_load_test_org.py --slug load-test-20260803 --org-id <ID>
--confirm`, déjà présent dans le dépôt (commit 8003109).

---

## 6. Paliers et critères

### 6.1 Profil de montée en charge

Chaque palier : montée d'une minute, puis 10 minutes en régime établi, puis
60 secondes de stabilisation avant le suivant. Le script attend `/health/ready`
avant chaque tir — le démarrage applicatif prend 34 à 50 s (Phase 4), et un
palier lancé trop tôt mesure le démarrage à froid, anomalie explicitement
identifiée en Phase 3.

| Palier | VU | Durée | Rôle |
|---|---|---|---|
| A | 10 | 10 min | référence à froid, détecte les régressions unitaires |
| B | 25 | 10 min | premier palier où la Phase 3 voyait la latence bouger |
| C | 50 | 10 min | palier qui dépassait la cible p95 en Phase 3 avec 1 worker |
| **D** | **100** | **10 min** | **palier de non-régression** — voir §8 |
| E | 200 | 10 min | objectif de la Phase 4 non encore atteint (« Valider 200 utilisateurs, générateur sur une machine SÉPARÉE ») |
| F | 100 | 60 min | endurance : fuite mémoire, dérive de latence, recyclage du pool (`DB_POOL_RECYCLE=1800`) |

Le palier E ne se lance qu'après validation de D, et son échec attendu est
informatif, pas disqualifiant : la projection de la Phase 4 chiffre 200
utilisateurs à ≈ 6 workers, ce que la machine de test ne fournit peut-être pas.

Think time 0,5 à 8 s selon l'écran, aligné sur le profil « réaliste » de
`load_campaign.py:623-627` mais différencié : on reste plus longtemps sur un
tableau de bord que sur une liste.

### 6.2 Seuils de réussite / échec

**Ce sont des cibles à valider, pas des résultats.** Elles sont dérivées du
critère d'entrée retenu par la Phase 4 (erreurs < 1 %, p95 < 3 s), décliné par
parcours : un tableau de bord et un export Excel n'ont pas le même budget de
latence. Elles sont codées en `thresholds` dans `journeys.js`, donc exécutables :
k6 sort en code d'erreur si l'une d'elles n'est pas tenue.

| Parcours | p50 | p95 | p99 | Taux d'erreur |
|---|---|---|---|---|
| Tableau de bord | < 400 ms | < 1,5 s | < 3 s | < 0,5 % |
| Listes et filtres | < 600 ms | < 2 s | < 4 s | < 1 % |
| Budget et rapports | < 900 ms | < 3 s | < 6 s | < 1 % |
| Encaissement (écriture) | < 700 ms | < 2 s | < 4 s | < 1 % |
| Cycle de réquisition (par appel) | < 800 ms | < 2,5 s | < 5 s | < 1 % |
| Cycle complet (3 écritures) | — | < 7 s | — | — |
| Sortie de fonds | < 900 ms | < 2,5 s | < 5 s | < 1 % |
| Export Excel | — | < 10 s | < 20 s | < 2 % |
| Connexion | — | < 2 s | — | hors `429` |
| **Global** | — | — | — | **< 1 %** |

Quatre critères **binaires**, qui priment sur les percentiles :

1. **Zéro `5xx`.** Compteur `erreurs_5xx`, seuil `count<1`.
2. **Zéro `502`/`503`/`504`.** Compteur `reponses_saturation` : ce sont les
   codes d'un worker tué ou d'un backend qui refuse. Un p95 excellent obtenu
   avec des 502 dans le lot est un faux succès.
3. **Zéro `QueuePool limit` dans les journaux backend.** Comptés automatiquement
   par `run_campaign.sh` après chaque palier.
4. **Zéro doublon de numérotation** (`observe/pg_after.sql`, section 6).

Sont explicitement **exclus** du taux d'erreur, car ce sont des réponses
métier correctes : `409` sur `POST /encaissements` (doublon détecté,
`encaissements.py:1428-1430`) et `429` sur `/auth/login` (anti-bruteforce).

### 6.3 Configurations à faire varier

Un palier n'a de sens qu'attaché à une configuration. Les deux leviers, tous
deux déjà paramétrables grâce au commit 8003109 :

- `BACKEND_WORKERS` : 1, 2, 3, 4 — la Phase 4 a mesuré une croissance
  quasi linéaire du débit avec le nombre de workers ;
- `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT`.

Garde-fou à vérifier avant chaque montée : le budget de connexions vaut
`workers × (pool_size + max_overflow)` et doit rester sous le `max_connections`
de PostgreSQL (100 par défaut) — la relation est déjà loguée au démarrage par
`log_pool_configuration` (`backend/app/db/session.py:115-128`).

---

## 7. Métriques serveur à collecter pendant le tir

Script : `loadtest/observe/server_metrics.sh` (échantillonnage toutes les 5 s),
requêtes : `observe/pg_before.sql` et `observe/pg_after.sql`.

### 7.1 CPU et mémoire par conteneur — la métrique décisive

`docker stats` sur `backend`, `db`, `redis`, échantillonné en continu. C'est
**la** métrique qui a permis à la Phase 4 de corriger le diagnostic de la
Phase 3 : le worker collé à 100 % d'un cœur pendant que PostgreSQL restait
inactif prouvait que les délais d'attente du pool étaient un symptôme et non la
cause. Sans cette courbe, on refait la même erreur d'interprétation.

À lire côte à côte : si `backend` sature et `db` non, ajouter des workers ; si
`db` sature, ce sont les requêtes ou les index qu'il faut traiter — et c'est
précisément ce que le passage à un volume réaliste (§5) peut faire basculer.

### 7.2 Connexions et saturation du pool

Trois sources complémentaires :

- `pg_stat_activity` groupé par `state`, échantillonné (fichier
  `_pg_activity.csv`) ;
- les journaux du backend : `DB_POOL_AT_CAPACITY` (émis pile quand
  `checked_out == pool_size + max_overflow`, `session.py:140-141`),
  `DB_POOL_SLOW_USAGE` (connexion gardée au-delà de
  `DB_POOL_SLOW_CHECKOUT_SECONDS`, `session.py:151-157`) et le message
  `QueuePool limit of size … reached` de SQLAlchemy ;
- `max_connections` comparé au budget `workers × (pool_size + max_overflow)`.

### 7.3 `pg_stat_statements`

`SELECT pg_stat_statements_reset()` avant chaque palier, dépouillement après :
top 25 par temps cumulé (ce qui coûte au total) **et** top 25 par temps moyen
sur plus de 20 appels (ce qui trahit un index manquant). L'extension exige
`shared_preload_libraries` ; le bloc `command:` à ajouter dans un override
local est donné en tête de `observe/pg_before.sql` — à ne pas mettre dans le
dépôt.

### 7.4 Ce que le backend loue déjà de lui-même

Le dépôt est mieux instrumenté qu'il n'y paraît, ces sources sont gratuites :

- `SLOW_REQUEST` au-delà de 500 ms, avec `db_queries`, `db_total_ms`,
  `db_slowest_ms`, `db_conn_max_ms` et l'énoncé SQL le plus lent
  (`backend/app/middleware/timing.py:74-91`). C'est ce qui a permis de chiffrer
  « `encaissement_create` : 19-20 requêtes SQL » en Phase 3 — à rejouer pour
  vérifier si la réduction demandée a eu lieu.
- `DB_SLOW_QUERY` au-delà de `DB_SLOW_QUERY_MS` (500 ms par défaut),
  `session.py:171-176`.
- `/metrics` Prometheus si `ENABLE_METRICS=true` (`app/core/metrics.py:34`),
  dont le compteur `onec_cpk_slow_requests_total` par méthode et chemin.

### 7.5 Verrous et santé de la base

`pg_stat_activity` filtré sur `wait_event IS NOT NULL` groupé par type — c'est
là que la contention d'écriture du §4 devient visible. Plus
`pg_stat_database` : `xact_rollback` rapporté à `xact_commit` (la Phase 1
relevait 3 463 rollbacks pour 2 334 commits, signal d'échecs en masse),
`deadlocks`, taux de cache, fichiers temporaires.

### 7.6 Profil CPU du worker, si le CPU sature

`py-spy record --pid <pid> --duration 60 --output profil.svg` **en mode
bloquant**. La Phase 4 documente précisément le piège : un relevé
`--nonblocking` attribuait 93,8 % du temps à une seule ligne, artefact de piles
incohérentes. Seul le mode bloquant est exploitable.

---

## 8. Validation du correctif de `docker-compose.prod.yml`

### 8.1 Ce qui était cassé

Avant correction, le service `backend` de `docker-compose.prod.yml` n'avait ni
`command:` ni variables `DB_POOL_*`. Deux conséquences qui se combinent :

- le conteneur exécutait le `CMD` de l'image (`backend/Dockerfile:27` :
  `gunicorn -w 4 -k uvicorn.workers.UvicornWorker …`, **sans `--timeout`**, donc
  arbitre au défaut de 30 s), ce qui rendait `BACKEND_WORKERS` inopérant ;
- le pool prenait les défauts du code : `pool_size=5`, `max_overflow=10`,
  `pool_timeout=30` (`backend/app/core/config.py:77-79`).

Le `pool_timeout` valait donc **exactement** le `--timeout` de gunicorn : une
requête atteignait la limite du pool à l'instant même où l'arbitre tuait le
worker — et un `UvicornWorker` tué emporte avec lui toutes ses requêtes
concurrentes. La configuration de développement, elle, avait reçu le correctif
dès le commit 8003109 ; la production ne l'avait jamais reçu.

Après correction : `command:` gunicorn explicite avec `--timeout 120`,
`--graceful-timeout 30`, et `DB_POOL_TIMEOUT=5`. Rapport de 24 entre le délai du
pool et celui de l'arbitre : le pool échoue vite et proprement, bien avant que
l'arbitre n'intervienne.

### 8.2 Le palier qui saturait l'ancienne configuration

**Le palier D, 100 VU, est le palier de non-régression.** Il n'est pas choisi
au hasard : c'est celui qui échouait dans toutes les phases antérieures — 100 %
de délais dépassés en Phase 1, erreur 500 par saturation de pool en Phase 3,
36,51 % d'erreurs à la re-baseline de la Phase 4. C'est donc le palier qui
discrimine.

### 8.3 Protocole A/B

`loadtest/validate_prod_fix.sh` joue **deux fois le même palier 100 VU** contre
`docker-compose.prod.yml`, en ne changeant que des variables d'environnement —
aucun fichier n'est modifié, le compose utilisant partout la forme
`${VAR:-défaut}` :

| Configuration | `BACKEND_TIMEOUT` | `DB_POOL_SIZE` | `DB_MAX_OVERFLOW` | `DB_POOL_TIMEOUT` |
|---|---|---|---|---|
| `avant_correctif` (reproduit l'ancien état) | 30 | 5 | 10 | 30 |
| `apres_correctif` (état actuel du fichier) | 120 | 5 | 5 | 5 |

Comparaison sur cinq signaux, dont trois viennent des journaux et non de k6 :

1. taux d'erreur global et p95 par parcours ;
2. nombre de réponses `502` / `503` / `504` (compteur `reponses_saturation`) ;
3. occurrences de `WORKER TIMEOUT` dans les journaux gunicorn — **c'est la
   signature directe du défaut corrigé** ;
4. occurrences de `QueuePool limit` et `DB_POOL_AT_CAPACITY` ;
5. `pg_stat_database.xact_rollback` rapporté aux commits.

Le correctif est validé si, à 100 VU, la configuration corrigée tient les
seuils du §6.2 là où l'ancienne produit des `WORKER TIMEOUT` et des `502`. Si
les deux configurations échouent, le correctif de compose n'est pas en cause et
il faut remonter au nombre de workers (§6.3) — la Phase 4 a montré que le débit
croît quasi linéairement avec eux.

---

## 9. Inventaire de ce qui est livré

```
loadtest/
├── README.md                  procédure de lancement en 8 étapes
├── run_campaign.sh            enchaîne les paliers, attend /health/ready,
│                              archive résumé k6 + JSON brut + journaux backend
├── validate_prod_fix.sh       A/B du correctif docker-compose.prod.yml (§8)
├── seed/
│   ├── seed_volume.py         semis de volume (§5) — complète load_campaign.py
│   └── mint_tokens.py         frappe des jetons + contexte pour k6 (§2.1)
├── k6/
│   ├── lib.js                 helpers partagés, chargement du contexte
│   ├── journeys.js            les 7 parcours + seuils exécutables (§3, §6.2)
│   └── contention.js          contention délibérée, 3 modes (§4)
└── observe/
    ├── server_metrics.sh      docker stats + pg_stat_activity toutes les 5 s
    ├── pg_before.sql          remise à zéro des compteurs, état initial
    └── pg_after.sql           pg_stat_statements, verrous, contrat de
                               numérotation, index et scans séquentiels
```

Réutilisé sans modification depuis le dépôt :
`backend/scripts/load_campaign.py` (mode semis, `--stages ""`),
`backend/scripts/cleanup_load_test_org.py`,
l'instrumentation de `backend/app/db/session.py` et
`backend/app/middleware/timing.py`,
et `backend/tests/test_document_sequences_concurrency.py` comme référence de
correction pour le §4.

---

## 10. Limites assumées

- **Rien n'a été exécuté.** Ces scénarios sont prêts à lancer ; ils n'ont pas
  été rodés contre une instance vivante. Le premier tir doit se faire en
  `--preset smoke` pour valider la mécanique avant d'engager le semis complet.
- Le générateur doit tourner sur une **machine séparée** pour que les mesures
  soient comparables à la production. Sur une machine unique, les valeurs
  absolues restent inexploitables — c'est déjà la conclusion de la Phase 4.
- Le frontend n'est pas couvert : ces scénarios mesurent l'API. Le rendu Chrome
  et Edge, resté « à faire » depuis la Phase 1, demande Playwright ou Lighthouse
  et sort du périmètre demandé ici.
- Les uploads (annexes de réquisition, pièces justificatives) et les imports
  Excel ne sont pas couverts : ils exigent des fichiers binaires réalistes, et
  la Phase 1 les avait déjà classés en priorité moyenne.
