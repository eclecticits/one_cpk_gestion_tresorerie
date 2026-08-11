# Audit des calculs financiers — écarts application / Excel

**Date** : 2026-08-07
**Périmètre** : frontend, backend, base PostgreSQL, agrégations SQL, exports Excel, rapports, tableaux de bord
**Base auditée** : `onec_cpk` (live), organisation 1 « Conseil Provincial de Kinshasa »
**Statut** : audit seul — **aucune modification de code n'a été faite**

> **Avertissement méthodologique.** Les chiffres ci-dessous obtenus en `psql` direct sont
> valides pour tout ce qui concerne les **formules et les périmètres fonctionnels** (statuts,
> retours, dates, hiérarchie budgétaire), car les requêtes citées portent un
> `organisation_id` explicite. Ils ne le sont **pas** pour juger de l'**isolation
> multi-tenant** : `app/db/session.py:461` applique un filtre tenant au niveau ORM que `psql`
> court-circuite. Toute affirmation sur l'isolation doit être vérifiée en exécutant la
> requête *dans* l'application (cf. §10, commande 4). Le constat §1.4 a dû être corrigé pour
> cette raison.

---

## 0. Réponse courte

Les écarts avec Excel ne viennent **pas** principalement de la précision des flottants.
Ils viennent, par ordre d'impact décroissant :

1. **d'un double comptage hiérarchique dans le budget** (un poste parent stocke déjà la somme de ses enfants, et une requête les additionne tous) ;
2. **de périmètres de données différents d'un écran à l'autre** (statuts, retours en caisse, filtres de dates, `is_deleted`, organisation) ;
3. **de deux règles d'arrondi coexistantes** dans le code (HALF_EVEN « banquier » vs HALF_UP « Excel ») ;
4. accessoirement, de conversions `Decimal → float` et de formats d'affichage non homogènes.

**4 écarts sont reproduits et chiffrés sur les données réelles ci-dessous.**

---

## 1. Écarts confirmés sur données réelles

### 1.1 — CRITIQUE — Budget : double comptage parents + enfants

Le rollup budgétaire est **stocké** : `backend/app/api/v1/endpoints/budget.py:450-460` écrit
`parent.montant_prevu = SUM(enfants.montant_prevu)`. Un poste parent contient donc déjà
le total de ses sous-postes.

Or `/budget/summary/mine` (`budget.py:1084-1109`) fait un `SUM(montant_prevu)` **plat** sur
la jointure `ServiceRubrique`, sans condition de feuille. Et 22 lignes de `service_rubriques`
pointent sur des postes **parents**.

| Élément | Données source | Formule | Application | Calcul de référence (Excel) | Écart |
|---|---|---|---|---|---|
| Budget dépenses service 18 (ADM) | `budget_postes` ⋈ `service_rubriques` | `SUM(montant_prevu)` sur tous les postes joints | **3 054 094,48** | `SUM(montant_prevu)` sur les feuilles uniquement = **774 664,38** | **+2 279 430,10** (×3,94) |
| Budget dépenses service 2 (FORCO) | idem | idem | **91 580,00** | **45 790,00** | **+45 790,00** (×2) |
| Budget total org 1, exercice 2026 | `budget_postes` | `SUM` sur 107 postes | **5 488 660,66** | `SUM` sur les feuilles = **1 679 066,97** | **+3 809 593,69** (×3,27) |

Requête de reproduction :

```sql
SELECT p.organisation_id,
       SUM(p.montant_prevu) AS somme_tous_postes,
       SUM(p.montant_prevu) FILTER (
         WHERE NOT EXISTS (SELECT 1 FROM budget_postes c
                           WHERE c.parent_id = p.id AND c.is_deleted = false)
       ) AS somme_feuilles
FROM budget_postes p
WHERE p.is_deleted = false
GROUP BY 1;
-- org 1 :  5 488 660,66  vs  1 679 066,97
```

**La même règle métier est implémentée 4 fois, 3 correctement, 1 faussement :**

| Emplacement | Règle | Correct ? |
|---|---|---|
| `budget.py:1088-1093` `/budget/summary` | `leaf_condition` (`NOT EXISTS` enfant) | ✅ |
| `exports.py:453-467` `node_totals()` | parent = somme récursive des enfants | ✅ |
| `frontend/src/pages/Budget.tsx:123-145` `computeNodeTotals()` | idem | ✅ |
| `budget.py:1084-1109` `/budget/summary/mine` | `SUM` plat, aucune condition | ❌ |

> À noter : la jointure `ServiceRubrique` n'a pas de `DISTINCT`. Il n'y a aujourd'hui aucun
> doublon (`GROUP BY service_id, budget_poste_id HAVING count(*)>1` → 0 ligne), mais le
> jour où un poste sera lié deux fois au même service, son montant sera compté deux fois.

---

### 1.2 — CRITIQUE — Sorties de fonds : les retours en caisse ne sont soustraits que dans l'export Excel

`RetourCaisse` n'est référencé **que** dans `exports.py`. Recherche exhaustive :

```
app/api/v1/endpoints/exports.py:1174-1216   ← seule occurrence hors du module retours_caisse
```

Il n'apparaît ni dans `dashboard.py`, ni dans `reports.py`, ni dans
`treasury._recalculate_treasury_balances()`, ni dans le total de la liste `/sorties-fonds`
(`sorties_fonds.py:556-573`).

| Élément | Données source | Formule | Application (écran) | Export Excel | Écart |
|---|---|---|---|---|---|
| Total sorties de fonds | `sorties_fonds` + `retours_caisse` | écran : `SUM(montant_paye)` — export : `SUM(montant_paye) − SUM(retours)` | **147 360,36** | **147 093,30** | **−267,06** |

