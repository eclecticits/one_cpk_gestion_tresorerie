# Module Comptabilité — Dossier d'architecture

**Projet :** ONEC Smart · **Date :** 31/07/2026 · **Statut : CONCEPTION — à valider avant tout développement**
**Méthode :** 4 agents spécialistes (domaine OHADA, architecture données/performance, moteur d'intégration, reporting/analytique/IA), chacun ancré par lecture du code réel. Aucun fichier applicatif modifié.

---

## 0. Cadrage honnête

Le périmètre demandé (17 sous-modules, OHADA, comptabilité d'engagement, multi-devise, multi-sociétés, millions d'écritures, IA) correspond à un **ERP comptable complet**. C'est un **programme de plusieurs mois**, pas une livraison unique. Ce document fixe l'architecture et découpe la construction en 6 lots livrables et testables.

**Constat de départ (vérifié) :** aucune comptabilité en partie double n'existe. Les 55 modèles couvrent la **trésorerie et le budget** (encaissements, sorties de fonds, ordres de décaissement, réquisitions, budget, caisse, banque, paie) ; `reports.py` produit des agrégats de flux, **pas un Grand Livre**. Le module est donc à créer intégralement — mais il se greffe sur un socle métier déjà riche, ce qui est un avantage : les faits générateurs existent déjà.

---

## 1. Contraintes imposées par le code existant (non négociables)

Ces cinq constats, vérifiés dans le code, conditionnent toute la conception.

| # | Constat vérifié | Conséquence |
|---|---|---|
| **C1** | Le multi-tenant est **applicatif**, pas RLS PostgreSQL : `db/session.py` filtre les SELECT (`do_orm_execute`) et estampille les écritures (`before_flush`) à partir de **listes de modèles codées en dur** (~60). | **Chaque table `compta_*` doit être ajoutée aux DEUX listes.** Un oubli = fuite inter-organisations silencieuse. **Risque n°1 du module.** À traiter par un mixin `TenantScoped` + test de couverture automatique. |
| **C2** | Le scoping ne s'applique **qu'à l'ORM**. Les requêtes `text()`/SQL Core ne sont **pas** filtrées. | Grand Livre, Balance et états financiers seront écrits en SQL optimisé → **le filtre `organisation_id` devra être explicite et testé** sur chacune de ces requêtes. |
| **C3** | Le **commit appartient à l'endpoint** ; les services (`log_action`, `record_status_history`) font `db.add()` + `flush()` et rejoignent la transaction de l'appelant. | Le moteur comptable doit **se conformer à ce style** : écriture générée dans la **même transaction ACID** que l'opération métier. Pas de canal parallèle. |
| **C4** | `services/tenant_manager.py` **clone des données métier entre organisations** lors du provisioning (postes budgétaires avec `montant_engage`, `montant_paye`). | **Argument décisif contre les hooks ORM automatiques** : ils généreraient des écritures fantômes au provisioning. → déclenchement **explicite** dans les services métier. |
| **C5** | `_validate_tenant_relationships` exécute des SELECT synchrones **par objet** au flush. | Une écriture de 50 lignes ≈ 150 requêtes par flush → **inutilisable en volume**. Le module compta devra contourner (FK composites incluant `organisation_id`, ou exemption ciblée). |

**Autres points relevés :**
- Incohérence de types monétaires (`Numeric(14,2)` vs `(15,2)`). Pour le cœur comptable : **`Numeric(18,2)`** (un budget de 5 M USD ≈ 14 Md CDF sature `Numeric(15,2)`), et **taux en `Numeric(18,8)`** (les `Numeric(12,4)` actuels perdent en précision sur le taux inverse CDF→USD ≈ 0,000357).
- `document_sequences` : les codes `OD`, `CLO`, `OUV` sont **déjà pris** (ordre de décaissement, clôture/ouverture de caisse) et la séquence est calée sur l'**année civile**, alors qu'une pièce comptable se numérote **par exercice et par journal** → **numérotation comptable dédiée**.
- Piège de performance déjà rencontré : `CAST(date AS date)` empêchait tout index (22 s, timeouts) — corrigé par `20260722d_perf_indexes`. **À ne pas reproduire.**
- Actifs réutilisables : `standard_classification.py` (`raw_label → assigned_account`, `occurrence_count`, `confidence_score`, scopé org) = socle du « compte probable selon l'historique » ; `anomaly_scoring.py` (z-score, déterministe) ; `approval_service.py` (modèle de validation humaine) ; RBAC et `audit_log`.
- ⚠️ **Bug confirmé indépendamment :** `services/ai_syscebnl.py` appelle `get_ai_service()` **sans contexte d'organisation** → le provider IA du tenant n'est pas respecté. À corriger (résidu AI-07 déjà documenté).

---

## 2. Architecture d'ensemble

Module autonome `backend/app/modules/comptabilite/`, organisé en domaine (DDD), sur le modèle du module `secretariat/` existant.

```
comptabilite/
├── models/          référentiel, écritures, exercices, analytique, rapprochement
├── schemas/         Pydantic (API)
├── services/
│   ├── referentiel/     plan comptable, journaux, exercices
│   ├── posting/         MOTEUR : résolution de comptes + génération + idempotence
│   ├── cloture/         à-nouveaux, clôture, verrouillage
│   ├── reporting/       grand livre, balances, états financiers
│   ├── rapprochement/   import relevés, matching
│   └── ia/              suggestions (jamais publiantes)
├── routers/
└── rules/           schémas comptables paramétrables (DONNÉES, pas code)
```

**Principe directeur :** aucun numéro de compte dans le code. Tout passe par le **paramétrage en base**.

---

## 3. Cœur du modèle de données

### 3.1 Référentiel

| Table | Rôle | Points clés |
|---|---|---|
| `compta_referentiel` | Le plan « type » (SYSCOHADA révisé, PCG, associatif, ONG, personnalisé) | Permet plusieurs référentiels coexistants ; import Excel alimente une instance |
| `compta_compte` | Comptes du plan | numéro, libellé, classe, sous-classe, **collectif/auxiliaire**, nature, **sens normal**, actif, **analytique obligatoire**, **devise autorisée**, `parent_id` (arbre) |
| `compta_journal` | Journaux illimités | code, libellé, **type** (BQ/CA/AC/VE/OD/SAL/IMMO/CLO/OUV/TVA/AJU), contrepartie par défaut, contrôles |
| `compta_exercice` | Exercices | dates, **statut** (ouvert/fermé/rouvert/clôturé/verrouillé), report à-nouveaux |
| `compta_periode` | Périodes (mois) | verrouillage fin de mois indépendant de la clôture annuelle |

### 3.2 Écritures (invariants stricts)

`compta_ecriture` (entête) + `compta_ligne_ecriture` (lignes).

**Entête :** `uuid`, numéro (par exercice+journal), journal, date, date_piece, référence pièce, libellé, **statut** (BROUILLON → VALIDÉE → CLÔTURÉE), version, créateur, validateur, **origine** (module, type, id), justificatif, `organisation_id`, `exercice_id`.

**Ligne :** compte, compte auxiliaire, libellé, **débit**, **crédit** (`Numeric(18,2)`, jamais négatifs), devise, **taux figé**, montants en devise de tenue, axes analytiques, lettrage, échéance.

**Invariants garantis en base (contraintes), pas seulement en code :**
1. `débit ≥ 0` et `crédit ≥ 0`, et jamais les deux non nuls sur une même ligne ;
2. **équilibre débit = crédit** par écriture (contrôle transactionnel + contrainte différée) ;
3. date **dans un exercice ouvert** ;
4. compte **actif** au moment de la validation ;
5. **aucune suppression physique** : uniquement annulation, contre-passation, historisation ;
6. une écriture **validée est immuable** (trigger interdisant UPDATE/DELETE, sur le modèle de l'immuabilité `audit_logs` déjà prévue).

### 3.3 Performance (volume cible : millions de lignes)

- **Partitionnement déclaratif** (PostgreSQL 16) de `compta_ligne_ecriture` par `organisation_id` (ou par exercice) → élagage des partitions sur toutes les restitutions.
- **Soldes pré-agrégés** `compta_solde_periode` (compte × période × devise × axe) mis à jour à la validation → Balance et états financiers **instantanés** sans balayer les lignes. Le Grand Livre reste détaillé, paginé par curseur.
- Index composites `(organisation_id, exercice_id, compte_id, date)` — **jamais** de fonction sur la colonne de date dans les filtres.
- FK composites incluant `organisation_id` pour contourner C5.

---

## 4. Moteur de génération automatique (le cœur)

### 4.1 Décision d'architecture

**Retenu : déclenchement explicite dans les services métier, dans la même transaction.**
Écarté : hooks ORM automatiques — **à cause de C4** (le clonage inter-tenants produirait des écritures fantômes) ; écarté : file asynchrone découplée — romprait la cohérence ACID avec l'opération financière.

### 4.2 Idempotence (obligatoire)

Chaque fait générateur produit une **clé d'idempotence** `(module, type_operation, operation_id, version)` avec **contrainte UNIQUE** sur la table de liaison `compta_origine`. Un rejeu (retry, double POST, reprise après crash) **ne peut pas** créer de doublon.

### 4.3 Table de liaison

`compta_origine` : `ecriture_id`, `module_origine`, `type_fait`, `objet_id`, `version`, `cle_idempotence` (unique), horodatage. Sert à la traçabilité, à la contre-passation et à la reprise d'historique.

### 4.4 Annulation

Une sortie de fonds annulée (le code ré-crédite déjà la caisse) déclenche :
- **exercice ouvert** → contre-passation datée du jour de l'annulation (jamais de modification de l'écriture d'origine) ;
- **exercice clôturé** → écriture d'ajustement sur l'exercice courant.

### 4.5 Catalogue des faits générateurs (extrait)

| Opération existante | Journal | Débit | Crédit |
|---|---|---|---|
| Encaissement (cotisation) | CA/BQ | Trésorerie (512/571) | Produit (706/756) |
| Sortie de fonds — caisse | CA | Charge (poste budgétaire) | Caisse (571) |
| Sortie de fonds — banque | BQ | Charge / Fournisseur (401) | Banque (512) |
| Ordre de décaissement payé | CA/BQ | Charge | Trésorerie |
| Réquisition — engagement | OD (classes 8/9) | Engagement | Crédits ouverts |
| Réquisition — liquidation | AC | Charge | Fournisseur (401) |
| Réquisition — paiement | BQ/CA | Fournisseur (401) | Trésorerie |
| Remboursement transport | CA/BQ | Charge déplacement (625) | Trésorerie |
| Paie | SAL | Charges de personnel (66) | Personnel (42) / Organismes (43) |
| Transfert interne | OD | Compte destination | Compte origine |
| Immobilisation | IMMO | Immobilisation (2x) + TVA (445) | Fournisseur (401) |
| Amortissement | OD | Dotation (681) | Amortissements (28) |

### 4.6 Résolution des comptes — 100 % paramétrable

Une **règle** (donnée, pas code) décrit : événement → conditions → lignes (sens, source du compte, source du montant).
Sources de compte : mapping **poste budgétaire → compte de charge**, **compte bancaire → 512x**, **client → auxiliaire 411x**, **rubrique → compte de produit**.
**Cas non paramétré : échec bloquant** (l'opération est refusée) plutôt qu'un compte d'attente silencieux — décision à confirmer (§8).

### 4.7 Robustesse et reprise

- Échec de génération après validation métier → **quarantaine** + alerte + file de reprise (jamais de perte silencieuse).
- **Reprise d'historique** : régénération des écritures pour les opérations déjà en base à la mise en service, via la clé d'idempotence (rejouable sans doublon).

---

## 5. Restitutions et états financiers

- **Grand Livre / Journal** : détail paginé par curseur, sur partitions.
- **Balances** (générale, auxiliaire, âgée, analytique) : servies par les **soldes pré-agrégés**.
- **États financiers OHADA** (Bilan, Résultat, Flux, Annexe, SIG) : construits via une table de **mapping paramétrable « poste d'état ↔ comptes »**, propre à chaque référentiel → aucun compte codé en dur, et support natif de SYSCOHADA/PCG/associatif/ONG.
- **Analytique** : axes multiples par ligne, clés de répartition automatique, articulation avec les `services` et le budget par service existants.
- **Multi-devise** : taux **figé** sur l'écriture, aucune réévaluation rétroactive, écarts de change générés automatiquement.

---

## 6. IA comptable — frontière stricte

| Déterministe (code, jamais LLM) | Probabiliste (LLM) |
|---|---|
| Contrôle d'équilibre, contraintes, règles OHADA, verrouillage d'exercice, calcul des soldes | Suggestion d'imputation, explication en langage naturel, détection d'anomalies « molles » |

- **Garde-fou technique :** l'IA écrit **uniquement** des écritures en statut BROUILLON accompagnées d'une **suggestion** ; la validation passe par le workflow humain (modèle `approval_service` existant), avec traçabilité « qui a accepté quelle suggestion ».
- **Socle historique déterministe :** `standard_classification` (libellé → compte, avec compteur d'occurrences et score) alimente les suggestions **avant** tout appel LLM — moins cher, plus fiable, sans fuite de données.
- **Confidentialité :** routage par organisation (`get_ai_service_for_org`) et repli **Ollama local** pour les tenants refusant l'envoi de données financières à un tiers.

---

## 7. Feuille de route (6 lots)

| Lot | Contenu | Valeur livrée |
|---|---|---|
| **1. Fondations** | Référentiel (plan/journaux/exercices), modèle d'écriture + invariants en base, RBAC comptable, audit | Saisie manuelle fiable et auditable |
| **2. Moteur** | Schémas paramétrables, résolution de comptes, idempotence, liaison origine, contre-passation | Première génération automatique (encaissement + sortie de fonds) |
| **3. Intégrations** | Tous les faits générateurs restants + reprise d'historique | « Aucune saisie manuelle » atteint |
| **4. Restitutions** | Grand Livre, balances, exports (soldes pré-agrégés reportés — cf. §7 sexies) | Utilisable par un comptable au quotidien |
| **5. États financiers** | Mapping paramétrable, Bilan/Résultat/Flux/Annexe/SIG, clôture et à-nouveaux | Conformité OHADA, prêt pour l'audit |
| **6. Avancé** | Engagement complet, analytique, multi-devise, rapprochement bancaire (CSV/Excel/CAMT053/MT940), immobilisations, IA | Parité ERP |

Chaque lot inclut ses tests (unitaires, intégration, concurrence) — non négociable sur des données financières.

---

## 7 bis. Décisions actées (31/07/2026) et démarrage du Lot 1

| Question | Décision |
|---|---|
| Devise de tenue | **USD**, paramétrable par société/exercice, convertible (taux historisés `Numeric(18,8)`) |
| Référentiels | **Plusieurs d'emblée**, réglables : SYSCOHADA révisé, **SYSCEBNL** (entités à but non lucratif — référentiel naturel d'un Ordre professionnel), PCG, associatif, ONG, personnalisé |
| Multi-sociétés | **1 organisation = 1 société en exploitation**, mais la **couche société/établissement est provisionnée dès la fondation** (l'ajouter après coup imposerait de migrer des millions de lignes d'écriture) |

**Portée retenue :** référentiel et comptes **mutualisés au niveau organisation** ; journaux, exercices et écritures **rattachés à une société**. `societe_id` est dénormalisé sur les lignes d'écriture pour éviter une jointure sur les restitutions volumineuses.

### Livré (Lot 1, en cours)
- `backend/app/modules/comptabilite/models.py` — 10 modèles : société, établissement, référentiel, compte, journal, exercice, période, taux de change, écriture, ligne d'écriture.
- Invariants en base : débit/crédit ≥ 0, sens exclusif, ligne non nulle, statuts contrôlés, dates d'exercice cohérentes, unicité de numérotation par société/exercice/journal.
- **Contrainte C1 traitée** : les 10 modèles sont déclarés dans `_apply_tenant_criteria` (`app/db/session.py`) — pas de fuite inter-organisations.
- Modèles enregistrés dans `alembic/env.py` (migration générable).

### Reste à faire sur le Lot 1
Migration Alembic, trigger d'immuabilité des écritures validées, service de numérotation comptable dédié (les codes `OD`/`CLO`/`OUV` de `document_sequences` sont déjà pris et calés sur l'année civile), RBAC comptable, jeux de plans comptables par défaut (SYSCOHADA/SYSCEBNL), tests.

## 7 quater. Lot 3 — intégrations restantes et reprise d'historique (livré, 31/07/2026)

### Faits générateurs ajoutés

| Opération | Journal | Débit | Crédit | Déclencheur |
|---|---|---|---|---|
| Transfert interne autonome | OD | Compte destination | Compte origine | `POST /transferts` |
| Encaissement par paiement en ligne | BQ | Trésorerie (512x) | Produit (rubrique) | webhook `online_payments` |
| Paie — constatation | SAL | Charges de personnel (66) | Personnel (42) + Organismes (43) + État IPR (44) | `POST /hr/payroll-entries/{id}/validate` |
| Annulation d'encaissement / de sortie | — | contre-passation | contre-passation | `cancel-operation`, `PATCH /statut=ANNULEE` |

**Trou comblé en priorité :** `POST /transferts` déplaçait de la trésorerie (caisse ↔ banque) **sans produire la moindre écriture**. C'était le seul mouvement de fonds resté hors du moteur après le Lot 2.

### Résolution par rubrique technique (`compta_mapping_rubrique`)

La paie et les encaissements sans imputation budgétaire n'ont ni poste budgétaire ni compte bancaire à mapper. Une troisième table de paramétrage résout le compte à partir d'un **code fonctionnel stable** : `PAIE_CHARGES_PERSONNEL`, `PAIE_PERSONNEL_DU`, `PAIE_ORGANISMES_SOCIAUX`, `PAIE_ETAT_IPR`, `PRODUIT_PAIEMENT_EN_LIGNE`. Même règle que les autres résolutions : aucun numéro de compte en Python, mapping absent = échec bloquant. `generer_mappings_par_defaut` provisionne les cinq rubriques (661 / 421 / 431 / 447 / 758), présentes dans les deux plans livrés.

### Paie : éviter la double comptabilisation (point de paramétrage important)

La validation d'un run de paie **constate la charge** (D 66 / C 42-43-44). Le règlement des salaires reste une sortie de fonds ordinaire, qui génère sa propre écriture à partir du poste budgétaire. Si ce poste est mappé sur un compte de charge, la charge est comptée **deux fois**.

→ **Le poste budgétaire « salaires » doit être mappé sur le compte de dette envers le personnel (42), pas sur un compte de charge.** Le règlement solde alors la dette (D 42 / C trésorerie). C'est du paramétrage, pas du code — aucune détection automatique n'est tentée, l'application ne peut pas savoir qu'une sortie de fonds donnée paie des salaires.

Une **écriture par devise** : un run peut mêler des bulletins USD et CDF, alors qu'une écriture porte une devise unique. La devise fait donc partie de la clé d'idempotence (`{payroll_entry_id}:{devise}`).

### Annulation

`annuler_ecriture_operation` distingue trois cas :
- **aucune écriture** (opération antérieure à l'activation du module) → sans effet ;
- **BROUILLON** → passage direct à ANNULEE. Contre-passer un brouillon polluerait le journal de deux écritures qui s'annulent, alors qu'il n'a jamais atteint le Grand Livre ;
- **VALIDEE / CLOTUREE** → contre-passation datée du jour, l'écriture d'origine n'étant jamais modifiée.

### Reprise d'historique

`scripts/backfill_compta_ecritures_historique.py` rejoue encaissements, sorties de fonds et transferts déjà en base (`--dry-run`, `--depuis`, `--organisation`). Deux propriétés délibérées :
- **idempotent** — la clé d'idempotence empêche tout doublon, le script est rejouable ;
- **non bloquant, contrairement au moteur en ligne** — chaque opération est traitée dans son propre point de sauvegarde ; un mapping manquant est rapporté sans interrompre la reprise. Refuser de reprendre les autres opérations n'apporterait rien puisque l'opération métier existe déjà.

Les écritures reprises sont au **BROUILLON**, comme celles du moteur : un comptable les revoit et les valide.

### Limites assumées du Lot 3

- **Répartition multi-postes reprise depuis l'ordre de décaissement** : elle n'est pas stockée sur la sortie de fonds (seul le libellé « Réparti sur N postes » en garde la trace). Le backfill la reconstitue depuis les lignes de l'ordre ; si l'ordre est introuvable, la sortie est **signalée** plutôt que comptabilisée sur un compte arbitraire.
- **`soft-delete` / `restore` d'un encaissement hors périmètre** : c'est une corbeille technique réversible, alors que la clé d'idempotence n'autorise qu'une écriture par opération — un cycle suppression/restauration exigerait un versionnement de cette clé. Seule l'annulation métier explicite (`cancel-operation`) est traitée.
- **Comptabilité d'engagement (réquisitions : engagement / liquidation / fournisseur 401)** non traitée : elle relève du Lot 6, et le paiement d'une réquisition est déjà comptabilisé via la sortie de fonds qu'il produit.
- **Webhook de paiement en ligne : échec bloquant conservé.** Une rubrique non mappée annule la transaction et fait échouer le webhook, ce qui déclenche un rejeu côté fournisseur. C'est voulu — encaisser sans écriture laisserait un trou comptable silencieux — et le rejeu ne peut pas créer de doublon.

## 7 quinquies. Écran de paramétrage des mappings (livré, 01/08/2026)

Le moteur ne contient aucun numéro de compte : il résout tout via les trois tables de mapping, et une résolution manquante **bloque l'opération métier**. Jusqu'ici ce paramétrage n'existait qu'en script (comptes génériques) ou en SQL manuel — l'écran comble ce manque.

- `GET /comptabilite/mappings` : état complet (postes budgétaires du dernier exercice budgétaire, comptes de trésorerie, rubriques techniques, caisse par défaut) avec **`nb_non_mappes`**, affiché en bandeau d'alerte permanent tant qu'il reste des trous.
- `PUT` unitaires + `POST /mappings/defaut` (« compléter », ne touche jamais un mapping affiné).
- **Garde-fous** : compte appartenant à l'organisation, actif, et **non collectif** — un 401/411 exige un compte auxiliaire par écriture, que le moteur ne fournit pas ; l'erreur est plus compréhensible au paramétrage qu'à la validation.
- **Aucune contrainte de nature** entre poste et compte : le cas « salaires → 421 » (cf. §7 quater) impose de pouvoir mapper une dépense sur un compte de passif. L'écran l'explique par un encart au lieu de l'interdire.
- Postes limités au **dernier exercice budgétaire** (paramétrable) : sur plusieurs années la liste serait ingérable, et seul l'exercice en cours conditionne les saisies.

## 7 sexies. Lot 4 — Restitutions (livré, 01/08/2026)

`services/reporting_service.py` + `routers/restitutions.py` + onglet « États » (Balance / Grand Livre / Journal, filtres partagés, drill-down vers l'écriture, exports PDF et Excel).

### Trois décisions structurantes

**1. Quelles écritures entrent dans les états.** Seules **VALIDEE** et **CLOTUREE**. Un BROUILLON n'a pas de numéro et peut encore changer ; une ANNULEE a été neutralisée. `inclure_brouillons` autorise une **simulation** explicite — jamais par défaut, signalée par un bandeau à l'écran et une mention « SIMULATION » sur les exports, qui sinon perdraient l'avertissement une fois imprimés.

**2. Filtre `organisation_id` explicite partout (contrainte C2).** Les requêtes restent en SQLAlchemy — donc scopées par l'ORM — mais chaque `where` porte malgré tout `organisation_id` : une bascule ultérieure vers du SQL brut pour la performance ne doit pas ouvrir de fuite par omission. Un test le vérifie sur deux organisations concurrentes.

**3. Agrégation directe — `compta_solde_periode` volontairement NON introduite.** Le dossier prévoyait des soldes pré-agrégés alimentés à la validation. Un agrégat dénormalisé peut **diverger du détail**, et sur des données financières cette divergence est un bug silencieux. La Balance est donc un `GROUP BY` sur les lignes, exact par construction.
→ **Critère de bascule** : au-delà du million de lignes par exercice, ou si la Balance dépasse ~1 s. La table devra alors s'accompagner d'un test de cohérence agrégat/détail obligatoire.

### Grand Livre — pagination par curseur

Keyset `(date_ecriture, ligne_id)` et non OFFSET : sur des centaines de milliers de lignes l'OFFSET se dégrade linéairement et peut **sauter ou dupliquer** des lignes si une écriture est validée entre deux pages. Le solde progressif reste juste d'une page à l'autre grâce à deux agrégats bornés : le **solde antérieur** à la période et le **cumul avant la page**. Un test parcourt toutes les pages et vérifie qu'aucune ligne n'est perdue ni vue deux fois.

### Contrôle d'équilibre affiché

`Balance.equilibree` est exposé et affiché. L'équilibre est déjà garanti écriture par écriture à la validation : s'il est rompu au niveau de la balance, des données ont été altérées hors de l'application. Le signaler vaut mieux qu'un état faux et muet.

### État vide : message explicite

Les écritures générées automatiquement restant au BROUILLON, une organisation fraîchement mise en service voit une balance vide. L'écran l'explique et renvoie vers la case « inclure les brouillons » plutôt que de laisser croire à une panne.

## 7 ter. Design UI/UX — cohérence avec l'existant

Un spécialiste design a analysé le design system réel. Points structurants :
- **Les couleurs sont des tokens de tenant surchargés à l'exécution** (`--tenant-primary`, `--tenant-sidebar`, `--tenant-accent`, alimentés par `orgSettings` dans `Layout.tsx`) → **ne jamais coder une couleur en dur** ; le module doit paraître natif.
- Palette neutre/sémantique existante à réutiliser telle quelle (`--color-surface`, `--color-border`, succès/alerte/danger/info).
- L'écran décisif pour la crédibilité professionnelle est la **saisie d'écriture** : grille type tableur, saisie clavier sans souris, autocomplétion de compte, **indicateur d'équilibre débit/crédit en temps réel**, contrepartie automatique, suggestions IA **visibles mais jamais bloquantes**.
- Densité informationnelle élevée (un comptable veut voir beaucoup de lignes), pagination par curseur, drill-down du Grand Livre vers l'écriture.
- Accessibilité : associer les labels (l'audit a relevé 585 champs pour 11 `htmlFor` — ne pas reproduire ce défaut).

## 8. Décisions à trancher avant le Lot 1

1. **Référentiel initial** : SYSCOHADA révisé uniquement, ou plusieurs dès le départ ?
2. **Devise de tenue** : USD ou CDF ? (détermine la conversion de toutes les écritures)
3. **Compte non paramétré** : échec bloquant (recommandé) ou compte d'attente ?
4. **Périmètre multi-sociétés** : une organisation = une société, ou plusieurs sociétés/établissements par organisation ?
5. **Comptabilité d'engagement** : obligatoire dès le Lot 2, ou après le socle général ?
6. **Antériorité** : reprend-on l'historique existant, et depuis quelle date ?
7. **Rôles** : la matrice Comptable/Chef comptable/DAF/Auditeur/CAC correspond-elle à votre organisation réelle ?

---

## 9. Points de vigilance (à ne pas oublier en construction)

- Ajouter **chaque** table `compta_*` aux deux listes de scoping tenant (C1) — idéalement via un mixin + test automatique.
- Filtrer explicitement `organisation_id` dans **toute** requête SQL brute de reporting (C2).
- Générer les écritures dans la **transaction de l'opération métier** (C3).
- **Ne pas** utiliser de hooks ORM globaux (C4).
- Neutraliser le coût de `_validate_tenant_relationships` sur les écritures volumineuses (C5).
- Jamais de fonction sur colonne de date dans un filtre (piège des 22 s).
- Corriger `ai_syscebnl.py` (appel IA sans contexte d'organisation).

---

*Document de conception. Aucun code écrit. En attente de validation et des réponses du §8 pour démarrer le Lot 1.*
