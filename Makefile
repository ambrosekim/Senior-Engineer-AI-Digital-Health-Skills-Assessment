.PHONY: test-backend-unit test-backend-integration test-frontend test-backend

BACKEND_VENV := backend/.venv

$(BACKEND_VENV):
	python3 -m venv $(BACKEND_VENV)

# Fast, no external services: mocks Ollama and the pgvector layer.
test-backend-unit: $(BACKEND_VENV)
	$(BACKEND_VENV)/bin/pip install -q -r backend/requirements-test.txt
	cd backend && ../$(BACKEND_VENV)/bin/python -m pytest tests/unit -m unit

# Requires `docker compose up -d relational_db ollama` (or the full stack) first.
test-backend-integration: $(BACKEND_VENV)
	$(BACKEND_VENV)/bin/pip install -q -r backend/requirements-test.txt
	cd backend && ../$(BACKEND_VENV)/bin/python -m pytest tests/integration -m integration

test-backend: test-backend-unit test-backend-integration

test-frontend:
	cd frontend && npm install && npm test
