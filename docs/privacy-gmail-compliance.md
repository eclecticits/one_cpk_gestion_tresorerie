# Confidentialité et conformité Gmail OAuth

Ce projet utilise les scopes Google restreints `gmail.readonly` et `gmail.compose`.
Avant toute publication OAuth externe, l'application doit disposer au minimum de :

- une politique de confidentialité publique (`PRIVACY_POLICY_URL`) ;
- des conditions d'utilisation publiques (`TERMS_OF_SERVICE_URL`) ;
- une procédure publique de suppression de compte et des données (`ACCOUNT_DELETION_URL`) ;
- un écran de consentement Google cohérent avec les usages réels ;
- une vérification Google OAuth, et très probablement un audit CASA si l'application traite des données Gmail en production.

## Données Gmail

L'accès Gmail est limité au module Secrétariat. Les messages sont lus pour afficher les courriers et générer des résumés ou brouillons internes. Le scope `gmail.compose` ne doit servir qu'à créer des brouillons après validation humaine ; aucun envoi automatique ne doit être activé.

## Suppression

Une demande de suppression doit supprimer ou anonymiser les comptes utilisateurs, connexions OAuth, tokens Gmail, brouillons, journaux applicatifs non obligatoires et fichiers rattachés, sauf obligation légale de conservation.

## Configuration

En production, le backend refuse de démarrer si Google OAuth est configuré sans les trois variables d'URL légales. Cela ne remplace pas la vérification Google ni l'audit CASA.
