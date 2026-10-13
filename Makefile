.PHONY: dev infra api web migrate db-check dq-report backtest worker beat test lint clean

## Full local stack in Docker (db + redis + api + web)
dev:
	docker compose up

## Infrastructure only (db + redis); run api and web natively for fast reload
infra:
	docker compose up -d db redis

api:
	cd apps/api && uvicorn app.main:app --reload --port 8000

web:
	cd apps/web && npm run dev

migrate:
	cd apps/api && alembic upgrade head

db-check:
	cd apps/api && alembic check

dq-report:
	cd apps/api && python -m app.dq

backtest:
	cd apps/api && python -m app.scoring.backtest

worker:
	cd apps/api && celery -A app.worker worker -Q ingest,compute,notify -l info

beat:
	cd apps/api && celery -A app.worker beat -l info

dq-report:
	cd apps/api && python -m app.dq

backtest:
	cd apps/api && python -m app.scoring.backtest

worker:
	cd apps/api && celery -A app.worker worker -Q ingest,compute,notify -l info

beat:
	cd apps/api && celery -A app.worker beat -l info

test:
	cd apps/api && python -m pytest -q

lint:
	cd apps/api && ruff check . && ruff format --check .

clean:
	docker compose down -v
