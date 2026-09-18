-- Contrôle du passage à cinq types de client (migration 20260918_types_client).
--
-- STRICTEMENT EN LECTURE. La première instruction met la session en lecture
-- seule : toute écriture, même accidentelle, échoue au lieu de passer.
--
--   docker exec -i <conteneur_db> psql -U <user> -d <base> \
--       -f - < backend/scripts/audit_types_client.sql
--
-- Se lance AVANT et APRÈS la migration :
-- - avant : la section 2 montre ce que chaque ancien type va devenir. Toute
--   personne qui y apparaît en « personne_morale » est mal classée : la
--   signaler pour l'ajouter aux exceptions de la migration avant de déployer ;
-- - après : les sections 1 à 3 doivent donner le résultat « attendu » indiqué.

SET default_transaction_read_only = on;
\pset pager off

\echo '=== 0. Version de la base (après : 20260918_types_client) ==='
SELECT version_num FROM alembic_version;

\echo ''
\echo '=== 1. Types par table (après : uniquement expert_comptable, personne_physique, personne_morale, partenaire, autre) ==='
SELECT 'encaissements' AS table_, type_client, count(*) AS n
FROM encaissements GROUP BY type_client
UNION ALL
SELECT 'clients', coalesce(type_client, '(vide)'), count(*)
FROM clients GROUP BY type_client
ORDER BY 1, 3 DESC;

\echo ''
\echo '=== 2. Anciens types restants et leur destination (après : aucune ligne) ==='
SELECT
    type_client AS ancien_type,
    CASE
        WHEN type_client = 'organisation'
             AND client_nom = 'Régularisation d''écart de caisse' THEN 'autre'
        WHEN type_client = 'organisation'
             AND lower(trim(client_nom)) = 'elie iwondo' THEN 'personne_physique'
        WHEN type_client = 'client_externe' THEN 'personne_physique'
        ELSE 'personne_morale'
    END AS deviendra,
    client_nom,
    count(*) AS n
FROM encaissements
WHERE type_client IN ('client_externe', 'banque_institution', 'organisation')
GROUP BY 1, 2, 3
ORDER BY 2, 4 DESC;

\echo ''
\echo '=== 3. Contraintes (après : ck_encaissements_type_client et ck_clients_type_client, sur les 5 types) ==='
SELECT conrelid::regclass AS table_, conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conname IN ('ck_encaissements_type_client', 'ck_clients_type_client')
ORDER BY 1;

\echo ''
\echo '=== 4. Pour information : personnes physiques dont la fiche ne connaît pas le sexe ==='
\echo '    (il sera demandé à leur prochain encaissement ; rien à corriger en urgence)'
SELECT nom, count(*) OVER () AS total
FROM clients
WHERE type_client = 'personne_physique' AND sexe IS NULL
ORDER BY nom
LIMIT 50;