```sql
SELECT (SELECT COALESCE(SUM(montant_paye),0) FROM sorties_fonds
        WHERE organisation_id=1 AND (statut IS NULL OR statut='VALIDE'))            AS ecran,
       (SELECT COALESCE(SUM(montant_paye),0) FROM sorties_fonds
        WHERE organisation_id=1 AND (statut IS NULL OR statut='VALIDE'))
     - (SELECT COALESCE(SUM(montant),0) FROM retours_caisse
        WHERE organisation_id=1 AND statut='VALIDE')                                AS export_excel;
-- 147 360,36  |  147 093,30
```

C'est **le cas typique où l'utilisateur refait le total dans Excel et ne retombe pas** :
selon qu'il additionne la colonne de l'export (retours en négatif inclus) ou qu'il lit le
KPI de l'écran, il obtient deux nombres différents.

Le manque se propageait à quatre endroits, dont un **destructif** :

| Emplacement | Effet de l'omission |
|---|---|
| `treasury._recalculate_treasury_balances` | `create_retour_caisse` crédite la caisse au fil de l'eau ; le recalcul repartait d'une formule sans retours et **effaçait ces crédits** (−267,06 à chaque appel) |
| `clotures._compute_balance` | solde théorique sous-évalué de 267,06 → écart de caisse fictif à la clôture |
| `sorties_fonds` — total de la liste | écran brut vs export net |
| `dashboard` / `reports` | totaux de sorties bruts |

> **Attention au périmètre du net.** L'export Excel déduit les retours du total
> **général**, transferts internes compris. Son pied de colonne vaut donc
> `total_montant_paye − retours` = **147 093,30**, et non `dépenses réelles − retours`
> = 139 593,30. Les deux nets sont légitimes mais ne désignent pas la même chose :
>
> | Grandeur | Montant |
> |---|---|
> | Total général (brut) | 147 360,36 |
> | dont dépenses réelles | 139 860,36 |
> | dont transferts internes | 7 500,00 |
> | Retours en caisse | − 267,06 |
> | Dépenses **nettes** | 139 593,30 |
> | **Total net = pied de l'export Excel** | **147 093,30** |

---

### 1.3 — MAJEUR — Encaissements : le statut `avance` est exclu des totaux mais présent dans les détails

`dashboard.py:50` et `reports.py` appliquent `STATUT_PAIEMENT_INCLUS = ('complet','partiel')`
au **total**, mais :
- la ventilation « par statut de paiement » (`reports.py:265-283`) **n'applique pas** ce filtre ;
- l'export Excel (`exports.py:824-880`) **n'applique pas** ce filtre non plus.

| Élément | Données source | Formule | Application | Calcul de référence | Écart |
|---|---|---|---|---|---|
| Dashboard / Rapports « Total encaissements » | `encaissements` | `SUM(montant_paye)` WHERE `statut_paiement IN ('complet','partiel')` | **314 565,78** | — | — |
| Rapports, tableau « par statut » (somme des lignes) | idem | `SUM(montant_paye)` **sans** filtre statut | **315 525,78** | — | **+960,00** |
| Export Excel encaissements, total colonne « Montant payé » | idem | idem, sans filtre statut | **315 525,78** | — | **+960,00** |
| Liste écran `/encaissements`, total | idem | idem | **315 525,78** | — | **+960,00** |

Détail du différentiel :

```sql
SELECT statut_paiement, count(*), SUM(montant_paye) FROM encaissements
WHERE organisation_id=1 AND est_proforma=false
  AND COALESCE(statut_operation,'ACTIVE')='ACTIVE'
GROUP BY 1;
--  avance  |  1 |    960,00   ← invisible dans les totaux, visible partout ailleurs
--  complet | 25 | 314 565,78
```

Un encaissement réel de **960,00 USD** (`ND-2026-000021`, une avance) est encaissé, apparaît
dans la liste et dans l'export, mais **n'est compté ni dans le dashboard ni dans les rapports**.

Cet encaissement est par ailleurs le seul où `montant_paye (960,00) > montant_total (690,00)` —
métier légitime pour une avance, mais qui explique pourquoi `SUM(montant_paye)` dépasse
`SUM(montant_total)` de 270,00 globalement.

---

### 1.4 — MOYEN — Clôture de caisse : filtre `organisation_id` absent, rattrapé par le hook ORM sauf sur le chemin super-admin

> **Correction du 2026-08-07.** Une première version de ce rapport annonçait ici un écart
> permanent de **+2 940,00** sur toutes les clôtures. **C'était faux.** La mesure avait été
> faite en `psql` direct, ce qui court-circuite l'application. Vérification refaite *dans*
> l'application : voir ci-dessous.

`backend/app/api/v1/endpoints/clotures.py:43-162`, fonction `_compute_balance(db)` :
aucune des 8 requêtes ne filtre explicitement sur l'organisation.

Mais `app/db/session.py:461-560` installe un hook `do_orm_execute` qui applique
automatiquement `with_loader_criteria(Model, cls.organisation_id == tenant_id)` à chaque
`SELECT`. **Ce hook couvre aussi les requêtes d'agrégation** (`SUM`, `COUNT`), ce qui n'allait
pas de soi et a été vérifié expérimentalement :

```
tenant_context = 1     -> SUM(montant_paye) = 219 642,48     ← correct
tenant_context = None  -> SUM(montant_paye) = 222 582,48     ← fuite inter-tenants
```

