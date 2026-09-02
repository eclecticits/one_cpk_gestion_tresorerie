-- Audit préalable au verrouillage « devise de la réquisition = devise de la sortie ».
--
-- STRICTEMENT EN LECTURE. La première instruction met la session en lecture
-- seule : toute écriture, même accidentelle, échoue au lieu de passer.
--
--   docker exec -i <conteneur_db> psql -U <user> -d <base> \
--       -f - < backend/scripts/audit_devise_requisition_sortie.sql
--
-- Chaque section répond à une question : « qu'est-ce qui, aujourd'hui en base,
-- cesserait de fonctionner si la devise de la réquisition devenait autoritaire ? »
-- Une section qui renvoie 0 ligne est un feu vert pour ce risque précis.

SET default_transaction_read_only = on;
\pset pager off

\echo '=== 0. Cadrage : réquisitions par devise et statut ==='
SELECT
    coalesce(nullif(trim(devise), ''), '(vide/NULL)') AS devise,
    status,
    count(*) AS n
FROM requisitions
WHERE is_deleted IS NOT TRUE
GROUP BY 1, 2
ORDER BY n DESC;

\echo ''
\echo '=== 1. BLOQUANT — réquisitions payables dont le compte rattaché est dans une'
\echo '    autre devise. Au premier paiement : 400 « Devise de la réquisition'
\echo '    incompatible avec le compte sélectionné ». ==='
SELECT
    r.organisation_id,
    r.numero_requisition,
    r.status,
    r.devise        AS devise_requisition,
    cb.devise       AS devise_compte,
    r.montant_total
FROM requisitions r
JOIN comptes_bancaires cb ON cb.id = r.compte_bancaire_id
WHERE r.is_deleted IS NOT TRUE
  AND r.status IN ('APPROUVEE', 'EN_DECAISSEMENT')
  AND nullif(trim(r.devise), '') IS NOT NULL
  AND upper(trim(cb.devise)) IS DISTINCT FROM upper(trim(r.devise))
ORDER BY r.organisation_id, r.numero_requisition;

\echo ''
\echo '=== 2. INCOHÉRENCE HISTORIQUE — sorties déjà payées dans une devise autre que'
\echo '    celle de leur réquisition. Le cumul « reste dû » compare des montants'
\echo '    sans conversion : ces pièces sont déjà fausses, et le verrouillage'
\echo '    changera le comportement des paiements complémentaires. ==='
SELECT
    r.organisation_id,
    r.numero_requisition,
    r.status,
    r.devise                       AS devise_requisition,
    sf.devise                      AS devise_sortie,
    count(*)                       AS nb_sorties,
    sum(sf.montant_paye)           AS total_paye
FROM sorties_fonds sf
JOIN requisitions r ON r.id = sf.requisition_id
WHERE sf.statut = 'VALIDE'
  AND nullif(trim(r.devise), '') IS NOT NULL
  AND upper(trim(sf.devise)) IS DISTINCT FROM upper(trim(r.devise))
GROUP BY 1, 2, 3, 4, 5
ORDER BY total_paye DESC;

\echo ''
\echo '=== 3. ANGLE MORT — réquisitions payables sans devise. Le garde-fou'
\echo '    `if req.devise:` les laisse passer : la sortie garde la devise du'
\echo '    payload, donc la règle ne les protège pas. ==='
SELECT
    organisation_id,
    numero_requisition,
    status,
    montant_total,
    compte_bancaire_id
FROM requisitions
WHERE is_deleted IS NOT TRUE
  AND status IN ('APPROUVEE', 'EN_DECAISSEMENT')
  AND nullif(trim(coalesce(devise, '')), '') IS NULL
ORDER BY organisation_id, numero_requisition;

\echo ''
\echo '=== 4. BLOQUANT — ordres autorisés dont la devise diffère de celle de leur'
\echo '    réquisition. Au paiement, la devise de la réquisition s''impose : le'
\echo '    montant autorisé serait débité dans une autre devise que prévu. ==='
SELECT
    od.organisation_id,
    od.numero_ordre,
    od.statut,
    od.devise       AS devise_ordre,
    r.devise        AS devise_requisition,
    od.montant
