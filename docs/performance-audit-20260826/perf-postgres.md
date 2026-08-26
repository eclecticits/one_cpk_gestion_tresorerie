# Audit de performance PostgreSQL — ONEC Smart

Date : 2026-08-26
Périmètre : `backend/app/models/`, `backend/alembic/versions/` (232 fichiers), `backend/app/api/v1/endpoints/`
Base de données : **non accessible** (Docker arrêté, le PostgreSQL local sur 5432 n'est pas celui de l'application).

## Méthode et convention de preuve

Aucun `EXPLAIN`, aucun `pg_stat_*`, aucune volumétrie réelle n'a pu être obtenu. Tout ce
qui suit est établi à partir du schéma **tel que déclaré** (migrations + modèles) et des
requêtes **telles qu'écrites** dans le code.

- **MESURÉ** = chiffre repris des campagnes de charge déjà consignées dans
  `docs/PERFORMANCE_SQL_OPTIMIZATION_20260803.md` et
  `docs/PERFORMANCE_WRITE_CONTENTION_20260803.md`. Ces mesures viennent d'un jeu de test
  (organisation `load-test-20260803`, ~13 lignes dans `document_sequences`, 127 postes
  budgétaires) : elles disent la contention et le nombre de requêtes, **pas** le
  comportement à volume de production.
- **DÉDUIT** = raisonnement sur le schéma et le code. Aucun plan d'exécution n'est
  affirmé. Là où le plan choisi par PostgreSQL décide de l'ampleur du gain, je le dis.

Inventaire reconstitué par parsing AST des 232 migrations (`create_index`, `op.execute("CREATE INDEX …")`,
`UniqueConstraint`, `create_unique_constraint`, moins les `drop_index`/`DROP CONSTRAINT`)
recoupé avec `Base.metadata` obtenu en important les 60 modules de `app/models/` plus
`app/modules/comptabilite/models.py` et `app/modules/secretariat/models.py`.
Total relevé : **425 index sur 116 tables**.

---

# 1. Inventaire des index existants

## 1.1 Migration de performance déjà appliquée

Deux migrations de performance existent déjà. **Aucune proposition ci-dessous ne les double.**

`backend/alembic/versions/20260722d_perf_indexes.py` :

| Index | Colonnes |
|---|---|
| `ix_enc_org_date` | `encaissements (organisation_id, date_encaissement)` |
| `ix_sorties_org_paiement_ts` | `sorties_fonds (organisation_id, (COALESCE(date_paiement, created_at)))` |
| `ix_sorties_org_created` | `sorties_fonds (organisation_id, created_at)` |
| `ix_requisitions_org_created` | `requisitions (organisation_id, created_at)` |

`backend/alembic/versions/20260818_perf_indexes.py` (rendu idempotent par le commit 5102fea :
`op.create_index` remplacé par `CREATE INDEX IF NOT EXISTS`) :

| Index | Colonnes |
|---|---|
| `ix_requisitions_org_deleted_created` | `requisitions (organisation_id, is_deleted, created_at)` |
| `ix_encaissements_org_deleted_date` | `encaissements (organisation_id, is_deleted, date_encaissement)` |
| `ix_encaissements_expert_comptable_id` | `encaissements (expert_comptable_id)` |
| `ix_sorties_fonds_org_date_paiement` | `sorties_fonds (organisation_id, date_paiement)` |
| `ix_ordres_decaissement_org_created` | `ordres_decaissement (organisation_id, created_at)` |
| `ix_payment_history_encaissement_created` | `payment_history (encaissement_id, created_at)` |
| `ix_participants_transport_remboursement_id` | `participants_transport (remboursement_id)` |
| `ix_budget_audit_logs_org_exercice_created` | `budget_audit_logs (organisation_id, exercice_id, created_at)` |
| `ix_budget_audit_logs_budget_poste_id` | `budget_audit_logs (budget_poste_id)` |

Le recoupement des deux migrations révèle un **recouvrement partiel non intentionnel** :
`20260818` a reposé sur trois tables des composites voisins de ceux de `20260722d`,
sans supprimer les précédents (constat C-3).

## 1.2 Tables métier chaudes

### `encaissements` — 18 index (+ PK)

```
ix_enc_org_date                        (organisation_id, date_encaissement)
ix_encaissements_org_deleted_date      (organisation_id, is_deleted, date_encaissement)
uq_encaissements_org_numero            (organisation_id, numero_recu) UNIQUE
ix_encaissements_organisation_id       (organisation_id)
ix_encaissements_date_encaissement     (date_encaissement)
ix_encaissements_numero_recu           (numero_recu)
ix_encaissements_expert_comptable_id   (expert_comptable_id)
ix_encaissements_client_id             (client_id)
ix_encaissements_compte_bancaire_id    (compte_bancaire_id)
ix_encaissements_service_id            (service_id)
ix_encaissements_budget_ligne_id       (budget_poste_id)      -- nom historique, colonne renommée en 20260217
ix_encaissements_project_activity_id   (project_activity_id)
ix_encaissements_is_deleted            (is_deleted)
ix_encaissements_is_reconciled         (is_reconciled)
ix_encaissements_statut_operation      (statut_operation)
ix_encaissements_statut_comptabilisation (statut_comptabilisation)
ix_encaissements_statut_paiement       (statut_paiement)
ix_encaissements_type_client           (type_client)
```

### `requisitions` — 16 index (+ PK)

```
ix_requisitions_org_deleted_created    (organisation_id, is_deleted, created_at)
ix_requisitions_org_created            (organisation_id, created_at)
uq_requisitions_org_numero             (organisation_id, numero_requisition) UNIQUE
uq_requisitions_org_reference_numero   (organisation_id, reference_numero) UNIQUE
ix_requisitions_organisation_id        (organisation_id)
ix_requisitions_numero                 (numero_requisition)
ix_requisitions_reference_numero       (reference_numero)
ix_requisitions_date_requisition       (date_requisition)
ix_requisitions_status                 (status)
ix_requisitions_examen_status          (examen_status)
ix_requisitions_is_deleted             (is_deleted)
ix_requisitions_service_id             (service_id)
ix_requisitions_created_by             (created_by)
ix_requisitions_signed_by_id           (signed_by_id)
ix_requisitions_dossier_id             (dossier_id)
ix_requisitions_compte_bancaire_id     (compte_bancaire_id)
```

### `sorties_fonds` — 14 index (+ PK)

```
ix_sorties_org_paiement_ts             (organisation_id, (COALESCE(date_paiement, created_at)))
ix_sorties_fonds_org_date_paiement     (organisation_id, date_paiement)
ix_sorties_org_created                 (organisation_id, created_at)
uq_sorties_fonds_org_reference_numero  (organisation_id, reference_numero) UNIQUE
ix_sorties_fonds_organisation_id       (organisation_id)
ix_sorties_fonds_date_paiement         (date_paiement)
ix_sorties_fonds_reference_numero      (reference_numero)
ix_sorties_fonds_requisition_id        (requisition_id)
ix_sorties_fonds_service_id            (service_id)
ix_sorties_fonds_budget_ligne_id       (budget_poste_id)      -- nom historique
ix_sorties_fonds_compte_bancaire_id    (compte_bancaire_id)
ix_sorties_fonds_created_by            (created_by)
ix_sorties_fonds_programme_par_id      (programme_par_id)
ix_sorties_fonds_is_reconciled         (is_reconciled)
ix_sorties_fonds_statut_comptabilisation (statut_comptabilisation)
```

### `audit_logs` — 7 index (+ PK)

```
ix_audit_logs_organisation_id  (organisation_id)
ix_audit_logs_created_at       (created_at)
ix_audit_logs_user_id          (user_id)
ix_audit_logs_action           (action)
ix_audit_logs_entity_type      (entity_type)
ix_audit_logs_entity_id        (entity_id)
ix_audit_logs_target_table     (target_table)   -- colonne morte, cf. C-6
```

Aucun composite. Aucun index commençant par `organisation_id` suivi d'autre chose.

### `experts_comptables` — 3 index (+ PK + unique)

```
numero_ordre UNIQUE (contrainte de colonne)
ix_experts_comptables_numero_ordre  (numero_ordre)
ix_experts_comptables_type_ec       (type_ec)
ix_experts_comptables_active        (active)
```

**Cette table ne porte aucune colonne `organisation_id`** (`app/models/expert_comptable.py:17-49`).
C'est un annuaire global partagé par tous les tenants — voir C-4.

### `document_sequences`

```
uq_docseq_central   (doc_type, year, tenant_id) UNIQUE WHERE service_id IS NULL
uq_docseq_service   (doc_type, year, tenant_id, service_id) UNIQUE WHERE service_id IS NOT NULL
ix_document_sequences_tenant_id  (tenant_id)
ix_document_sequences_service_id (service_id)
```

Les deux uniques non partiels historiques (`uq_doc_type_year_tenant`,
`uq_doc_type_year_tenant_service`) ont bien été supprimés par `20260723a_finance_guards.py:120`
et `20260327_docseq_tenant.py:46`. **RAS sur cette table côté index.**

### `budget_postes`

