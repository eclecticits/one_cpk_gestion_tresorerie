# RAPPORT — agent HOOKS

Branchement des six événements WhatsApp sur le code de production. Cinq fichiers
modifiés, un correctif livré à part.

| Livrable | Avant | Après | Lignes supprimées |
|---|---|---|---|
| `backend/app/api/v1/endpoints/encaissements.py` | 2189 | 2352 | 34 |
| `backend/app/api/v1/endpoints/payments.py` | 170 | 188 | 0 |
| `backend/app/api/v1/endpoints/sorties_fonds.py` | 2167 | 2374 | 0 |
| `backend/app/api/v1/endpoints/requisitions.py` | 2257 | 2350 | 22 |
| `backend/app/services/whatsapp.py` | 45 | 75 | 45 (coque assumée) |
| `backend/app/api/v1/endpoints/requisitions.py.deadcode-patch` | — | 159 | — |

Les 34 lignes retirées d'`encaissements.py` sont exactement : l'import déprécié,
l'import `SystemSettings` devenu inutile, et les 32 lignes du bloc WhatsApp
absorbé. Les 22 de `requisitions.py` sont exactement le bloc WhatsApp du visa
final. Tout le reste est de l'ajout — vérifié par `diff … | grep "^<"`.

**Contrôles passés sur chaque fichier** : `python3 -m py_compile` (OK), et
`python3 -m pyflakes` comparé à la même commande sur l'original — aucune
nouvelle alerte introduite. Le rendu des gabarits a été exécuté hors application
avec les jeux de variables réels de chaque événement.

---

## 1. Les sept points d'insertion

Chaque numéro de ligne de l'audit a été revérifié avant édition ; tous étaient
justes. Les colonnes « avant / après » donnent la ligne dans le fichier d'origine
et dans le fichier livré.

### 1.1 `PAYMENT_RECEIVED` — note de débit avec paiement

* **Fichier** : `encaissements.py`, `create_encaissement`
* **Ligne** : 1352 (avant) → **1513** (après)
* **Condition** : `if montant_paye > 0` — la même que l'e-mail juste au-dessus.
* **Placement** : après `db.commit()` (l. 1616 d'origine), après l'e-mail, et
  après la résolution de l'expert-comptable — de sorte que l'objet déjà chargé
  soit réutilisé plutôt que relu.
* **Entité** : `entity_type="encaissement"`, `entity_id=str(encaissement.id)`.
* **Variables** : `nom`, `reference` (`numero_recu` ou `numero_proforma`),
  `date`, `montant` (= le montant encaissé), `devise`, `motif` (= `libelle`),
  `total` (= `montant_total`), `reste_a_payer`, `mode_paiement`, `canal`.

### 1.2 `PAYMENT_PROFORMA_CONVERTED` — conversion de pro forma

* **Fichier** : `encaissements.py`, `convertir_proforma`
* **Ligne** : 1665 (avant) → **1804** (après)
* **Absorption** : le bloc 1632–1662 est supprimé. Trois gains au passage —
  le client non-expert n'est plus ignoré (l'ancien code ne regardait que
  `expert.telephone`) ; la clé API n'est plus lue en clair ; l'envoi laisse une
  ligne dans `notification_logs` au lieu de disparaître dans un
  `logger.exception`.
* **Entité / variables** : identiques à 1.1, `montant` = `montant_paye`.

### 1.3 `PAYMENT_COMPLEMENT` — paiement complémentaire

* **Fichier** : `payments.py`, `create_payment`
* **Ligne** : 112 (avant) → **123** (après), juste après l'e-mail.
* **Entité** : `entity_type="payment_history"`, `entity_id=str(payment.id)` —
  **et non l'encaissement**. Voir §4.1 : c'est une correction de fond, pas un
  détail.
* **Variables** : comme 1.1, avec `montant` = le montant de **ce** versement,
  `total` = montant total de la pièce, `reste_a_payer` = solde après ce
  versement.

### 1.4 `PAYMENT_REMINDER` — relance manuelle

