FROM python:3.12-slim as base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential libpq-dev \
  && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements/prod.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r prod.txt

# Copy app
COPY . .

# Collectstatic
RUN python manage.py collectstatic --noinput --settings=config.settings.prod || true

# ── Production service ────────────────────────────────────────────────────────
FROM python:3.12-slim as production

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
  libpq5 \
  && rm -rf /var/lib/apt/lists/*

COPY --from=base /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=base /app /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=config.settings.prod

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
