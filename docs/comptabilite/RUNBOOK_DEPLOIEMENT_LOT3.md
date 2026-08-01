# Runbook — Déploiement module Comptabilité (Lot 3)

Suite du déploiement Lot 1 + Lot 2 (cf. `RUNBOOK_DEPLOIEMENT_LOT1_LOT2.md`).
Pré-requis : la révision `20260731_compta_caisse_defaut` est déjà appliquée en
production.

Ce lot ajoute les faits générateurs restants (transferts internes, paiements
en ligne, paie), la contre-passation automatique à l'annulation, et un script
de reprise d'historique.

**Une migration**, `20260731_compta_rubriques` : une seule nouvelle table
`compta_mapping_rubrique`. Aucune table existante n'est modifiée.

---

## 0. Sauvegarde (obligatoire)

```bash
cd /chemin/vers/onec_smart
mkdir -p backups
BACKUP_FILE="backups/onec_cpk_prod_$(date +%Y%m%d_%H%M%S).dump"
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -F c -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$BACKUP_FILE"
ls -lh "$BACKUP_FILE"
```

---

## 1. Code et images

```bash
git checkout master && git pull origin master
docker compose -f docker-compose.prod.yml build backend frontend
```

---

## 2. Migration

```bash
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose -f docker-compose.prod.yml run --rm backend alembic current
```

Doit se terminer sur `20260731_compta_rubriques`. Réversible :
`alembic downgrade 20260731_compta_caisse_defaut`.

---

## 3. Mapping des rubriques techniques (AVANT de servir du trafic)

Les nouveaux faits générateurs résolvent leurs comptes via
`compta_mapping_rubrique`. Sans ce mapping, une organisation ayant activé la
comptabilité verrait **échouer** la validation d'un run de paie et les
paiements en ligne (échec bloquant assumé du moteur).

Le script de mapping par défaut du Lot 2 provisionne désormais aussi les cinq
rubriques — il est idempotent, le rejouer est sans risque :

```bash
docker compose -f docker-compose.prod.yml run --rm backend \
  python -m scripts.backfill_compta_mapping_defaut --dry-run

docker compose -f docker-compose.prod.yml run --rm backend \
  python -m scripts.backfill_compta_mapping_defaut --log /tmp/backfill_rubriques.log
```

Attendu par organisation ayant la comptabilité activée : `5 rubrique(s)`
mappée(s) au premier passage, `0` ensuite.

---

## 4. Point de paramétrage à trancher avec le comptable — poste « salaires »

**À faire avant d'utiliser la paie**, sinon la charge de personnel sera
comptabilisée deux fois.

La validation d'un run de paie constate la charge (D 66 / C 42-43-44). Le
versement des salaires reste une sortie de fonds, qui génère sa propre
écriture depuis le poste budgétaire imputé.

→ Le poste budgétaire « salaires » doit être mappé sur le **compte de dette
envers le personnel (421)**, pas sur un compte de charge. Le règlement solde
alors la dette (D 421 / C trésorerie).

```sql
-- Vérifier le compte actuellement mappé sur les postes « salaires » :
SELECT bp.code, bp.libelle, cc.numero, cc.libelle
FROM compta_mapping_poste_budgetaire m
JOIN budget_postes bp ON bp.id = m.budget_poste_id
JOIN compta_comptes cc ON cc.id = m.compte_id
WHERE m.organisation_id = :org AND bp.libelle ILIKE '%salaire%';
```

Si le compte n'est pas 421, corriger le mapping avant le premier run de paie.

---

## 5. Redéploiement

```bash
docker compose -f docker-compose.prod.yml up -d backend frontend
docker compose -f docker-compose.prod.yml logs -f backend --tail=100
```

Vérifier : `Alembic revision after upgrade: 20260731_compta_rubriques` et
démarrage sans traceback à l'import.

---

## 6. Reprise d'historique (optionnel, par organisation)

Une organisation qui active la comptabilité aujourd'hui a un Grand Livre qui
démarre aujourd'hui. Ce script rejoue les encaissements, sorties de fonds et
transferts déjà en base pour reconstituer l'historique.

```bash
# Toujours commencer par un aperçu :
docker compose -f docker-compose.prod.yml run --rm backend \
  python -m scripts.backfill_compta_ecritures_historique \
  --organisation <ID> --depuis 2026-01-01 --dry-run

# Exécution réelle :
docker compose -f docker-compose.prod.yml run --rm backend \
  python -m scripts.backfill_compta_ecritures_historique \
  --organisation <ID> --depuis 2026-01-01 --log /tmp/reprise_compta.log
```

Choisir `--depuis` avec le comptable : reprendre au **début de l'exercice
comptable ouvert** est le choix habituel (une opération datée hors exercice
est de toute façon refusée par le moteur et rapportée en échec).

Le script est **idempotent** (rejouable) et **non bloquant** : les opérations
non reprises (mapping manquant, répartition multi-postes introuvable) sont
listées en fin d'exécution sans interrompre les autres. Relire ce rapport et
traiter les cas signalés manuellement.

Les écritures reprises sont au **BROUILLON** : elles n'entrent au Grand Livre
qu'après validation par un comptable.

---

## 7. Vérification post-déploiement

Le point le plus important reste inchangé : **une organisation qui n'active
pas la comptabilité ne doit voir AUCUN changement.**

1. Sur une organisation sans le module : créer un transfert interne, un
   encaissement, une sortie de fonds → comportement identique à avant.
2. Sur l'organisation pilote (module activé) :
   - transfert caisse → banque : une écriture OD apparaît, débit = crédit ;
   - annuler une sortie de fonds : son écriture passe à ANNULEE (ou une
     contre-passation apparaît si l'écriture avait été validée) ;
   - valider un run de paie : une écriture SAL par devise, débit 661 = crédit
     421 + 431 + 447.

---

## 8. Rollback

Code : revenir au commit précédent, rebuild, `up -d`.

Base :
```bash
docker compose -f docker-compose.prod.yml run --rm backend \
  alembic downgrade 20260731_compta_caisse_defaut
```

Le downgrade supprime `compta_mapping_rubrique`. Les écritures déjà générées
par le Lot 3 (paie, transferts) restent en base et demeurent valides — elles
référencent des comptes, pas des mappings. Seule la génération de nouvelles
écritures de paie / paiement en ligne redevient impossible.
