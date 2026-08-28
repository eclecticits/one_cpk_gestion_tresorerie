# Campagne de charge des 27–28/08/2026 — ce qui saturait le banc

Suite de `perf-validation-20260827.md`. Les trois prérequis qu'il posait sont
levés : le tenant de test est `ACTIVE`, les adresses sont valides, le
générateur ne meurt plus par manque de mémoire. Une matrice complète
(1, 2, 4 workers × 10, 25, 50, 100 VU, 10 min par palier) a donc été tirée.

**Elle est ininterprétable, et pour une raison qui n'a rien à voir avec
l'application : le scénario d'export du banc consomme à lui seul plus que la
capacité de la machine.** L'expérience qui l'établit est en section 2 ; elle
tient en un seul paramètre changé.

Tout ce qui suit est mesuré. Les commandes de reproduction sont données.

---

## 1. La matrice : rien ne tient, nulle part

`observe/matrice_tableau.py resultats/matrice_20260827_163416`

| workers | VU | requêtes | échecs | taux | p50 | p95 |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 10 | 258 | 166 | 64,3 % | 59,79 s | 2m07s |
| 1 | 25 | 369 | 341 | 92,4 % | 1m03s | 2m07s |
| 1 | 50 | 985 | 767 | 77,9 % | 41,41 s | 1m01s |
| 1 | 100 | 1 293 | 1 288 | 99,6 % | 1m00s | 1m00s |
| 2 | 10 | 391 | 154 | 39,4 % | 17,44 s | 1m59s |
| 2 | 25 | 467 | 337 | 72,2 % | 59,20 s | 1m39s |
| 2 | 50 | 907 | 760 | 83,8 % | 59,96 s | 1m00s |
| 2 | 100 | 1 671 | 1 461 | 87,4 % | 56,90 s | 1m00s |
| 4 | 10 | 222 | 179 | 80,6 % | 59,98 s | 1m56s |
| 4 | 25 | 369 | 335 | 90,8 % | 59,98 s | 1m59s |
| 4 | 50 | 842 | 747 | 88,7 % | 59,96 s | 166m48s |
| 4 | 100 | — | — | non mesuré | | |

Deux détails disent que ce tableau ne parle pas de l'application :

- **Les échecs sont des `status 0`** — aucune réponse HTTP reçue, le client
  abandonne. 4 784 des 6 535 échecs de la matrice. Ce n'est pas un code
  d'erreur applicatif, c'est une file d'attente.
- **Les 1 712 échecs `5xx` restants sont tous le même** : `sqlalchemy.exc.TimeoutError:
  QueuePool limit of size 5 overflow 5 reached, connection timed out`. Aucune
  autre exception dans les journaux des douze paliers. Là encore, une file
  d'attente — pas un défaut de traitement.
- **Les p50 se collent au délai d'expiration du client** (60 s), pas à un
  temps de traitement. À froid, sans concurrence, ces mêmes routes répondent
  entre 25 et 200 ms (`w4_chauffe.txt`).

Et le classement du nombre de workers n'est pas monotone (2 workers meilleur
que 4 à 10 VU, l'inverse à 50 VU) : signature d'une variable non contrôlée,
pas d'un effet de dimensionnement.

---

## 2. L'expérience décisive : un seul paramètre

Même machine, même configuration (4 workers, `pool_size=5`, `max_overflow=5`),
même palier (25 VU, 5 min + 1 min de montée), jetons frappés du jour. Seul
`EXPORT_RATE` change — le débit du scénario 8, « export Excel ».

```bash
WORKERS=4 STAGES=25 DUREE=5m EXPORT_RATE=4 RACINE_RESULTATS=.../avec_exports ./matrice_workers.sh
WORKERS=4 STAGES=25 DUREE=5m EXPORT_RATE=0 RACINE_RESULTATS=.../sans_exports ./matrice_workers.sh
```

| | avec exports (4/min) | sans exports | écart |
|---|---:|---:|---:|
| requêtes servies | 492 | **3 548** | **×7,2** |
| débit | 1,21 req/s | **8,78 req/s** | ×7,2 |
| taux d'échec | 18,1 % | **3,3 %** | |
| erreurs 5xx | 12 | **0** | |
| p50 | 5,13 s | **88 ms** | **×58** |
| p95 | 1m31s | **3,78 s** | ×24 |
| `QueuePool limit` (journaux) | 12 | **0** | |
| `WORKER TIMEOUT` | 6 | **0** | |
| `DB_POOL_AT_CAPACITY` | 106 | 12 | |
| CPU backend (moy.) | 335 % | 221 % | |