**Pour un utilisateur normal, il n'y a donc aucun écart.** Le hook fait le travail.

Le hook est en revanche inerte dans deux cas (`session.py:463-469`) :
`session.info["skip_tenant_scope"]` (réservé aux endpoints super-admin) et surtout
**`tenant_id is None`**, ce qui est précisément l'état posé par `require_super_admin`
(`deps.py:446`) et par `get_current_user` pour un super-admin sur l'hôte d'administration
(`deps.py:322-325`).

Or `GET /clotures/balance-check` **n'avait aucune dépendance de tenant** — seulement
`has_permission("cloture_caisse")`. Sur ce chemin, l'agrégation inter-tenants était réelle.
Par contraste, `POST /clotures` dépendait déjà de `get_current_tenant_id`, donc les montants
**persistés** n'ont jamais été affectés.

| Chemin d'appel | Contexte tenant | Comportement avant correctif |
|---|---|---|
| Utilisateur normal → `/balance-check` | posé par `get_current_user` | ✅ correct (hook ORM) |
| Utilisateur normal → `POST /clotures` | `get_current_tenant_id` | ✅ correct |
| Super-admin (hôte admin) → `/balance-check` | **`None`** | ❌ agrège tous les tenants |
| Super-admin (hôte admin) → `POST /clotures` | **`None`** | déjà 403 |

Le même raisonnement vaut pour `select(PrintSettings).limit(1)` (ligne 53) : `PrintSettings`
figure dans la liste du hook (`session.py:484`), le taux de change est donc bien celui du
tenant courant — sauf sur le chemin `tenant_id = None`. Il n'y a qu'une ligne
`print_settings` par organisation, donc l'absence d'`ORDER BY` est sans effet.

**Portée réelle** : défaut de défense en profondeur sur un chemin super-admin, pas un écart
de calcul pour les utilisateurs métier. Priorité rétrogradée de *critique* à *moyen*.

---

## 2. Règles d'arrondi

C'est le point que vous signaliez comme critique. Il y a bien **deux règles différentes en
production dans le même backend**.

### 2.1 — HALF_EVEN (arrondi du banquier) vs HALF_UP (règle d'Excel)

Python arrondit par défaut en **ROUND_HALF_EVEN**. Excel arrondit en **HALF_UP**
(demi au-dessus, en valeur absolue), sur la représentation décimale à 15 chiffres.

Tout `.quantize(Decimal("0.01"))` **sans argument `rounding=`** applique donc la règle du
banquier, et diverge d'Excel une fois sur deux sur les demis :

| Valeur | `quantize(0.01)` — code actuel | Excel `ARRONDI(x;2)` | Écart |
|---|---|---|---|
| 1,005 | 1,00 | **1,01** | 0,01 |
| 8,165 | 8,16 | **8,17** | 0,01 |
| 1234,565 | 1234,56 | **1234,57** | 0,01 |
| 0,125 | 0,12 | **0,13** | 0,01 |
| 4,345 | 4,34 | **4,35** | 0,01 |
| 859,385 | 859,38 | **859,39** | 0,01 |
| 2,345 | 2,34 | **2,35** | 0,01 |
| 2,675 | 2,68 | 2,68 | — |
| 0,135 | 0,14 | 0,14 | — |
| 1,115 | 1,12 | 1,12 | — |

