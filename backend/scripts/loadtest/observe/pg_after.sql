-- A jouer JUSTE APRES un palier.
--   docker compose exec -T db psql -U $POSTGRES_USER -d $POSTGRES_DB -f - < observe/pg_after.sql > resultats/<palier>_pg.txt

\echo '=== 1. Requetes les plus couteuses en temps cumule ==='
SELECT round(total_exec_time::numeric, 1)          AS total_ms,
       calls,
       round(mean_exec_time::numeric, 2)           AS moyenne_ms,
       round((100 * total_exec_time / NULLIF(sum(total_exec_time) OVER (), 0))::numeric, 1) AS pct,
       rows,
       left(regexp_replace(query, '\s+', ' ', 'g'), 160) AS requete
  FROM pg_stat_statements
 ORDER BY total_exec_time DESC
 LIMIT 25;

\echo '=== 2. Requetes les plus lentes a l unite (index manquant ?) ==='
SELECT round(mean_exec_time::numeric, 2) AS moyenne_ms,
       calls,
       round(stddev_exec_time::numeric, 2) AS ecart_type_ms,
       left(regexp_replace(query, '\s+', ' ', 'g'), 160) AS requete
  FROM pg_stat_statements
 WHERE calls > 20
 ORDER BY mean_exec_time DESC
 LIMIT 25;

\echo '=== 3. Connexions : la saturation du pool se voit ici autant que dans les logs ==='
SELECT state, count(*) FROM pg_stat_activity WHERE datname = current_database() GROUP BY state;
SELECT max(count) AS pic_connexions_observe FROM (SELECT count(*) AS count FROM pg_stat_activity) s;
SELECT setting::int AS max_connections FROM pg_settings WHERE name = 'max_connections';

\echo '=== 4. Attentes de verrou (contention d ecriture) ==='
SELECT wait_event_type, wait_event, count(*)
  FROM pg_stat_activity
 WHERE datname = current_database() AND wait_event IS NOT NULL
 GROUP BY 1, 2 ORDER BY 3 DESC;

\echo '=== 5. Sante de la base sur la duree du tir ==='
SELECT xact_commit, xact_rollback,
       round(100.0 * xact_rollback / NULLIF(xact_commit + xact_rollback, 0), 2) AS pct_rollback,
       blks_read, blks_hit,
       round(100.0 * blks_hit / NULLIF(blks_hit + blks_read, 0), 2) AS pct_cache,
       deadlocks, temp_files, pg_size_pretty(temp_bytes) AS temp
  FROM pg_stat_database WHERE datname = current_database();

\echo '=== 6. CONTRAT DE NUMEROTATION : aucun doublon ne doit apparaitre ==='
SELECT 'requisitions' AS table, organisation_id, numero_requisition, count(*)
  FROM requisitions GROUP BY 1,2,3 HAVING count(*) > 1
UNION ALL
SELECT 'encaissements', organisation_id, numero_recu, count(*)
  FROM encaissements WHERE numero_recu IS NOT NULL GROUP BY 1,2,3 HAVING count(*) > 1
UNION ALL
SELECT 'sorties_fonds', organisation_id, reference_numero, count(*)
  FROM sorties_fonds WHERE reference_numero IS NOT NULL GROUP BY 1,2,3 HAVING count(*) > 1;

\echo '=== 7. Sequences documentaires apres tir (progression et trous) ==='
-- Le contrat retenu en Phase 3 est l unicite et l ordre croissant, PAS
-- l absence de trous (docs/PERFORMANCE_WRITE_CONTENTION_20260803.md,
-- « Garantie non revendiquee : absence absolue de trous »). Un ecart entre
-- compteur et nombre de documents mesure les rollbacks, il n est pas un echec.
SELECT s.doc_type, s.year, s.service_id, s.counter AS compteur_sequence,
       (SELECT count(*) FROM requisitions r
         WHERE r.organisation_id = s.tenant_id
           AND r.numero_requisition LIKE s.doc_type || '-%-' || s.year || '-%') AS documents_reels
  FROM document_sequences s
 WHERE s.doc_type = 'REQ'
 ORDER BY s.service_id;

\echo '=== 8. Index reellement utilises sur les tables chaudes ==='
SELECT relname AS table, indexrelname AS index, idx_scan AS lectures_index
  FROM pg_stat_user_indexes
 WHERE relname IN ('requisitions','encaissements','sorties_fonds','lignes_requisition','budget_postes')
 ORDER BY relname, idx_scan DESC;

\echo '=== 9. Scans sequentiels sur les tables chaudes (index manquant) ==='
SELECT relname AS table, seq_scan, seq_tup_read, idx_scan,
       round(100.0 * seq_scan / NULLIF(seq_scan + idx_scan, 0), 1) AS pct_seq
  FROM pg_stat_user_tables
 WHERE relname IN ('requisitions','encaissements','sorties_fonds','lignes_requisition','budget_postes')
 ORDER BY seq_tup_read DESC;
