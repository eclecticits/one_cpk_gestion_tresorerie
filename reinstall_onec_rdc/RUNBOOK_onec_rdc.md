# Runbook — Recréer une base propre `onec_rdc` (ONEC RDC)

Objectif : repartir sur une base **propre**, en **conservant les tenants, tous les comptes admin/super‑admin, les rôles et privilèges, les services et les paramètres**, en **vidant les données de test** (réquisitions, encaissements, sorties, caisse, budgets, RH, compta, secrétariat, journaux…), puis **peupler** le Conseil National et le Conseil de Kinshasa (bureaux, commissions, présidents) à partir des données du site onecrdc.com.

> **Nom de base.** PostgreSQL n'accepte pas d'espace ni de majuscules simplement dans une URL de connexion. On utilise donc l'identifiant **`onec_rdc`** (le nom « ONEC RDC » reste le libellé fonctionnel). Tout le runbook utilise `onec_rdc`.

Architecture (rappel) : FastAPI + SQLAlchemy async + Alembic + PostgreSQL 16 (Docker). **Multi‑tenant par ligne** : un seul schéma, chaque ligne portée par `organisation_id`. Donc « les tenants » = lignes de `organisations`, « les données internes » = toutes les autres tables.

---

## ⚠️ Avant de commencer

- Faites la manip **hors heures d'utilisation** : l'API sera arrêtée quelques minutes.
- **Toutes les commandes se lancent à la racine du projet** `D:\Projet_dev_ck\onec_smart` (là où se trouve `docker-compose.yml`).
- On **ne supprime pas** `onec_cpk` : elle reste comme filet de sécurité (rollback) jusqu'à validation complète.
- Les fichiers de ce dossier `reinstall_onec_rdc/` :
  - `reset_transactionnel_onec_rdc.sql` — purge des données transactionnelles.
  - `seed_onec_organes.py` — peuplement (bureaux, commissions, présidents).
  - `data_onec_organes.json` — données collectées sur le site.
  - `modele_membres_commissions.xlsx` — pour saisir les membres de commission (non publiés sur le site).

---

## PARTIE A — Base propre `onec_rdc`

### Étape 1 — Sauvegarde de sécurité (obligatoire)
```bash
docker compose exec -T db pg_dump -U christian -Fc onec_cpk > backups/onec_cpk_avant_reset_$(date +%Y%m%d_%H%M%S).dump
```
Vérifiez que le fichier `.dump` est bien créé et non vide dans `backups/`.

### Étape 2 — Arrêter l'API (libère les connexions à la base)
```bash
docker compose stop backend
```
Fermez aussi toute session psql/DBeaver ouverte sur `onec_cpk` (le clonage exige 0 connexion active sur la base source).

### Étape 3 — Créer `onec_rdc` par CLONE de `onec_cpk`
Le clone copie **schéma + données + version Alembic + tous les comptes** à l'identique.
```bash
docker compose exec db psql -U christian -d postgres -c "CREATE DATABASE onec_rdc WITH TEMPLATE onec_cpk OWNER christian;"
```
> Si Postgres refuse (« source database is being accessed »), c'est qu'une connexion reste ouverte sur `onec_cpk`. Fermez‑la, ou forcez :
> ```bash
> docker compose exec db psql -U christian -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='onec_cpk' AND pid<>pg_backend_pid();"
> ```
> **Solution de repli** (si le clone par TEMPLATE échoue) :
> ```bash
> docker compose exec db psql -U christian -d postgres -c "CREATE DATABASE onec_rdc OWNER christian;"
> docker compose exec -T db pg_dump -U christian -Fc onec_cpk | docker compose exec -T db pg_restore -U christian -d onec_rdc --no-owner
> ```

### Étape 4 — Vider les données transactionnelles sur `onec_rdc`
Le script contient un **garde‑fou** : il refuse de s'exécuter si vous n'êtes pas sur `onec_rdc`.
```bash
docker compose exec -T db psql -U christian -d onec_rdc -v ON_ERROR_STOP=1 -f - < reinstall_onec_rdc/reset_transactionnel_onec_rdc.sql
```
Après ça : `organisations`, `users`, `roles`, `permissions`, `services`, paramètres = **conservés** ; toutes les tables d'exploitation = **vides** ; numérotation des reçus remise à zéro.

### Étape 5 — Basculer l'application sur `onec_rdc`
Éditez le fichier `.env` à la racine :
```dotenv
POSTGRES_DB=onec_rdc
DATABASE_URL=postgresql+asyncpg://christian:kncd@db:5432/onec_rdc
```
(le reste inchangé).