> **Sans le scénario d'export, l'application sert 25 utilisateurs simultanés
> avec une médiane de 88 ms et zéro erreur serveur.** Les mêmes 25 VU, avec
> 4 exports par minute, ne dépassent pas 1,2 requête par seconde.

Ventilation des 116 échecs restants (sans exports, 3 548 requêtes) :

| cause | n | nature |
|---|---:|---|
| 403 sur `encaissement_create` | 84 | jeu de test (voir §5) |
| 400 sur `sortie_create` | 25 | règle métier appliquée — comportement correct |
| `status 0` | 7 | **seuls échecs imputables à la charge : 0,2 %** |

---

## 3. Pourquoi 4 exports par minute suffisent

Le commentaire du scénario dit « un export est un pic CPU dans le worker, pas
une action répétée par tous les utilisateurs ». C'était vrai sur une base vide.
À volume réel, ce n'est plus un pic, c'est un régime permanent.

Le parcours demande `periode(365)` : l'export porte sur l'exercice entier, donc
sur les 120 000 encaissements et les 60 000 réquisitions du tenant. Coûts
serveur mesurés dans `perf-exports-20260827.md`, après correctifs : 75 s pour
60 000 réquisitions, 1,25 à 1,46 ms par ligne.

Comptabilité de capacité sur le palier de 5 minutes :

| | |
|---|---:|
| capacité totale des workers | 4 × 300 s = **1 200 worker·s** |
| exports lancés | 10 |
| temps occupé par export (plafonné par le client à 120 s) | ≥ 120 s |
| demande des seuls exports | **≥ 1 200 worker·s** |

**Les dix exports demandent à eux seuls la totalite de la machine.** Les 482
autres requetes se partagent ce qui reste, c'est-a-dire rien. Et le compte est
un plancher : trois de ces exports ont ete traces cote serveur a 48 s, 69 s et
168 s.

Deux aggravations mesurées :

1. **L'abandon du client ne libère pas le worker.** Un `/exports/budget` a été
   tracé à `duration_ms=168496` alors que k6 avait renoncé à 120 s : la
   génération openpyxl tourne dans un thread, elle va jusqu'au bout. Le travail
   payé n'est même pas livré.
2. **Le pool suit.** `db_conn_total_ms=71592` sur cette même requête : la
   connexion est retenue toute la durée. Le relâchement posé le 27/08 ne couvre
   que `encaissements` et `requisitions`, pas `budget`.

PostgreSQL, lui, n'a jamais été la contrainte : 30 connexions en pic sur 40
autorisées, CPU moyen 52 %.

---

## 4. Un défaut applicatif trouvé au passage : `/exports/budget` écrit

Dans les journaux du tir, la requête la plus lente d'un `GET /exports/budget` :

```
UPDATE budget_postes SET montant_engage=$1, montant_paye=$2 WHERE budget_postes.id = $3
```

Tracé à `DB_SLOW_QUERY duration_ms=11462.78` — onze secondes et demie pour
mettre à jour **un seul poste**, dans une requête de lecture.

### Cause

`exports.py` surchargeait les montants affichés des postes de recette en
**affectant les attributs des entités de la session** :

```python
for poste in lignes:
    if (poste.type or "").upper() == "RECETTE":
        poste.montant_engage = recettes_actives.get(poste.id, Decimal("0"))
        poste.montant_paye = poste.montant_engage
```

Les postes deviennent *sales*. Le premier `db.execute` suivant — commentaires
budgétaires, exercice précédent — déclenche l'autoflush, et SQLAlchemy émet un
`UPDATE` par poste. La transaction est annulée en fin de requête, donc **rien
n'est persisté** : ce qui reste, ce sont les **verrous de ligne**, tenus
jusqu'à la fin de l'export, contre les écritures réelles du tenant.

### Mesure

La preuve ne se lit pas dans les journaux applicatifs (seule la requête la plus
lente y figure) mais dans `pg_stat_user_tables.n_tup_upd`, qui compte les
lignes modifiées même par une transaction annulée :

| `GET /exports/budget?annee=2026` | avant | après |
|---|---:|---:|
| lignes `budget_postes` écrites | **76** | **0** |
| code HTTP | 200 | 200 |
| durée (à chaud, sans concurrence) | 1 058 ms | 1 408 ms |
| classeur produit | — | **identique** |