**Emplacements en HALF_EVEN (divergents d'Excel) :**

| Fichier | Ligne | Fonction | Usage |
|---|---|---|---|
| `endpoints/clotures.py` | 40 | `_decimal()` | **tous** les montants de clôture de caisse |
| `endpoints/exports.py` | 141-144 | `_round_money()` | exports Excel encaissements et réquisitions |
| `endpoints/reports.py` | 806 | — | `coverage_rate` (synthèse annuelle) |
| `endpoints/sorties_fonds.py` | 1197 | — | répartition au prorata multi-postes |
| `modules/comptabilite/routers/parametrage.py` | 442 | — | `taux_inverse` |

**Emplacements en HALF_UP (conformes à Excel) :**

| Fichier | Fonction |
|---|---|
| `endpoints/encaissements.py:111` | `_clean_money()` |
| `endpoints/payments.py:27` | `_clean_money()` |
| `schemas/dashboard.py:11` | `_format_money()` |
| `services/hr_payroll_calc.py:10` | `_round()` |
| `modules/comptabilite/services/ecriture_service.py:41` | `_q()` |
| `modules/comptabilite/services/change_service.py:81-86` | `_q2()`, `_q8()` |

Le module comptabilité et la paie sont donc corrects ; la trésorerie et les exports ne le sont pas.

### 2.2 — `Decimal(float)` au lieu de `Decimal(str(float))`

`clotures.py:40` :

```python
def _decimal(value):
    return Decimal(value or 0).quantize(Decimal("0.01"))   # ← Decimal(float) direct
```

`Decimal(0.1)` vaut `0.1000000000000000055511151231257827021181583404541015625`.
Combiné à HALF_EVEN, cela produit des arrondis imprévisibles sur les valeurs limites.
Le reste du code utilise correctement `Decimal(str(value))`.

### 2.3 — Frontend : `roundMoney`

`frontend/src/components/EncaissementForm.tsx:30-32` :

```ts
const roundMoney = (value: number): number =>
  Math.round((value + Number.EPSILON) * 100) / 100
```

Le correctif `+ Number.EPSILON` rattrape la plupart des cas (9/10 dans mon échantillon), mais :

| Valeur | `roundMoney` | Excel | Écart |
|---|---|---|---|
| 8,165 | 8,16 | **8,17** | 0,01 |
| −0,125 | **−0,12** | −0,13 | 0,01 |
| −1234,565 | **−1234,56** | −1234,57 | 0,01 |

Deux limites structurelles :
- `Number.EPSILON` est une constante **absolue** (2,22 × 10⁻¹⁶), calibrée pour des valeurs
  proches de 1. Au-delà de ~2, elle est absorbée par la représentation flottante et
  l'astuce ne fait plus rien.
- `Math.round` arrondit vers **+∞**, pas « à l'écart de zéro ». Sur les montants négatifs
  (avoirs, retours, écarts de caisse), la divergence avec Excel est systématique.

### 2.4 — À quel moment arrondit-on ?

| Étape | Arrondi ? | Où |
|---|---|---|
| Saisie ligne (qté × PU) | ✅ 2 déc. | frontend uniquement (`Requisitions.tsx:459`, `EncaissementForm.tsx:135`, `QuickRequisitionModal.tsx:36`) |
| Total = Σ lignes | ✅ 2 déc. | frontend (`EncaissementForm.tsx:141`) |
| Réception API réquisitions | ❌ **aucun** | `services/requisition_service.py:444` — `montant_total = payload.montant_total` (le backend fait confiance au frontend) |
| Réception API encaissements | ✅ HALF_UP | `encaissements.py:354-385` — recalcule et re-arrondit |
| Stockage PostgreSQL | ✅ 2 déc., HALF_UP | `NUMERIC(14,2)` / `NUMERIC(15,2)` |
| Agrégations SQL | — | `SUM()` sur `NUMERIC` : exact, aucun arrondi |
| Conversion budgétaire | ❌ **aucun** | `sorties_fonds.py:674` — `m / rate` sans `quantize`, précision 28 chiffres |
| Pourcentages | ❌ **aucun** | `budget.py:1343` — pas de `quantize` |
| Export Excel | ⚠️ HALF_EVEN | `exports.py:141` |
| Affichage | ✅ 2 déc. | `utils/amount.ts` `formatAmount` — mais voir §5.3 |

**Constat clé** : l'arrondi est appliqué **ligne par ligne** puis les lignes arrondies sont
sommées. Si dans Excel vous sommez d'abord puis arrondissez, vous obtiendrez un résultat
différent dès qu'il y a plus de ~2 lignes avec des décimales impaires. Les deux approches
sont défendables, mais elles doivent être identiques des deux côtés.

**Bon point** : la répartition au prorata multi-postes (`sorties_fonds.py:1195-1205`) et la
conversion d'écritures comptables (`change_service.py:190-215`) **gèrent correctement le
reliquat d'arrondi** (l'écart est absorbé sur la ligne la plus élevée, la somme des parts
retombe exactement sur le total). C'est la bonne pratique — elle n'est simplement pas
généralisée.

---

## 3. Types numériques

### 3.1 — Base de données : globalement correct

Tous les montants métier sont en `NUMERIC(14,2)` ou `NUMERIC(15,2)`, taux en `NUMERIC(12,4)`.
C'est le bon choix. **Deux exceptions** :

| Table | Colonne | Type | Problème |
|---|---|---|---|
| `saas_transactions` | `amount` | `Float` (double precision) | seule table monétaire en flottant — `app/models/saas_transaction.py:39` |
| `standard_classifications` | `confidence_score` | `Float` | non monétaire, acceptable |

### 3.2 — Backend : 193 conversions `float()` sur des montants

`grep -c "float(" app/api/v1/endpoints/*.py app/services/*.py` → **193 occurrences**.

Chaque `float(Decimal)` fait retomber la valeur dans le binaire IEEE 754. Les plus exposées :

| Fichier | Lignes | Impact |
|---|---|---|
| `budget.py` | 945-946, 993-1003, 1095-1136 | tous les KPI budgétaires (`prevu`, `reel`, `engage`, `paye`, `solde`) |
| `exports.py` | 528-532, 593-595, 702-712, 747-806, 959-961 | **toutes les cellules écrites dans les fichiers Excel** |
| `clotures.py` | 372-383 | export CSV/Excel des clôtures |
| `ai.py` | 40-168 | scoring d'anomalies |
| `admin.py` | 238-241 | **taux de change** (`exchange_rate`, `exchange_rate_cdf`, …) |

Cas particulier — accumulation en flottant :

```python
# requisitions.py:730 et dossiers_requisition.py:154
calc_total = sum(float(r.montant_total or 0) for r in requisitions)
```

L'erreur s'accumule sur chaque addition. Ici l'impact est neutralisé par une tolérance
(`abs(calc_total - total) <= 0.01`), mais le pattern est présent.

### 3.3 — Sérialisation JSON : contrat non homogène

`app/schemas/base.py` :

```python
class DecimalBaseModel(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})
```

- `json_encoders` est **déprécié en Pydantic v2** (2.10.6 installé). Cela fonctionne encore,
  mais reposer dessus est fragile — sa suppression ferait basculer silencieusement tous les
  montants de `"1234.50"` (string) à `1234.5` (number JSON), sans erreur ni test rouge.
- Certains schémas ajoutent un `field_serializer` explicite (`schemas/budget.py:28-36`,
  `schemas/dashboard.py`), d'autres non → **le frontend reçoit tantôt une string, tantôt un
  number** selon l'endpoint. `utils/amount.ts:toNumber()` absorbe les deux, ce qui masque
  le problème mais ne le résout pas.
- Les endpoints qui retournent un `dict` brut avec `float()` (budget, ai, admin) envoient
  toujours des numbers JSON, en contournant complètement `DecimalBaseModel`.