* **Fichier** : `encaissements.py`, `relancer_solde_client`
* **Ligne** : 1729 (avant) → **1914** (après), après le `db.commit()` de la
  ligne 1897.
* **Non bloquant** : l'e-mail de cet endpoint est volontairement synchrone
  (`send_now=True`) et son échec renvoie un `400`, parce que la relance ne doit
  pas être décomptée si rien ne part. **Le WhatsApp ne suit pas cette règle** :
  il est appelé après le `commit()`, sa remise part en tâche de fond, et son
  échec n'a aucun effet sur le compteur de relances ni sur la réponse HTTP.
* **`nonce="relance-{n}"`** : voir §4.1.
* **Variables** : `montant` vaut ici le montant total de la pièce (rien n'est
  reçu lors d'une relance) ; `reste_a_payer` porte l'information utile.

### 1.5 `FUND_OUTFLOW` — sortie de fonds

* **Fichier** : `sorties_fonds.py`, `create_sortie_fonds`
* **Ligne** : **1870**, entre le `db.commit()` (l. 1833) et le
  `return _sortie_out(...)` (l. 1880).
* **Signature** : `background_tasks: BackgroundTasks` ajouté en 3ᵉ position
  (l. 1034), avant les paramètres à valeur par défaut. `BackgroundTasks` était
  déjà importé (l. 12). Aucun appelant direct de cette fonction n'existe dans le
  dépôt ni dans les tests — vérifié.
* **Aucune requête ajoutée pour les objets métier** : `requisition`,
  `validateur` et `approbateur` sont chargés juste au-dessus (l. 1843–1868) et
  passés tels quels. Les seules requêtes du bloc sont celles qu'impose le
  service : réglages du tenant, nom d'organisation, destinataires du Bureau — et
  elles ne partent que si le canal est ouvert (§3.2).
* **Entité** : `entity_type="sortie_fonds"`, `entity_id=str(sortie.id)`.
* **Variables** : `reference` (`reference_numero`), `date`, `beneficiaire`,
  `motif`, `montant`, `devise`, `canal`, `mode_paiement`, `poste_budgetaire`,
  `auteur`, `validateur`, `solde_apres`, `tranche` (vide — §4.4).

### 1.6 `REQUISITION_APPROVED` — visa final

* **Fichier** : `requisitions.py`, `vise_requisition`
* **Ligne** : 1966–1987 (avant) → **2076** (après).
* **Absorption + requalification** : le message passe du vocabulaire de sortie
  de fonds (« ✅ Réquisition validée (2/2) ») au gabarit `REQUISITION_APPROVED`,
  qui dit « en attente de paiement — aucun fonds n'a encore été décaissé ».
* **Sorti du `try` de l'e-mail** : l'ancien bloc partageait le `try` de la
  notification e-mail, dont la préparation appelle
  `_collect_requisition_email_attachments` (génération et collecte de PDF). Une
  exception là-dedans faisait sauter le WhatsApp avec. Les deux canaux sont
  désormais indépendants.
* **Entité** : `entity_type="requisition"`, `entity_id=str(req.id)`.
* **Variables** : `reference` (`numero_requisition`), `date` (`approuvee_le`),
  `beneficiaire` (`instance_beneficiaire`), `motif` (`objet`), `montant`,
  `devise`, `validateur` (l'utilisateur qui vient de viser).

### 1.7 `app/services/whatsapp.py` — coque de délégation

`normalize_whatsapp_numbers` et `send_whatsapp_message` restent en place avec la
même signature (`requisition_service.py:47` et le bloc mort de `requisitions.py`
les importent encore) et délèguent respectivement à
`notifications.phone.normalize_phone_list` et à `EvolutionWhatsAppProvider`. Les
deux docstrings portent **Déprécié** et disent pourquoi : clé en clair devenue
inopérante après migration, aucune trace en journal, aucune dé-duplication. Les
imports du paquet `notifications` sont différés à l'intérieur des fonctions,
pour ne créer aucun risque de cycle au chargement.

---

## 2. Aucun appel direct ne subsiste dans le code vivant

Les trois appels signalés sont traités :

| Appel | Sort |
|---|---|
| `requisitions.py:1984` | supprimé, remplacé par le service (§1.6) |
| `requisitions.py:2063` | **code mort** — laissé en place ici, supprimé par le correctif séparé |
| `encaissements.py:1657` | supprimé, remplacé par le service (§1.2) |

`grep send_whatsapp_message` sur les fichiers livrés ne renvoie plus que : la
définition dans la coque `whatsapp.py`, l'import mort de `requisitions.py`, et
le bloc mort qui le consomme. Rien d'atteignable à l'exécution.

**Reste à traiter hors périmètre** : `requisition_service.py:47` importe
`normalize_whatsapp_numbers` et `send_whatsapp_message` sans jamais les appeler
— import mort d'origine. Ce fichier n'étant pas dans mes livrables, je ne l'ai
pas touché ; la coque le protège de toute façon.

---

## 3. Preuve qu'un échec d'envoi ne peut pas casser l'opération métier

Quatre barrières, dont trois sont dans le socle et une dans mon code.

### 3.1 L'appel est toujours après le `commit()` métier

| Point | `commit()` métier | Appel WhatsApp |
|---|---|---|
| `create_encaissement` | l. 1616 | l. 1513 (après la boucle de retry, l'opération est committée) |
| `convertir_proforma` | l. 1775 | l. 1804 |
| `create_payment` | l. 108 | l. 123 |
| `relancer_solde_client` | l. 1897 | l. 1914 |
| `create_sortie_fonds` | l. 1833 | l. 1870 |
| `vise_requisition` | dans `vise_requisition_logic` | l. 2076 |

À l'instant de l'appel, l'argent est enregistré et la transaction est close.
Aucun chemin ne peut plus l'annuler : `queue_whatsapp` ouvre sa propre
transaction (`INSERT` dans `notification_logs` puis `commit`), et son propre
`except` fait un `rollback` qui ne peut porter que sur ces lignes de journal.

### 3.2 Rien ne remonte

* `notify_whatsapp` encapsule la mise en file dans un `try/except` et renvoie
  `0` en cas d'échec (`service.py`, « notifications.queue_failed »).
* `deliver_pending` — la remise réseau — s'exécute en tâche de fond, après que la
  réponse HTTP est partie, et son corps entier est sous `try/except`.
* Le provider ne lève pas : il renvoie un `ProviderResult` (`ok=False`, motif).
* **Mes trois helpers** (`_notify_paiement_whatsapp`,
  `_notify_sortie_fonds_whatsapp`, `_notify_requisition_approuvee_whatsapp`)
  ajoutent une ceinture par-dessus les bretelles : la résolution des
  destinataires interroge la base (expert, client, Bureau, organisation) et ces
  requêtes-là ne sont pas couvertes par le `try` du service. Tout est donc sous
  un `try/except Exception` qui journalise et retourne `None`. **Aucun de ces
  trois helpers ne peut lever.**

### 3.3 Sortie anticipée avant toute dépense inutile

Chaque helper commence par lire les réglages du tenant et sort immédiatement si
`settings.accepts(event_type)` est faux. Pour un tenant qui n'a pas activé
WhatsApp — le cas de tous les tenants au jour du déploiement — le coût ajouté à
une opération de caisse est **une seule requête** sur `system_settings`, et zéro
ligne de journal. Les requêtes de destinataires ne partent que sur le chemin où
un message va réellement être écrit.

### 3.4 Le solde après opération est capturé avant le `commit()`

`sorties_fonds.py`, l. 1826–1831 : `solde_apres_operation` est calculé en
arithmétique pure sur deux locales (`solde_disponible`, lue sous
`FOR UPDATE` au contrôle de provision, et `montant_paye`), **avant** le
`commit()` de la l. 1833. Le bloc de notification ne relit aucun objet de
trésorerie. Aucun accès différé, donc aucun `MissingGreenlet` possible.

> Note factuelle : `SessionLocal` est construit avec `expire_on_commit=False`
> (`app/db/session.py:98`), donc les objets ne sont en pratique pas expirés au
> commit. La capture anticipée reste néanmoins la bonne construction — elle ne
> dépend pas de ce réglage, et évite une requête.

---

## 4. Écarts, décisions et données non fiables

### 4.1 Dé-duplication — deux événements auraient été rendus muets

C'est le point le plus important du rapport. La clé de dé-duplication porte sur
`(organisation, événement, entité, canal, destinataire)`. Deux événements se
répètent légitimement pour la même entité :

* **Paiement complémentaire** : un client qui règle en trois fois produit trois
  `PAYMENT_COMPLEMENT` sur le même encaissement. Rattachés à l'encaissement, les
  2ᵉ et 3ᵉ auraient la même clé que le 1ᵉʳ et seraient avalés en silence par le
  `ON CONFLICT DO NOTHING`. → `entity_id` porte l'identifiant du **paiement**
  (`entity_type="payment_history"`), unique par versement.
* **Relance** : jusqu'à trois relances sont autorisées par note de débit
  (`MAX_RELANCES_PAR_RECU`). Même problème. → `nonce="relance-{relance_count}"`.
  Le nonce est déterministe et non aléatoire : un rejeu HTTP de la *même*
  relance reste dé-dupliqué, ce qui est le comportement voulu.

Les quatre autres événements sont bien uniques par entité et n'ont besoin de
rien.

### 4.2 Gabarit `PAYMENT_COMPLEMENT` — libellé contradictoire à corriger

`templates.TEMPLATE_VARIABLES` définit `total` = « Montant total de la pièce ».
C'est cette définition que j'ai suivie. Mais le gabarit par défaut affiche cette
variable sous l'étiquette **« Total réglé »**, ce qui produit :

```
Montant reçu : 300.00 USD
Total réglé : 1 000.00 USD      <-- en réalité : montant total de la pièce
Reste à payer : 200.00 USD
```

Un client lit qu'il a réglé 1 000 tout en devant encore 200. **Le correctif est
dans `templates.py`, pas ici** : remplacer l'étiquette par « Montant total ».
Fichier de contrat, non modifié par moi. À arbitrer par l'agent qui en est
propriétaire — soit l'étiquette change, soit `TEMPLATE_VARIABLES` redéfinit
`total`, mais les deux ne peuvent pas rester en l'état.

### 4.3 `resolve_client_recipient` ne sait pas nommer un expert-comptable

Le contrat cherche `nom_complet`, `prenom`/`nom`, `raison_sociale`,
`denomination`. Le modèle `ExpertComptable` ne porte **aucun** de ces champs sauf
`raison_sociale`, réservée aux sociétés (SEC) : pour un expert personne
physique, `Recipient.name` ressort vide et le message commencerait par
« Bonjour , ». `Client`, lui, est correctement nommé (`nom`).

Sans toucher au fichier de contrat, je passe `nom` dans `variables` :
`queue_whatsapp` applique `recipient.name or base_variables["nom"]`, donc le
repli fonctionne. La valeur est `expert.nom_denomination`, sinon `client.nom`,
sinon `encaissement.client_nom`. **À corriger à la source** en ajoutant
`nom_denomination` à la liste lue par `resolve_client_recipient`.

### 4.4 `tranche` — laissée **vide**, faute de donnée fiable

Le décaissement progressif produit plusieurs sorties pour une même réquisition,
mais **le nombre total de tranches n'existe nulle part** :

* aucun champ `nombre_tranches` sur `Requisition` ni sur `OrdreDecaissement`
  (vérifié champ par champ) ;
* les ordres sont créés et autorisés au fil de l'eau par le demandeur ; le total
  d'aujourd'hui n'est pas celui de demain ;
* ce que le code calcule à cet endroit (`total_paye_od`, l. 1601 d'origine) est
  une **somme de montants**, pas un compte de tranches.

Écrire « Tranche 2 sur 3 » sur la foi du nombre d'ordres existants produirait un
message faux dès qu'un 4ᵉ ordre serait autorisé — et il aurait déjà été envoyé.
J'ai donc laissé la variable vide, conformément à la consigne.

Deux notes pour qui reprendra le sujet :

* le gabarit insère `{{tranche}}` **sur sa propre ligne, sans étiquette** — la
  valeur devra donc porter son propre `\n` final, sinon elle se colle à
  « Enregistrée par : ». C'est documenté dans le code au point d'insertion.
* si l'on veut malgré tout une information de progression **exacte**, le cumul
  décaissé et le montant total de la réquisition sont tous deux disponibles
  avant le commit et n'exigent aucune requête supplémentaire : « 1 250 sur
  3 000 USD décaissés » serait vrai, là où « Tranche N sur M » ne l'est pas.

### 4.5 `canal` déduit du mode de paiement

La colonne `canal` ne connaît que `CAISSE` et `BANQUE`, et
`reglement.canal_pour_mode` y range **tout ce qui n'est pas `cash`** — mobile
money compris. Annoncer « Banque » au Bureau pour un paiement Mobile Money serait
faux sur le point le plus utile du message : d'où l'argent est parti.

`_canal_lisible(mode, canal)` répond donc à partir du **mode** : `cash` →
« Caisse », `mobile_money` → « Mobile money », virement / carte / chèque →
« Banque », et ne retombe sur la colonne que si le mode est inconnu. La variable
`mode_paiement` porte en parallèle le libellé détaillé.

### 4.6 `poste_budgetaire` en dépense multi-postes

`sortie.budget_poste_id` est `None` mais `budget_poste_libelle` porte déjà
« Réparti sur N postes » (écrit l. 1441 d'origine). C'est cette chaîne qui passe
telle quelle. En mono-poste, le code est préfixé : « 6120 — Frais de mission ».
Si les deux champs sont vides, la variable est vide et `templates.render`
supprime la ligne — pas de « Poste budgétaire : » orphelin.

`rubrique_code` n'est alimenté nulle part dans le dépôt : il n'entre pas dans le
message. Commentaire laissé dans le code pour que la question ne se repose pas.

### 4.7 Types de sortie exclus

`TYPES_SORTIE_SANS_NOTIFICATION = {"versement_banque", "approvisionnement_caisse",
"regularisation_caisse"}` — valeurs exactes relevées respectivement à
`sorties_fonds.py:897`, `sorties_fonds.py:901` et
`services/regularisation_caisse.py:38` (`TYPE_SORTIE_REGULARISATION`). Les deux
premières sont des transferts internes de trésorerie ; la troisième est une
correction d'écart de caisse, produite par son propre service et jamais par cet
endpoint — filtrée par précaution, `type_sortie` étant repris tel quel du
payload sans validation.

### 4.8 Aucune condition sur `statut == "VALIDE"`

Respecté, et pour une raison vérifiée dans le code : le décrément de
`caisse.solde_usd` / `compte.solde_actuel` (l. 1468–1475 d'origine) ne regarde
pas `sortie.statut`. Une sortie créée avec `statut="BROUILLON"` — valeur non
validée par `SortieFondsCreate` — débite quand même la trésorerie. La notifier
est donc correct.

Deux voisins vérifiés au passage, tous deux légitimement muets :
`POST /sorties-fonds/drafts` crée un `BROUILLON` **sans toucher aucun solde**, et
`PATCH /{id}/statut` n'accepte que `ANNULEE`, qui recrédite (les annulations sont
explicitement hors périmètre dans `events.py`).

### 4.9 `build_settings` plutôt que `load_whatsapp_settings`

J'utilise `get_system_settings(db, tenant_id)` puis
`build_settings(ns, org_name)` — les deux sont exportés par le paquet — au lieu
de `load_whatsapp_settings`. Trois raisons :

1. **Il faut `ns` de toute façon** pour les sorties de fonds et le visa :
   `resolve_outflow_recipients` prend `fallback_numbers=ns.whatsapp_agents`.
   Passer par `load_whatsapp_settings` ferait deux requêtes au lieu d'une.
2. **Sortie anticipée** : `build_settings` est du Python pur, ce qui permet de
   tester `accepts()` et de sortir avant la requête du nom d'organisation.
3. **Robustesse aux doublons** — c'est le point de fond.
   `load_whatsapp_settings` fait un `scalar_one_or_none()` sans `limit`, qui lève
   `MultipleResultsFound` si un tenant a plusieurs lignes `system_settings`. Le
   cas n'est pas théorique : `system_settings_service.consolidate_system_settings`
   existe précisément pour le réparer. L'exception est avalée par le `try` du
   loader, qui renvoie alors des réglages désactivés — **le tenant concerné
   cesserait silencieusement d'être notifié**. `get_system_settings` applique un
   `ORDER BY … LIMIT 1` et n'a pas ce défaut.

   → **Correctif suggéré dans le socle** : ajouter `.limit(1)` (et de préférence
   le même `ORDER BY`) à la requête de `settings_loader.load_whatsapp_settings`.

### 4.10 Import inter-endpoints dans `payments.py`

`payments.py` importe `_notify_paiement_whatsapp` depuis `encaissements.py`
plutôt que d'en dupliquer 90 lignes. Pas de cycle : `encaissements.py` n'importe
rien de `payments.py`. Le dépôt fait déjà exactement cela
(`retours_caisse.py:42` importe `_get_or_create_caisse` et `_to_budget_currency`
de `sorties_fonds.py`). Si vous préférez, l'extraction dans un
`app/services/payment_notifications.py` est mécanique — je ne l'ai pas faite
pour rester dans la liste de livrables.

### 4.11 Résidu sans conséquence dans `requisitions.py`

Le garde `if ((smtp_cfg and ns.email_tresorier) or (ns.whatsapp_api_url and
ns.whatsapp_agents)):` (l. 2039) sert encore à décider s'il faut aller chercher
`org_name` / `org_slug` pour l'e-mail. Sa moitié WhatsApp ne pilote plus rien.
Je l'ai laissée : la retirer changerait les conditions d'affectation d'`org_slug`
sans aucun gain. À nettoyer si vous repassez sur ce bloc e-mail.

---

## 5. Le correctif de code mort, livré à part

`backend/app/api/v1/endpoints/requisitions.py.deadcode-patch` — diff unifié,
**non appliqué** au livrable 4, comme demandé.

**Ce qu'il supprime** : les 78 lignes qui suivent le `return _requisition_out(req)`
de `vise_requisition` (l. 2085–2162 du fichier livré), plus l'import déprécié
devenu inutile (5 lignes avec son commentaire). 2350 → 2267 lignes.

**Pourquoi c'est sans perte** : tout ce que contient ce bloc est déjà exécuté par
`requisition_service.vise_requisition_logic` — snapshot historique (l. ~946),
`log_action("REQUISITION_FINAL_APPROVED")` (l. ~949), `commit`/`refresh`
(l. ~959), `check_cash_watchdog` (l. ~963) — et le reste est un duplicata du bloc
de notifications situé avant le `return`.

**Pourquoi il fallait y regarder à deux fois** : le bloc lit `old_status` dans
`old_value={"status": old_status}`, variable **jamais assignée dans cette
fonction**. Confirmé par pyflakes sur le fichier d'origine :

```
requisitions.py:2000:30: undefined name 'old_status'
```

Le danger n'est donc pas de supprimer ce bloc — c'est de le *réanimer*. Qui
« corrigerait » la fonction en retirant seulement le `return` prématuré pour
rendre la suite atteignable déclencherait un `NameError` au premier visa final,
après le commit : réquisition approuvée en base, 500 renvoyée à l'utilisateur.
Supprimer est la bonne correction ; le patch la rend relisible isolément.

**Vérifications** : `patch -p1 --dry-run` et `git apply --check` passent tous
deux ; appliqué pour de bon, le fichier compile (`py_compile` OK) et pyflakes ne
signale plus ni `undefined name 'old_status'` ni import `whatsapp` inutilisé.

```
cd <racine du dépôt>
git apply backend/app/api/v1/endpoints/requisitions.py.deadcode-patch
```