76 = le nombre exact de postes de recette du tenant. Deux passages, même
résultat.

### Correctif

Un dictionnaire local (`recettes_affichees`) porte la surcharge d'affichage ;
`node_totals` le consulte au lieu de lire l'attribut. Aucune entité n'est
modifiée, donc aucun flush, donc aucun verrou.

Suite de tests : `tests/test_budget_engagements.py` et
`tests/test_tenant_loader_options_cache.py` (11 passés),
`tests/test_multi_tenant_isolation.py` (4 passés). Rendu vérifié cellule par
cellule (`observe/comparer_classeurs.py`) :

```
Cellules comparees : 4810
  ecarts de valeur : 0
  ecarts de style  : 0
IDENTIQUE — valeurs, styles et largeurs de colonnes.
```

### Le jumeau latent

`GET /budget/lines/tree` (`budget.py:2114-2126`) applique exactement le même
motif. Il ne déclenche rien aujourd'hui : aucun `db.execute` ne suit
l'affectation, donc aucun autoflush, et la session est annulée à la fermeture.
**C'est une propriété de l'ordre des lignes, pas une garantie** — une requête
ajoutée après ce bloc suffirait à reproduire le défaut. Non modifié, signalé.

---

## 5. Deux défauts de banc corrigés

### 5a. Jetons périmés, échec silencieux

Le 27/08 à 23 h 09, un palier a été lancé sur des jetons frappés à 15 h 00 avec
480 minutes de validité. Toutes les requêtes ont répondu `401 Invalid token`.
La campagne tourne, produit un summary, et ne mesure rien.

`run_campaign.sh` refuse désormais de démarrer sur un contexte périmé, et
avertit s'il expire dans moins d'une heure. Le contrôle lit
`jetons_valides_minutes`, écrit par `mint_tokens.py`, et l'âge du fichier.

### 5b. Le parcours d'écriture mesurait le contrôle de permission

`parcoursEncaissement` tirait son compte dans les 400 utilisateurs semés, tous
rôles confondus : 84 des 102 `POST /encaissements` du tir sans exports sont
revenus en **403**. Les deux autres parcours d'écriture utilisaient déjà un
compte de plein droit ; celui-ci le fait maintenant aussi. Un caissier réel
n'ouvre pas un écran qu'il n'a pas le droit d'utiliser.

### 5c. `EXPORT_RATE` traversait mal le harnais

`run_campaign.sh` ne transmettait pas la variable à k6, et k6 refuse un
`constant-arrival-rate` à 0. `EXPORT_RATE=0` retire maintenant le scénario et
ses seuils. C'est le paramètre de la section 2.

---

## 6. Ce que la campagne ne dit toujours pas

- **Le gain du cache du listener multi-tenant n'est toujours pas chiffré.** Il
  faut une référence stable ; la section 2 fournit enfin un palier exploitable
  (25 VU sans exports) pour la produire.
- **Le dimensionnement workers/pool reste ouvert.** L'A/B pool 5+5 contre
  20+4 n'a pas été mené : la matrice qui devait le trancher était saturée par
  les exports. À refaire sur le palier propre.
- **Rien au-delà de 25 VU sans exports.** Les paliers 50 et 100 VU n'ont pas
  été rejoués dans cette configuration.

---

## 7. Ordre de traitement proposé

1. **Décider du sort des exports lourds.** Servis en ligne, ils tiennent un
   worker plusieurs dizaines de secondes et l'abandon du client ne les arrête
   pas. C'est une question d'architecture (file d'attente, génération
   asynchrone, fichier remis par lien), pas de réglage.
2. **Rendre le scénario d'export réaliste** — fenêtre d'un mois plutôt que d'un
   an, débit d'un export toutes les quelques minutes — pour que la campagne
   mesure l'application et non le banc.
3. **Relâcher la connexion sur `/exports/budget`**, comme sur les deux autres
   exports (vérification du chargement anticipé à faire, cf. le `MissingGreenlet`
   décrit dans `perf-exports-20260827.md`).
4. **Rejouer la matrice workers × pool** sur le palier propre, pour trancher le
   dimensionnement avec des chiffres qui veulent dire quelque chose.
5. **Chiffrer le listener** sur cette même référence.

Ce qu'il ne faut **pas** faire : conclure quoi que ce soit de la matrice du
27/08 (section 1), ni des 34,6 % d'échec du 26/08. Aucune des deux ne mesurait
l'application.
