-- Audit des dénouements budgétaires manqués à l'annulation d'un paiement.
--
-- STRICTEMENT EN LECTURE. La première instruction met la session en lecture
-- seule : toute écriture, même accidentelle, échoue au lieu de passer.
--
--   docker exec -i <conteneur_db> psql -U <user> -d <base> \
--       -f - < backend/scripts/audit_budget_annulations_non_denouees.sql
--
-- CE QU'ON CHERCHE
-- ---------------
-- `cancel_encaissement_payment` décidait d'un impact budgétaire ainsi :
--
--     if (encaissement.nature_mouvement or "").strip():
--         budget_poste_id = payment.budget_poste_id     -- NULL sur l'historique
--     impact_budgetaire = budget_poste_id is not None
--
-- Or la migration 20260905 a posé `nature_mouvement = 'BUDGETAIRE'` sur TOUTES
-- les lignes existantes, tandis que les paiements antérieurs à cette bascule ne
-- portent aucun `budget_poste_id`. La condition était donc vraie pour tout
-- l'historique, `impact_budgetaire` retombait à False, et l'annulation ne
-- défaisait RIEN côté budget : ni reprise d'imputation, ni ajustement du poste.
--
-- Conséquence : `budget_postes.montant_paye` reste crédité de paiements annulés.
-- La trésorerie, elle, était bien débitée (`_debit_treasury` est hors de ce
-- test) — l'écart est purement budgétaire.
--
-- Les deux chemins d'annulation sont couverts : annulation de l'encaissement
-- entier (encaissements.py) et annulation d'un paiement isolé (payments.py).
--
-- COMMENT ON RECONNAÎT UNE LIGNE TOUCHÉE
-- --------------------------------------
--   * le paiement est annulé (`payment_history.statut = 'ANNULE'`) ;
--   * il ne porte pas de poste (`budget_poste_id IS NULL`) — c'est ce qui
--     faisait retomber `impact_budgetaire` à False ;
--   * l'encaissement porte un poste : le paiement a donc bien crédité un budget
--     au moment de son enregistrement, et ce crédit n'a pas été défait ;
--   * l'encaissement n'a AUCUNE imputation, quel que soit son statut. C'est ce
--     qui sépare un mouvement d'avant le registre (à corriger) d'un mouvement
--     hors budget régularisé (déjà dénoué par la reprise de son imputation).
--
-- Le montant est pris brut, sans conversion : c'est ainsi que le crédit avait
-- été appliqué (`_adjust_budget(montant=montant, direction=1)`), donc c'est
-- ainsi qu'il faut le défaire. Si la section 2 fait apparaître du CDF, le poste
-- mélange déjà les devises — question distincte, antérieure à ce bug.
--
-- LIMITE
-- ------
-- L'écart calculé suppose qu'aucune correction manuelle n'a été passée sur
-- `montant_paye` depuis. Une section 2 non vide se recoupe avec la section 1
-- avant toute reprise.

SET default_transaction_read_only = on;
\pset pager off

\echo '=== 0. Cadrage : paiements annulés, selon qu ils portent un poste ==='
SELECT
    (ph.budget_poste_id IS NOT NULL) AS paiement_porte_un_poste,
    (e.budget_poste_id IS NOT NULL) AS encaissement_porte_un_poste,
    count(*) AS n,
    min(ph.date_paiement) AS plus_ancien,
    max(ph.date_paiement) AS plus_recent
FROM payment_history ph
JOIN encaissements e ON e.id = ph.encaissement_id
WHERE ph.statut = 'ANNULE'
GROUP BY 1, 2
ORDER BY n DESC;

\echo ''
\echo '=== 1. ACTIONNABLE — paiements annulés dont le budget n a jamais été'
\echo '    dénoué. Chaque ligne est un montant qui pèse encore sur son poste'
\echo '    alors que le paiement est annulé. ==='
SELECT
    e.numero_recu,
    ph.id AS payment_id,
    ph.montant,
    ph.devise,
    ph.date_paiement,
    e.statut_operation AS encaissement_statut,
    e.nature_mouvement,
    e.budget_poste_id,
    bp.code AS poste_code,
    bp.libelle AS poste_libelle
FROM payment_history ph
JOIN encaissements e ON e.id = ph.encaissement_id
JOIN budget_postes bp ON bp.id = e.budget_poste_id
WHERE ph.statut = 'ANNULE'
  AND ph.budget_poste_id IS NULL
  AND e.budget_poste_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM mouvement_budget_imputations mbi
      WHERE mbi.encaissement_id = e.id
  )
