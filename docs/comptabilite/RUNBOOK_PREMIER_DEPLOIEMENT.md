# Runbook — Premier déploiement du module Comptabilité (Lots 1 à 5)

Les trois runbooks précédents (`LOT1_LOT2`, `LOT3`, `LOT5`) décrivent des
déploiements **incrémentaux**, chacun supposant le précédent appliqué. Or le
module n'a **jamais été déployé** : la production ne porte aucune table
`compta_*`.

Ce document remplace les trois pour un premier déploiement. Les runbooks
d'origine restent la référence pour comprendre chaque lot et pour les
déploiements ultérieurs.

**Commit à déployer :** `61588be` (branche `master`).
**Révision Alembic cible :** `20260801_compta_etats`.

---

## Ce qui change en production

Six migrations comptables s'appliquent d'un coup. Elles créent uniquement des
tables `compta_*` et des permissions/rôles RBAC `compta.*` — **aucune table
métier existante n'est modifiée**, à deux exceptions près, toutes deux
internes au module :

- `ck_compta_journal_type` est élargi pour accepter le type `AN` ;
- la fonction `compta_ecriture_immutable()` est remplacée pour autoriser la
  transition `VALIDEE → CLOTUREE` (un durcissement).

**Le module est opt-in par organisation.** Une organisation qui ne l'active
pas ne doit voir **aucun changement** : c'est le point à vérifier en priorité
après déploiement.

---

## 0. Pré-requis (à vérifier avant de commencer)

```bash
# Sur votre poste : le commit est bien sur GitHub
git ls-remote origin master        # doit afficher 61588be

# Sur le serveur
cd /chemin/vers/onec_smart
git log -1 --oneline               # état actuel, à noter pour le rollback
docker compose -f docker-compose.prod.yml ps
```

Notez le commit actuel : c'est votre point de retour.

---

## 1. Sauvegarde de la base — obligatoire

```bash
mkdir -p backups
BACKUP_FILE="backups/onec_cpk_prod_$(date +%Y%m%d_%H%M%S).dump"
docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -F c -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$BACKUP_FILE"
ls -lh "$BACKUP_FILE"    # vérifier que le fichier n'est PAS vide
```

Conserver ce fichier jusqu'à validation complète (étape 6).
`backups/` est exclu du dépôt : ces fichiers contiennent des données réelles.

---

## 2. Récupérer le code et reconstruire

```bash
git checkout master
git pull origin master
git log -1 --oneline          # doit afficher 61588be

docker compose -f docker-compose.prod.yml build backend frontend
```

Ne pas encore redémarrer : les migrations tournent d'abord à froid.

---

## 3. Migrations

```bash
docker compose -f docker-compose.prod.yml run --rm backend alembic current
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose -f docker-compose.prod.yml run --rm backend alembic current
```

Doit se terminer sur **`20260801_compta_etats`**.

Les DDL PostgreSQL étant transactionnels, un échec ne laisse pas d'état
partiel : corriger puis rejouer `alembic upgrade head`. En dernier recours,
restaurer le dump de l'étape 1.

---

## 4. Backfill des mappings

Sans mapping, une organisation ayant activé la comptabilité verrait ses
saisies de trésorerie **bloquées** (échec bloquant assumé du moteur).

```bash
docker compose -f docker-compose.prod.yml run --rm backend \
  python -m scripts.backfill_compta_mapping_defaut --dry-run

docker compose -f docker-compose.prod.yml run --rm backend \
  python -m scripts.backfill_compta_mapping_defaut --log /tmp/backfill_compta.log
```

Sortie attendue pour un premier déploiement : **`0 organisation(s) avec
comptabilité activée`** — aucune organisation n'a encore activé le module. Le
script est idempotent : à rejouer après chaque activation.

---

## 5. Redémarrage

```bash
docker compose -f docker-compose.prod.yml up -d backend frontend
docker compose -f docker-compose.prod.yml logs -f backend --tail=100
```

