# ONEC/CPK - Système de Gestion de Trésorerie et Caisse

Application web complète de gestion de trésorerie pour le Conseil Provincial de Kinshasa (ONEC/CPK).

## Fonctionnalités principales

### 1. Gestion des encaissements
- Enregistrement des paiements (formations, livres, services)
- Identification automatique des experts-comptables par numéro d'ordre
- Génération automatique de reçus avec numérotation séquentielle
- Support de plusieurs modes de paiement (Cash, Mobile Money, Virement)

### 2. Gestion des réquisitions de fonds
- Création de demandes de fonds avec lignes de détail
- Workflow d'approbation à plusieurs niveaux :
  - Validation par la trésorerie
  - Approbation par le rapporteur
- Traçabilité complète (qui a fait quoi, quand)
- Gestion des rubriques de dépenses

### 3. Sorties de fonds
- Enregistrement des paiements effectués
- Lien avec les réquisitions approuvées
- Suivi des références de paiement

### 4. Rapports et analyses
- Synthèse des encaissements et sorties par période
- Analyses par type d'opération
- Export des données en CSV pour Excel

### 5. Gestion des experts-comptables
- Import massif depuis fichier Excel
- Recherche par numéro d'ordre ou nom
- Gestion des informations de contact

### 6. Administration
- Gestion des utilisateurs avec rôles
- Configuration des rubriques de dépenses
- Contrôle d'accès basé sur les rôles

## Rôles utilisateurs

- **Réception** : Enregistrement des encaissements
- **Trésorerie** : Validation des réquisitions, gestion des sorties de fonds
- **Rapporteur** : Approbation finale des réquisitions
- **Secrétariat** : Création des réquisitions de fonds
- **Comptabilité** : Consultation et export des données
- **Administrateur** : Gestion complète du système

## Technologies utilisées

- **Frontend** : React 18 + TypeScript + Vite
- **Backend** : FastAPI + PostgreSQL
- **Authentification** : JWT + refresh tokens (FastAPI)
- **Styling** : CSS Modules
- **Export** : XLSX pour Excel

## Installation et démarrage

```bash
# Installer les dépendances
npm install

# Lancer en développement
npm run dev

# Construire pour production
npm run build
```

## Configuration

Variables d'environnement (Vite) :
- `VITE_API_BASE_URL` : URL du backend FastAPI (ex: `http://localhost:8000/api/v1`)

## API FastAPI (endpoints utilisés)

L'application frontend consomme l'API FastAPI sous `/api/v1`. Principaux endpoints :
- `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`
- `GET /experts-comptables`, `POST /experts-comptables`, `POST /experts-comptables/import`
- `GET /requisitions`, `POST /requisitions`, `POST /requisitions/{id}/validate`, `POST /requisitions/{id}/reject`
- `GET /remboursements-transport`, `POST /remboursements-transport`
- `GET /requisition-approvers`

## Import Excel Experts-Comptables (format attendu)

Colonnes Excel attendues (ligne d'entête) :
- `N° d’ordre`
- `Dénomination`
- `Raison sociale`
- `N° de téléphone` (format texte recommandé)
- `E-mail`
- `Associé gérant`

Règles de normalisation :
- Téléphone : chaîne texte (ex : `(+243)829000113`, `+243829000113`, `0829000113`, `829000113`).
- Email : nettoyé en minuscules, invalide => ignoré (ligne importée quand même).

## Première utilisation

1. Créez un compte administrateur via la page Settings
2. Importez la liste des experts-comptables depuis un fichier Excel
3. Configurez les rubriques de dépenses si nécessaire
4. Créez les utilisateurs pour chaque rôle

## Structure de la base de données

- **users** : Utilisateurs du système
- **experts_comptables** : Référentiel des EC
- **encaissements** : Recettes enregistrées
- **requisitions** : Demandes de fonds
- **lignes_requisition** : Détails des réquisitions
- **sorties_fonds** : Paiements effectués
- **rubriques** : Catégories de dépenses

## Sécurité

- Authentification requise pour tous les accès
- Contrôle d'accès basé sur les rôles
- Traçabilité complète de toutes les opérations

## Support

Pour toute question ou assistance, contactez l'administrateur système.
