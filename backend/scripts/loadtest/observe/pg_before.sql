-- A jouer JUSTE AVANT un palier, pour partir de compteurs propres.
--   docker compose exec -T db psql -U $POSTGRES_USER -d $POSTGRES_DB -f - < observe/pg_before.sql
--
-- pg_stat_statements exige shared_preload_libraries. L'image postgres:16-alpine
-- de docker-compose.yml ne le charge pas par defaut : ajouter, le temps de la
-- campagne, sous le service `db` :
--
--   command:
--     - postgres
--     - -c
--     - shared_preload_libraries=pg_stat_statements
--     - -c
--     - pg_stat_statements.max=5000
--     - -c
--     - pg_stat_statements.track=all
--     - -c
--     - log_min_duration_statement=500
--     - -c
--     - log_lock_waits=on
--
-- (modification a faire dans un fichier d'override local, PAS dans le depot).

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

SELECT pg_stat_statements_reset();
SELECT pg_stat_reset();

\echo '--- Configuration ---'
SELECT name, setting
  FROM pg_settings
 WHERE name IN ('max_connections','shared_buffers','work_mem','effective_cache_size',
                'log_min_duration_statement','log_lock_waits');

\echo '--- Volume par table (le test doit porter sur des donnees, pas sur du vide) ---'
SELECT relname AS table,
       n_live_tup AS lignes_estimees,
       pg_size_pretty(pg_total_relation_size(relid)) AS taille
  FROM pg_stat_user_tables
 WHERE relname IN ('requisitions','lignes_requisition','encaissements','sorties_fonds',
                   'budget_postes','experts_comptables','users','services','document_sequences')
 ORDER BY n_live_tup DESC;

\echo '--- Etat des sequences documentaires avant tir ---'
SELECT doc_type, year, tenant_id, service_id, counter
  FROM document_sequences
 ORDER BY tenant_id, doc_type, year, service_id NULLS FIRST;
