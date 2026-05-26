.PHONY: help install dev migrate makemigrations shell test lint format typecheck celery-worker celery-beat docker-up docker-down

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies with uv
	uv sync --all-extras

dev: ## Run development server
	uv run python manage.py runserver

migrate: ## Apply migrations
	uv run python manage.py migrate

makemigrations: ## Create migrations
	uv run python manage.py makemigrations

shell: ## Django shell_plus
	uv run python manage.py shell

createsuperuser: ## Create superuser
	uv run python manage.py createsuperuser

test: ## Run tests
	uv run pytest

test-cov: ## Run tests with coverage
	uv run pytest --cov --cov-report=html

lint: ## Lint with ruff
	uv run ruff check .

format: ## Format with black + ruff
	uv run black .
	uv run ruff check --fix .

typecheck: ## Type check with mypy
	uv run mypy apps/ config/

celery-worker: ## Start Celery worker
	uv run celery -A config.celery worker -l info --concurrency=4

celery-beat: ## Start Celery beat scheduler
	uv run celery -A config.celery beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

docker-up: ## Start full Docker stack
	docker compose up -d

docker-down: ## Stop Docker stack
	docker compose down

docker-logs: ## Tail Docker logs
	docker compose logs -f

collectstatic: ## Collect static files
	uv run python manage.py collectstatic --noinput
