# Bascule des transferts internes — plan et filet

Deux moteurs déplacent aujourd'hui de l'argent entre la caisse et les banques :

- le **chemin historique**, dans `sorties_fonds`, sous deux `type_sortie`
  (`versement_banque` caisse → banque, `approvisionnement_caisse` banque →
  caisse) ;
- le **moteur dédié**, `app/services/transferts_internes_service.py`, qui écrit
  dans `transferts_internes` : idempotence, verrouillage canonique des deux
  comptes, contrôle de période close, écriture comptable, et une correction
  **additive** (contre-passation par transfert inverse daté du jour, jamais de
  réécriture de l'original).

Le moteur dédié est livré et testé. Ce dossier traite de la question suivante,
qui est d'une autre nature : **comment basculer l'application dessus sans casser
la lecture des anciennes données.**

## Le fait structurant

Les trois agrégateurs de trésorerie lisent **déjà les deux sources** et les
additionnent : `clotures.py` (`_appro_sum` + `_transf_sum`), `reports.py`
(`_sum_appro` + `_sum_transferts`), `treasury.py` (`_recalculate_treasury_balances`).
Une opération vit dans exactement une des deux tables, donc l'union ne double
compte pas.

La bascule n'est donc **pas une migration de données, c'est un changement de
chemin d'écriture**. D'où la règle absolue du chantier :

> **Aucune ligne n'est jamais copiée de `sorties_fonds` vers
> `transferts_internes`.** Les lecteurs unionnent déjà les deux ; toute reprise
> d'historique doublerait instantanément chaque total de clôture et de rapport.

C'est le seul geste vraiment irréversible. Tout le reste se corrige.

## Ce qui est aveugle au moteur dédié

Inventaire dressé avant la Phase 1, qui a bouché le seul trou réel.

| Lecteur | Voit l'historique | Voit le moteur dédié | Effet d'une bascule prématurée |
|---|---|---|---|
| `clotures.py`, `reports.py`, `treasury.py` | ✅ | ✅ | rien |
| `services/entrees_caisse.py` (lignes affichées) | ✅ | ❌ → ✅ *(Phase 1)* | **totaux ≠ lignes** |
| `exports.py` (classeurs Excel) | ✅ | ❌ → ✅ *(Phase 1, par `entrees_caisse`)* | transferts absents |
| `dashboard.py` | ✅ | ❌ | sans effet : les soldes sont lus sur les comptes |
| `retours_caisse.py` | ✅ | ❌ | sans effet : c'est un garde-fou |

Le seul trou réel était `entrees_caisse.py`, et il était net parce que le module
énonce lui-même son contrat en tête : « pour que tous ces écrans montrent
exactement les mêmes lignes que celles agrégées dans les totaux ». Basculer les
écritures avant de le rendre bilingue aurait fait afficher à une clôture une
entrée que sa propre liste ne justifie pas — sur un document signé et imprimé.

D'où le principe d'ordonnancement : **rendre les lectures bilingues pendant que
la table neuve est encore vide**, moment où le changement est inobservable en
production donc testable sans risque.

## Deux pièges connus

**Le cache de rapports.** `encaissements`, `retours_caisse` et `sorties_fonds`
appellent tous `invalidate_report_summary_cache`. Le service transferts, non.
Sans volume ça ne se voit pas ; sous volume réel les rapports restent périmés
après chaque transfert. *Traité en Phase 1* — après le commit, et pas sur un
rejeu idempotent, qui n'a rien écrit.

**L'asymétrie d'annulation.** Les lecteurs filtrent l'historique sur
`statut = 'VALIDE'` : annuler un versement le fait disparaître rétroactivement
des totaux d'une période **déjà clôturée**. Le moteur dédié, lui, ne réécrit
jamais le passé. Pendant toute la transition, le même écran affiche de
l'histoire immuable pour les nouvelles lignes et de l'histoire révisable pour
les anciennes. Ça n'a pas de solution propre tant que les deux chemins
coexistent — c'est l'argument le plus fort pour que la transition soit courte.

## Les phases

| Phase | Contenu | État |
|---|---|---|
| **0** | **Le filet** : réconciliation exécutable, photo de départ | **livrée le 29/08** |
| **1** | **Combler les aveugles** : `entrees_caisse` unionne les deux sources, invalidation du cache dans le service. Aucun changement d'écriture. | **livrée le 29/08** |
| **2** | **Équivalence** pour `versement_banque` : numérotation tranchée, colonnes d'identité documentaire, drapeau de bascule, écran / bon / annulation bilingues. | **livrée le 30/08** |
| **3** | **Bascule d'écriture** : `sorties-fonds` délègue au moteur dédié, un `type_sortie` et une organisation à la fois. Le frontend ne change pas. | **livrée le 30/08 — drapeau fermé** |
| 4 | Lecture unifiée : un service `mouvements_internes` qui union, les lecteurs y migrent un par un. | à faire |
| 5 | Gel des deux `type_sortie`. | à faire |

Chaque phase se valide en rejouant le filet et en comparant à la photo de
départ.

## Phase 0 — le filet

`backend/scripts/reconcile_tresorerie.py`, en lecture seule. Trois contrôles :

- **C1 — caisse centrale** : `solde stocké == solde initial + Σ entrées − Σ sorties`,
  entrées et sorties lues sur les deux sources. La formule reproduit
  `_recalculate_treasury_balances` : la réconciliation n'invente pas sa propre
  définition, elle vérifie celle que l'application se donne.
- **C2 — comptes bancaires** : même équation, par compte. Elle n'existait nulle
  part — aucun endpoint ne recalcule un solde bancaire. Elle est dérivée des
  endroits qui écrivent `CompteBancaire.solde_actuel`, et **toute nouvelle
  écriture de ce champ doit être ajoutée à `termes_compte_bancaire`.**
- **C3 — lignes affichées contre totaux** : chaque terme d'entrée face à la
  somme des lignes qu'un écran sait afficher pour lui. Écrit comme le voyant de
  la Phase 1 — il signalait alors un total sans chemin d'affichage ; depuis
  qu'elle est livrée, il compare l'union des lignes à l'union des totaux et
  redevient rouge si un filtre est ajouté d'un seul côté.

```bash
# rapport lisible (code de sortie 1 s'il reste un écart)
python -m scripts.reconcile_tresorerie
python -m scripts.reconcile_tresorerie --tenant 8
# photo comparable
python -m scripts.reconcile_tresorerie --json > photo.json
# sur une restauration de dump
python -m scripts.reconcile_tresorerie --database-url postgresql+asyncpg://...
```

Tests : `backend/tests/test_reconciliation_tresorerie.py`. Chacun part d'une
organisation dont les soldes sont justes, casse **une** chose, et vérifie que le
rapport la nomme — un contrôle qui ne tombe jamais en panne ne prouve rien.

## La photo de départ (29/08/2026, base locale)

Brut : `photo-depart-20260829.json`.

| Organisation | Caisse | Comptes bancaires | Verdict |
|---|---|---|---|
| 1 — Conseil Provincial de Kinshasa | 36 719,96 USD | 2 comptes (71 346,22 / 52 008,07) | **écart 0,00 partout** |
| 8 — Conseil National | 6 785,00 USD | 3 comptes (489 902,72 / 106 752,00 / 205 510,00) | **écart 0,00 partout** |
| 9, 10, 20 — Haut-Katanga, Sud-Kivu, Nord-Kivu | aucun mouvement | — | conforme |
| 18 — Load Test | 506 690,00 stocké / 6 690,00 attendu | 1 compte, écart 0,00 | **écart 500 000,00** |

**Les deux organisations réelles réconcilient au centre près**, caisse et
chaque compte bancaire. Rien n'a dérivé : le chantier part d'une base saine, et
tout écart apparu après une phase sera imputable à cette phase.

L'écart de l'organisation 18 n'était pas une dérive : `scripts/load_campaign.py`
créditait `caisse_centrale.solde_usd = 500 000` en dur sans créer le compte
`CASH` qui porte ce solde d'ouverture. Le tenant de charge naissait donc avec
une caisse que rien n'expliquait — ce qui aurait faussé toute mesure de clôture
faite sur lui.

**Corrigé le 29/08**, des deux côtés : le semeur crée désormais le compte `CASH`
avec son solde d'ouverture (comme il le faisait déjà pour la banque), et le
compte manquant a été créé sur le tenant 18 existant.

## La photo d'avant bascule (29/08/2026)

Brut : `photo-avant-bascule-20260829.json`. Prise juste avant de basculer
`versement_banque` vers le moteur dédié, avec les phases 0 et 1 livrées.

**Six organisations, zéro écart, code de sortie 0.** Solde par solde, elle est
identique à la photo de départ ; seul le tenant de charge est passé de
500 000,00 d'écart à 0,00, par la correction ci-dessus. Le contrôle C3 tombe
juste des deux côtés : les lignes que les écrans affichent somment exactement
les totaux agrégés, sur les deux sources.

C'est la référence à laquelle comparer après chaque phase de bascule.

## Phase 1 — combler les aveugles

`app/services/entrees_caisse.py` unionne désormais les deux sources. Ses deux
fonctions ont changé de nom, parce que l'ancien ne décrivait plus ce qu'elles
rendent :

| avant | après |
|---|---|
| `list_approvisionnements_caisse` | `list_entrees_internes_caisse` |
| `list_versements_banque` | `list_entrees_internes_banque` |

Les trois écrans qui les consomment — détail de balance de clôture
(`clotures.py`), liste des entrées de caisse (`encaissements.py`), classeur
d'encaissements (`exports.py`) — deviennent bilingues sans changer de code :
les lignes des deux origines portent exactement les mêmes clés. Seul
`type_operation` les distingue (`APPROVISIONNEMENT`, `VERSEMENT_BANQUE`,
`TRANSFERT_INTERNE`), pour qui veut les reconnaître.

Le champ de réponse `approvisionnements` de la balance de clôture **garde son
nom** : c'est un contrat déjà consommé par le frontend. Il porte maintenant les
deux sources.

Trois pièges traités au passage :

- **les identifiants sont préfixés** (`transfert-12`). Une sortie n°12 et un
  transfert n°12 sont deux lignes distinctes ; sans préfixe, elles partagent la
  même clé d'affichage et l'une remplace l'autre à l'écran ;
- **les bornes de date suivent la source.** Une sortie est datée par
  `coalesce(date_paiement, created_at)`, un transfert par `date_transfert` —
  comme les agrégats. Uniformiser ferait diverger la liste du total qu'elle
  détaille ;
- **l'origine est portée par la ligne.** Le classeur écrivait « Caisse » en dur
  dans la colonne source des entrées bancaires : vrai pour un versement, faux
  pour un virement de banque à banque, et un faux sur un document exporté.

Le contrôle C3 du filet a changé de sens en conséquence : il ne signale plus
« aucun chemin d'affichage », il compare l'union des lignes à l'union des
totaux. Il redevient rouge si un filtre est ajouté d'un seul côté.

Tests : `backend/tests/test_entrees_internes_bilingues.py`.

**Vérification.** Le filet rejoué après la Phase 1 rend exactement la photo de
départ — mêmes soldes, même unique écart sur le tenant de charge. C'était
l'objet de l'ordonnancement : rendre les lectures bilingues pendant que la
table dédiée est encore vide, donc pendant que le changement est inobservable.

### Une migration de convergence, découverte en route

La base de développement était **estampillée `20260830_transferts_additive` avec
un schéma qui n'était pas celui de cette révision** : elle portait `annule_le` /
`annule_par`, d'une première version de la migration écrite avant que la
correction ne devienne additive. La révision avait été réécrite après avoir été
appliquée.

Alembic ne rejoue jamais une révision estampillée : `upgrade head` y était un
no-op définitif, le modèle référençait des colonnes absentes, et toute lecture
de transfert répondait 500. D'où `20260831_transferts_repair`, en avant et
idempotente : elle ajoute les colonnes de contre-passation, les trois
contraintes et les deux index manquants, reprend d'éventuelles annulations de
l'ancien modèle, puis retire `annule_*` — **uniquement si aucune valeur n'y
subsiste**, sinon elle s'arrête et le dit. Sur une base neuve, elle ne fait
rien.

Appliquée à la base de développement le 29/08 (table vide, 0 ligne concernée),
et vérifiée en aller-retour sur une base construite depuis zéro.

## Phase 2 — équivalence de `versement_banque`

### La numérotation, tranchée

Toutes les opérations du moteur dédié portent une référence `TRF-<année>-<n>`,
quel que soit le sens : caisse → banque, banque → caisse, banque → banque.

**Aucune opération historique n'est renumérotée.** Les versements déjà
enregistrés gardent définitivement leur `PAY-…`. Les documents assument cette
rupture de série comme une conséquence normale du changement de moteur.

Pour lire un écran mixte, chaque ligne d'entrée interne porte désormais
`origine` :

| valeur | signification |
|---|---|
| `legacy` | la ligne vient de `sorties_fonds` |
| `transfert_interne` | la ligne vient du moteur dédié |

`origine` répond à « quelle table a écrit cette ligne ». Ne pas la confondre
avec `provenance`, introduite en Phase 1, qui répond à « d'où vient l'argent »
(« Caisse centrale », « Rawbank - Compte courant ») et alimente la colonne
source des classeurs.

### L'inventaire d'équivalence

Ce que le chemin historique garantit à un versement, et où en est le moteur :

| Garantie | Moteur dédié |
|---|---|
| écriture comptable, journal, clôture, export, soldes de caisse et de banque | ✅ équivalents (Phases 0 et 1, vérifiés) |
| pas de notification, pas d'impact budgétaire | ✅ par construction |
| référence de document | ✅ `TRF-`, tranché |
| identifiant UUID annoncé au frontend | ✅ colonne `document_uuid` |
| le bon imprimé et ses pièces jointes | ✅ colonnes `pdf_path`, `annexes` |
| ligne dans `GET /sorties-fonds` (écran + total « transferts internes ») | ✅ livré le 30/08 |
| ligne dans le classeur Excel des sorties de fonds | ✅ livré le 30/08 — **absent de cet inventaire jusque-là** |
| `POST /sorties-fonds/{id}/pdf` acceptant un transfert délégué | ✅ livré le 30/08 |
| annulation par `PATCH /sorties-fonds/{id}/statut` | ✅ livré le 30/08 (contre-passation additive) |

Migration : `20260901_transferts_document`. L'index unique sur `document_uuid`
est partiel — un transfert créé directement sur `/transferts-internes` n'a
jamais annoncé d'UUID à personne et n'en porte pas.

### Le drapeau

`TRANSFERTS_ENGINE_TYPES` (types délégués) et `TRANSFERTS_ENGINE_TENANTS`
(organisations concernées, vide = toutes). **Les deux sont vides par défaut :
rien ne change tant qu'ils ne sont pas ouverts.** Même dispositif que
`EXPORT_ASYNC_TYPES`, pour la même raison : la bascule doit être réversible un
type à la fois, sans redéploiement du frontend.

Refermer le drapeau n'annule rien : les transferts déjà écrits dans la table
dédiée y restent et continuent d'être lus par les agrégateurs. C'est la règle
absolue du chantier — aucune ligne n'est jamais recopiée d'une table à l'autre.

Le drapeau ne devait pas être ouvert tant que les lignes ❌ ci-dessus
subsistaient : un versement délégué aurait disparu de l'écran des sorties de
fonds et son bon n'aurait plus pu être attaché. Elles sont traitées.

### L'écran, le bon, l'annulation — et le classeur

`app/services/transferts_delegues.py` projette un transfert du moteur dédié dans
la forme de lecture de l'écran (`SortieFondsOut`), et `sorties_fonds.py` s'en
sert aux trois endroits qui adressent une opération par son UUID. Quatre règles
tiennent l'ensemble.

**Seuls les transferts qui portent un `document_uuid` sont projetés.** C'est ce
qui distingue une opération saisie sur cet écran d'un transfert saisi
directement sur `/transferts-internes`, qui a le sien et n'a jamais figuré ici.

**La projection ne consulte pas le drapeau.** Refermer le drapeau n'efface
aucune ligne déjà écrite ; une lecture qui en dépendrait les ferait disparaître
de l'écran tout en les laissant dans les soldes. Même raison d'ordonnancement
qu'en Phase 1 : le changement est inobservable tant que la table est vide, donc
testable sans risque. Concrètement, tant qu'aucun transfert délégué n'existe, la
requête historique garde exactement sa forme — `offset` et `limit` compris.

**La page est fusionnée après coup.** Les deux sources sont ramenées sur
`offset + limit` lignes chacune puis triées ensemble : borner chaque source à sa
propre page rendrait les N premières de chacune, c'est-à-dire pas les N plus
récentes de l'ensemble. Le tri SQL place désormais explicitement les NULL du
côté des plus petites valeurs, pour que la fusion Python ne déplace pas une
ligne sans date de paiement.

**Le classeur suit l'écran.** Il ne figurait pas dans l'inventaire
d'équivalence, et c'était un trou de même nature que celui de `entrees_caisse`
en Phase 1 : le total du pied de colonne se calcule sur les lignes présentes,
une ligne manquante ne fait donc pas qu'une absence, elle fausse la somme.

### Annuler, de ce côté-là, veut dire contre-passer

`PATCH /sorties-fonds/{id}/statut` avec `ANNULEE` sur un transfert délégué
appelle `contrepasser_transfer`. Deux écarts assumés avec le chemin historique :

- **pas de fenêtre de 30 minutes.** Elle protège une période passée d'être
  réécrite ; une contre-passation n'écrit que dans le présent. L'appliquer
  laisserait une erreur ancienne sans correction possible ;
- **le motif est obligatoire.** La correction laisse deux lignes dans les
  livres : sans motif écrit, plus personne ne peut dire pourquoi il y en a deux.

La ligne inverse reçoit son propre `document_uuid` **quand l'original en a
un** : sans lui, l'écran montrerait un original contre-passé sans la ligne qui
le compense — un +100 privé de son −100. Un transfert saisi hors de cet écran
garde une correction sans UUID, comme lui.

Le statut affiché est `CONTREPASSE`, jamais `ANNULEE` : les confondre ferait
croire à l'écran qu'il peut masquer la ligne, alors que la masquer tout en
gardant son inverse afficherait de l'argent venu de nulle part. Le pied de
colonne « transferts internes » vaut donc 200 après la correction d'un
mouvement de 100 — c'est un **volume** de mouvements internes, comme il l'est
déjà pour le chemin historique, qui y additionne les deux sens (versement
`CAISSE → BANQUE` **et** approvisionnement `BANQUE → CAISSE`). La trésorerie,
elle, est bien revenue à son point de départ.

### Ce que le frontend a dû apprendre

`SortieFondsOut` porte désormais `origine` (`legacy` / `transfert_interne`),
même vocabulaire que les lignes d'entrées internes de la Phase 1. L'écran s'en
sert pour trois choses seulement : afficher un badge « Contre-passée », ne pas
opposer la fenêtre de 30 minutes à une ligne du moteur dédié, et dire dans la
boîte de dialogue ce qui va réellement se passer — l'opération reste, un
transfert inverse la compense. Un caissier qui croit annuler et retrouve les
deux lignes pense à un bug.

Tests : `backend/tests/test_sorties_fonds_bilingues.py`.

## Phase 3 — la bascule d'écriture

`POST /sorties-fonds` délègue à `create_transfer` quand
`delegue_au_moteur(type_sortie, tenant_id)` répond oui. Le payload, les
permissions et **toutes** les validations restent celles de l'endpoint : seule
la table dans laquelle l'opération atterrit change.

### Où la délégation est placée, et pourquoi

Juste après les validations de payload — compte existant, actif, de type
`BANK`, devise concordante, montant strictement positif, bénéficiaire par
défaut — et **avant** tout verrou, toute numérotation et toute écriture.

Plus tôt, la délégation relâcherait des contrôles que le moteur dédié ne fait
pas (il ne vérifie pas qu'un compte est de type `BANK`, par exemple : un compte
`CASH` passerait pour une banque). Plus tard, elle consommerait un numéro
`PAY-` que rien n'utiliserait, laissant un trou dans une série de documents
comptables.

### L'identité documentaire est tirée à la délégation

L'UUID annoncé dans la réponse est généré par l'endpoint et porté par le
transfert (`document_uuid`). C'est lui que le frontend utilise ensuite pour
attacher le bon imprimé. Un rejeu idempotent rend le transfert existant, donc
l'UUID d'origine — jamais un nouveau, qui ferait attacher le bon à une
opération inexistante.

### Le piège de l'idempotence dérivée

Le transfert transmis au service est **dérivé** du payload client : il porte
une `date_transfert` résolue côté serveur, différente à chaque appel. Comparer
les rejeux sur l'empreinte de ce payload dérivé aurait refusé tout rejeu en
« payload différent » — c'est-à-dire cassé l'idempotence exactement là où elle
sert, sur le double-clic. `create_transfer` accepte donc une empreinte imposée,
et l'endpoint lui passe celle du payload **du client**.

### Trois propriétés vérifiées par les tests

- **fermé, le drapeau ne fait rien.** Le code part en production inerte, ce qui
  rend la bascule déployable sans décision ;
- **elle s'ouvre un type et une organisation à la fois.** Ouvrir
  `versement_banque` ne bascule pas les approvisionnements ;
  `TRANSFERTS_ENGINE_TENANTS` permet un tenant pilote ;
- **la refermer n'annule rien.** Les nouvelles opérations repartent sur le
  chemin historique, les anciennes restent dans la table dédiée, et l'écran les
  affiche toutes — c'est la règle absolue du chantier.

Tests : `backend/tests/test_bascule_ecriture_transferts.py`.

### Un défaut trouvé en passant

Un versement dont le bénéficiaire était laissé vide répondait **500** : le
chemin historique lisait `compte_destination.banque` sur un objet issu d'un
`SELECT … FOR UPDATE`, donc sans relation chargée — un accès paresseux hors
contexte async. Le nom de la banque est désormais relu par une requête
explicite. Le chargement empressé n'était pas une option : il rend une jointure
externe, que `FOR UPDATE` interdit.

## Ce qui reste avant d'ouvrir le drapeau en production

Le code est livré fermé. Avant de l'ouvrir sur une organisation réelle :

1. ~~rejouer le filet et comparer à `photo-avant-bascule-20260829.json`~~ —
   **fait le 30/08** ;
2. ~~ouvrir `TRANSFERTS_ENGINE_TYPES=versement_banque` sur le seul tenant de
   charge (18), y saisir un versement, l'imprimer, le contre-passer~~ —
   **fait le 30/08** ;
3. ~~rejouer le filet : l'écart doit rester nul, la trésorerie étant revenue à
   son point de départ~~ — **fait le 30/08** ;
4. ouvrir sur une organisation réelle, un type à la fois. **Reste à décider.**

## L'ouverture sur le tenant de charge (30/08/2026)

`.env` porte désormais `TRANSFERTS_ENGINE_TYPES=versement_banque` et
`TRANSFERTS_ENGINE_TENANTS=18`, et le backend a été recréé pour les lire
(`docker compose up -d backend` — `restart` ne relit pas `.env`, il redémarre
le conteneur avec l'environnement résolu à sa création). Les deux variables
sont documentées vides dans `.env.example` : le dépôt reste fermé par défaut.

Vérifié sur le processus qui tourne :

| organisation | `versement_banque` | `approvisionnement_caisse` |
|---|---|---|
| 18 — Load Test | **délégué** | historique |
| 1 — Kinshasa | historique | historique |
| 8 — Conseil National | historique | historique |

Les deux organisations réelles ne sont pas touchées, et le second type ne l'est
sur aucune : la bascule s'ouvre bien un type et une organisation à la fois.

**Filet rejoué : 6 organisations, 0 écart, code de sortie 0.** Brut :
`photo-drapeau-ouvert-20260830.json`, **identique champ par champ** à
`photo-avant-bascule-20260829.json` (hors horodatage de la prise).

### Ce que cette photo prouve, et ce qu'elle ne prouve pas

Elle prouve qu'**ouvrir le drapeau ne change aucun chemin de lecture** : les
soldes, les termes de trésorerie et le contrôle C3 sont au centre près ceux
d'avant. C'est attendu — la projection de lecture est inconditionnelle, elle ne
consulte pas le drapeau — mais le vérifier vaut mieux que le supposer.

Elle ne prouve **rien sur la délégation elle-même** : `transferts_internes` est
encore vide côté tenant 18, donc aucune ligne n'est passée par le moteur dédié.
C'est une photo *avant*, la référence à laquelle comparer après le versement
d'essai. Tant que ce versement n'est pas saisi, imprimé et contre-passé, le
point 2 n'est fait qu'à moitié.

La transition doit rester **courte** : tant que les deux chemins coexistent, le
même écran affiche de l'histoire immuable pour les nouvelles lignes et de
l'histoire révisable pour les anciennes.

## Le versement d'essai (30/08/2026, tenant 18)

Première opération réelle écrite par le moteur dédié. Menée en pilotant les
fonctions d'endpoint sur la base de développement — le tenant de charge est
inactif et sans utilisateur, l'activer pour un essai aurait coûté plus que ce
que la voie HTTP aurait prouvé de plus. L'authentification et la résolution de
tenant ne sont donc pas exercées ; ce chantier n'y touche pas.

| étape | résultat |
|---|---|
| saisie d'un `versement_banque` de 250,00 USD | `TRF-2026-00001`, `origine = transfert_interne`, aucune ligne dans `sorties_fonds` |
| trésorerie | caisse 506 690 → 506 440, banque 500 000 → 500 250 |
| rejeu de la même `Idempotency-Key` | même UUID rendu, un seul transfert écrit, soldes inchangés |
| écran des sorties de fonds | la ligne s'affiche, total « transferts internes » 250,00, dépenses réelles 0 |
| bon imprimé | PDF de 1 781 octets attaché sous `TRF-2026-00001-bon.pdf` |
| annulation | `CONTREPASSE` + `TRF-2026-00002` en sens inverse ; caisse et banque **revenues au centime près** |

Le bénéficiaire calculé — « LOAD BANK - Compte load test » — est la poche qui
reçoit, comme prévu : le payload ne le portait pas.

**Filet rejoué : 6 organisations, 0 écart, code de sortie 0.**
Brut : `photo-apres-versement-essai-20260830.json`.

### Le diff des photos est le vrai résultat

Comparée à `photo-drapeau-ouvert-20260830.json`, la photo d'après ne bouge que
sur l'organisation 18, et **jamais sur un solde ni sur un écart** :

```
termes.transferts_entrants  : 0 → 250.00     (caisse ET banque)
termes.transferts_sortants  : 0 → -250.00    (caisse ET banque)
couverture[0..1].lignes     : 0 → 1
couverture[0..1].total      : 0 → 250.00
couverture[0..1].affichable : 0 → 250.00
couverture[0..1].ecart      : 0 → 0.00
```

Chaque poche a envoyé 250 et reçu 250 : l'aller et le retour apparaissent
séparément, ils se compensent, et rien n'est réécrit. C'est la correction
additive vue depuis la trésorerie.

Surtout, le contrôle C3 a enfin quelque chose à contrôler du côté du moteur
dédié — et il tombe juste : `total == affichable` sur les deux termes. Jusqu'à
cet essai il comparait deux zéros.

### Ce que l'essai laisse derrière lui

Volontairement, et c'est la règle du chantier — rien n'est jamais effacé :

- **deux transferts sur le tenant 18** (`TRF-2026-00001` contre-passé,
  `TRF-2026-00002` sa correction), net nul en trésorerie ;
- **un bon PDF** sous `backend/app/uploads/tenants/49395da4-…/sorties-fonds/2026/08/` ;
- **un utilisateur d'essai**, `essai-bascule@load-test.local`, créé sur le
  tenant 18 pour porter `execute_par` et la piste d'audit.

### Un piège relevé au passage

`create_sortie_fonds` **mutate le payload reçu** : pour un transfert interne il
annule `service_id`, `budget_poste_id`, `rubrique_code`, force `mode_paiement`,
et remplit `beneficiaire` s'il est vide. L'empreinte d'idempotence, elle, est
calculée avant ces mutations. Sur HTTP c'est sans conséquence — FastAPI
reconstruit un objet à chaque requête. Mais un appelant **in-process** qui
réutilise le même objet pour un rejeu se voit répondre « payload différent » :
c'est ce qui a interrompu la première passe de cet essai. Rien à corriger pour
la production ; à savoir pour tout script qui pilote l'endpoint directement.