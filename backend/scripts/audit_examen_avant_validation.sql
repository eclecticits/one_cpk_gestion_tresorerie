-- Audit préalable au contrôle « examen requis » sur la validation technique.
--
-- STRICTEMENT EN LECTURE. La première instruction met la session en lecture
-- seule : toute écriture, même accidentelle, échoue au lieu de passer.
--
--   docker exec -i <conteneur_db> psql -U <user> -d <base> \
--       -f - < backend/scripts/audit_examen_avant_validation.sql
--
-- `validate_requisition_logic` oppose désormais l'examen au passage en
-- validation, comme la mise à jour PATCH le faisait déjà. La question à
-- trancher avant déploiement est unique :
--
--     existe-t-il, en base, des réquisitions en attente de validation dont
--     l'examen n'a jamais été fait ?
--
-- Elles deviendraient non validables tant qu'elles ne repassent pas par
-- l'examen. Ce n'est pas un blocage définitif — le circuit reste ouvert par
-- `/submit-examen` puis `/validate-examen` — mais c'est une intervention
-- manuelle qu'il vaut mieux connaître avant que le caissier ne la découvre.
--
-- Attention au repli : `workflow_snapshot` NULL vaut « circuit complet »
-- (preset par défaut), donc examen ACTIF. Une réquisition sans photo de
-- circuit est concernée, pas épargnée.
--
-- Une section qui renvoie 0 ligne est un feu vert pour ce risque précis.

SET default_transaction_read_only = on;
\pset pager off

\echo '=== 0. Cadrage : réquisitions en attente, par statut et état d examen ==='
SELECT
    status,
    coalesce(nullif(trim(examen_status), ''), '(vide/NULL)') AS examen_status,
    (workflow_snapshot IS NULL) AS sans_snapshot_circuit,
    count(*) AS n
FROM requisitions
WHERE is_deleted IS NOT TRUE
  AND upper(status) IN ('EN_ATTENTE', 'EN_ATTENTE_COMMISSION')
GROUP BY 1, 2, 3
ORDER BY n DESC;

\echo ''
\echo '=== 1. BLOQUANT — réquisitions que la validation technique refusera.'
\echo '    En attente de validation, examen non fait, et examen actif dans le'
\echo '    circuit (snapshot NULL = circuit complet = examen actif). ==='
SELECT
    r.id,
    r.numero_requisition,
    r.status,
    r.examen_status,
    r.montant_total,
    r.devise,
    r.service_id,
    r.dossier_id,
    (r.workflow_snapshot IS NULL) AS sans_snapshot_circuit,
    r.created_at
FROM requisitions r
WHERE r.is_deleted IS NOT TRUE
  AND upper(r.status) IN ('EN_ATTENTE', 'EN_ATTENTE_COMMISSION')
  AND upper(coalesce(r.examen_status, '')) <> 'EXAMINE'
  AND (
      r.workflow_snapshot IS NULL
      OR coalesce(
             (r.workflow_snapshot -> 'steps' -> 'examen' ->> 'enabled')::boolean,
             true
         ) IS TRUE
  )
ORDER BY r.created_at;

\echo ''
\echo '=== 2. Contexte — parmi les bloquantes, celles déjà rattachées à un'
\echo '    dossier d examen : elles se débloquent par le dossier, pas une à une. ==='
SELECT
    d.id AS dossier_id,
    d.status AS dossier_status,
    count(r.id) AS requisitions_bloquees
FROM requisitions r
JOIN dossiers_requisition d ON d.id = r.dossier_id
WHERE r.is_deleted IS NOT TRUE
  AND upper(r.status) IN ('EN_ATTENTE', 'EN_ATTENTE_COMMISSION')
  AND upper(coalesce(r.examen_status, '')) <> 'EXAMINE'
GROUP BY 1, 2
ORDER BY requisitions_bloquees DESC;

\echo ''
\echo '=== 3. Contre-épreuve — réquisitions AUTORISEE (en attente de visa) dont'
\echo '    l examen n a jamais été fait. Le visa n est volontairement PAS gardé :'
\echo '    ces lignes passeront. Si ce compte n est pas nul, c est que des pièces'
\echo '    ont franchi la validation sans examen AVANT ce correctif. ==='
SELECT
    r.id,
    r.numero_requisition,
    r.examen_status,
    r.montant_total,
    r.devise,
    r.validee_par,
    r.validee_le
FROM requisitions r
WHERE r.is_deleted IS NOT TRUE
  AND upper(r.status) = 'AUTORISEE'
  AND upper(coalesce(r.examen_status, '')) <> 'EXAMINE'
ORDER BY r.validee_le NULLS LAST;
