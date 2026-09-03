FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN addgroup --system app && adduser --system --ingroup app app \
    && chmod +x /app/entrypoint.sh \
    && chown -R app:app /app

# ─── Image d'exécution des tests ─────────────────────────────────────────────
# Les dépendances de test sont installées ICI, aux versions épinglées de
# requirements-dev.txt, plutôt qu'à la main dans un conteneur en marche : un
# `pip install` fait après coup disparaît au premier redémarrage, et rien ne
# garantit qu'il pose les versions attendues. pytest-asyncio en particulier
# n'est pas interchangeable — une version trop ancienne ignore
# `asyncio_default_test_loop_scope` et met tous les teardowns en erreur.
#
# Cette étape est placée AVANT l'étape applicative, et non après : la DERNIÈRE
# étape d'un Dockerfile en est la cible par défaut. En la mettant ici, tout
# `build: ./backend` sans `target` — le backend de développement comme celui de
# docker-compose.prod.yml — continue de produire l'image applicative, sans
# pytest ni httpx de test embarqués.
FROM base AS tests

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

# `pytest` (le script) n'ajoute pas le repertoire courant a sys.path, la ou
# `python -m pytest` le fait. Sans ceci, conftest.py echoue des son import sur
# `ModuleNotFoundError: No module named 'app'`, et la difference ne se voit
# qu'a l'execution. On fixe le chemin dans l'image : les deux invocations
# marchent alors, quelle que soit celle que l'on tape.
ENV PYTHONPATH=/app

USER app

# Pas d'entrypoint applicatif : la suite n'a ni migration à appliquer (le
# harnais reconstruit le schéma depuis les modèles) ni API à démarrer.
ENTRYPOINT []
CMD ["pytest", "-q"]

# ─── Image applicative (cible par défaut) ────────────────────────────────────
FROM base AS app

USER app

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "app.main:app", "--bind", "0.0.0.0:8000"]
