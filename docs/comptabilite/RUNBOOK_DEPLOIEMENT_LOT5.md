# Runbook — Déploiement module Comptabilité (Lot 5 + écran de mappings + Lot 4)

Couvre tout ce qui a été livré après le Lot 3 : écran de paramétrage des
mappings, restitutions (Lot 4), états financiers et clôture (Lot 5).

Pré-requis : la révision `20260731_compta_rubriques` (Lot 3) est appliquée.

**Une seule migration**, `20260801_compta_etats` : deux nouvelles tables, un
élargissement de contrainte, et une **évolution du trigger d'immuabilité**.

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

Le répertoire `backups/` est désormais exclu du dépôt (`.gitignore`) : ces
fichiers contiennent des données réelles.

---

## 1. Code, images, migration

```bash
git checkout master && git pull origin master
docker compose -f docker-compose.prod.yml build backend frontend
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
docker compose -f docker-compose.prod.yml run --rm backend alembic current
```

Doit se terminer sur `20260801_compta_etats`.

**Ce que fait cette migration :**
- crée `compta_postes_etat` et `compta_poste_etat_comptes` ;
- élargit `ck_compta_journal_type` pour accepter le type `AN` (à-nouveaux) ;
- **remplace la fonction `compta_ecriture_immutable()`** pour autoriser la
  transition `VALIDEE → CLOTUREE`. C'est un durcissement, pas un
  assouplissement : une écriture clôturée est encore moins modifiable qu'une
  écriture validée. Sans cette évolution, la clôture d'exercice échouerait.

Réversible : `alembic downgrade 20260731_compta_rubriques` restaure la version
précédente du trigger et supprime les journaux de type `AN`.

---

## 2. Provisionnement des structures d'états (organisations déjà actives)

Les structures d'états (Bilan, Résultat, SIG, Flux) sont créées à l'activation
de la comptabilité. **Une organisation qui a activé le module avant le Lot 5
n'en a pas** : ses écrans d'états afficheront « Aucune structure d'état pour le
référentiel de cet exercice ».

Le provisionnement étant idempotent, il suffit de rejouer l'activation depuis
l'application (Super Admin → organisation → module Comptabilité → activer) :
rien n'est recréé ni écrasé, seules les structures manquantes sont ajoutées.

De même, les journaux `CLO` et `AN` n'existent que depuis le Lot 5 : le rejeu
de l'activation les crée. **Sans eux, la clôture échouera** avec un message
explicite.

---

## 3. Vérification du paramétrage des états

Avant de produire un état officiel, contrôler la **couverture** : un compte
mouvementé qui n'entre dans aucun poste disparaîtrait silencieusement.

Dans l'application : Comptabilité → **États financiers** → le bandeau en tête
indique si le bilan est équilibré et liste les comptes non couverts.

Les structures livrées rattachent les comptes **par préfixe de numéro**. Deux
points d'attention si votre plan a été enrichi :
- un compte hors nomenclature (numéro qui ne commence par aucun préfixe
  paramétré) sera signalé — à rattacher ;
- les comptes « parents » structurels (21, 24, 62…) ne sont volontairement pas
  rattachés : ils ne doivent pas recevoir d'écriture directe. S'ils en portent,
  ils apparaîtront dans les comptes non couverts.

---

## 4. Clôture d'un exercice — procédure

Trois étapes, **dans cet ordre**, depuis l'onglet États financiers (permission
`compta.cloture`). Chacune est rejouable sans risque.

1. **Déterminer le résultat** — solde les comptes de charges et de produits par
   120 (bénéfice) ou 129 (perte), au journal CLO. Le bilan ne peut pas être
   équilibré avant.
2. **Clôturer** — fige l'exercice. **Refusé** s'il reste des écritures au
   brouillon : elles seraient définitivement absentes des états. Validez-les ou
   annulez-les d'abord.
3. **Reporter les à-nouveaux** — reprend les soldes de bilan sur l'exercice
   suivant, au journal AN. Nécessite que l'exercice de destination existe et
   soit ouvert. **Refusé** tant que l'exercice source n'est pas clôturé.

Vérification après coup : sur l'exercice suivant, le bandeau de contrôle doit
annoncer un bilan équilibré avant toute saisie.

---

## 5. Limite opérationnelle à connaître

**Les états ne retiennent que les écritures VALIDÉES.** Or le moteur de
génération automatique produit des écritures au **BROUILLON**, et il n'existe
pas encore de validation en lot : elles se valident une par une.

Conséquence concrète : une organisation qui vient de mettre le module en
service verra des états **vides**, et une reprise d'historique de plusieurs
centaines d'opérations produira autant de brouillons à traiter.

La case « inclure les brouillons » permet de visualiser en **simulation** — les
exports portent alors la mention SIMULATION — mais ce n'est pas un état
officiel, et la clôture reste bloquée tant que des brouillons subsistent.

Un écran de validation en lot est le complément naturel de ce lot.

---

## 6. Vérification post-déploiement

Inchangé et prioritaire : **une organisation qui n'active pas la comptabilité
ne doit voir AUCUN changement.** Créer un encaissement, une sortie de fonds et
un transfert sur une telle organisation → comportement identique à avant.

Sur l'organisation pilote :
1. onglet États financiers → les cinq états s'affichent sans erreur ;
2. exports PDF et Excel d'un état → fichiers générés, en-tête de
   l'organisation présent ;
3. déterminer le résultat → le bandeau passe à « Bilan équilibré » ;
4. clôturer puis reporter les à-nouveaux sur l'exercice suivant → le nouvel
   exercice s'ouvre sur un bilan équilibré.

---

## 7. Rollback

Code : revenir au commit précédent, rebuild, `up -d`.

```bash
docker compose -f docker-compose.prod.yml run --rm backend \
  alembic downgrade 20260731_compta_rubriques
```

Le downgrade supprime les structures d'états et les journaux `AN`, et restaure
le trigger dans sa version Lot 1. **Attention** : les écritures déjà passées à
CLOTUREE le restent — elles sont simplement figées, ce qui reste cohérent. En
revanche, un exercice clôturé ne pourra plus être rouvert par le trigger
restauré ; restaurer le dump de l'étape 0 si c'est nécessaire.
