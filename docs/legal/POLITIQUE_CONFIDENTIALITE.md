# Politique de confidentialité — ONEC Smart

**Dernière mise à jour :** 30/07/2026
**Version :** 2.5 (projet à faire valider juridiquement)

> ⚠️ **Avis important.** Ce document est un modèle technique rédigé à partir de l'analyse de l'application. Il **n'est pas un avis juridique**. Faites-le relire et adapter par un conseil juridique compétent (RGPD si vous traitez des données de personnes dans l'UE ; loi congolaise sur la protection des données / autres juridictions applicables) avant publication. Les mentions entre crochets `[À COMPLÉTER]` doivent être renseignées.

---

## 1. Qui sommes-nous ?

ONEC Smart (« l'Application », « le Service ») est une plateforme de gestion de trésorerie, de comptabilité et d'administration destinée aux organisations professionnelles.

- **Responsable du traitement (éditeur) :** Eclectic IT Services
- **Adresse :** N°137 MBOMU, Kinshasa, République Démocratique du Congo
- **Représentant légal :** KIDIKALA NGABA Christian
- **Contact protection des données / DPO :** kidikala@gmail.com

Le Service est proposé en mode SaaS multi-organisations : chaque organisation cliente dispose d'un espace cloisonné. Pour les données saisies par une organisation dans son espace (données financières, RH, clients…), **l'organisation cliente agit comme responsable de traitement** et l'éditeur d'ONEC Smart agit comme **sous-traitant** au sens du RGPD. Pour les données de gestion du compte (identifiants, journaux de sécurité), l'éditeur est responsable de traitement.

## 2. Quelles données collectons-nous ?

### 2.1 Données de compte utilisateur
- Adresse e-mail, nom, prénom.
- Mot de passe (stocké **haché**, jamais en clair).
- Rôle, organisation de rattachement, service.
- Codes à usage unique (OTP) et métadonnées de vérification, état du compte (actif, e-mail vérifié).
- Journaux techniques : dates de création/connexion, adresse IP (utilisée pour la sécurité et la limitation de débit).

### 2.2 Données d'inscription d'une organisation
- Nom de l'organisation, coordonnées de contact, numéro de téléphone du demandeur, informations d'abonnement/facturation.

### 2.3 Données métier saisies par les organisations
- **Financières :** réquisitions, sorties de fonds, encaissements, ordres de décaissement, comptes bancaires, bénéficiaires (noms), montants, pièces justificatives téléversées.
- **Ressources humaines :** données des salariés (identité, contrats, rémunérations, cotisations sociales de type IPR/CNSS). **Ces données peuvent être sensibles** et sont traitées pour le compte de l'organisation cliente.
- **Clients / tiers :** nom, numéro de téléphone, historique de reçus.

### 2.4 Données liées aux fonctionnalités d'intelligence artificielle
Lorsque le module IA est activé par une organisation, certaines données de contexte (par ex. libellés de dépenses, instantané financier, contenu de documents ou d'e-mails à synthétiser) sont transmises à un fournisseur de modèle de langage pour produire une réponse. Voir §5.

### 2.5 Données Google / Gmail (module Secrétariat, optionnel)
Si une organisation connecte un compte Google, l'Application utilise le périmètre `gmail.compose` pour **créer des brouillons** d'e-mails soumis à validation humaine. Le périmètre de **lecture** de la boîte (`gmail.readonly`) est **désactivé par défaut** et n'est demandé que si l'organisation l'active explicitement. Aucun e-mail n'est envoyé automatiquement par l'IA sans validation humaine.

### 2.6 Cookies
L'Application utilise un cookie **strictement nécessaire** : un cookie `HttpOnly` de session (jeton de rafraîchissement) permettant de maintenir la connexion. Aucun cookie publicitaire ou de suivi tiers n'est utilisé. Le jeton d'accès est conservé uniquement en mémoire du navigateur (jamais dans le stockage local).

## 3. Pourquoi et sur quelle base légale ?

| Finalité | Base légale (RGPD) |
|---|---|
| Fournir le service (comptes, trésorerie, RH, reporting) | Exécution du contrat |
| Authentification, sécurité, prévention de la fraude, journaux d'audit | Intérêt légitime / obligation légale |
| Facturation et gestion des abonnements | Exécution du contrat / obligation légale |
| Notifications par e-mail / WhatsApp liées au service | Exécution du contrat / intérêt légitime |
| Fonctionnalités IA (synthèses, classification, brouillons) | Intérêt légitime, sur activation par l'organisation ; validation humaine requise |
| Respect des obligations comptables et fiscales | Obligation légale |

## 4. Combien de temps conservons-nous les données ?

- **Comptes utilisateurs :** pendant la durée de la relation contractuelle, puis suppression ou anonymisation dans un délai de [À COMPLÉTER, ex. 30 jours] après clôture, sauf obligation de conservation.
- **Données financières et comptables :** conservées pour la durée légale de conservation applicable [À COMPLÉTER selon la juridiction], même après clôture du compte utilisateur individuel (les écritures sont conservées de façon **anonymisée** au niveau de l'utilisateur si nécessaire).
- **Journaux d'audit de sécurité :** [À COMPLÉTER, ex. 12 mois] ; ces journaux sont **inaltérables** (append-only).
- **Codes OTP :** durée de vie très courte, invalidés après usage/expiration.

## 5. Avec qui partageons-nous les données (sous-traitants) ?

Nous ne vendons aucune donnée. Nous recourons à des sous-traitants strictement nécessaires au fonctionnement du Service. Un accord de traitement des données (DPA) doit être conclu avec chacun.

| Sous-traitant | Rôle | Données concernées | À prévoir |
|---|---|---|---|
| Fournisseurs de modèle IA — OpenAI et Anthropic (Claude) ; option d'auto-hébergement (Ollama) | Génération de synthèses/classifications/brouillons | Contexte transmis au moment de la requête | DPA ; option d'hébergement local (Ollama) pour les données sensibles |
| ePaieLink | Paiement (Mobile Money / carte) | Redirection de paiement ; **aucune donnée de carte n'est stockée par l'Application** | DPA ; conformité de l'agrégateur |
| Google (OAuth / Gmail API) | Création de brouillons e-mail (module Secrétariat) | Jetons OAuth, contenu des brouillons | Écran de consentement, vérification Google |
| Fournisseur SMTP — [À COMPLÉTER] | Envoi d'e-mails (OTP, notifications) | Adresse e-mail, contenu des notifications | Envoi chiffré (TLS) |
| Fournisseur WhatsApp / messagerie — [À COMPLÉTER, si activé] | Notifications | Numéro de téléphone, contenu de la notification | DPA |
| Amazon Web Services (AWS) — région Europe (Paris) `eu-west-3` ; EC2, RDS PostgreSQL, S3, CloudFront | Hébergement des serveurs et de la base | L'ensemble des données | DPA AWS, données hébergées dans l'UE |

### Transferts hors de votre pays / hors UE
Les données sont hébergées dans l'Union européenne (région AWS Europe / Paris). Toutefois, certains sous-traitants sont établis aux États-Unis : Amazon Web Services, Inc. (société mère de l'hébergeur) et les fournisseurs d'IA (OpenAI, Anthropic) lorsque le module IA est activé. Ces transferts doivent être encadrés par des garanties appropriées (clauses contractuelles types, DPA). [À COMPLÉTER : confirmer les garanties contractuelles avec chaque fournisseur.]

## 6. Comment protégeons-nous les données ?

- Chiffrement en transit (HTTPS/TLS), terminaison TLS assurée via Amazon CloudFront.
- Mots de passe hachés (bcrypt) ; jetons de rafraîchissement hachés en base ; jeton d'accès en mémoire seule.
- Cloisonnement multi-organisations appliqué au niveau applicatif (filtrage systématique par organisation).
- Clés d'API des fournisseurs IA chiffrées au repos.
- Journal d'audit inaltérable des opérations sensibles.
- Limitation de débit contre les attaques par force brute.

Aucun système n'est infaillible ; nous nous efforçons de maintenir des mesures conformes à l'état de l'art.

## 7. Vos droits

Selon la réglementation applicable (RGPD notamment), vous disposez des droits d'**accès**, de **rectification**, d'**effacement**, de **limitation**, d'**opposition** et de **portabilité** de vos données personnelles, ainsi que du droit de retirer votre consentement.

- **Export de vos données :** vous pouvez demander une copie de vos données personnelles (fonction d'export disponible dans l'Application ou sur demande à kidikala@gmail.com).
- **Suppression de votre compte :** vous pouvez demander la suppression de votre compte. Pour respecter les obligations comptables/légales, les écritures financières que la loi impose de conserver ne sont pas supprimées mais **dissociées de votre identité (anonymisées)**.
- **Réclamation :** vous pouvez saisir l'autorité de contrôle compétente [À COMPLÉTER : autorité applicable].

Pour exercer ces droits : kidikala@gmail.com. Nous répondons dans les délais légaux [ex. 1 mois].

## 8. Intelligence artificielle — transparence

Certains contenus (synthèses, classifications, brouillons de courrier/PV) sont **générés par une intelligence artificielle**. Ils sont fournis à titre d'assistance, **doivent être relus et validés par un humain** avant toute utilisation ou envoi, et peuvent comporter des erreurs. Aucune action sensible (envoi d'e-mail, opération financière) n'est exécutée automatiquement par l'IA.

## 9. Mineurs

Le Service est destiné à un usage professionnel et n'est pas destiné aux personnes de moins de [À COMPLÉTER : 18] ans. Nous ne collectons pas sciemment de données de mineurs.

## 10. Modifications

Nous pouvons mettre à jour cette politique. Toute modification substantielle sera notifiée via l'Application ou par e-mail. La date de dernière mise à jour figure en tête de document.

## 11. Contact

Pour toute question relative à la présente politique ou à vos données :
- **E-mail :** kidikala@gmail.com
- **Adresse :** Eclectic IT Services, N°137, Avenue Mbomu, Kinshasa, République Démocratique du Congo
- **Téléphone :** +243 818 080 946
- **Site web :** https://onec-rdc.org