```
uq_budget_postes_org_exercice_code_active (organisation_id, exercice_id, code) UNIQUE WHERE is_deleted = false
ix_budget_postes_organisation_id (organisation_id)
ix_budget_postes_exercice_id     (exercice_id)
ix_budget_postes_code            (code)
ix_budget_postes_parent_id       (parent_id)
ix_budget_postes_is_global       (is_global)
ix_budget_postes_is_deleted      (is_deleted)
```

L'unique partiel couvre exactement `budget.py:1789-1798` (`WHERE exercice_id = … AND
organisation_id = … AND is_deleted = false ORDER BY code`). **Rien à ajouter ici** — la note
de `PERFORMANCE_WRITE_CONTENTION_20260803.md` (« un index composite devra être reconsidéré
avec un volume réel ») est déjà satisfaite par cet index.

### Autres tables métier

| Table | Index pertinents |
|---|---|
| `ordres_decaissement` | `ix_ordres_decaissement_org_created (organisation_id, created_at)`, `uq_ordres_decaissement_org_numero`, + 7 FK simples |
| `payment_history` | `ix_payment_history_encaissement_created (encaissement_id, created_at)`, `_organisation_id`, `_encaissement_id`, `_created_at`, `_date_paiement`, `_statut` |
| `remboursements_transport` | `_organisation_id`, `_requisition_id`, 2 uniques `(organisation_id, numero/reference)` |
| `participants_transport` | `_organisation_id`, `_remboursement_id` |
| `lignes_requisition` | `_requisition_id`, `_organisation_id`, `_budget_poste_id`, `_compte_bancaire_id` |
| `requisition_status_history` | `_requisition_id`, `_changed_by`, `_changed_at`, `_organisation_id` |
| `clotures` | `_organisation_id`, `_caissier_id`, `_date_cloture`, `_reference_numero`, `uq_clotures_org_reference_numero` |
| `retours_caisse` | 9 index simples + unique `(organisation_id, reference_numero)` |
| `transferts_internes` | `_organisation_id` **seulement** |
| `users` | `_organisation_id`, `_email`, `_role_id`, `_service_id`, `uq_users_org_email` |
| `notification_logs` | `ix_notification_logs_org_created (organisation_id, created_at)`, `_entity (entity_type, entity_id)`, `_event_type`, `_status`, `_organisation_id`, `uq_…_dedup_key` |
| `ai_usage_logs` | `ix_ai_usage_org_date (organisation_id, created_at)`, `_organisation_id`, `_created_at` |
| `system_events` | `_organisation_id`, `_created_at` (aucun composite) |
| `payment_logs` | `_organisation_id` **seulement** |
| `hr_attendance_punches` | `ix_hr_punch_tenant_time`, `ix_hr_punch_tenant_employee_time`, `ix_hr_punch_tenant_source`, `uq_hr_punch_tenant_device_external_ref`, + 3 simples |
| `hr_attendances` | `uq_hr_attendances_tenant_emp_date`, `_tenant_id`, `_employee_id`, `_date_presence` |
| `compta_ecritures` / `compta_lignes_ecriture` | `ix_compta_ecriture_soc_ex_date (organisation_id, societe_id, exercice_id, date_ecriture)`, `ix_compta_ecriture_origine (organisation_id, module_origine, objet_origine_id)`, `ix_compta_ligne_soc_compte (organisation_id, societe_id, compte_id)` |
| `secretariat_*` | 12 composites préfixés `organisation_id` (agenda, documents, réunions), bien conçus |

**Le module comptabilité et le module secrétariat sont les mieux indexés du dépôt** : leurs
composites commencent systématiquement par `organisation_id`. Les tables financières
historiques (`encaissements`, `sorties_fonds`, `requisitions`, `audit_logs`) portent au
contraire une accumulation d'index mono-colonne posés au fil des migrations 2026-02 à
2026-08, dont beaucoup ne servent aucune requête du code.

---

# 2. Constats classés par (gain × confiance)

## Les trois changements qui rapportent le plus

1. **C-1 — Raccourcir les transactions d'écriture financière.** Trois verrous de ligne
   (poste budgétaire, caisse centrale, séquence documentaire) sont pris tôt et tenus
   jusqu'au `COMMIT` d'une transaction de 13 à 20 requêtes. Aucun index ne corrige cela.
   C'est la cause directe des p95 de 12,3 s et 12,9 s **mesurés** en création.
2. **C-2 — Rendre les agrégats de `reports/summary` et `dashboard/stats` indexables et bornés.**
   Les prédicats de date sont écrits `:param IS NULL OR colonne >= :param` et les colonnes
   sont enveloppées dans `LOWER()`/`UPPER()`/`COALESCE()`, ce qui empêche l'usage des index
   composites déjà en place. Deux agrégats balaient de surcroît tout l'historique du tenant,
   sans borne de date.
3. **C-3 — Supprimer les index redondants sur les trois grosses tables d'écriture.**
   `encaissements` maintient 19 entrées d'index par `INSERT`, `requisitions` 17,
   `sorties_fonds` 15 — à l'intérieur même des transactions du point C-1. Une douzaine
   d'entre eux ne sert aucune requête du code ou est couverte par le préfixe d'un autre.

---

## C-1 — Verrous de ligne tenus pendant toute la transaction de création (gain élevé, confiance élevée)

**Statut : MESURÉ pour la contention, DÉDUIT pour le correctif.**

`docs/PERFORMANCE_WRITE_CONTENTION_20260803.md` mesure à 100 utilisateurs :
`requisition_create` p95 **12,93 s** / 13 requêtes SQL, `encaissement_create` p95 **12,34 s**
/ 19-20 requêtes SQL. La Phase 3 a remplacé le `SELECT … FOR UPDATE` de
`document_sequences` par un `INSERT … ON CONFLICT DO UPDATE … RETURNING counter`
(`app/services/document_sequences.py:23-53`). **Ce changement supprime un aller-retour
réseau, pas le verrou** : la ligne reste verrouillée de l'`UPSERT` jusqu'au `COMMIT` de la
transaction applicative, exactement comme avec `FOR UPDATE`. Le document le reconnaît
implicitement (« sequence documentaire encore lente sous contention »).

Le chemin de paiement `sorties_fonds.py` prend les verrous dans cet ordre :

| Ordre | Verrou | Fichier:ligne | Cardinalité de la ressource |
|---|---|---|---|
| 1 | `BudgetPoste … FOR UPDATE` (1 par poste imputé) | `sorties_fonds.py:1500-1504` et `:1530-1538` | N postes/tenant |
| 2 | `CaisseCentrale … FOR UPDATE` | `sorties_fonds.py:1562-1568` | **1 seule ligne par tenant** (`uq_caisse_centrale_organisation_id`) |
| 3 | `CompteBancaire … FOR UPDATE` (canal BANQUE) | `sorties_fonds.py:1579-1587` | N comptes/tenant |
| 4 | `document_sequences` UPSERT | `sorties_fonds.py:1603` | 1 ligne par (doc_type, année, tenant, service) |

Ensuite seulement viennent la lecture de `PrintSettings`, la construction de l'objet, les
écritures dérivées et le `COMMIT`. **La ligne `caisse_centrale` du tenant est le goulot le
plus étroit** : toute opération de caisse d'une organisation la traverse, et le verrou est
pris avant une dizaine de requêtes supplémentaires. `retours_caisse.py`, `transferts.py`,
`encaissements.py:2044-2298`, `ordres_decaissement.py:336` prennent le même verrou —
`grep with_for_update` remonte 40 occurrences sur 8 endpoints.

**Correctif proposé (aucun DDL) :**

1. Déplacer `generate_document_number` **au plus près de l'`INSERT`**, après toutes les
   validations et lectures (`PrintSettings`, service, taux de change). Aujourd'hui, à
   `sorties_fonds.py:1603`, il précède encore la lecture de `PrintSettings` (`:1604-1606`).
2. Ordonner les verrous de façon **globale et stable** (par exemple toujours
   `caisse_centrale` en dernier des ressources de solde, `budget_postes` triés par `id`
   croissant). L'imputation multi-postes de `sorties_fonds.py:1499` boucle sur
   `repartition_postes` dans l'ordre d'arrivée du payload : deux requêtes concurrentes avec
   des répartitions en ordre inverse peuvent se bloquer mutuellement (deadlock, résolu par
   PostgreSQL avec une erreur `40P01` — donc une 500 pour l'utilisateur).
3. Sortir les traitements non transactionnels (génération PDF, notifications WhatsApp,
   `audit_logs`) hors de la transaction porteuse des verrous.

**Gain attendu :** proportionnel à la durée du verrou. Réduire la fenêtre de verrouillage de
la caisse d'un facteur 3 à 5 multiplie d'autant le débit de créations concurrentes par
tenant. **Fondement :** la contention sur une ressource unique impose un débit maximal de
`1 / durée_de_maintien_du_verrou` — la mesure Phase 3 (p95 12,9 s avec 13 requêtes en série)
est cohérente avec cette lecture, mais je ne peux pas la confirmer sans `pg_locks`.
**Coût en écriture :** nul. **Risque :** modification du code métier de paiement — exige des
tests de concurrence ; `backend/tests/test_document_sequences_concurrency.py` (16 tests,
10/25/50/100 réservations concurrentes) est le bon modèle à étendre au verrou caisse.

**Alternative à écarter :** remplacer `document_sequences` par une `SEQUENCE` PostgreSQL
native. Le document Phase 3 l'a déjà rejetée, à raison : la numérotation est cloisonnée par
(type, année, tenant, service) et les séquences natives laissent des trous après `ROLLBACK`.

---

## C-2 — Agrégats de rapports non indexables et non bornés (gain élevé, confiance élevée)

**Statut : MESURÉ pour le coût, DÉDUIT pour la cause.**

`reports/summary` à froid : **14-15 requêtes SQL, p95 7,30 s** (`PERFORMANCE_WRITE_CONTENTION_20260803.md`).
Un cache Redis court (`REPORT_SUMMARY_CACHE_TTL_SECONDS=15`) masque le coût mais ne le
supprime pas — chaque miss le paie, et un dashboard multi-tenant multiplie les miss.

### C-2a — Prédicat `:param IS NULL OR colonne >= :param`

`app/api/v1/endpoints/reports.py:326-327`, et le même motif répété **10 fois** dans le même
endpoint (`:326-327`, `:359-360`, `:401-402`, `:450-451`, `:527-528`, `:556-557`, `:584-585`,
`:615-616`) puis encore à `:823-824` et `:970-971` dans les autres rapports :

```sql
AND (CAST(:date_start AS date) IS NULL OR date_encaissement >= CAST(:date_start AS date))
AND (CAST(:date_end_excl AS date) IS NULL OR date_encaissement < CAST(:date_end_excl AS date))
```

Ce motif est **conditionnellement indexable** : avec un *plan personnalisé*, PostgreSQL
replie `CAST('2026-01-01' AS date) IS NULL` en `false` et la clause se réduit à
`date_encaissement >= …`, utilisable par `ix_enc_org_date`. Avec un *plan générique* — que
PostgreSQL peut adopter à partir de la 6ᵉ exécution d'une requête préparée, et asyncpg
prépare toutes les requêtes — le repliage n'a plus lieu et la clause devient
`$n IS NULL OR date_encaissement >= $n`, **non indexable**. L'endpoint retombe alors sur un
parcours complet des lignes du tenant, neuf fois de suite.

**Je ne peux pas confirmer quel plan est retenu sans accès à la base.** C'est exactement le
genre d'écart qu'un `EXPLAIN (ANALYZE, BUFFERS)` sur la production trancherait en une minute.

**Correctif (aucun DDL) :** construire le fragment SQL en Python plutôt que de le paramétrer
— n'ajouter `AND date_encaissement >= :date_start` que si `date_start` est non nul, comme le
fait déjà `dashboard.py:198-202` (« Comparaison de plage sur la colonne brute (pas de
`func.date`) pour que l'index sur `date_encaissement` soit utilisé » — l'intention est là,
mais `reports.py` ne l'applique pas).

### C-2b — Colonnes enveloppées dans des fonctions

`reports.py:320-325` :

```sql
AND COALESCE(est_proforma, false) = false
AND COALESCE(is_deleted, false) = false
AND COALESCE(statut_operation, 'ACTIVE') = 'ACTIVE'
AND LOWER(statut_paiement) = ANY(:statuts)
AND (CAST(:canal AS text) IS NULL OR UPPER(canal) = CAST(:canal AS text))
AND (CAST(:devise AS text) IS NULL OR UPPER(devise_perception) = CAST(:devise AS text))
```

Or **ces six colonnes sont `NOT NULL` dans le modèle** (`app/models/encaissement.py` :
`est_proforma` NOT NULL default false, `is_deleted` NOT NULL, `statut_operation` NOT NULL
default `'ACTIVE'`, `statut_paiement` NOT NULL, `canal` NOT NULL, `devise_perception`
NOT NULL) et trois d'entre elles portent déjà une contrainte `CHECK` sur un vocabulaire
fermé en majuscules (`ck_encaissements_canal`, `ck_encaissements_devise_perception`).
Les `COALESCE` et les `UPPER` sont donc **du travail pur perte** : ils rendent la colonne
non indexable sans protéger de quoi que ce soit.

`LOWER(statut_paiement)` est le seul cas discutable : `ck_encaissements_statut_paiement`
impose déjà `('non_paye','partiel','complet','avance')`, tous en minuscules. Le `LOWER` est
donc lui aussi inutile.

Même remarque sur `sorties_fonds` : `reports.py:524` et `dashboard.py:237`
écrivent `(statut IS NULL OR UPPER(statut) = 'VALIDE')` alors que `statut` est
`NOT NULL default 'VALIDE'` (`app/models/sortie_fonds.py`).

**Correctif :** retirer les enveloppes. Si l'on préfère ne pas toucher au SQL, un index
d'expression est possible mais je le déconseille — il fige la fonction et coûte à l'écriture :

```sql
-- À NE FAIRE QUE si le SQL ne peut pas être corrigé
CREATE INDEX CONCURRENTLY ix_encaissements_org_date_actif
  ON encaissements (organisation_id, date_encaissement)
  WHERE est_proforma = false AND is_deleted = false AND statut_operation = 'ACTIVE';
