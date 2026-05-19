.PHONY: help dev test lint typecheck loadtest gen-api docker-up docker-down

help:
	@echo "Targets:"
	@echo "  dev         start backend (auto-reload) and frontend dev server"
	@echo "  test        run pytest + vitest"
	@echo "  lint        ruff + next lint"
	@echo "  typecheck   tsc --noEmit"
	@echo "  loadtest    run k6 against local backend (requires k6 in PATH)"
	@echo "  gen-api     regenerate frontend/lib/openapi.d.ts from live /openapi.json"
	@echo "  docker-up   docker compose up --build -d"
	@echo "  docker-down docker compose down"

dev:
	@( cd backend/.. && uvicorn backend.main:app --reload --port 8000 ) & \
	 ( cd frontend && npm run dev ) ; \
	 wait

test:
	pytest -q
	cd frontend && npm test

lint:
	ruff check .
	cd frontend && npx next lint

typecheck:
	cd frontend && npx tsc --noEmit

loadtest:
	k6 run loadtest/k6.js

gen-api:
	cd frontend && npm run gen:api

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down
