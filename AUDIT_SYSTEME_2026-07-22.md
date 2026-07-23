# Audit système — one_cpk_gestion_trésorerie
Date : 22/07/2026 · Périmètre : sécurité, multi-tenant, intégrité financière (backend FastAPI + frontend React)

Cet audit relève les failles et fragilités par ordre de gravité, avec pour chacune l'emplacement, le risque et la correction recommandée. Aucune modification de code n'a été appliquée : ce document sert de plan d'action à valider.

## Synthèse

L'architecture est saine dans l'ensemble : cloisonnement multi-tenant systématique via `tenant_id`, tokens JWT en mémoire seule (pas de localStorage), verrous `with_for_update` sur les soldes, rate-limiting du login et plafonnement des tentatives OTP. Les points ci-dessous sont les axes d'amélioration, dont deux critiques à traiter en priorité.

## Critique

### C1 — Clé SSH privée et dump de base présents dans l'historique git
Les fichiers `onec.pem`, `onec ck.ppk` (clés SSH) et `onec_cpk_local.sql` (dump complet de la base) ont été committés (commit `c7cee81`) puis retirés du suivi dans des commits ultérieurs. Ils restent récupérables dans l'historique git par quiconque a accès au dépôt.

Risque : accès serveur complet via la clé privée, et exposition de toutes les données clients/financières du dump. Le `.gitignore` corrige le futur mais pas le passé.

Correction : considérer la clé SSH comme compromise et la **révoquer/régénérer immédiatement** sur le serveur. Purger l'historique git (`git filter-repo` ou BFG Repo-Cleaner) pour supprimer ces fichiers de tous les commits, puis forcer le push. Changer aussi tout secret présent dans le dump (mots de passe applicatifs).

### C2 — Crash de la sortie de fonds si l'organisation n'a pas de PrintSettings
Dans `backend/app/api/v1/endpoints/sorties_fonds.py`, la création de l'objet `sortie = SortieFonds(...)` est indentée **à l'intérieur** du bloc `if print_settings is not None:` (~ligne 1000-1034), alors que `db.add(sortie)` est à l'extérieur (~ligne 1035). Pour une organisation sans ligne PrintSettings configurée, la variable `sortie` n'est jamais créée et la requête échoue (UnboundLocalError / erreur 500) — aucune sortie de fonds n'est possible.

Risque : blocage total des paiements pour toute nouvelle organisation tant que PrintSettings n'est pas renseigné, sans message clair.

Correction : désindenter le bloc `sortie = SortieFonds(...)` pour le sortir du `if print_settings`. Le calcul de `exchange_rate_snapshot` peut rester conditionnel, mais la création de la sortie doit être inconditionnelle.

## Élevé

### H1 — Montant négatif accepté sur les sorties de fonds
Le schéma `SortieFondsCreate` déclare `montant_paye: Decimal` sans contrainte de positivité (`backend/app/schemas/sortie_fonds.py`). Les contrôles métier ne testent que `montant_paye > solde_disponible`. Un montant négatif passe ce test, puis `caisse.solde = solde - montant_paye` **augmente** le solde de caisse.

Risque : injection de fonds fictifs en caisse/banque via une valeur négative — falsification directe de la trésorerie.