FROM ordres_decaissement od
JOIN requisitions r ON r.id = od.requisition_id
WHERE od.statut = 'AUTORISE'
  AND nullif(trim(r.devise), '') IS NOT NULL
  AND upper(trim(od.devise)) IS DISTINCT FROM upper(trim(r.devise))
ORDER BY od.organisation_id, od.numero_ordre;

\echo ''
\echo '=== 5. SIGNAL — réquisitions dont des lignes portent une autre devise que'
\echo '    l''en-tête. L''imputation budgétaire et le montant total y sont déjà'
\echo '    exposés à une addition de devises hétérogènes. ==='
SELECT
    r.organisation_id,
    r.numero_requisition,
    r.status,
    r.devise                          AS devise_requisition,
    lr.devise                         AS devise_ligne,
    count(*)                          AS nb_lignes,
    sum(lr.montant_total)             AS total_lignes
FROM lignes_requisition lr
JOIN requisitions r ON r.id = lr.requisition_id
WHERE r.is_deleted IS NOT TRUE
  AND nullif(trim(r.devise), '') IS NOT NULL
  AND upper(trim(coalesce(lr.devise, 'USD'))) IS DISTINCT FROM upper(trim(r.devise))
GROUP BY 1, 2, 3, 4, 5
ORDER BY r.organisation_id, r.numero_requisition;

\echo ''
\echo '=== 6. Synthèse : nombre de pièces concernées par section ==='
SELECT '1. compte en devise différente (payables)' AS section, count(*) AS pieces
FROM requisitions r JOIN comptes_bancaires cb ON cb.id = r.compte_bancaire_id
WHERE r.is_deleted IS NOT TRUE AND r.status IN ('APPROUVEE','EN_DECAISSEMENT')
  AND nullif(trim(r.devise),'') IS NOT NULL
  AND upper(trim(cb.devise)) IS DISTINCT FROM upper(trim(r.devise))
UNION ALL
SELECT '2. sorties payées en devise différente', count(DISTINCT sf.requisition_id)
FROM sorties_fonds sf JOIN requisitions r ON r.id = sf.requisition_id
WHERE sf.statut = 'VALIDE' AND nullif(trim(r.devise),'') IS NOT NULL
  AND upper(trim(sf.devise)) IS DISTINCT FROM upper(trim(r.devise))
UNION ALL
SELECT '3. réquisitions payables sans devise', count(*)
FROM requisitions
WHERE is_deleted IS NOT TRUE AND status IN ('APPROUVEE','EN_DECAISSEMENT')
  AND nullif(trim(coalesce(devise,'')),'') IS NULL
UNION ALL
SELECT '4. ordres autorisés en devise différente', count(*)
FROM ordres_decaissement od JOIN requisitions r ON r.id = od.requisition_id
WHERE od.statut = 'AUTORISE' AND nullif(trim(r.devise),'') IS NOT NULL
  AND upper(trim(od.devise)) IS DISTINCT FROM upper(trim(r.devise))
UNION ALL
SELECT '5. réquisitions à lignes en devise différente', count(DISTINCT lr.requisition_id)
FROM lignes_requisition lr JOIN requisitions r ON r.id = lr.requisition_id
WHERE r.is_deleted IS NOT TRUE AND nullif(trim(r.devise),'') IS NOT NULL
  AND upper(trim(coalesce(lr.devise,'USD'))) IS DISTINCT FROM upper(trim(r.devise));

\echo ''
\echo '=== 7. Représentativité de la base auditée ==='
\echo '    Un audit sur une base sans historique de paiement ne prouve rien.'
SELECT
    (SELECT count(*) FROM requisitions WHERE is_deleted IS NOT TRUE) AS requisitions,
    (SELECT count(*) FROM lignes_requisition)                        AS lignes,
    (SELECT count(*) FROM sorties_fonds)                             AS sorties,
    (SELECT count(*) FROM ordres_decaissement)                       AS ordres,
    (SELECT count(*) FROM requisitions
      WHERE is_deleted IS NOT TRUE
        AND status IN ('APPROUVEE','EN_DECAISSEMENT'))               AS req_payables;