Vérifier dans les logs :
- `Alembic revision after upgrade: 20260801_compta_etats`
- démarrage de l'API **sans traceback à l'import** (confirme que
  `app.modules.comptabilite.*` s'importe correctement).

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://api.onec-rdc.org/health
```

---

## 6. Vérification de NON-RÉGRESSION — la plus importante

Avec un compte réel d'une organisation **qui n'a pas activé** la comptabilité :

1. créer un encaissement → comportement identique à avant, aucune écriture ;
2. créer une sortie de fonds → idem ;
3. créer un transfert interne caisse ↔ banque → idem ;
4. valider un run de paie (si le module RH est utilisé) → idem ;
5. le menu ne doit **pas** afficher de module « Comptabilité ».

Si l'un de ces points échoue, revenir à l'étape 8 (rollback) : le module ne
vaut pas une régression sur la trésorerie.

---

## 7. Mise en service sur une organisation pilote

À faire **après** avoir validé l'étape 6, et sur une seule organisation.

1. **Activer** : Super Admin → Paramètres province → onglet Comptabilité.
2. **Ouvrir le module** → écran d'activation → choisir SYSCOHADA ou SYSCEBNL,
   dates d'exercice → valider. Crée le plan de comptes, les journaux
   (CA, BQ, OD, SAL, CLO, AN), l'exercice et les structures d'états.
3. **Compléter les mappings** : onglet Paramétrage → bouton « Compléter par
   défaut », puis **affiner poste par poste**. Le mapping par défaut envoie
   toutes les dépenses sur `605` et toutes les recettes sur `758` : utilisable
   pour démarrer, pas acceptable durablement.
4. ⚠️ **Poste « salaires » → compte 421** (dette envers le personnel), **pas**
   un compte de charge : la validation d'un run de paie constate déjà la
   charge en 66x, et un poste de charge la compterait **deux fois**.
5. **Reprise d'historique** (optionnel, par organisation) :
   ```bash
   docker compose -f docker-compose.prod.yml run --rm backend \
     python -m scripts.backfill_compta_ecritures_historique \
     --organisation <ID> --depuis <AAAA-MM-JJ> --dry-run
   ```
   Choisir `--depuis` avec le comptable — le début de l'exercice comptable
   ouvert est le choix habituel. Relire le rapport des opérations non reprises
   avant de relancer sans `--dry-run`.
6. **Valider les brouillons** : onglet Écritures → « Valider les brouillons ».
   La simulation s'affiche d'abord. Tant que les écritures restent au
   brouillon, le Grand Livre et les états financiers sont **vides** — c'est
   normal, pas une panne.
7. **Contrôler** : onglet États financiers → le bandeau doit annoncer un bilan
   équilibré (après détermination du résultat) et ne signaler aucun compte
   hors de tout poste.

---

## 8. Rollback

**Code :**
```bash
git checkout <commit noté à l'étape 0>
docker compose -f docker-compose.prod.yml build backend frontend
docker compose -f docker-compose.prod.yml up -d backend frontend
```

**Base** — supprime toutes les tables `compta_*` :
```bash
docker compose -f docker-compose.prod.yml run --rm backend \
  alembic downgrade 20260725_grant_authorize_disb
```

Ou restauration complète depuis le dump de l'étape 1 :
```bash
pg_restore -c -d "$POSTGRES_DB" backups/<fichier>.dump
```

Le rollback code seul suffit si le problème est applicatif : les tables
`compta_*` inutilisées n'ont aucun effet sur le reste de l'application.

---

## Points restés ouverts (hors de ce déploiement)

- **SEC-01 (critique)** : la clé SSH `onec.pem` et un dump SQL sont
  récupérables dans l'historique git. Révoquer la clé et purger l'historique.
- **FE-03** : `xlsx@0.18.5` vulnérable, à migrer vers la build SheetJS
  officielle.
- **Documents légaux** : champs à compléter (RCCM, ID.NAT, NIF) et pages à
  héberger aux URLs liées depuis le signup, sinon le consentement pointe dans
  le vide.
- **Consentement RGPD non horodaté** côté backend : la preuve manque.