```

Cet index partiel a l'avantage d'être **plus petit** que `ix_enc_org_date` et de servir aussi
la liste par défaut (`encaissements.py:873-876`). Mais il n'est utilisable que si les
prédicats du `WHERE` sont écrits sans `COALESCE` — le correctif applicatif reste prérequis.

### C-2c — Deux agrégats sans borne de date

`app/api/v1/endpoints/dashboard.py:178-184` (`enc_all_stmt`) et `:255-257` (`sorties_all_stmt`)
somment **tout l'historique du tenant**, sans filtre de date, à chaque calcul du solde :

```python
enc_all_stmt = select(func.coalesce(func.sum(...), 0)).where(*enc_filters)  # dashboard.py:178
```

Le coût de ces deux requêtes croît **linéairement et sans borne** avec l'ancienneté du
tenant. Le cache de 60 s (`DASHBOARD_CACHE_TTL`) plafonne la fréquence, pas le coût unitaire.

**Correctif :** un solde cumulé n'a pas à être recalculé depuis l'origine. Deux options,
par ordre de préférence :
1. Lire le solde faisant autorité — le code le fait déjà partiellement pour la caisse
   (`dashboard.py:296-303`, « on lit le solde CENTRAL faisant autorité ») ; étendre le même
   principe aux encaissements/sorties.
2. À défaut, une table de cumuls mensuels par (organisation, mois, canal, devise), et ne
   sommer en direct que le mois courant.

**Gain attendu :** transforme un coût O(historique) en O(1) ou O(mois courant).
**Fondement :** structure de la requête, pas mesure. **Coût en écriture :** nul pour
l'option 1 ; une ligne de cumul à maintenir pour l'option 2. **Risque :** logique
financière — à traiter avec la même prudence que les soldes de caisse.

---

## C-3 — Index redondants et jamais sollicités (gain moyen-élevé, confiance élevée)

**Statut : DÉDUIT** — le code n'émet aucune requête qui les utiliserait. Sans `pg_stat_user_indexes`
je ne peux pas prouver un `idx_scan = 0`, mais l'absence de requête correspondante dans
`backend/app/` est vérifiable et vérifiée.

### C-3a — Préfixes couverts par un composite existant

Un index `(a)` est inutile dès lors qu'existe `(a, b)` : PostgreSQL utilise le composite pour
toute requête sur `a` seul. Ces trois index sont donc redondants :

| Index à supprimer | Couvert par |
|---|---|
| `ix_encaissements_organisation_id` | `ix_enc_org_date (organisation_id, date_encaissement)` |
| `ix_requisitions_organisation_id` | `ix_requisitions_org_deleted_created` |
| `ix_sorties_fonds_organisation_id` | `ix_sorties_fonds_org_date_paiement` |

Réserve honnête : un index mono-colonne est plus compact, donc marginalement plus rapide
pour un `COUNT(*) WHERE organisation_id = X` en *index-only scan*. Le gain à l'écriture
l'emporte largement sur ces trois tables à fort taux d'insertion.

### C-3b — Doublons entre les deux migrations de performance

`20260818_perf_indexes.py` a posé des composites qui recouvrent ceux de `20260722d_perf_indexes.py`
sans supprimer ces derniers :

| Paire | Analyse |
|---|---|
| `ix_requisitions_org_created (org, created_at)` vs `ix_requisitions_org_deleted_created (org, is_deleted, created_at)` | La liste par défaut filtre **toujours** `is_deleted = false` (`requisitions.py:956-959`, en dur, non paramétrable) et trie par `created_at DESC` (`requisitions.py:826-827`). Le composite à 3 colonnes est strictement meilleur. **`ix_requisitions_org_created` est superflu.** |
| `ix_encaissements_org_deleted_date (org, is_deleted, date)` vs `ix_enc_org_date (org, date)` | **Cas inverse.** `deleted_status` vaut `"all"` par défaut (`encaissements.py:788`, `:873-876`) : `is_deleted` n'est alors **pas** dans le `WHERE`, et le composite à 3 colonnes ne peut pas fournir un tri sur `date_encaissement`. `ix_enc_org_date` est l'index du chemin par défaut ; `ix_encaissements_org_deleted_date` ne sert que `deleted_status=active|deleted`, un filtre rare. |
| `ix_sorties_fonds_org_date_paiement (org, date_paiement)` vs `ix_sorties_org_paiement_ts (org, COALESCE(date_paiement, created_at))` vs `ix_sorties_org_created (org, created_at)` | Trois composites sur la même table pour trois expressions de date voisines. Le tri par défaut de la liste est `date_paiement DESC` (`sorties_fonds.py:513-514`) → `ix_sorties_fonds_org_date_paiement`. Les rapports utilisent `COALESCE(date_paiement, created_at)` (`reports.py:527-528`) → `ix_sorties_org_paiement_ts`. **`ix_sorties_org_created` n'est utilisé par aucune requête relevée** : `sorties_fonds.py` ne trie jamais par `created_at` seul avec `organisation_id`. |

### C-3c — Index mono-colonne à très faible sélectivité

Booléens et statuts à valeur dominante, toujours combinés à `organisation_id` dans le code.
PostgreSQL n'utilisera quasiment jamais un index dont la valeur recherchée couvre >10 % de
la table ; il coûte pourtant à chaque `INSERT`/`UPDATE`.

| Index | Distribution attendue | Requête qui l'utiliserait |
|---|---|---|
| `ix_encaissements_is_deleted` | `false` sur ~99 % | aucune (toujours avec `organisation_id`) |
| `ix_encaissements_is_reconciled` | `false` dominant | `reconciliation.py` filtre par `organisation_id` d'abord |
| `ix_encaissements_statut_operation` | `'ACTIVE'` sur ~99 % | aucune |
| `ix_encaissements_statut_comptabilisation` | `'NON_COMPTABILISEE'` dominant | aucune sans `organisation_id` |
| `ix_encaissements_type_client` | 8 valeurs | aucune sans `organisation_id` |
| `ix_encaissements_statut_paiement` | 4 valeurs | aucune sans `organisation_id` |
| `ix_requisitions_is_deleted` | `false` dominant | aucune |
| `ix_requisitions_examen_status` | `'NON_EXAMINE'` dominant | `requisitions.py:981` mais toujours avec `organisation_id` |
| `ix_sorties_fonds_is_reconciled` | `false` dominant | aucune |
| `ix_sorties_fonds_statut_comptabilisation` | dominant | aucune |
| `ix_budget_postes_is_deleted` | `false` dominant | couvert par l'unique partiel |
| `ix_budget_postes_is_global` | `false` dominant | aucune |

### C-3d — Index de date mono-colonne dominés par leur composite

| Index | Dominé par |
|---|---|
| `ix_encaissements_date_encaissement` | `ix_enc_org_date` |
| `ix_sorties_fonds_date_paiement` | `ix_sorties_fonds_org_date_paiement` |
| `ix_payment_history_created_at` | `ix_payment_history_encaissement_created` |
| `ix_payment_history_encaissement_id` | `ix_payment_history_encaissement_created` (préfixe) |
| `ix_ai_usage_logs_organisation_id` | `ix_ai_usage_org_date` (préfixe) |
| `ix_ai_usage_logs_created_at` | `ix_ai_usage_org_date` |
| `ix_notification_logs_organisation_id` | `ix_notification_logs_org_created` (préfixe) |
| `ix_budget_audit_logs_organisation_id` | `ix_budget_audit_logs_org_exercice_created` (préfixe) |
| `ix_hr_attendance_punches_tenant_id` | `ix_hr_punch_tenant_time` (préfixe) |

Aucune requête du dépôt ne balaie ces tables par date **sans** filtre de tenant : les seuls
appelants inter-tenants sont `super_admin.py` et `saas_console.py`, qui agrègent par
organisation.

### DDL proposé

```sql
-- Chaque DROP INDEX prend un ACCESS EXCLUSIVE bref sur la table.
-- CONCURRENTLY évite de bloquer les lectures ; il est INCOMPATIBLE avec
-- l'environnement Alembic actuel (cf. C-10) : à passer en psql, hors migration.

