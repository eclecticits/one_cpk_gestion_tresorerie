# Secretariat User Guide

## Vue d'ensemble

Le module Secrétariat permet de travailler sur les courriers, les réunions, l'agenda, les documents et les validations centralisées.

## Agent Courrier

Ce que vous pouvez faire:

- consulter les mails Gmail autorisés
- préparer un projet de réponse
- enregistrer un brouillon interne
- demander la validation d'un brouillon
- créer un brouillon Gmail après approbation centralisée si le compte dispose du scope requis

Ce que vous ne pouvez pas faire:

- envoyer un mail directement depuis le module
- contourner la validation humaine

Messages fréquents:

- "Connexion Google non configurée"
- "Le scope gmail.compose est requis"
- "La validation directe est désactivée"

## Agent Réunion

Ce que vous pouvez faire:

- créer une réunion interne
- préparer l'ordre du jour
- créer un projet d'invitation administrative
- saisir des notes
- extraire des décisions
- extraire des tâches de suivi
- générer un projet de PV
- soumettre le PV à validation

Ce que vous ne pouvez pas faire:

- créer un Google Meet
- créer un événement Google Calendar
- valider un PV sans workflow centralisé

## Agent Agenda

Ce que vous pouvez faire:

- créer des échéances internes
- suivre les échéances du jour
- suivre les échéances de la semaine
- marquer une échéance terminée, annulée ou en retard
- gérer des rappels internes

Ce que vous ne pouvez pas faire:

- synchroniser avec Google Calendar
- envoyer des notifications externes

## Agent Documents

Ce que vous pouvez faire:

- enregistrer et classer un document interne
- consulter ses métadonnées
- résumer un document
- générer une fiche synthèse
- soumettre la synthèse à validation
- gérer les versions

Ce que vous ne pouvez pas faire:

- partager le document à l'extérieur
- télécharger le fichier via un lien public
- voir un chemin serveur interne

## Agent Manager

Ce que vous pouvez faire:

- consulter la synthèse des activités
- voir les validations en attente
- voir les recommandations
- créer des tâches de suivi

Ce que vous ne pouvez pas faire:

- approuver à la place du workflow centralisé si vous n'avez pas la permission
- exécuter automatiquement une action sensible à partir d'une recommandation

## Validations

Le module utilise un workflow centralisé pour:

- approuver les brouillons courrier
- approuver les PV de réunion
- approuver les fiches synthèse documents

Étapes:

1. l'utilisateur prépare le contenu
2. le système crée une demande d'approbation
3. un validateur approuve ou rejette
4. l'effet métier n'est appliqué qu'après décision

## Erreurs fréquentes

- accès refusé: permission manquante
- validation impossible: la demande a déjà été décidée
- brouillon Gmail impossible: scope absent ou validation non obtenue
- document archivé: modification ou génération bloquée
- élément multi-tenant introuvable: accès hors organisation