### Étape 6 — Redémarrer et vérifier les migrations
```bash
docker compose up -d
docker compose exec backend alembic current    # doit afficher la révision = head
docker compose logs -f backend                  # vérifier le démarrage sans erreur
```
La base étant un clone déjà à jour, Alembic ne fait rien de plus (déjà à `head`).

### Étape 6 bis (optionnel) — Vider proprement les utilisateurs de test non‑admin
Pour repartir avec **uniquement** les comptes `admin` / `super_admin` et supprimer tous les autres comptes de test. Le script `purge_users_non_admin.sql` conserve les admins, **détecte automatiquement toutes les clés étrangères vers `users`** (colonnes nullable → NULL, NOT NULL → lignes supprimées) et nettoie sans jamais violer une contrainte.

1. **Aperçu** (ne supprime rien : liste les comptes conservés et ceux à supprimer) :
```bash
docker compose exec -T db psql -U christian -d onec_rdc -v ON_ERROR_STOP=1 -f - < reinstall_onec_rdc/purge_users_non_admin.sql
```
2. **Suppression réelle** (ajouter `-v purge=true`) :
```bash
docker compose exec -T db psql -U christian -d onec_rdc -v ON_ERROR_STOP=1 -v purge=true -f - < reinstall_onec_rdc/purge_users_non_admin.sql
```
> - À lancer **après l'étape 4** (les tables transactionnelles doivent être vides).
> - Pour conserver aussi certains comptes non‑admin : ajoutez leurs e‑mails dans le tableau `_keep_emails` en tête du fichier.
> - Ce script agit sur **tous les tenants**. Il ne touche pas aux services ; pour aussi retirer les services/commissions de test, utilisez ensuite le peuplement avec `--purge` (étape 9).

> **Deux façons de nettoyer, au choix :**
> - **Par tenant (recommandé)** : `seed_onec_organes.py --purge --commit` supprime services **et** utilisateurs non‑admin des 2 conseils ciblés, puis recrée la structure officielle — en une commande.
> - **Global (users seulement)** : `purge_users_non_admin.sql` ci‑dessus, puis peuplement (étape 9).

---

## PARTIE B — Peupler les organes (Conseil National + Kinshasa)

Le script réutilise **les rôles existants** de la base ; il ne redéfinit aucun privilège et **ne touche pas** aux comptes `admin` / `super_admin`.

### Étape 7 — Copier le script et les données dans le conteneur
```bash
docker compose cp reinstall_onec_rdc/seed_onec_organes.py backend:/app/seed_onec_organes.py
docker compose cp reinstall_onec_rdc/data_onec_organes.json backend:/app/data_onec_organes.json
```

### Étape 8 — (recommandé) Voir les tenants actuels + simulation (dry‑run)
Le dry‑run **n'écrit rien** : il liste les organisations existantes et affiche tout ce qui serait créé.
```bash
docker compose exec backend python /app/seed_onec_organes.py --dry-run
```
Slugs par défaut (confirmés depuis le code : sous‑domaines `cn.localhost` / `cpk.localhost`) :
- **`cn`** = Conseil National, **`cpk`** = Conseil Provincial de Kinshasa.

Contrôlez dans la sortie la ligne « Organisations actuelles » → les slugs réels de vos tenants. S'ils diffèrent, fixez‑les au lancement, ex. :
  ```bash
  docker compose exec -e ONEC_SLUG_CONSEIL_NATIONAL=cn \
                       -e ONEC_SLUG_CONSEIL_KINSHASA=cpk \
                       backend python /app/seed_onec_organes.py --dry-run
  ```

### Étape 9 — Écrire réellement en base
- **Sans purge** (ajoute/complète sans rien supprimer) :
  ```bash
  docker compose exec backend python /app/seed_onec_organes.py --commit
  ```
- **Avec purge** (recommandé pour une base 100 % propre) — supprime d'abord les services/commissions et **utilisateurs non‑admin de test** du tenant ciblé, puis recrée la structure officielle. Les comptes `admin`/`super_admin` sont préservés :
  ```bash
  docker compose exec backend python /app/seed_onec_organes.py --purge --commit
  ```
  > Faites **toujours** un `--dry-run` d'abord (idéalement avec `--purge --dry-run`) pour voir le nombre d'éléments supprimés avant d'écrire.

### Étape 10 — (optionnel) Membres des commissions
Le site ne publie **pas** la liste nominative des membres de commission (seulement les présidents). Deux options :
1. Les saisir dans l'application, commission par commission.
2. Compléter `modele_membres_commissions.xlsx`, me le renvoyer pour l'injecter dans `data_onec_organes.json`, puis relancer l'étape 9 (idempotente).

