-- Relevé d'utilisation des index — LECTURE SEULE, ne modifie rien.
--
-- À lancer SUR LA PRODUCTION avant toute suppression d'index. C'est le
-- prérequis posé par docs/performance-audit-20260826/perf-postgres.md (C-3) :
-- l'analyse statique dit qu'un index n'a pas de requête qui le servirait ;
-- seul `idx_scan` relevé en production dit s'il est réellement inutilisé.
--
--   psql "$DATABASE_URL" -f backend/scripts/pg_index_usage.sql > idx_prod.txt
--
-- Deux pièges à vérifier dans la sortie :
--   1. `stats_reset` récent  → les compteurs ne couvrent pas un cycle complet
--      (fin de mois, clôtures, rapports annuels). Attendre.
--   2. base de faible volume → un `idx_scan` bas peut vouloir dire « table trop
--      petite pour qu'un index serve », pas « index inutile ». Regarder `lignes`.

\pset pager off

\echo '== 1. Ancienneté des compteurs (si récent, le relevé ne conclut pas) =='
SELECT datname, stats_reset, now() - stats_reset AS anciennete
FROM pg_stat_database WHERE datname = current_database();

\echo ''
\echo '== 2. Volume des tables visées (un idx_scan bas sur table vide ne prouve rien) =='
SELECT relname AS "table", n_live_tup AS lignes, seq_scan, idx_scan,
       pg_size_pretty(pg_total_relation_size(relid)) AS taille_totale
FROM pg_stat_user_tables
WHERE relname IN ('encaissements','requisitions','sorties_fonds','payment_history',
                  'budget_postes','notification_logs','ai_usage_logs',
                  'budget_audit_logs','hr_attendance_punches')
ORDER BY n_live_tup DESC;

\echo ''
\echo '== 3. Les 25 index candidats à la suppression (C-3) =='
SELECT s.relname AS "table", s.indexrelname AS index, s.idx_scan AS scans,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS taille,
       CASE WHEN i.indisunique THEN 'UNIQUE — ne pas supprimer' ELSE '' END AS reserve
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE s.indexrelname IN (
  -- C-3a : préfixes couverts par un composite
  'ix_encaissements_organisation_id','ix_requisitions_organisation_id','ix_sorties_fonds_organisation_id',
  -- C-3b : doublons entre les deux migrations de perf
  'ix_requisitions_org_created','ix_sorties_org_created',
  -- C-3c : mono-colonne à faible sélectivité
  'ix_encaissements_is_deleted','ix_encaissements_is_reconciled','ix_encaissements_statut_operation',
  'ix_encaissements_statut_comptabilisation','ix_encaissements_type_client','ix_encaissements_statut_paiement',
  'ix_requisitions_is_deleted','ix_requisitions_examen_status','ix_sorties_fonds_is_reconciled',
  'ix_sorties_fonds_statut_comptabilisation','ix_budget_postes_is_deleted','ix_budget_postes_is_global',
  -- C-3d : dates mono-colonne dominées par leur composite
  'ix_encaissements_date_encaissement','ix_sorties_fonds_date_paiement',
  'ix_payment_history_created_at','ix_payment_history_encaissement_id',
  'ix_ai_usage_logs_organisation_id','ix_ai_usage_logs_created_at',
  'ix_notification_logs_organisation_id','ix_budget_audit_logs_organisation_id',
  'ix_hr_attendance_punches_tenant_id'
)
ORDER BY s.idx_scan, s.relname, s.indexrelname;

\echo ''
\echo '== 4. Nombre d''entrees d''index maintenues par INSERT sur les tables d''ecriture =='
SELECT t.relname AS "table", count(*) AS index_maintenus
FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid
WHERE t.relname IN ('encaissements','requisitions','sorties_fonds')
GROUP BY t.relname ORDER BY count(*) DESC;
