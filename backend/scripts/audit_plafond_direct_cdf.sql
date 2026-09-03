-- Audit du résidu de reprise du plafond anti-fractionnement (ordres en CDF).
--
-- STRICTEMENT EN LECTURE. La première instruction met la session en lecture
-- seule : toute écriture, même accidentelle, échoue au lieu de passer.
--
--   docker exec -i <conteneur_db> psql -U <user> -d <base> \
--       -f - < backend/scripts/audit_plafond_direct_cdf.sql
--
-- Le plafond des 100 USD sur 24 h somme `montant_usd_snapshot`. Deux reprises
-- l'ont rempli pour l'historique : les ordres en USD (20260908, montant = USD)
-- puis les ordres en CDF payés (20260910, taux lu sur la sortie rattachée).
-- Un ordre à snapshot NULL compte donc pour zéro : il ne pèse pas sur le
-- plafond, et un fractionnement pourrait s'appuyer sur lui.
--
-- À lancer APRÈS les deux migrations. La section 1 doit être vide ou ne
-- contenir que des ordres de plus de 24 h — auquel cas ils ne comptent plus de
-- toute façon et le résidu est inoffensif.

SET default_transaction_read_only = on;
\pset pager off

\echo '=== 0. Cadrage : ordres directs par devise et état de reprise ==='
SELECT
    upper(devise) AS devise,
    statut,
    (montant_usd_snapshot IS NULL) AS snapshot_manquant,
    count(*) AS n,
    min(created_at) AS plus_ancien,
    max(created_at) AS plus_recent
FROM ordres_decaissement
WHERE requisition_id IS NULL
GROUP BY 1, 2, 3
ORDER BY snapshot_manquant DESC, n DESC;

\echo ''
\echo '=== 1. ACTIONNABLE — ordres directs encore invisibles au plafond ET'
\echo '    dans la fenêtre des 24 h. Ceux-là comptent pour zéro alors qu ils'
\echo '    devraient peser. Vide = plus aucun angle mort actif. ==='
SELECT
    o.id,
    o.numero_ordre,
    o.beneficiaire,
    o.montant,
    o.devise,
    o.statut,
    o.service_id,
    o.created_at,
    (o.sortie_fonds_id IS NULL) AS jamais_paye
FROM ordres_decaissement o
WHERE o.requisition_id IS NULL
  AND o.montant_usd_snapshot IS NULL
  AND o.statut IN ('AUTORISE', 'PAYE')
  AND o.created_at >= now() - interval '24 hours'
ORDER BY o.created_at;

\echo ''
\echo '=== 2. Contexte — le résidu attendu : ordres directs en CDF autorisés'
\echo '    mais jamais payés, donc sans sortie donc sans taux. Hors fenêtre des'
\echo '    24 h ils sont sans effet ; la section 1 dit s il en reste d actifs. ==='
SELECT
    o.id,
    o.numero_ordre,
    o.montant,
    o.devise,
    o.statut,
    o.created_at
FROM ordres_decaissement o
WHERE o.requisition_id IS NULL
  AND o.montant_usd_snapshot IS NULL
  AND upper(o.devise) = 'CDF'
  AND o.sortie_fonds_id IS NULL
ORDER BY o.created_at DESC;

\echo ''
\echo '=== 3. Contre-épreuve de la reprise CDF — les ordres payés doivent tous'
\echo '    porter un snapshot cohérent avec le taux de leur sortie. Une ligne'
\echo '    ici signale une reprise incomplète ou un taux aberrant. ==='
SELECT
    o.numero_ordre,
    o.montant AS montant_cdf,
    s.exchange_rate_snapshot AS taux,
    o.montant_usd_snapshot AS usd_repris,
    round(o.montant / nullif(s.exchange_rate_snapshot, 0), 2) AS usd_attendu
FROM ordres_decaissement o
JOIN sorties_fonds s ON s.id = o.sortie_fonds_id
WHERE o.requisition_id IS NULL
  AND upper(o.devise) = 'CDF'
  AND (
      o.montant_usd_snapshot IS NULL
      OR abs(o.montant_usd_snapshot - round(o.montant / nullif(s.exchange_rate_snapshot, 0), 2)) > 0.01
  )
ORDER BY o.created_at;
