# Runbook — Déploiement module Comptabilité (Lot 1 + Lot 2)

Premier déploiement en production : le module n'existe pas encore côté serveur
(ni tables, ni code). Ce runbook suppose un accès SSH au serveur de production
et `docker compose -f docker-compose.prod.yml` comme méthode de déploiement
(cf. README).

Commit à déployer : `389255f` (branche `master`).

À exécuter dans l'ordre, sur le serveur de production. Ne pas sauter d'étape.

---

## 0. Pré-requis

```bash
git -C /chemin/vers/onec_smart log -1 --oneline   # vérifier l'état actuel
git -C /chemin/vers/onec_smart fetch origin
git -C /chemin/vers/onec_smart log origin/master -1 --oneline   # doit montrer 389255f
```

---

## 1. Sauvegarde de la base (obligatoire, avant toute migration)

```bash
cd /chemin/vers/onec_smart
mkdir -p backups
BACKUP_FILE="backups/onec_cpk_prod_$(date +%Y%m%d_%H%M%S).dump"

docker compose -f docker-compose.prod.yml exec -T db \
  pg_dump -F c -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$BACKUP_FILE"

ls -lh "$BACKUP_FILE"   # vérifier que le fichier n'est pas vide
```

Garder ce fichier accessible tant que le déploiement n'est pas validé (étape 6).
Restauration si besoin : `pg_restore -c -d "$POSTGRES_DB" "$BACKUP_FILE"`.

---

## 2. Récupérer le code

```bash
git checkout master
git pull origin master
git log -1 --oneline   # doit afficher 389255f
```

---

## 3. Reconstruire les images

```bash
docker compose -f docker-compose.prod.yml build backend frontend
```

Ne pas encore redémarrer les conteneurs — les migrations doivent d'abord
tourner à froid dans un conteneur jetable pour ne pas laisser l'API en L7
pendant l'upgrade de schéma (le service `backend` en place applique déjà les
migrations à son propre démarrage si `RUN_MIGRATIONS_ON_STARTUP=true`, mais on
vérifie explicitement ici pour garder le contrôle).

---

## 4. Migrations (4 nouvelles, toutes réversibles)

```bash
docker compose -f docker-compose.prod.yml run --rm backend alembic current
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose -f docker-compose.prod.yml run --rm backend alembic current
```

Doit se terminer sur la révision `20260731_compta_caisse_defaut`. Les 4
migrations créent des tables et triggers PL/pgSQL (immuabilité des écritures
validées) — aucune ne modifie de table existante utilisée par le reste de
l'application (isolation par nouvelles tables `compta_*` uniquement, sauf
l'ajout de permissions/rôles RBAC globaux `compta.*`).

Si une migration échoue : elle est transactionnelle (DDL Postgres), donc pas
d'état partiel. Corriger puis rejouer `alembic upgrade head`. En dernier
recours, restaurer le dump de l'étape 1.

---

## 5. Backfill du mapping comptable par défaut

**Important** : ce script doit tourner AVANT de servir du trafic avec le
nouveau code, sinon toute organisation ayant déjà activé la comptabilité (peu
probable pour un premier déploiement, mais le script le vérifie) verrait ses
sorties de fonds / encaissements bloqués tant qu'un poste ou compte bancaire
n'est pas mappé.

```bash
# Aperçu sans écriture :
docker compose -f docker-compose.prod.yml run --rm backend \
  python -m scripts.backfill_compta_mapping_defaut --dry-run

# Exécution réelle :
docker compose -f docker-compose.prod.yml run --rm backend \
  python -m scripts.backfill_compta_mapping_defaut --log /tmp/backfill_compta.log
```

Pour un premier déploiement, la sortie attendue est `0 organisation(s) avec
comptabilité activée` (aucune organisation n'a encore activé le module). Le
script est idempotent — le rejouer plus tard (après qu'une organisation active
le module) est sans risque.

---

## 6. Redéploiement

```bash
docker compose -f docker-compose.prod.yml up -d backend frontend
docker compose -f docker-compose.prod.yml logs -f backend --tail=100
```

Vérifier dans les logs :
- `[entrypoint] Alembic revision after upgrade: 20260731_compta_caisse_defaut`
- Démarrage de l'API sans traceback à l'import (confirme que
  `app.modules.comptabilite.*` s'importe correctement).

---

## 7. Vérification post-déploiement (non-régression)

Le point le plus important : **une organisation qui n'active pas la
comptabilité ne doit voir AUCUN changement.**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://api.onec-rdc.org/health
```

Puis, via l'application (avec un compte réel non lié au module compta) :
1. Créer une sortie de fonds normale (cas simple) → doit fonctionner
   exactement comme avant (aucune écriture comptable générée, aucun message
   d'erreur).
2. Créer un encaissement normal → idem.
3. Vérifier que le menu applicatif ne montre PAS de nouveau module
   "Comptabilité" pour les organisations existantes (il faut l'activer
   explicitement via Super Admin → Paramètres province → onglet
   Comptabilité).

Pour valider le nouveau module lui-même (optionnel, sur une organisation
pilote) :
1. Super Admin → activer le module Comptabilité pour une organisation test.
2. Ouvrir le module → écran d'activation → choisir SYSCOHADA ou SYSCEBNL →
   valider.
3. Lancer `generer_mappings_par_defaut` pour cette organisation (ou attendre
   qu'un admin configure les mappings manuellement).
4. Créer une sortie de fonds / un encaissement pour cette organisation → une
   écriture BROUILLON doit apparaître dans le module Comptabilité, montant
   débit = montant crédit.

---

## 8. Rollback (si problème détecté)

Code :
```bash
git checkout f551b74   # commit précédent
docker compose -f docker-compose.prod.yml build backend frontend
docker compose -f docker-compose.prod.yml up -d backend frontend
```

Base (downgrade complet, réversible) :
```bash
docker compose -f docker-compose.prod.yml run --rm backend \
  alembic downgrade 20260725_grant_authorize_disb
```

Ou restauration complète depuis le dump de l'étape 1 si nécessaire.
