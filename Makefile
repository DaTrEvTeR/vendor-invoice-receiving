.PHONY: run up migrate seed reset test test-coverage outcomes

COMPOSE_RUN = docker compose run --rm backend

# One command from a clean clone: build, migrate, load data/, then start the app.
run: .env
	docker compose build
	$(MAKE) migrate seed
	docker compose up

# Build and start the containers (shortcut for docker compose up --build).
up: .env
	docker compose up --build

# Apply database migrations. An explicit step, never run on container start-up.
migrate: .env
	$(COMPOSE_RUN) python manage.py migrate --noinput

# Load the reference data from data/ into an empty database (no-op if already loaded).
seed: .env
	$(COMPOSE_RUN) python manage.py seed_data

# Wipe the dev database (invoices, stock movements, PO progress) and reload data/.
reset: .env
	$(COMPOSE_RUN) python manage.py seed_data --reset

# Run the backend test suite inside the container.
test: .env
	$(COMPOSE_RUN) pytest

# Run the backend test suite inside the container with coverage.
test-coverage: .env
	$(COMPOSE_RUN) pytest --cov=receiving --cov=config

# Regenerate results/outcomes.json on a fresh, separate database.
outcomes: .env
	$(COMPOSE_RUN) python manage.py build_outcomes

# Create the local env file from the template on first use.
.env:
	cp .env.example .env
