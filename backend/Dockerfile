FROM python:3.13.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Unprivileged user for hosts where mounted files look root-owned (Docker Desktop).
RUN useradd --uid 1000 --create-home app

COPY --chown=app . .

# The container starts as root only to switch to the owner of the mounted project files
# (see docker-entrypoint.sh), so the SQLite database (/app/db.sqlite3, i.e. backend/db.sqlite3
# on the host) and results/outcomes.json stay owned by the developer on Linux and macOS alike.
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]

EXPOSE 8000

# Migrations and seeding are explicit steps (make migrate / make seed), never part of start-up.
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
