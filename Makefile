.PHONY: health migrate migrate-status

health:
	./scripts/health.sh

# --- Migrations Alembic sur la base de développement ---------------------------
#
# On passe par `backend-tests` et non par `backend` : l'image du service backend
# embarque une copie figée des migrations, si bien qu'un `alembic upgrade head`
# lancé depuis ce conteneur ignore en silence les fichiers ajoutés depuis le
# dernier build — il annonce « déjà à jour » sans rien migrer. Le service
# backend-tests, lui, monte ./backend/alembic en direct.
#
# DATABASE_URL est forcée vers la base de développement : sans elle, le conteneur
# de tests viserait la base `_test`, que le harnais recrée à chaque session.
#
# Les variables sont lues dans .env sans le sourcer : il contient des valeurs
# (regex CORS) que le shell n'interprète pas correctement.

ENV_FILE ?= .env
REV ?= head

pg_var = $(shell grep -E '^$(1)=' $(ENV_FILE) | cut -d= -f2-)
DEV_DATABASE_URL = postgresql+asyncpg://$(call pg_var,POSTGRES_USER):$(call pg_var,POSTGRES_PASSWORD)@db:5432/$(call pg_var,POSTGRES_DB)

# Applique les migrations en attente. `make migrate REV=<revision>` s'arrête à
# une révision précise plutôt que d'aller jusqu'à la tête.
migrate:
	@docker compose --profile test run --rm \
		-e DATABASE_URL="$(DEV_DATABASE_URL)" \
		backend-tests alembic upgrade $(REV)

# Révision actuelle de la base, et têtes disponibles dans le code.
migrate-status:
	@docker compose --profile test run --rm \
		-e DATABASE_URL="$(DEV_DATABASE_URL)" \
		backend-tests sh -c 'alembic current && alembic heads'
