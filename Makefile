.PHONY: setup backend frontend test build demo

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r backend/requirements-dev.txt
	cd frontend && npm install

backend:
	cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && ../.venv/bin/python -m pytest -q
	cd frontend && npm run typecheck

build:
	cd frontend && npm run build

demo:
	cd backend && ../.venv/bin/python -m app.demo ../demo.mp4
