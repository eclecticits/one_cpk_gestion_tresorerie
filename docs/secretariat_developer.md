# Secretariat Developer Guide

## Architecture

Le module Secrétariat est organisé dans `backend/app/modules/secretariat/` avec:

- `routes.py` pour les endpoints FastAPI
- `schemas.py` pour les schémas Pydantic
- `models.py` pour les tables SQLAlchemy
- `services/` pour la logique métier
- `prompts/` pour les prompts IA
- `permissions.py` pour le catalogue central de permissions et rôles

Le frontend Secrétariat est regroupé dans `frontend/src/pages/SecretariatPage.tsx` et `frontend/src/api/secretariat.ts`.

## Services principaux

- `approval_service.py`: workflow centralisé
- `audit.py`: audit logs Secrétariat
- `oauth_service.py`: OAuth Google
- `gmail_service.py`: lecture et brouillons Gmail
- `ai_service.py`: appels IA
- `documents_agent.py`: documents internes
- `reunion_agent.py`: réunions
- `agenda_agent.py`: agenda interne
- `agent_manager.py`: tableau de bord consolidé

## Permissions

La source de vérité est `backend/app/modules/secretariat/permissions.py`.

Règles:

- ne pas recopier les permissions en dur ailleurs
- les seeds doivent utiliser le catalogue central
- les rôles types doivent être alignés sur la matrice centrale
- `secretariat.view` est une permission de lecture, pas d'action
- `secretariat.use_agent_*` ouvre l'usage d'un agent, pas l'administration

## Multi-tenant

Règles:

- chaque requête Secrétariat filtre par `organisation_id`
- les enfants d'objet doivent rester dans le même tenant
- les approvals sont tenant-scopées
- les logs d'audit sont tenant-scopés

## Audit logs

Règles:

- journaliser l'action, les identifiants et les compteurs
- ne pas journaliser le contenu complet des objets métier
- ne pas journaliser tokens, secrets, réponses IA brutes ou chemins internes
- utiliser un sanitiseur central avant persistance

## IA

Règles:

- prompts séparés par usage
- contexte minimisé
- texte borné avant envoi
- validation humaine obligatoire pour les sorties sensibles
- réponse IA traitée comme suggestion

## Approvals

Règles:

- aucun workflow parallèle
- aucun contournement de `approval_service`
- l'effet métier est appliqué dans `approval_service`
- les routes publiques ne doivent pas modifier directement les états sensibles

## Documents

Règles:

- pas de `file_path` dans les DTO publics
- pas d'endpoint public de téléchargement
- pas de partage externe
- pas d'URL brute de fichier renvoyée au frontend

## OAuth Gmail

Règles:

- scopes autorisés: `gmail.readonly`, `gmail.compose`
- pas de `gmail.send`
- tokens chiffrés au repos
- tokens jamais renvoyés au frontend
- déconnexion propre
- reconnexion si scope requis manquant

## Tests

La suite de référence utilise PostgreSQL réel avec `TEST_DATABASE_URL`.

Commandes de validation:

```bash
docker compose exec -T backend env TEST_DATABASE_URL='postgresql+asyncpg://christian:kncd@db:5432/onec_tresorerie_test' python -m pytest -q tests/test_secretariat_module.py -rs
docker compose exec -T backend env TEST_DATABASE_URL='postgresql+asyncpg://christian:kncd@db:5432/onec_tresorerie_test' python -m pytest -q -rs
docker compose exec -T backend python -m alembic heads
npm run build
```

## Commandes utiles

- `python -m compileall backend/app/modules/secretariat`
- `python -m pytest -q backend/tests/test_secretariat_module.py`
- `python -m pytest -q`

## Current warnings to monitor

These warnings are currently expected and come from dependencies or broad project-wide compatibility choices:

- `passlib` / `crypt`: dependency warning under Python 3.12; monitor until the password stack is upgraded.
- `reportlab` / `ast.NameConstant`: dependency warning; monitor the report generation stack.
- `pydantic` / `json_encoders`: project-level compatibility warning from legacy schema declarations; safe to keep for now, but plan a broader Pydantic cleanup later.
- `pydantic` / class `Config`: project-level compatibility warning from legacy schema declarations; safe to keep for now, but plan a broader Pydantic cleanup later.

Do not attempt a large Pydantic v3 migration inside the Secretariat hardening lot.