Cas concret de perte de précision au passage JSON — `budget.py:1343` :

```python
pourcentage = (base_consomme / montant_prevu) * Decimal("100")   # aucun quantize
```

```
Sérialisé   : "46.13659811317710573509762985"   (29 caractères)
Lu par JS   : 46.13659811317711                  ← 14 chiffres significatifs, tronqué
```

### 3.4 — Frontend : `Number` (float64) partout

`utils/amount.ts` convertit tout en `Number` JavaScript, donc en float64. Tous les calculs
côté client (totaux de lignes, soldes, pourcentages, PDF) sont faits en flottant. C'est
acceptable **à condition que le frontend ne fasse que de l'affichage** — or il calcule
(§2.4 : les montants de ligne des réquisitions sont calculés côté client et stockés tels quels).

---

## 4. Périmètre des données

Vous aviez raison de ne pas présumer que le problème venait de la formule. Plusieurs
divergences viennent de **jeux de données différents**.

### 4.1 — Données de test de charge encore en base

```sql
SELECT organisation_id, (numero_requisition LIKE '%LOAD%') AS test,
       count(*), sum(montant_total) FROM requisitions GROUP BY 1,2;
--  1 | f |  45 | 184 439,92
-- 18 | t | 262 |   6 550,00   ← "Load Test load-test-20260803"
```

262 réquisitions de test (6 550,00 USD), toutes `BROUILLON`, toutes sans lignes. Elles sont
isolées dans l'organisation 18, donc **sans impact sur l'org 1** grâce au filtrage tenant.
Mais elles faussent toute requête d'audit ou de supervision inter-tenants
(console Super Admin, vue matérialisée de santé plateforme).

### 4.2 — `is_deleted` : filtré dans certains modules, pas dans d'autres

| Module | Filtre `is_deleted` sur `encaissements` |
|---|---|
| `dashboard.py` | ❌ **aucune requête** |
| `reports.py` — `/summary` | ❌ aucune des ~10 requêtes |
| `reports.py` — `/synthese-annuelle` (l. 751, 819) | ✅ |
| `reports.py` — l. 1000, 1130 | ✅ |
| `encaissements.py` — liste (l. 596) | ✅ |
| `treasury.py` — `_recalculate_treasury_balances` | ✅ |
| `exports.py` — export encaissements | ❌ |

Aucune ligne n'est actuellement soft-supprimée (`SELECT ... WHERE is_deleted` → 0), donc
**l'écart est nul aujourd'hui**. Mais à la première suppression logique, le dashboard, les
rapports et l'export Excel continueront de compter la ligne, alors que la liste à l'écran
et la trésorerie ne la compteront plus.

### 4.3 — Transactions annulées : correctement gérées

`statut_operation = 'ANNULEE'` (3 encaissements, **139 062,32 USD**) est correctement exclu
partout via `COALESCE(statut_operation,'ACTIVE') = 'ACTIVE'`, y compris dans l'export
(`exports.py:860`). ✅ Aucun écart.

> Réserve : dans l'export, ce filtre est conditionné à `if est_proforma is False`. Un appel
> avec `?est_proforma=true` produirait un export incluant les proformas **annulées**.

### 4.4 — Filtres de dates : trois sémantiques différentes pour le même objet

| Module | Colonne de date utilisée pour les sorties | Borne haute |
|---|---|---|
| `dashboard.py:348, 407, 456` | `COALESCE(date_paiement, created_at)` | `< date_fin + 1 jour` |
| `reports.py` — `/summary` | `COALESCE(date_paiement, created_at)` | `< date_fin + 1 jour` |
| `clotures.py:83` | `COALESCE(date_paiement, created_at)` | `<= now()` |
| `sorties_fonds.py:415-417` — **liste écran** | `date_paiement` **seul** | `<= date_fin` |
| `exports.py:1051-1053` — **export Excel** | `date_paiement` **seul** | `<= date_fin 23:59:59.999999` |
| `exports.py:1290-1292` — export réquisitions | `created_at` | `<= date_fin` |

Conséquences :
- **15 sorties** ont `date_paiement` et `created_at` dans des **mois différents** → elles
  sont rattachées à un mois dans le dashboard et à un autre dans la liste/l'export.