-- C-3a : préfixes couverts
DROP INDEX CONCURRENTLY IF EXISTS ix_encaissements_organisation_id;
DROP INDEX CONCURRENTLY IF EXISTS ix_requisitions_organisation_id;
DROP INDEX CONCURRENTLY IF EXISTS ix_sorties_fonds_organisation_id;

-- C-3b : doublons entre migrations de perf
DROP INDEX CONCURRENTLY IF EXISTS ix_requisitions_org_created;
DROP INDEX CONCURRENTLY IF EXISTS ix_sorties_org_created;

-- C-3c : faible sélectivité, aucune requête
DROP INDEX CONCURRENTLY IF EXISTS ix_encaissements_is_deleted;
DROP INDEX CONCURRENTLY IF EXISTS ix_encaissements_is_reconciled;
DROP INDEX CONCURRENTLY IF EXISTS ix_encaissements_statut_operation;
DROP INDEX CONCURRENTLY IF EXISTS ix_encaissements_statut_comptabilisation;
DROP INDEX CONCURRENTLY IF EXISTS ix_encaissements_type_client;
DROP INDEX CONCURRENTLY IF EXISTS ix_encaissements_statut_paiement;
DROP INDEX CONCURRENTLY IF EXISTS ix_requisitions_is_deleted;
DROP INDEX CONCURRENTLY IF EXISTS ix_sorties_fonds_is_reconciled;
DROP INDEX CONCURRENTLY IF EXISTS ix_sorties_fonds_statut_comptabilisation;
DROP INDEX CONCURRENTLY IF EXISTS ix_budget_postes_is_deleted;
DROP INDEX CONCURRENTLY IF EXISTS ix_budget_postes_is_global;

-- C-3d : dates mono-colonne dominées
DROP INDEX CONCURRENTLY IF EXISTS ix_encaissements_date_encaissement;
DROP INDEX CONCURRENTLY IF EXISTS ix_sorties_fonds_date_paiement;
DROP INDEX CONCURRENTLY IF EXISTS ix_payment_history_created_at;
DROP INDEX CONCURRENTLY IF EXISTS ix_payment_history_encaissement_id;
DROP INDEX CONCURRENTLY IF EXISTS ix_ai_usage_logs_organisation_id;
DROP INDEX CONCURRENTLY IF EXISTS ix_ai_usage_logs_created_at;
DROP INDEX CONCURRENTLY IF EXISTS ix_notification_logs_organisation_id;
DROP INDEX CONCURRENTLY IF EXISTS ix_budget_audit_logs_organisation_id;
DROP INDEX CONCURRENTLY IF EXISTS ix_hr_attendance_punches_tenant_id;
```

**Gain attendu :** `encaissements` passe de 19 à 11 entrées d'index maintenues par `INSERT`,
`requisitions` de 17 à 14, `sorties_fonds` de 15 à 11 — soit **~40 % de travail d'index en
moins** sur les insertions, à l'intérieur des transactions qui tiennent déjà les verrous de
C-1. Réduit aussi l'amplification d'écriture sur les `UPDATE` non-HOT.
**Fondement :** un `INSERT` maintient toutes les entrées d'index de la table ; le rapport est
arithmétique. L'effet en millisecondes dépend du taux de cache — non mesurable ici.
**Coût :** nul en écriture ; risque de régression en lecture si l'une de ces colonnes est
interrogée seule par un chemin que je n'aurais pas vu.
**Risque de migration :** faible. `DROP INDEX` est instantané mais prend un `ACCESS EXCLUSIVE`
sur la table ; `CONCURRENTLY` l'évite. **Procédure recommandée : ne rien supprimer avant
d'avoir relevé `pg_stat_user_indexes.idx_scan` sur la production** — le vrai critère de
décision, inaccessible ici. La liste ci-dessus est une hypothèse à confirmer, pas un ordre.

---

## C-4 — `experts_comptables` : endpoint le plus lent mesuré, table sans cloisonnement tenant (gain élevé, confiance moyenne)

**Statut : MESURÉ pour la lenteur, DÉDUIT pour la cause.**

`/api/v1/experts-comptables` est **le 1er endpoint du classement initial** :
1179 ms de moyenne, p95 2619 ms, 11 requêtes SQL (`PERFORMANCE_SQL_OPTIMIZATION_20260803.md`).
La Phase 2 a réduit le nombre de requêtes de 11 à 3, mais le p95 restait à **5,73 s** à
100 utilisateurs en Phase 3.

Deux problèmes distincts.

### C-4a — Aucun cloisonnement multi-tenant

`app/models/expert_comptable.py:17-49` ne déclare **aucune colonne `organisation_id`**.
`experts.py:334-367` construit sa requête sans aucun filtre de tenant. C'est un annuaire
national partagé : chaque tenant balaie l'annuaire complet, et le volume ne se divise
jamais par le nombre d'organisations. Le contraste avec les 60 autres tables est net.

Je signale le point comme performance ; **c'est aussi une question d'isolation de données
qui dépasse le cadre de cet audit** et qui mérite une décision produit (annuaire
volontairement partagé, ou fuite de cloisonnement ?).

### C-4b — Requête par défaut sans index utilisable

La requête par défaut, sans paramètre (`experts.py:334-367`) :

```sql
SELECT … FROM experts_comptables WHERE active = true ORDER BY numero_ordre ASC LIMIT 50 OFFSET 0;
```

`ix_experts_comptables_active` est un index sur un booléen dont `true` est la valeur
dominante — inexploitable. `ix_experts_comptables_numero_ordre` peut fournir l'ordre, à
charge de filtrer `active` ligne à ligne. **DÉDUIT** : le plan probable est un parcours de
`ix_experts_comptables_numero_ordre` avec filtre, ce qui reste acceptable à `OFFSET 0` mais
se dégrade linéairement avec l'`OFFSET` — et la pagination frontale utilise `offset`
(`experts.py:327`).

**DDL proposé** — un index partiel qui porte à la fois le filtre et le tri :

```sql
CREATE INDEX CONCURRENTLY ix_experts_actifs_numero
  ON experts_comptables (numero_ordre)
  WHERE active = true;
