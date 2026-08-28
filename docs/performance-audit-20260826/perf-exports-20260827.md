# Exports Excel — diagnostic, correctifs et mesures avant/après (27/08/2026)

Trois défauts distincts sur les exports Excel, trouvés en levant les artefacts
de la campagne de charge. Chacun est **mesuré avant et après**, et le rendu des
classeurs est vérifié cellule par cellule.

Aucune fonctionnalité, aucun format, aucune règle métier n'a été modifié. Les
fichiers produits sont identiques à ceux d'avant les correctifs.

---

## 1. `/exports/requisitions` — échec fonctionnel, pas un problème de vitesse

### Symptôme

```
sqlalchemy.exc.InterfaceError: (asyncpg.exceptions._base.InterfaceError):
the number of query arguments cannot exceed 32767
```

**500 après 41,8 s, avec un seul utilisateur, sans aucune concurrence.**

### Cause

`app/api/v1/endpoints/exports.py` construisait une clause `IN` à partir d'un jeu
de résultats non borné :

```python
req_ids = [req.id for req, _ in rows]        # 60 000 identifiants
select(...).where(SortieFonds.requisition_id.in_(req_ids))
```

PostgreSQL n'accepte pas plus de **32 767 paramètres de bind** par requête —
limite du protocole, pas un réglage. Au-delà de ce seuil, **l'export est
impossible**, quelle que soit la charge.

Le défaut n'était pas isolé. Trois sites présentaient le même schéma :

| ligne | requête | source des identifiants |
|---|---|---|
| 1542 | `LigneRequisition.requisition_id.in_(req_ids)` | export des sorties de fonds |
| 1846 | `SortieFonds.requisition_id.in_(req_ids)` | export des réquisitions |
| 1865 | `User.id.in_(validation_user_ids)` | utilisateurs de validation |

### Correctif

Découpage en lots de 10 000 (`_par_lots`), qui laisse de la marge pour les
autres paramètres de la requête. Le regroupement se fait par `requisition_id` :
découper ne change aucun total, chaque clé n'appartenant qu'à un seul lot.

### Mesures

| | avant | après |
|---|---|---|
| statut HTTP | **500** | **200** |
| durée | 41,8 s (échec) | 159,5 s (succès) |
| fichier produit | aucun | 3 855 357 o |

Le correctif ajoute des requêtes (6 → 13 sur cet export) : c'est le prix du
découpage, très inférieur à l'échec qu'il remplace.

---

## 2. Le coût CPU — openpyxl re-hache les styles à chaque cellule

### Ce que le profil a montré

Profilage du chemin réel (`observe/profil_export.py`, qui neutralise
`anyio.to_thread.run_sync` pour profiler en ligne — le travail lourd s'exécute
dans un thread que `cProfile` ne suivrait pas).

`/exports/encaissements`, 4 800 lignes, **25,7 s** au total :

| fonction | temps |
|---|---:|
| `_build_list_sheet` | **18,0 s** |
| └ `openpyxl styleable.__set__` — 276 358 appels | **14,9 s** |
| └ `Serialisable.__hash__` — **2,5 M appels** | 13,4 s cumulé |
| `save_workbook` (sérialisation XML) | 4,5 s |

**Le coupable n'était pas le code applicatif.** La boucle d'écriture réutilisait
déjà des objets de style partagés — l'optimisation évidente était donc déjà
faite, et sans effet : openpyxl re-sérialise et re-hache l'objet de style
**complet** à chaque affectation (`cell.border = ...`), même quand c'est
exactement le même objet.

### Correctif

Une cellule stylée ne porte en interne qu'un `StyleArray` : des index vers les
tables de styles du classeur. Deux cellules d'apparence identique partagent
exactement le même tuple d'index.

Le coût openpyxl est donc payé **une fois par combinaison de style distincte**,
puis le `StyleArray` obtenu est recopié. Les combinaisons sont peu nombreuses
(monétaire / ordinal / normal × zébrage / mise en évidence / aucun).

### Vérification du rendu

`observe/comparer_classeurs.py` compare, pour chaque cellule : valeur, format de
nombre, police, remplissage, bordure, alignement — et les largeurs de colonnes.

```
Cellules comparees : 110635
  ecarts de valeur : 0
  ecarts de style  : 0

IDENTIQUE — valeurs, styles et largeurs de colonnes.
```

Taille du fichier : 606 175 o → 606 174 o.

---

## 3. La connexion à la base retenue pendant toute la génération

### Symptôme

`/exports/encaissements`, relevé applicatif :

```
duration_ms=33616  db_queries=6  db_total_ms=730  db_conn_total_ms=33204
```

**La connexion était retenue 33,2 s pour 0,73 s de SQL réel** — 45 fois plus
longtemps que le travail en base. Avec `pool_size=5` par worker, quelques
exports simultanés suffisent à vider le pool, et les requêtes qui échouent
alors n'ont aucun rapport avec l'export :