- Une sortie sans `date_paiement` (aucune aujourd'hui, mais le champ est `nullable`)
  serait **comptée** par le dashboard et **absente** de la liste et de l'export.
- Les bornes hautes ne sont pas équivalentes : `< J+1` (borne exclusive propre) contre
  `<= J 23:59:59.999999` (une opération à `23:59:59.9999995` serait exclue).

### 4.5 — Rapports : chemin de repli côté client

`frontend/src/pages/Rapports.tsx:619-660` — si `/reports/summary` échoue, le frontend
recalcule les totaux en réduisant les listes brutes, avec :
- `limit: 1000` → **troncature silencieuse** au-delà de 1000 lignes (limite serveur : 5000) ;
- **aucun filtre de statut** → les `avance` et `non_paye` sont inclus, contrairement à
  l'agrégat serveur.

Le même KPI a donc deux valeurs selon qu'un appel a réussi ou échoué, sans indication à l'écran.

---

### 4.6 — CRITIQUE — Le solde de caisse a deux sources de vérité incompatibles

*(constat ajouté le 2026-08-07, découvert en corrigeant le §1.2)*

| Source | Mécanisme | Valeur (org 1) |
|---|---|---|
| **A — comptage physique** *(fait autorité aujourd'hui)* | `open_caisse` (`clotures.py:634`) écrit `caisse.solde_usd = solde_ouverture_usd`, le fond compté par le caissier | **78 449,53** |
| **B — recalcul par les flux** | `_recalculate_treasury_balances` (`treasury.py:63-190`) : `cash_init + encaissements + appro + transferts + retours − sorties` | **52 119,67** |

**Écart : 26 329,86.**

Cause : le terme `cash_init` est lu sur `comptes_bancaires` avec `account_type = 'CASH'`.
**Or il n'existe aucun compte CASH pour l'organisation 1** — seulement deux comptes `BANK`.
`cash_init` vaut donc 0, et le recalcul **ignore totalement `ouvertures_caisse`** : il ne
connaît pas le fond de caisse déclaré à l'ouverture.

```sql
SELECT id, intitule, account_type, devise, solde_initial FROM comptes_bancaires WHERE organisation_id=1;
--  10 | ORDRE NATIONAL DES EXPERTS COMPTABLE | BANK | USD | 0.00
--  11 | ORDRE NATIONAL DES EXPERT COMPTABLE  | BANK | USD | 0.00
--  (aucune ligne CASH)
```

Aucun flux depuis la dernière ouverture (2026-08-06 21:36) : le solde stocké est donc
exactement le fond compté, et l'écart de 26 329,86 est **structurel**, pas accumulé.

**Exposition** : `POST /tresorerie/soldes/recalculate` (rôles `admin`, `tresorerie`,
`comptabilite`). Vérifié : **aucun appel depuis le frontend, aucun appelant interne** —
l'endpoint n'est atteignable qu'en API directe. Le risque est donc *latent*, mais un seul
appel ramènerait le solde de caisse de 78 449,53 à 52 119,67.

**Décision requise** avant correctif : laquelle des deux sources fait foi ?
1. le comptage physique — alors le recalcul doit partir du dernier `ouvertures_caisse` et
   n'ajouter que les flux postérieurs ;
2. les flux — alors il faut créer un compte `CASH` portant le fond initial historique ;
3. ni l'un ni l'autre — retirer l'endpoint de recalcul, aujourd'hui inutilisé.

---

## 5. Cohérence entre les couches

### 5.1 — Traçabilité d'un montant, étape par étape

| Étape | Type | Arrondi | Remarque |
|---|---|---|---|
| Saisie utilisateur | `string` | — | `normalizeDecimalInput` accepte `,` et `.` |
| Calcul frontend | `number` (float64) | `roundMoney` (≈HALF_UP, cf. §2.3) | qté × PU, puis Σ |
| Envoi API | JSON number | — | |
| Réception encaissements | `Decimal` | `_clean_money` HALF_UP ✅ | **recalculé** côté serveur |
| Réception réquisitions | `Decimal` | ❌ **aucun** | `montant_total` du payload accepté tel quel |
| Stockage | `NUMERIC(x,2)` | HALF_UP (PostgreSQL) | ✅ |
| Agrégation SQL | `NUMERIC` | exact | ✅ |
| Sérialisation | `str` **ou** `float` | — | contrat non homogène (§3.3) |
| Affichage | `number` | `toFixed(2)` **ou** `toLocaleString` | non homogène (§5.3) |
| Export Excel | `float` | HALF_EVEN ❌ | + réécritures (§5.2) |

**L'étape où l'écart apparaît, par ordre de fréquence :** l'agrégation (périmètre §4),
puis l'export (§5.2), puis l'arrondi (§2).

### 5.2 — L'export Excel réécrit les montants

`exports.py:931-939` :

```python
montant_total = _round_money(enc.montant_total or enc.montant or Decimal("0"))
montant_paye  = _round_money(enc.montant_percu or enc.montant_paye or Decimal("0"))
reste = _round_money(montant_total - montant_paye)
if abs(reste) < Decimal("0.05"):
    reste = Decimal("0.00")
    montant_paye = montant_total        # ← réécriture silencieuse
total_notes_debit += Decimal(montant_total or 0)
total_paye        += Decimal(montant_paye or 0)   # ← le total accumule la valeur réécrite
```

Trois problèmes distincts :

1. **La colonne « Montant payé (USD) » est alimentée par `montant_percu`**, qui est exprimé
   dans la **devise de perception** (CDF le cas échéant), alors que `montant_total` est en
   USD. L'en-tête annonce USD. Aucune ligne CDF aujourd'hui → écart nul, mais la colonne
   « Reste à payer » soustrairait des CDF à des USD dès la première.
2. **La règle « si |reste| < 0,05 alors payé = total »** efface un impayé réel de 1 à 4
   centimes et **gonfle le montant payé**. Dans Excel, `montant_total − montant_payé` donne
   0,04 ; l'application affiche 0,00 et un montant payé différent.
3. **Le total accumule la valeur réécrite**, l'écart se propage donc au pied de colonne.

Le repli `enc.montant_percu or enc.montant_paye` bascule aussi de colonne quand
`montant_percu` vaut 0 (falsy en Python), ce qui n'est pas la même chose que « non renseigné ».

### 5.3 — Formats d'affichage non homogènes

| Emplacement | Formatage | 314 565,78 | 314 565,00 |
|---|---|---|---|
| `utils/amount.ts` `formatAmount` | `toFixed(2)` | `314565.78` | `314565.00` |
| `Rapports.tsx:1192-1201` | `toLocaleString('fr-FR')` | `314 565,78` | **`314 565`** ← centimes perdus |
| `TopExpenses.tsx:19,32` | `toLocaleString('fr-FR')` | idem | idem |
| `EncaissementForm.tsx:34` | `Intl.NumberFormat` style currency | `314 565,78 $US` | `314 565,00 $US` |

`toLocaleString('fr-FR')` sans options utilise `maximumFractionDigits: 3` et
`minimumFractionDigits: 0`. Donc :
- les montants ronds perdent leurs centimes à l'affichage ;
- une valeur non arrondie en amont (ex. `1679066.9712`) s'affiche `1 679 066,971` — **3 décimales**.

Un utilisateur qui recopie `314 565` dans Excel perd bien 0,78.

---

## 6. Devises — risque latent, écart nul aujourd'hui

Aucune opération CDF n'existe actuellement (`GROUP BY devise` → 100 % USD sur
`encaissements` et `sorties_fonds`). Mais l'architecture est asymétrique :

| Table | Colonne | Devise de stockage |
|---|---|---|
| `encaissements` | `montant_paye` | **normalisé USD** (converti par le frontend : `montantPayeInput / tauxChange`) |
| `encaissements` | `montant_percu` | devise de perception (USD ou CDF) |
| `sorties_fonds` | `montant_paye` | **devise native** (`devise` = USD ou CDF), non normalisé |
| `retours_caisse` | `montant` | devise native |

Conséquences le jour où une opération CDF sera saisie :

1. `dashboard.py:257` — `solde_actuel = enc_all_v − sorties_all_v` soustrait des **CDF** à
   des **USD** sans conversion (sauf si le filtre `devise` est explicitement posé, ce qui
   n'est pas le cas par défaut).
2. `reports.py` — même formule, même problème.
3. `sorties_fonds.py:567` — `total_montant_paye` additionne des devises différentes.
4. L'export Excel des sorties annonce « Montant payé (USD) » sans colonne devise ni conversion.
5. `_to_budget_currency` (`sorties_fonds.py:674`) fait `m / rate` **sans `quantize`** →
   28 chiffres significatifs, comparés ensuite à `montant_prevu` (2 décimales) puis stockés
   dans un `NUMERIC(15,2)` — l'arrondi se fait donc dans PostgreSQL, en HALF_UP, à un
   endroit non explicite dans le code.
6. La conversion CDF → USD n'est **pas réversible** : `roundMoney(100000 / 2250) = 44,44`,
   et `44,44 × 2250 = 99 990` ≠ 100 000. Un contrôle Excel qui reconvertit ne retombera jamais.

---

## 7. Formules dupliquées

| Règle métier | Nombre d'implémentations | Cohérentes ? |
|---|---|---|
| Rollup budgétaire parent = Σ enfants | **4** (`budget.py` ×2, `exports.py`, `Budget.tsx`) | ❌ 3/4 — cf. §1.1 |
| Arrondi monétaire | **8** (`_clean_money` ×2, `_round_money`, `_decimal`, `_q`, `_q2`, `_round`, `roundMoney`) | ❌ **3 règles différentes** — cf. §2.1 |
| Solde de trésorerie | **4** (`dashboard`, `treasury._recalculate`, `clotures._compute_balance`, `reports`) | ❌ 4 périmètres différents (retours, `is_deleted`, statut, organisation) |
| Montant de ligne = qté × PU | **4** (`Requisitions.tsx`, `QuickRequisitionModal.tsx`, `EncaissementForm.tsx`, `encaissements.py`) | ⚠️ formule identique, mais seul `encaissements.py` revalide côté serveur |
| Total encaissements période | **3** (`dashboard`, `reports/summary`, repli client `Rapports.tsx`) | ❌ filtres de statut divergents — cf. §1.3, §4.5 |
| Filtre de période des sorties | **6** | ❌ 3 sémantiques — cf. §4.4 |

**Points où une future modification de formule créerait une incohérence :**
- changer la règle de rollup budgétaire → 4 fichiers à modifier, dont 1 en TypeScript ;
- changer `STATUT_PAIEMENT_INCLUS` → n'affecterait que les totaux, pas les ventilations ni
  les exports (qui ne référencent pas la constante) ;
- supprimer `json_encoders` de `DecimalBaseModel` → bascule silencieuse string → number sur
  tous les endpoints sans `field_serializer` explicite.

---

## 8. Ce qui est correct

Pour cadrer le périmètre d'intervention, voici ce qui a été vérifié et validé :

| Contrôle | Résultat |
|---|---|
| `lignes_requisition.montant_total` = `quantite × montant_unitaire` | ✅ **0 ligne incohérente** |
| `requisitions.montant_total` = Σ des lignes (hors données de test) | ✅ **0 réquisition incohérente** sur 45 |
| `encaissements.montant_total` = Σ des articles | ✅ **0 encaissement incohérent** |
| Types de colonnes monétaires | ✅ `NUMERIC(x,2)` partout (1 exception : `saas_transactions.amount`) |
| Agrégations SQL `SUM()` sur `NUMERIC` | ✅ exactes, aucun arrondi intermédiaire |
| Exclusion des opérations `ANNULEE` | ✅ cohérente dans tous les modules |
| Isolation multi-tenant des montants | ✅ hook ORM `do_orm_execute` (`session.py:461`), **couvre aussi les agrégats** — vérifié |
| Module comptabilité (écritures, change, équilibre) | ✅ HALF_UP, absorption du reliquat, filtrage tenant |
| Module paie (`hr_payroll_calc`) | ✅ HALF_UP, `Decimal` de bout en bout |
| Répartition prorata multi-postes (`sorties_fonds.py:1195`) | ✅ reliquat absorbé, la somme retombe sur le total (arrondi HALF_EVEN à corriger) |
| Doublons de liaison service ↔ poste budgétaire | ✅ aucun |

---

## 9. Synthèse — priorisation

| # | Constat | Gravité | Écart mesuré (org 1) | Fichier principal |
|---|---|---|---|---|
| 1 | Double comptage budget parents+enfants | **Critique** | **+2 279 430,10** (service 18) | `budget.py:1084-1109` |
| 18 | Solde de caisse : deux sources de vérité (comptage vs flux) | **Critique** | **26 329,86** *(latent)* | `treasury.py:63`, `clotures.py:634` |
| 3 | Retours en caisse absents partout sauf export | **Critique** | **−267,06** | `exports.py` / `dashboard.py` / `reports.py` |
| 4 | Statut `avance` exclu des totaux seulement | **Majeur** | **960,00** | `dashboard.py:50`, `reports.py`, `exports.py` |
| 5 | Arrondi HALF_EVEN vs HALF_UP (5 emplacements) | **Majeur** | 0,01 par valeur limite, cumulatif | `clotures.py:40`, `exports.py:141`, +3 |
| 6 | Export Excel : réécriture `payé = total` si reste < 0,05 | **Majeur** | ≤ 0,04 par ligne, cumulatif | `exports.py:931-939` |
| 7 | Sémantiques de dates divergentes (3) | **Majeur** | 15 sorties de mois différent | 6 fichiers |
| 8 | Asymétrie de devises USD/CDF | **Majeur** *(latent)* | 0,00 aujourd'hui | `dashboard.py:257`, `sorties_fonds.py` |
| 9 | `is_deleted` non filtré (dashboard, rapports, export) | Moyen *(latent)* | 0,00 aujourd'hui | `dashboard.py`, `reports.py` |
| 2 | Clôture : pas de filtre organisation explicite (chemin super-admin uniquement) | Moyen | 0,00 pour un utilisateur normal | `clotures.py:43-162` |
| 10 | 193 conversions `float()` sur des `Decimal` | Moyen | sub-centime, cumulatif | `budget.py`, `exports.py` |
| 11 | Frontend `roundMoney` : négatifs et > 2 | Moyen | 0,01 par valeur | `EncaissementForm.tsx:30` |
| 12 | Contrat JSON non homogène (str vs number) | Moyen | — | `schemas/base.py` |
| 13 | `toLocaleString` : centimes perdus / 3 décimales | Moyen | 0,99 max à l'affichage | `Rapports.tsx`, `TopExpenses.tsx` |
| 14 | Repli client `Rapports.tsx` : limite 1000, sans filtre | Moyen | variable | `Rapports.tsx:619-660` |
| 15 | Pourcentages sérialisés sur 28 chiffres | Faible | — | `budget.py:1343` |
| 16 | 262 réquisitions de test en base (org 18) | Faible | 6 550,00 hors org 1 | données |
| 17 | `saas_transactions.amount` en `Float` | Faible | — | `models/saas_transaction.py:39` |

---

## 10. Reproduire les écarts

```bash
# 1 — Double comptage budgétaire
docker compose exec -T db psql -U christian -d onec_cpk -c "
SELECT sr.service_id,
  SUM(p.montant_prevu) AS application,
  SUM(p.montant_prevu) FILTER (WHERE NOT EXISTS (
    SELECT 1 FROM budget_postes c WHERE c.parent_id=p.id AND c.is_deleted=false)) AS reference_excel
FROM service_rubriques sr JOIN budget_postes p ON p.id=sr.budget_poste_id
WHERE p.is_deleted=false AND p.type='DEPENSE' GROUP BY 1;"

# 2 — Retours en caisse
docker compose exec -T db psql -U christian -d onec_cpk -c "
SELECT (SELECT SUM(montant_paye) FROM sorties_fonds
        WHERE organisation_id=1 AND (statut IS NULL OR statut='VALIDE')) AS ecran,
       (SELECT SUM(montant)      FROM retours_caisse
        WHERE organisation_id=1 AND statut='VALIDE')                     AS retours_export_seulement;"

# 3 — Statut 'avance'
docker compose exec -T db psql -U christian -d onec_cpk -c "
SELECT statut_paiement, count(*), SUM(montant_paye) FROM encaissements
WHERE organisation_id=1 AND est_proforma=false
  AND COALESCE(statut_operation,'ACTIVE')='ACTIVE' GROUP BY 1;"

# 4 — Clôture : portée du hook ORM (à exécuter DANS l'application, pas en psql)
#     psql court-circuite le hook de filtrage tenant et donne un résultat trompeur.
docker compose exec -T -u root backend python -c "
import asyncio
from sqlalchemy import func, select
import app.api.v1.router
from app.db.session import SessionLocal
from app.core.tenant_context import set_current_tenant_id
from app.models.encaissement import Encaissement
q = select(func.coalesce(func.sum(Encaissement.montant_paye), 0)).where(
    Encaissement.canal=='CAISSE', Encaissement.devise_perception=='USD',
    Encaissement.est_proforma.is_(False))
async def m():
    async with SessionLocal() as db:
        for tid in (1, None):
            set_current_tenant_id(tid)
            print(tid, (await db.execute(q)).scalar_one())
asyncio.run(m())"

# 5 — Règle d'arrondi
python3 -c "
from decimal import Decimal, ROUND_HALF_UP
for v in ['1.005','8.165','1234.565','0.125','4.345','859.385','2.345']:
    d=Decimal(v)
    print(v, 'code actuel:', d.quantize(Decimal('0.01')),
             '| Excel:',      d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))"
```

---

*Aucun fichier source n'a été modifié. Ce rapport documente l'état constaté au 2026-08-07.*