```

**Gain attendu :** rend la liste par défaut servie par un parcours d'index ordonné sur les
seules lignes actives. **Fondement :** le prédicat partiel correspond exactement au filtre
par défaut `active = true` (`experts.py:361-362`). **Coût en écriture :** faible — table
alimentée par imports, pas par transactions courantes. **Risque :** nul (ajout d'index) hors
le verrou de construction (cf. C-10).

Compléter par : `DROP INDEX CONCURRENTLY IF EXISTS ix_experts_comptables_active;`

### C-4c — Filtres non indexables sur la même table

- `experts.py:355-358` : `func.trim(statut_professionnel).in_(variants)` — `TRIM()` sur la
  colonne interdit tout index. Idem `_category_conditions` (`experts.py:254-269`) et
  `province_attache` (`experts.py:359`).
- **La bonne correction n'est pas un index d'expression** mais un nettoyage des données :
  si `statut_professionnel` et `province_attache` contenaient des valeurs normalisées, le
  `TRIM` disparaîtrait. Ces colonnes sont des énumérations stockées en texte libre
  (`String(50)`, `String(100)`, sans `CHECK`) — cf. C-8.

---

## C-5 — `audit_logs` : aucun index composite pour la seule requête de lecture (gain moyen-élevé, confiance élevée)

**Statut : DÉDUIT.**

`app/api/v1/endpoints/audit_logs.py:104` (et `:188`, `:261` pour les exports CSV/Excel) :

```python
stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
```

avec, en `WHERE` (`audit_logs.py:50-56`) :

```python
or_(AuditLog.organisation_id == user.organisation_id, AuditLog.organisation_id.is_(None))
```

Les 7 index de la table sont tous mono-colonne. **Aucun ne permet de restituer les lignes
d'un tenant déjà triées par `created_at`.** Le plan doit combiner un accès par
`ix_audit_logs_organisation_id` puis **trier l'intégralité de l'historique d'audit du tenant**
pour n'en rendre que 100 lignes — sur une table qui, elle, ne cesse de grossir (cf. C-7).

Le `OR … IS NULL` aggrave le cas : il force un `BitmapOr` sur deux branches, dont aucune ne
préserve l'ordre.

**DDL proposé :**

```sql
CREATE INDEX CONCURRENTLY ix_audit_logs_org_created
  ON audit_logs (organisation_id, created_at DESC);
```

Ce seul index ne suffit pas tant que le `OR` subsiste. **Correctif applicatif conjoint** —
remplacer le `OR` par deux branches `UNION ALL` triées, ou, plus simple, rendre
`organisation_id` non nul en journalisant les événements plateforme sous une organisation
technique. La seconde option supprime le problème définitivement.

Si le `OR` doit rester, un second index partiel rend la branche NULL indexée et ordonnée :

```sql
CREATE INDEX CONCURRENTLY ix_audit_logs_global_created
  ON audit_logs (created_at DESC) WHERE organisation_id IS NULL;
```

**Gain attendu :** remplace un tri de l'historique complet du tenant par la lecture des N
premières entrées d'index. Sur une table de journal, l'écart croît avec le volume — c'est
précisément la table qui grossit le plus vite. **Fondement :** structure de la requête et
inventaire des index ; **le plan effectif reste à confirmer par `EXPLAIN`**.
**Coût en écriture :** +1 index sur une table append-only à fort débit — à compenser en
supprimant les index morts de C-6. **Risque :** faible.

---

## C-6 — `audit_logs` : colonnes mortes et index sur colonne toujours NULL (gain faible, confiance très élevée)

**Statut : DÉDUIT, mais avec une preuve documentaire nette.**

`20260212_audit_logs.py:20-38` crée la table avec `target_table` / `target_id` et les index
`ix_audit_logs_target_table`, `ix_audit_logs_action`.
`20260216_fix_audit_cols.py:19-29` ajoute ensuite `entity_type` / `entity_id` **sans
supprimer** `target_table` / `target_id` ni leurs index.

`app/models/audit_log.py` ne déclare que `entity_type` / `entity_id`. `app/services/audit_service.py:35`
et `app/db/audit.py:28` n'écrivent que ces dernières. **Conclusion : `target_table` et
`target_id` sont NULL sur toutes les lignes écrites depuis février 2026**, et
`ix_audit_logs_target_table` indexe une colonne entièrement NULL — coût d'écriture pur,
utilité nulle. (En B-tree PostgreSQL les NULL sont bien indexés, l'index n'est donc pas
vide : il pèse.)

```sql
DROP INDEX CONCURRENTLY IF EXISTS ix_audit_logs_target_table;
-- puis, après vérification que les colonnes sont bien vides :
--   SELECT count(*) FROM audit_logs WHERE target_table IS NOT NULL;   -- doit renvoyer 0
-- ALTER TABLE audit_logs DROP COLUMN target_table, DROP COLUMN target_id;
```

`ix_audit_logs_action` : `audit_logs.py:58` filtre bien sur `action`, mais **toujours**
conjointement au tenant. Une fois `ix_audit_logs_org_created` en place, cet index devient un
candidat à la suppression — à confirmer par `idx_scan`.

**Risque de migration :** le `DROP COLUMN` est instantané en PostgreSQL (marquage logique,
pas de réécriture). Il prend néanmoins un `ACCESS EXCLUSIVE` bref, incompatible avec le
verrou déjà posé si la migration tourne pendant un pic. **Vérifier d'abord le `count(*)`.**

---

## C-7 — Croissance sans borne : aucune purge, aucun partitionnement (gain élevé à terme, confiance très élevée)

**Statut : DÉDUIT — confirmé par absence.**

`grep -rni "purge|retention|cleanup|partition"` sur `backend/app/` ne remonte **aucune
politique de rétention, aucun `DELETE` de purge, aucune table partitionnée**. Le seul
`delete(NotificationLog)` du dépôt est dans un test (`tests/test_whatsapp_notifications.py:101`).

Tables à croissance non bornée, par risque décroissant :

| Table | Écrite par | Borne ? | Index maintenus/INSERT |
|---|---|---|---|
| `audit_logs` | `app/services/audit_service.py:35`, `app/db/audit.py:28` — une ligne par mutation métier | **aucune** | 7 (+PK) |
| `compta_lignes_ecriture` | module comptabilité — ≥2 lignes par écriture | **aucune** | 7 (+PK) |
| `compta_ecritures` | idem | **aucune** | 9 (+PK) |
| `hr_attendance_punches` | agents de pointage, plusieurs par employé et par jour | **aucune** | 6 (+PK+unique) |
| `notification_logs` | une ligne par (événement × destinataire × canal) — WhatsApp inclus | **aucune** | 5 (+PK+unique) |
| `system_events` | journal d'incidents | **aucune** | 2 |
| `payment_logs` | webhooks de paiement, `raw_response` en texte | **aucune** | 1 |
| `budget_audit_logs` | une ligne par mouvement de crédit | **aucune** | 3 |
| `ai_usage_logs` | un appel LLM = une ligne | **aucune** | 3 |
| `requisition_status_history` | une ligne par transition | **aucune** | 4 |
| `generated_documents` | une ligne par PDF produit | **aucune** | 6 (+unique) |

`audit_logs` est le cas le plus aigu : elle porte **le plus d'index de toutes les tables de
journal** (7) tout en étant la plus sollicitée en écriture, et son seul endpoint de lecture
ne peut utiliser aucun d'eux efficacement (C-5). À terme elle domine la base en volume comme
en coût d'écriture.

**Correctifs, par ordre de rapport sur effort :**

1. **Rétention par tenant, applicative.** Une tâche périodique
   `DELETE FROM audit_logs WHERE created_at < now() - interval '24 months'` par lots de
   quelques milliers de lignes (jamais en un seul `DELETE` : il gonflerait le WAL et
   bloquerait l'autovacuum). Trivial à écrire, aucun changement de schéma.
2. **Partitionnement par plage de dates** pour `audit_logs`, `notification_logs` et
   `hr_attendance_punches` :

```sql
-- Esquisse : PostgreSQL 16, partitionnement déclaratif mensuel.
-- Migration lourde (recréation + copie) : à faire en fenêtre de maintenance,
-- ou en table miroir + bascule de nom.
CREATE TABLE audit_logs_part (LIKE audit_logs INCLUDING ALL) PARTITION BY RANGE (created_at);
CREATE TABLE audit_logs_2026_08 PARTITION OF audit_logs_part
  FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');