Correction : ajouter `montant_paye: Decimal = Field(gt=0)` dans le schéma (comme c'est déjà fait pour les encaissements), et une garde explicite `if montant_paye <= 0: raise HTTPException(400, ...)` dans l'endpoint. Vérifier le même point pour les transferts internes (déjà protégés par `montant <= 0`).

### H2 — Contrôle de plafond de la sortie directe contournable via le montant
Le plafond « 100 USD » de la sortie directe est vérifié à la programmation de l'ordre, et à l'exécution le montant est repris de l'ordre — c'est correct. En revanche, s'assurer qu'aucun autre endpoint (édition, conversion) ne permet de modifier `montant` d'un ordre `AUTORISE` après coup. À vérifier : il n'existe pas de PUT sur `ordres_decaissement` (bon), mais documenter cette invariance.

Correction : ajouter un test automatisé garantissant qu'un ordre AUTORISE est immuable en montant/bénéficiaire jusqu'au paiement ou à l'annulation.

## Moyen

### M1 — Emails de reçu/relance sans journalisation d'échec visible par l'utilisateur
Les envois passent en tâche de fond (`background_tasks`) et les erreurs SMTP ne sont que loguées. La caissière croit que le client a été notifié alors que l'email a pu échouer silencieusement.

Correction : tracer le résultat d'envoi (succès/échec) dans une table ou un champ, et l'exposer dans l'UI (« dernier email : échec »). Pour les relances, l'incrément de `relance_count` a lieu même si l'envoi échoue ensuite en tâche de fond — envisager de n'incrémenter qu'après confirmation d'envoi, ou d'exposer l'état réel.

### M2 — Cohérence des soldes à l'annulation d'un encaissement partiel
L'annulation d'un encaissement retire `montant_paye` de la caisse avec `max(0, solde - montant_paye)`. Le `max(0, …)` évite un solde négatif mais **masque** une incohérence : si le solde était insuffisant, une partie de la sortie disparaît sans trace. De plus, avec l'historique de paiements complémentaires, `montant_paye` cumulé peut différer de ce qui est réellement entré par canal (si des paiements ont transité par des canaux différents).

Correction : reconstituer le montant à re-débiter à partir de l'historique des paiements (par canal réel), et journaliser tout écart plutôt que de le tronquer silencieusement à zéro.

### M3 — Pas de contrôle de solde caisse suffisant côté versement/annulation banque
Le versement caisse→banque vérifie le solde de caisse (bon). Vérifier que l'annulation d'un versement ne peut pas rendre le solde bancaire négatif si des mouvements ont eu lieu entre-temps (le re-débit banque n'a pas de garde `max(0, …)` ni de contrôle).

Correction : ajouter un contrôle de solde/borne lors des annulations de transferts, avec journalisation des cas limites.

### M4 — Absence de tests automatisés sur les flux financiers modifiés
Les tests nécessitent `TEST_DATABASE_URL` (PostgreSQL) et ne sont pas exécutables en l'état ici. Les récents changements (sorties directes verrouillées, versement/approvisionnement, compléments de paiement, relances) ne sont pas couverts.

Correction : ajouter des tests d'intégration sur : invariance des ordres, positivité des montants, cohérence des soldes après paiement/annulation, plafond des relances.

## Faible

### F1 — `access_token_expire_minutes` à 480 (8 h)
Durée de vie de l'access token relativement longue pour une application financière. Acceptable si le refresh est bien géré, mais 8 h laisse une fenêtre d'usage d'un token volé.

Correction : envisager 30–60 min pour l'access token, en s'appuyant sur le refresh HttpOnly déjà en place.

### F2 — Messages d'erreur exposant des détails d'implémentation
Certaines erreurs renvoient des détails techniques (« Contrainte SQL non mise à jour sur… »). Utile en interne, à masquer en production.

Correction : messages génériques côté client, détails réservés aux logs serveur.

### F3 — Validation d'email absente sur les fiches clients
Le champ email client accepte toute chaîne. Un email mal formé fera échouer les relances silencieusement.

Correction : valider le format email (Pydantic `EmailStr`) à la création/mise à jour de client et à la saisie côté frontend.

## Points positifs relevés
Cloisonnement multi-tenant appliqué sur chaque requête (filtre `organisation_id`), rejet des conflits de tenant entre host et header, tokens en mémoire seule, cookies refresh HttpOnly, verrous `with_for_update` sur caisse/banque/réquisition, rate-limiting login (5/min) et plafond OTP (3 tentatives), séparation des pouvoirs sur les décaissements, contrôle de caisse ouverte avant tout mouvement, et — récemment — plafonnement des relances et anti-doublons clients.

## Ordre de traitement recommandé
1. C1 (révoquer la clé SSH, purger l'historique git) — à faire aujourd'hui.
2. C2 (désindenter la création de sortie) — correctif d'une ligne, à déployer vite.
3. H1 (positivité des montants de sortie) — correctif court, fort impact.
4. H2, M1–M4 — dans le sprint courant.
5. F1–F3 — améliorations continues.