```
QueuePool limit of size 5 overflow 5 reached, connection timed out
```

### Correctif

`_relacher_connexion(db)` avant le travail CPU, appliqué à
`export_encaissements` et `export_requisitions`.

Il n'est sûr que parce que deux conditions sont réunies, vérifiées et non
supposées :

1. `expire_on_commit=False` (`app/db/session.py:99`) — les attributs déjà
   chargés restent lisibles après la fin de la transaction ;
2. tout ce que lit la closure de construction est chargé en amont —
   `joinedload(Encaissement.compte_bancaire).joinedload(CompteBancaire.banque)`,
   et les entités `ExpertComptable` / `Encaisseur` ramenées par la requête
   elle-même.

### La nuance qui a coûté un 500

Le premier essai utilisait `rollback()`, logique pour un export en lecture
seule. Résultat :

```
sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called;
can't call await_only() here. Was IO attempted in an unexpected place?
```

…et sur une **colonne ordinaire** (`enc.montant_total`), pas une relation.

`expire_on_commit=False` ne concerne que `commit()`. **`rollback()` expire
systématiquement tous les objets** de la session pour la ramener à un état
propre : la première lecture d'attribut dans le thread déclenchait donc un
rechargement, hors contexte greenlet.

`commit()` rend la connexion sans expirer. L'export est en lecture seule, il
n'y a rien à écrire. La panne a été **visible et immédiate**, pas silencieuse —
c'est le comportement attendu si un export venait à lire un attribut non
préchargé après ce point.

---

## Mesures finales

### `/exports/encaissements` — 4 800 lignes (filtre : août 2026)

| | avant | après | gain |
|---|---:|---:|---:|
| durée serveur | 33 616 ms | **7 005 ms** | **×4,8** |
| durée client | 49,8 s | **9,3 s** | **×5,4** |
| **connexion DB retenue** | **33 204 ms** | **3 582 ms** | **×9,3** |
| requêtes SQL | 6 | 6 | inchangé |
| temps SQL | 730 ms | 1 716 ms | — |
| rendu | — | **identique** | 110 635 cellules, 0 écart |

### `/exports/requisitions` — 60 000 lignes (aucun filtre)

| | avant | après correctif `IN` | après les deux correctifs |
|---|---:|---:|---:|
| statut HTTP | **500** | 200 | **200** |
| durée client | 41,8 s (échec) | 159,5 s | **99,1 s** |
| durée serveur | — | — | 75 314 ms |
| connexion DB retenue | — | ~totalité | **22 441 ms** sur 75 314 |
| requêtes SQL | — | — | 13 |
| temps SQL | — | — | 12 086 ms |
| fichier | **aucun** | 3 855 357 o | **3 855 357 o** |

Gain global sur cet export : d'un **échec fonctionnel** à un succès en 99 s,
soit **×1,6 sur le temps** depuis la première version qui aboutissait, et une
connexion retenue ramenée de la quasi-totalité de la requête à **30 %**.

### Coût par ligne, après correctifs

| export | lignes | durée serveur | par ligne |
|---|---:|---:|---:|
| encaissements | 4 800 | 7 005 ms | 1,46 ms |
| réquisitions | 60 000 | 75 314 ms | 1,25 ms |

Le coût par ligne est désormais **cohérent entre les deux exports** : il n'y a
plus de pathologie propre à l'un d'eux, seulement le volume.

---

## Ce qui reste, et pourquoi je m'arrête là

Profil de `/exports/requisitions` après correctifs : `_build_list_sheet` a
disparu du haut du classement. Le temps restant se partage entre la
sérialisation XML d'openpyxl (58 s) et le SQL (37 s) — inhérents à un export de
60 000 lignes sans filtre.

Aller plus loin supposerait le mode `write_only` d'openpyxl, qui change la
façon de construire les feuilles (plus d'accès aléatoire aux cellules, donc
refonte des lignes de total, du figeage d'en-tête et des largeurs
automatiques). Mauvais ratio gain/risque pour un rendu qui doit rester
identique.

**Non appliqué** : le relâchement de connexion sur les trois autres exports
(`budget`, `sorties-fonds`, `experts-comptables`). Ils ont le correctif de
style, qui est sans risque. Le relâchement, lui, exige de vérifier pour chacun
que rien n'est chargé paresseusement après ce point — la même vérification que
ci-dessus, faite export par export. L'appliquer à l'aveugle produirait le
`MissingGreenlet` décrit plus haut, en production.

## Outils ajoutés

| outil | rôle |
|---|---|
| `observe/profil_export.py` | profile la génération en neutralisant le passage en thread |
| `observe/comparer_classeurs.py` | compare deux classeurs cellule par cellule, valeurs et rendu |
| `observe/cout_unitaire.sh` | coût d'une requête sans concurrence, froid et chaud |