-- … puis INSERT INTO audit_logs_part SELECT * FROM audit_logs; et bascule.
```

Le partitionnement transforme la purge en `DROP TABLE` d'une partition — instantané, sans
`VACUUM` derrière. C'est le bon investissement **si** la volumétrie le justifie, ce que je ne
peux pas établir sans accès à la base.

3. **Décision préalable, non technique :** `audit_logs` a vocation à être un journal légal.
   La migration en attente `docs/pending_migrations/20260726_db_hardening_REVIEW.py` prévoit
   d'y poser un trigger `prevent_audit_log_mutation()` refusant `UPDATE`/`DELETE`. **Ce
   trigger et une politique de purge sont contradictoires** : il faudra soit un
   `ALTER TABLE … DISABLE TRIGGER` pendant la purge, soit exempter `DELETE` du trigger, soit
   renoncer à purger. Ce point doit être tranché **avant** d'appliquer cette migration.

---

## C-8 — Types et contraintes (gain faible en perf, confiance élevée sur la correction)

**Statut : DÉDUIT (lecture des modèles).**

### C-8a — Montant en `Float` — déjà identifié

`transactions.amount` est un `Float` (`app/models/saas_transaction.py`) : arrondis binaires
sur un montant de facturation SaaS. Déjà relevé et corrigé dans la migration en attente
`docs/pending_migrations/20260726_db_hardening_REVIEW.py:70` :

```sql
ALTER TABLE transactions ALTER COLUMN amount TYPE numeric(15,2) USING amount::numeric(15,2);
```

**Rien à ajouter, sauf un avertissement de migration** : ce `ALTER COLUMN … TYPE` **réécrit
toute la table** sous `ACCESS EXCLUSIVE`. Sur `transactions` (facturation SaaS, volume
modeste) c'est acceptable ; le noter quand même dans la fenêtre de maintenance.

`standard_classifications.confidence_score` est aussi un `Float` — légitime ici (score, pas
un montant).

**Point positif à confirmer :** tous les autres montants du dépôt sont en `Numeric` avec
précision explicite (`Numeric(15,2)`, `Numeric(14,2)`, `Numeric(12,4)` pour les taux). Aucun
`Numeric` sans précision. C'est propre.

### C-8b — Fuseaux horaires : rien à signaler

Vérification exhaustive sur `Base.metadata` : **aucune colonne `DateTime` sans
`timezone=True`** dans les 87 tables importées. Tous les `created_at`/`updated_at` utilisent
`DateTime(timezone=True)` avec un `default=utcnow` renvoyant un datetime aware. C'est le
point le mieux tenu de tout le schéma.

### C-8c — Énumérations en texte libre, sans contrainte

`encaissements` et `sorties_fonds` sont bien protégés (`ck_encaissements_type_client`,
`_statut_paiement`, `_mode_paiement`, `_devise_perception`, `_canal`, `ck_sorties_fonds_canal`,
`_devise`). Les tables suivantes ne le sont pas :

| Colonne | Type | Vocabulaire attendu | Contrainte |
|---|---|---|---|
| `requisitions.status` | `String(30)` | `EN_ATTENTE`, `AUTORISEE`, `APPROUVEE`, … | **aucune** |
| `requisitions.examen_status` | `String(30)` | `NON_EXAMINE`, … | **aucune** |
| `requisitions.type_requisition` | `String(50)` | `classique`, … | **aucune** |
| `requisitions.mode_paiement` | `String(50)` | idem encaissements | **aucune** |
| `experts_comptables.type_ec` | `String(10)` | `EC`, `SEC` | **aucune** |
| `experts_comptables.statut_professionnel` | `String(50)` | `En Cabinet`, `Indépendant`, `Salarié` | **aucune** |
| `ordres_decaissement.statut` | `String` | — | **aucune** |
| `notification_logs.status` / `channel` | `String(20)` | `PENDING`, … | **aucune** |
| `compta_ecritures.statut` | `String(20)` | `BROUILLON`, … | **aucune** |

Le cas `experts_comptables.statut_professionnel` a un **coût de performance direct** : c'est
parce que la colonne n'est pas normalisée que `experts.py:355` doit écrire
`func.trim(statut_professionnel).in_(variants)`, ce qui interdit tout index (C-4c). De même,
`_statut_professionnel_variants()` existe uniquement pour rattraper les variantes
d'accentuation et d'espacement en base.

`requisitions.status` est le plus exposé fonctionnellement : `requisitions.py:895-901`
étend un filtre via `_status_values_for_filter()`, signe que plusieurs orthographes
coexistent en base.

**DDL proposé** (`NOT VALID` : ne bloque pas sur l'historique, valide seulement les
écritures futures — même technique que `20260723a_finance_guards.py`) :

```sql
-- À poser uniquement après avoir relevé les valeurs réellement présentes :
--   SELECT DISTINCT status FROM requisitions;
--   SELECT DISTINCT trim(statut_professionnel) FROM experts_comptables;
ALTER TABLE experts_comptables
  ADD CONSTRAINT ck_experts_type_ec CHECK (type_ec IN ('EC','SEC')) NOT VALID;
```

**Gain :** indirect (rend `experts.py` indexable une fois les données normalisées).
**Coût :** `NOT VALID` = verrou bref, pas de scan. **Risque :** faible, mais **inutile de
poser la contrainte avant d'avoir normalisé les données existantes** — sinon toute mise à
jour d'une ligne non conforme échouera.

---

## C-9 — Recherche plein texte : `ILIKE '%…%'` sur les tables volumineuses (gain moyen, confiance moyenne)

**Statut : DÉDUIT.**

29 occurrences de `ILIKE '%…%'` (motif non ancré, donc **aucun index B-tree ne peut servir**).
Les cas qui portent sur des tables destinées à grossir :

| Fichier:ligne | Colonnes | Table | Aggravant |
|---|---|---|---|
| `experts.py:344-350` et `:385-390` | `numero_ordre`, `nom_denomination`, `email`, `cabinet_attache`, `province_attache` | `experts_comptables` | **`OR` sur 5 colonnes**, table non cloisonnée par tenant (C-4a) |
| `encaissements.py:852-856` | `client_nom` + 2 colonnes de `experts_comptables` | `encaissements` ⨝ `experts_comptables` | `OR` **à travers une jointure** |
| `requisitions.py:1009-1018` | `numero_requisition`, `objet`, + sous-requête sur `users` | `requisitions` | `OR` incluant un `IN (SELECT …)` |
| `audit_logs.py:65-68` | `entity_type`, `entity_id` | `audit_logs` | table de journal non bornée (C-7) |
| `billing.py:558`, `:603` | `phone_number` | `payment_logs` | table non bornée, `ILIKE` sur un numéro |
| `exports.py:1817-1828`, `:2040-2043` | idem requisitions/experts | export **sans `LIMIT`** | balaie tout le résultat |
| `hr.py:739` | `concat(nom,' ',post_nom,' ',prenom,' ',matricule)` | `hr_employees` | concaténation → non indexable même ancrée |

Le `OR` multi-colonnes est le vrai problème : PostgreSQL ne peut pas combiner plusieurs
index sur un `OR` de `ILIKE` non ancrés — il n'a d'autre choix qu'un parcours séquentiel.

**Correctif proposé — index trigramme :**

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- experts : la recherche globale `q` porte sur ces deux colonnes en priorité
CREATE INDEX CONCURRENTLY ix_experts_nom_trgm
  ON experts_comptables USING gin (nom_denomination gin_trgm_ops);
CREATE INDEX CONCURRENTLY ix_experts_numero_trgm
  ON experts_comptables USING gin (numero_ordre gin_trgm_ops);

-- encaissements : recherche client sur le nom libre
CREATE INDEX CONCURRENTLY ix_encaissements_client_nom_trgm
  ON encaissements USING gin (client_nom gin_trgm_ops)
  WHERE client_nom IS NOT NULL;

-- requisitions : recherche par objet
CREATE INDEX CONCURRENTLY ix_requisitions_objet_trgm
  ON requisitions USING gin (objet gin_trgm_ops);
```

**Gain attendu :** GIN trigramme est le seul mécanisme qui indexe `ILIKE '%…%'`. Il rend
la recherche sous-linéaire pour les motifs de 3 caractères ou plus. **Il ne sert à rien pour
les motifs de 1 ou 2 caractères** — et `experts.py:343` n'impose aucune longueur minimale au
paramètre `q`. **Ajouter une garde applicative `len(q) >= 3` est un prérequis**, sans quoi
l'index sera contourné à chaque frappe d'une recherche « au fil de la saisie ».

**Fondement :** propriété connue de `pg_trgm`. **Je n'ai pas mesuré le gain** : il dépend
entièrement du nombre de lignes, inconnu ici.
**Coût en écriture :** **élevé, et c'est le point de vigilance.** Un index GIN coûte
nettement plus cher à maintenir qu'un B-tree. Sur `encaissements` (table de C-1, déjà
lourde), l'ajout d'un GIN peut **aggraver** la contention en écriture. Recommandation :
poser d'abord les GIN sur `experts_comptables` (table alimentée par imports, peu d'écritures
transactionnelles), mesurer, et n'étendre à `encaissements`/`requisitions` que si le gain
en lecture le justifie. Régler `gin_pending_list_limit` et surveiller l'autovacuum.
**Risque de migration :** construction GIN longue et coûteuse en mémoire (`maintenance_work_mem`).

**Le `OR` à travers une jointure** (`encaissements.py:852-856`) ne sera pas résolu par un
index : le prédicat mélange une colonne de `encaissements` et deux de `experts_comptables`.
Le correctif est applicatif — deux requêtes distinctes réunies par `UNION`, ou une recherche
en deux temps (résoudre les experts, puis filtrer sur `expert_comptable_id IN (…)`,
qui bénéficie de `ix_encaissements_expert_comptable_id`).