ORDER BY ph.date_paiement;

\echo ''
\echo '=== 2. CHIFFRAGE — écart par poste budgétaire : ce que montant_paye'
\echo '    porte aujourd hui, et ce qu il vaudrait une fois ces annulations'
\echo '    défaites. C est la reprise à passer. ==='
SELECT
    bp.id AS poste_id,
    bp.code,
    bp.libelle,
    bp.montant_paye AS montant_paye_actuel,
    sum(ph.montant) AS credit_annule_non_defait,
    bp.montant_paye - sum(ph.montant) AS montant_paye_corrige,
    count(*) AS paiements_concernes
FROM payment_history ph
JOIN encaissements e ON e.id = ph.encaissement_id
JOIN budget_postes bp ON bp.id = e.budget_poste_id
WHERE ph.statut = 'ANNULE'
  AND ph.budget_poste_id IS NULL
  AND e.budget_poste_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM mouvement_budget_imputations mbi
      WHERE mbi.encaissement_id = e.id
  )
GROUP BY bp.id, bp.code, bp.libelle, bp.montant_paye
ORDER BY credit_annule_non_defait DESC;

\echo ''
\echo '=== 3. GARDE-FOU — postes que la reprise rendrait négatifs. Un montant'
\echo '    ici signale autre chose qu un simple dénouement manqué (correction'
\echo '    manuelle passée depuis, ou double comptage) : à instruire avant'
\echo '    toute écriture. ==='
SELECT
    bp.code,
    bp.montant_paye AS montant_paye_actuel,
    sum(ph.montant) AS credit_annule_non_defait,
    bp.montant_paye - sum(ph.montant) AS resultat_negatif
FROM payment_history ph
JOIN encaissements e ON e.id = ph.encaissement_id
JOIN budget_postes bp ON bp.id = e.budget_poste_id
WHERE ph.statut = 'ANNULE'
  AND ph.budget_poste_id IS NULL
  AND e.budget_poste_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM mouvement_budget_imputations mbi
      WHERE mbi.encaissement_id = e.id
  )
GROUP BY bp.id, bp.code, bp.montant_paye
HAVING bp.montant_paye - sum(ph.montant) < 0
ORDER BY resultat_negatif;

\echo ''
\echo '=== 4. CONTRE-ÉPREUVE — paiements annulés qui, eux, PORTENT un poste :'
\echo '    ceux-là passaient par le chemin correct. Leur présence en nombre'
\echo '    confirme que la section 1 isole bien l historique, et non tout'
\echo '    l ensemble des annulations. ==='
SELECT count(*) AS annulations_correctement_traitees
FROM payment_history ph
WHERE ph.statut = 'ANNULE'
  AND ph.budget_poste_id IS NOT NULL;

\echo ''
\echo '=== 5. EXPOSITION LATENTE — paiements ENCORE ACTIFS qui ne portent pas de'
\echo '    poste. Ce sont eux qui emprunteraient le chemin fautif le jour où on'
\echo '    les annulerait. La colonne `verdict` dit ce qu il adviendrait :'
\echo '      - RIEN A DENOUER  : ni le paiement ni l encaissement ne portent de'
\echo '        poste (fonds de tiers, hors budget non régularisé) — correct,'
\echo '        avant comme après le correctif ;'
\echo '      - DENOUE PAR IMPUTATION : la reprise passe par le registre ;'
\echo '      - A RISQUE SANS LE CORRECTIF : le poste de l encaissement resterait'
\echo '        crédité. Ces lignes justifient à elles seules le déploiement. ==='
SELECT
    e.numero_recu,
    ph.montant,
    ph.devise,
    e.nature_mouvement,
    e.budget_poste_id AS poste_encaissement,
    (SELECT count(*) FROM mouvement_budget_imputations m WHERE m.encaissement_id = e.id) AS imputations,
    CASE
        WHEN e.budget_poste_id IS NULL THEN 'RIEN A DENOUER'
        WHEN EXISTS (SELECT 1 FROM mouvement_budget_imputations m WHERE m.encaissement_id = e.id)
            THEN 'DENOUE PAR IMPUTATION'
        ELSE 'A RISQUE SANS LE CORRECTIF'
    END AS verdict
FROM payment_history ph
JOIN encaissements e ON e.id = ph.encaissement_id
WHERE ph.statut = 'ACTIF'
  AND ph.budget_poste_id IS NULL
ORDER BY 7, ph.date_paiement;