---

## PARTIE C — Vérifications

```bash
docker compose exec db psql -U christian -d onec_rdc -c "
SELECT o.nom,
       count(DISTINCT u.id)  AS users,
       count(DISTINCT s.id)  AS services,
       count(DISTINCT cm.id) AS membres_commission
FROM organisations o
LEFT JOIN users u    ON u.organisation_id = o.id
LEFT JOIN services s ON s.organisation_id = o.id
LEFT JOIN commission_members cm ON cm.service_id = s.id
GROUP BY o.nom ORDER BY o.nom;"
```
Contrôles utiles :
```bash
# Présidents nommés (responsable de chaque commission)
docker compose exec db psql -U christian -d onec_rdc -c "
SELECT o.nom AS tenant, s.libelle AS commission, u.email AS president
FROM services s JOIN organisations o ON o.id=s.organisation_id
LEFT JOIN users u ON u.id=s.responsable_id
ORDER BY o.nom, s.libelle;"

# Tables transactionnelles bien vides (doit renvoyer 0)
docker compose exec db psql -U christian -d onec_rdc -c "
SELECT (SELECT count(*) FROM requisitions) req,
       (SELECT count(*) FROM encaissements) enc,
       (SELECT count(*) FROM sorties_fonds) sorties;"

# Comptes admin/super_admin préservés
docker compose exec db psql -U christian -d onec_rdc -c "
SELECT email, role, organisation_id FROM users WHERE lower(role) IN ('admin','super_admin') ORDER BY role;"
```

---

## Annexe 1 — Correspondance fonction → rôle (rôles EXISTANTS réutilisés)

| Fonction (organe)                 | Rôle appli (`User.role`) | Privilèges (déjà en base) |
|-----------------------------------|--------------------------|---------------------------|
| Président (bureau)                | `president`              | Validation finale, rapports |
| Vice‑président                    | `president`              | Validation finale, rapports |
| Rapporteur / Rapporteur adjoint   | `rapporteur`             | Avis technique, rapports |
| Trésorier(ère) / adjoint          | `tresorier`              | Exécution paiements, rapports |
| Membre                            | `demandeur`              | Initier des réquisitions |
| Président de commission           | `president` + `PRESIDENT` de sa commission | Validation finale |
| **admin / super_admin existants** | **inchangés**            | **conservés à l'identique** |

> Pour ajuster : modifiez le dictionnaire `FUNCTION_ROLE` en tête de `seed_onec_organes.py`.
> Mot de passe initial des comptes créés : valeur de `DEFAULT_USER_PASSWORD` du `.env` (`Onec2025`), avec **changement obligatoire à la 1ʳᵉ connexion**. Pensez à modifier `DEFAULT_USER_PASSWORD` si besoin avant le seed.
> E‑mails : ceux du site quand disponibles (Kinshasa) ; sinon générés `prenom.nom@onec-rdc.org` (variable `ONEC_EMAIL_DOMAIN`).

## Annexe 2 — Ce qui est conservé vs vidé (partie A)

**Conservé** : `organisations`, `organisation_settings`, `system_settings`, `platform_settings`, `print_settings`, `users`, `user_roles`, `user_services`, `services`, `roles`, `permissions`, `role_permissions`, `plans`.

**Vidé** : réquisitions & annexes, encaissements, sorties, ordres de décaissement, caisse (ouvertures/clôtures/centrale), transferts, transport, budgets, documents générés + séquences, paiements & factures SaaS, experts & clients, RH (agents/contrats/paie/congés…), écritures comptables, secrétariat (tâches/réunions/docs/messages…), journaux d'audit, historiques, refresh tokens, demandes d'inscription.

**Config potentiellement « de test » conservée par défaut** (banques, comptes bancaires, rubriques, plan comptable compta_*, dénominations, classifications…) : voir le bloc commenté en bas de `reset_transactionnel_onec_rdc.sql` pour aussi les vider si nécessaire.

## Annexe 3 — Rollback
En cas de problème, revenez sur l'ancienne base sans rien perdre :
```dotenv
# .env
POSTGRES_DB=onec_cpk
DATABASE_URL=postgresql+asyncpg://christian:kncd@db:5432/onec_cpk
```
```bash
docker compose up -d
```
`onec_cpk` est intacte. Vous pourrez supprimer `onec_rdc` (`DROP DATABASE onec_rdc;`) et recommencer.