---

## C-10 — Migrations : verrous longs en production (gain — ; confiance très élevée)

**Statut : DÉDUIT, avec confirmation par le code et par la documentation du dépôt.**

### C-10a — `CONCURRENTLY` est structurellement impossible

`backend/alembic/env.py:167-171` :

```python
def do_run_migrations(connection: Connection) -> None:
    with context.begin_transaction():
        context.run_migrations()
```

Chaque migration s'exécute **dans une transaction**. Or `CREATE INDEX CONCURRENTLY` et
`DROP INDEX CONCURRENTLY` sont interdits en transaction. La conséquence est explicitement
assumée dans le docstring de `20260818_perf_indexes.py:15-21` :

> « `CREATE INDEX` pose un verrou SHARE qui bloque les écritures (INSERT/UPDATE/DELETE) sur
> la table le temps de la construction. »

**Toute future migration d'index sur `encaissements`, `requisitions`, `sorties_fonds` ou
`audit_logs` bloquera les écritures pendant sa construction.** Tous les DDL proposés dans ce
rapport sont écrits en `CONCURRENTLY` : ils doivent donc être passés **en `psql`, hors
Alembic**, puis marqués comme appliqués — ou bien `env.py` doit être doté d'un mode
`transaction_per_migration` / `autocommit_block()`. Le second choix est le bon à moyen terme :

```python
# Piste, non appliquée (audit en lecture seule) :
#   with op.get_context().autocommit_block():
#       op.execute("CREATE INDEX CONCURRENTLY …")
```

**Aggravant opérationnel :** l'entrypoint du conteneur exécute `alembic upgrade head` au
démarrage (mentionné dans `docs/pending_migrations/20260726_db_hardening_REVIEW.py:5-8`).
Une migration verrouillante s'exécute donc **au boot, sans fenêtre choisie**.

### C-10b — Migrations passées à risque (déjà appliquées, pour mémoire)

| Migration | Opération | Verrou |
|---|---|---|
| `20260808_req_date.py:24-32` | `ADD COLUMN` nullable, puis `UPDATE requisitions SET date_requisition = created_at` sur **toute la table**, puis `CREATE INDEX` | l'`UPDATE` réécrit chaque ligne (doublement temporaire de la table + toutes les entrées d'index), le `CREATE INDEX` bloque ensuite les écritures |
| `20260310_multi_tenant_orgs.py:158-164` | 7 × `ALTER COLUMN … SET NOT NULL` | `ACCESS EXCLUSIVE` + scan complet de validation par table |
| `20260212_encaissements_devise.py:19-23` | 3 `ADD COLUMN … NOT NULL server_default` puis `UPDATE encaissements` complet | l'`ADD COLUMN` avec `server_default` est instantané en PG ≥ 11 ; **c'est l'`UPDATE` qui coûte** |
| `20260428_financial_cancel_control.py:43` | `UPDATE encaissements SET statut_operation = 'ACTIVE' WHERE statut_operation IS NULL` | réécriture de toutes les lignes concernées |

Point positif : les `ADD COLUMN NOT NULL` du dépôt fournissent **systématiquement** un
`server_default`, ce qui évite la réécriture de table depuis PostgreSQL 11. La pratique est
bonne ; ce sont les `UPDATE` de reprise qui portent le risque.

### C-10c — Migration en attente

`docs/pending_migrations/20260726_db_hardening_REVIEW.py` est correctement mise en
quarantaine (hors de `alembic/versions/`, avec pré-vérifications documentées). Deux réserves :

1. `ALTER TABLE transactions ALTER COLUMN amount TYPE numeric(15,2)` (`:70`) **réécrit la
   table** sous `ACCESS EXCLUSIVE`.
2. Le trigger `prevent_audit_log_mutation()` entre en conflit avec toute politique de purge
   d'`audit_logs` (cf. C-7).

---

## C-11 — Index composites manquants, second rang (gain faible-moyen, confiance moyenne)

**Statut : DÉDUIT.**

### C-11a — `transferts_internes`

`app/api/v1/endpoints/transferts.py:82-87` :

```python
select(TransfertInterne)
  .where(TransfertInterne.organisation_id == tenant_id)
  .order_by(TransfertInterne.date_transfert.desc())
```

La table ne porte que `ix_transferts_internes_organisation_id`. Le tri n'est pas indexé.

```sql
CREATE INDEX CONCURRENTLY ix_transferts_internes_org_date
  ON transferts_internes (organisation_id, date_transfert DESC);
DROP INDEX CONCURRENTLY IF EXISTS ix_transferts_internes_organisation_id;
```

### C-11b — `payment_logs`

`app/api/v1/endpoints/billing.py:548-560` : `WHERE organisation_id = … [AND status] [AND provider]
ORDER BY created_at DESC LIMIT/OFFSET`, plus un export **sans `LIMIT`** (`:597-605`). Un seul
index sur `organisation_id`. Table non bornée (C-7).

```sql
CREATE INDEX CONCURRENTLY ix_payment_logs_org_created
  ON payment_logs (organisation_id, created_at DESC);
DROP INDEX CONCURRENTLY IF EXISTS ix_payment_logs_organisation_id;
```

### C-11c — `system_events`

Deux index mono-colonne, aucun composite, alors que la consultation est nécessairement
`(organisation_id, created_at DESC)`.

```sql
CREATE INDEX CONCURRENTLY ix_system_events_org_created
  ON system_events (organisation_id, created_at DESC);
DROP INDEX CONCURRENTLY IF EXISTS ix_system_events_organisation_id;
DROP INDEX CONCURRENTLY IF EXISTS ix_system_events_created_at;
```

### C-11d — `requisitions` filtrées par statut

`requisitions.py:973-979` combine très fréquemment `organisation_id` + `is_deleted` +
`status IN (…)` + tri `created_at DESC` (c'est le filtre des files d'attente de validation).
`ix_requisitions_org_deleted_created` sert le tenant et le tri mais pas le statut ;
`ix_requisitions_status` seul est trop peu sélectif.

```sql
CREATE INDEX CONCURRENTLY ix_requisitions_org_status_created
  ON requisitions (organisation_id, status, created_at DESC)
  WHERE is_deleted = false;
```

**À poser en dernier, et seulement si `EXPLAIN` montre un tri coûteux sur ce chemin** :
`requisitions` porte déjà 16 index (C-3) et l'écriture y est le goulot (C-1). Ajouter un
17ᵉ index avant d'en avoir supprimé une demi-douzaine serait contre-productif.

### C-11e — Clés étrangères non indexées

Repérées par recoupement `Base.metadata` × inventaire des migrations. Une FK non indexée
coûte un parcours séquentiel de la table enfant à chaque `DELETE`/`UPDATE` de la clé parente
(et pour toute jointure remontante).

| Table.colonne | Impact | Priorité |
|---|---|---|
| `budget_audit_logs.exercice_id` | couvert en 2ᵉ position par `ix_budget_audit_logs_org_exercice_created` → **suffisant pour les requêtes filtrées par tenant**, insuffisant pour un `DELETE` d'exercice | basse |
| `user_services.service_id` | PK composite `(user_id, service_id)` → `user_id` couvert, `service_id` non. Suppression d'un service ⇒ parcours séquentiel | moyenne |
| `role_permissions.permission_id` | PK composite `(role_id, permission_id)` → même situation. `service_access.py:71-78` joint sur `role_id` (couvert) | basse |
| `encaissements.annulee_par_id`, `.reconciled_by_id`, `.source_proforma_id` | suppression d'utilisateur ⇒ parcours de `encaissements` | moyenne |
| `sorties_fonds.annulee_par_id`, `.reconciled_by_id` | idem | moyenne |
| `participants_transport.expert_comptable_id` | jointure vers l'annuaire | basse |
| `services.responsable_id` | table petite | très basse |
| `hr_*` : `validateur_id`, `uploaded_by`, `saisi_par`, `created_by`, `evaluateur_id`, `revoked_by` | 11 colonnes, tables de taille modérée | basse |

**Je ne recommande pas d'indexer ces FK en masse.** Sur `encaissements` et `sorties_fonds`,
l'ajout de 5 index supplémentaires aggraverait C-1 et C-3 pour un bénéfice qui ne se
matérialise qu'à la suppression d'un utilisateur — opération rare, et qui peut se permettre
un parcours séquentiel. **Les seules à considérer sérieusement sont `user_services.service_id`**
(la suppression d'un service est une opération d'administration courante) :

```sql
CREATE INDEX CONCURRENTLY ix_user_services_service_id ON user_services (service_id);
```

---

## C-12 — Dérive entre le modèle SQLAlchemy et le schéma réel (risque, confiance très élevée)

**Statut : DÉDUIT, vérifié par comparaison automatique.**

`alembic/env.py:151` fixe `target_metadata = Base.metadata`, ce qui rend `--autogenerate`
opérationnel. Or **une trentaine d'index posés par `op.execute("CREATE INDEX …")` ne sont pas
déclarés dans les modèles** : `ix_enc_org_date`, `ix_sorties_org_created`,
`ix_sorties_org_paiement_ts`, `ix_requisitions_org_created`, `ix_encaissements_date_encaissement`,
`ix_encaissements_numero_recu`, `ix_encaissements_statut_paiement`, `ix_encaissements_type_client`,
`ix_sorties_fonds_date_paiement`, `ix_audit_logs_created_at`, `ix_audit_logs_action`,
`ix_audit_logs_target_table`, les trois `ix_experts_comptables_*`, `ix_users_email`,
`ix_refresh_tokens_jti`…

