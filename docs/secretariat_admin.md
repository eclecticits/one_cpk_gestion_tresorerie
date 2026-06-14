# Secretariat Admin

## Scope

Le module Secrétariat couvre cinq agents internes, un workflow centralisé d'approbation, une journalisation d'audit et une logique multi-tenant stricte.

## Rôles et permissions

Les rôles Secrétariat sont définis par une matrice centrale dans `backend/app/modules/secretariat/permissions.py`.

Rôles types:

- Administrateur Secrétariat
- Agent Courrier
- Agent Réunion
- Agent Agenda
- Agent Documents
- Validateur
- Auditeur

Règles de gouvernance:

- lecture n'autorise pas l'écriture
- génération IA n'autorise pas la validation
- validation n'autorise pas l'administration
- navigation n'autorise pas l'action sensible
- aucun rôle opérationnel n'obtient `secretariat.manage_oauth` ou `secretariat.manage_ai_settings`

## Matrice des rôles

La matrice officielle est centralisée côté backend. Les seeds et les tests doivent s'y référer comme source de vérité.

Points de contrôle:

- `menu_secretariat` ouvre la navigation
- `secretariat.view` ouvre la lecture du tableau de bord et des vues non sensibles
- `secretariat.use_agent_*` ouvre l'usage agent, pas l'administration
- `secretariat.approve_action` et `secretariat.reject_action` restent réservés au workflow centralisé
- `secretariat.create_gmail_draft` reste limité à l'Agent Courrier

## Workflow d'approbation

Les actions sensibles passent par `secretariat_approvals`.

Flux attendu:

1. création de la demande
2. validation ou rejet humain
3. exécution du side effect par `approval_service`

Règles:

- aucun chemin direct ne doit approuver un PV, une synthèse ou un brouillon Gmail
- `approval_service` reste le seul endroit où les effets de bord métier sont appliqués

## OAuth Gmail

Le module utilise uniquement:

- `gmail.readonly`
- `gmail.compose`

Règles:

- aucun envoi automatique
- aucun `gmail.send`
- tokens chiffrés avant stockage
- tokens jamais retournés au frontend
- déconnexion et révocation propres
- scope manquant => reconnexion explicite

## Audit logs

Les audit logs servent à tracer:

- les actions
- les identifiants
- les statuts
- les compteurs
- les tailles
- les liens de cible

Ils ne doivent jamais stocker:

- contenu complet des mails
- contenu complet des PV
- notes complètes
- `extracted_text` complet
- `summary_text` complet
- `synthesis_text` complet
- `file_path`
- tokens
- secrets
- réponses IA brutes sensibles

## IA

Les prompts IA sont administratifs, séparés par usage et soumis à validation humaine.

Règles:

- pas d'invention
- informations manquantes signalées
- contexte minimisé
- texte limité avant envoi
- sortie IA = aide à la lecture, pas décision finale

## Documents

Le sous-module Documents reste interne.

Règles:

- `file_path` n'est pas exposé dans les DTO publics
- `file_path` n'est pas accepté par l'API publique
- aucun téléchargement public non sécurisé
- aucun partage externe
- aucune intégration Drive / SharePoint / Dropbox

## Sécurité et limites

Actions interdites:

- envoi Gmail automatique
- `gmail.send`
- Google Calendar
- Google Meet
- partage documentaire externe
- exposition de chemin local

## Monitoring

À surveiller en production:

- erreurs backend Secrétariat
- échecs OAuth
- échecs IA
- actions bloquées par permission
- validations rejetées
- validations en attente trop longtemps
- tâches Agenda en retard
- anomalies d'audit
- accès cross-tenant
- échecs de création de brouillon Gmail