**Conséquence :** un `alembic revision --autogenerate` proposerait de **supprimer** ces index,
dont les quatre composites de performance de `20260722d`. C'est un piège armé — d'autant que
`20260722d` et `20260818` sont précisément les migrations censées corriger les lenteurs.

**Correctif (aucun DDL) :** soit déclarer ces index dans les `__table_args__` des modèles
concernés, soit poser un `include_object` dans `env.py` qui ignore les index dont le nom
correspond à une liste maintenue. La première option est plus sûre.

Note connexe, sans gravité : `ix_encaissements_budget_ligne_id` et `ix_sorties_fonds_budget_ligne_id`
portent un nom obsolète — la colonne a été renommée `budget_poste_id` par
`20260217_budget_postes.py:19-20` et PostgreSQL a conservé le nom d'origine de l'index.
Ce ne sont **pas** des doublons, seulement du bruit de nommage.

---

# 3. Récapitulatif des DDL proposés

Aucun index déjà présent n'est proposé à la création. Ordre d'application recommandé :

```sql
-- ÉTAPE 0 — prérequis absolu, à exécuter sur la production AVANT tout DROP :
--   SELECT relname, indexrelname, idx_scan, pg_size_pretty(pg_relation_size(indexrelid))
--   FROM pg_stat_user_indexes ORDER BY idx_scan ASC;
-- Tout index de la liste C-3 avec idx_scan > 0 doit être réexaminé.

-- ÉTAPE 1 — ajouts à faible risque (hors Alembic, cf. C-10a)
CREATE INDEX CONCURRENTLY ix_audit_logs_org_created      ON audit_logs (organisation_id, created_at DESC);
CREATE INDEX CONCURRENTLY ix_experts_actifs_numero       ON experts_comptables (numero_ordre) WHERE active = true;
CREATE INDEX CONCURRENTLY ix_transferts_internes_org_date ON transferts_internes (organisation_id, date_transfert DESC);
CREATE INDEX CONCURRENTLY ix_payment_logs_org_created    ON payment_logs (organisation_id, created_at DESC);
CREATE INDEX CONCURRENTLY ix_system_events_org_created   ON system_events (organisation_id, created_at DESC);
CREATE INDEX CONCURRENTLY ix_user_services_service_id    ON user_services (service_id);

-- ÉTAPE 2 — suppressions (liste complète en C-3, après validation par idx_scan)

-- ÉTAPE 3 — trigrammes, uniquement après garde `len(q) >= 3` côté applicatif (C-9)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX CONCURRENTLY ix_experts_nom_trgm    ON experts_comptables USING gin (nom_denomination gin_trgm_ops);
CREATE INDEX CONCURRENTLY ix_experts_numero_trgm ON experts_comptables USING gin (numero_ordre gin_trgm_ops);

-- ÉTAPE 4 — seulement si EXPLAIN le justifie, et après l'étape 2
CREATE INDEX CONCURRENTLY ix_requisitions_org_status_created
  ON requisitions (organisation_id, status, created_at DESC) WHERE is_deleted = false;
CREATE INDEX CONCURRENTLY ix_encaissements_org_date_actif
  ON encaissements (organisation_id, date_encaissement)
  WHERE est_proforma = false AND is_deleted = false AND statut_operation = 'ACTIVE';
```

Les correctifs qui rapportent le plus (C-1, C-2) **ne comportent aucun DDL** : ce sont des
changements de code.

---

# 4. Ce que je n'ai pas pu vérifier

Rien de ce qui suit n'a été mesuré. Ces vérifications **exigent un accès à la base de
production** et devraient précéder toute application des propositions de ce rapport.

### Exigent `pg_stat_*` sur la production

1. **Quels index sont réellement utilisés.** `pg_stat_user_indexes.idx_scan` est le seul juge
   de la liste C-3. J'ai déduit l'inutilité de ~24 index de l'absence de requête
   correspondante dans le code ; un job, un script d'administration ou un outil de BI que je
   n'ai pas lu pourrait en solliciter certains. **Ne supprimer aucun index sans ce relevé.**
2. **La volumétrie réelle par table.** `pg_relation_size` / `pg_total_relation_size`.
   Tout le raisonnement de C-7 (croissance non bornée) est structurellement certain, mais son
   **urgence** dépend entièrement de chiffres que je n'ai pas. Un `audit_logs` de 50 000
   lignes ne pose aucun problème ; à 50 millions, il domine la base.
3. **Le taux de cache.** `pg_statio_user_tables.heap_blks_hit / heap_blks_read`. Détermine si
   les parcours séquentiels décrits en C-2 coûtent des microsecondes ou des secondes.
4. **Les requêtes réellement lentes.** `pg_stat_statements` classé par `total_exec_time`
   trancherait en une requête ce que j'ai dû déduire endpoint par endpoint — et révélerait
   probablement des chemins que je n'ai pas examinés.
5. **La contention de verrous.** `pg_locks` joint à `pg_stat_activity` pendant une campagne
   de charge confirmerait ou infirmerait C-1 : quelle ligne est effectivement attendue, et
   combien de temps. C'est **la mesure la plus utile de toute cette liste**.

### Exigent `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)`

6. **C-2a — plan générique ou personnalisé.** Le cœur de mon raisonnement sur `reports/summary`.
   Si PostgreSQL retient un plan personnalisé, le motif `:param IS NULL OR …` n'est pas un
   problème et le gain de C-2a s'effondre. `EXPLAIN` sur la requête préparée, après six
   exécutions, tranche. Alternative : `SET plan_cache_mode = force_custom_plan` et comparer.
7. **C-5 — le plan effectif de la liste d'audit.** J'affirme qu'il y a un tri complet de
   l'historique du tenant. C'est le plan le plus probable au vu des index, pas une certitude.
8. **C-4b — le plan de la liste d'experts.** Parcours séquentiel avec tri, ou parcours de
   `ix_experts_comptables_numero_ordre` avec filtre ? L'écart de gain est considérable.
9. **L'effet réel des index partiels proposés** (C-4b, C-9, ÉTAPE 4). Un index partiel n'est
   utilisé que si le planificateur prouve que le prédicat de la requête implique celui de
   l'index — à vérifier requête par requête.

### Exigent des données de production

10. **Les valeurs réellement présentes** dans les colonnes-énumérations de C-8c
    (`SELECT DISTINCT status FROM requisitions`, etc.). Indispensable avant toute contrainte
    `CHECK`, même `NOT VALID`.
11. **`audit_logs.target_table` est-elle bien vide ?** `SELECT count(*) FROM audit_logs
    WHERE target_table IS NOT NULL` doit renvoyer 0 avant le `DROP COLUMN` de C-6. Ma
    déduction repose sur la lecture du code d'écriture, pas sur les données.
12. **La cardinalité réelle des colonnes de C-3c.** Je postule que `is_deleted = false` couvre
    ~99 % des lignes. `SELECT is_deleted, count(*) … GROUP BY 1` le confirmerait. Si un tenant
    a massivement supprimé en douceur, la conclusion change.

### Hors de portée d'un audit du schéma

13. **La configuration du serveur PostgreSQL** : `shared_buffers`, `work_mem`,
    `effective_cache_size`, `random_page_cost`, réglages de l'autovacuum. Un `work_mem` trop
    bas transforme chaque tri de C-5 en tri sur disque — cause plausible d'une partie des
    latences mesurées, totalement invisible depuis le code.
14. **L'état de l'autovacuum et le bloat.** Sur des tables à fort taux d'`UPDATE` comme
    `budget_postes` (montants réécrits à chaque mouvement) et `caisse_centrale` (une ligne
    par tenant réécrite à chaque opération), le bloat peut dominer tout le reste.
    **`caisse_centrale` mérite une attention particulière** : une table d'une ligne par
    tenant, réécrite en permanence, est le cas d'école du bloat — chaque `UPDATE` crée une
    version morte, et si l'autovacuum ne suit pas, la « ligne unique » devient des milliers
    de tuples morts à parcourir. `pg_stat_user_tables.n_dead_tup` le dirait immédiatement.
15. **La part non-SQL des latences.** `PERFORMANCE_WRITE_CONTENTION_20260803.md` relève un
    démarrage applicatif de 1 min 50 s dû aux imports (`openpyxl`, `pdfplumber`, `pandas`) et
    recommande d'« analyser les traitements non SQL qui occupent le worker pendant que les
    connexions restent rares ». **Une partie des p95 attribués à PostgreSQL pourrait être du
    temps CPU Python**, notamment la génération PDF et la sérialisation des listes. Aucun
    index ne corrigera cela.

### Enfin

16. Le classement de ce rapport par (gain × confiance) repose sur des gains **estimés**. Sans
    mesure avant/après sur des données réelles, l'ordre proposé est un pari argumenté, pas un
    résultat. La séquence honnête est : relever `pg_stat_statements` et `pg_locks` sous charge
    → confirmer ou réviser ce classement → n'appliquer qu'ensuite, une modification à la fois,
    en mesurant entre chaque.
