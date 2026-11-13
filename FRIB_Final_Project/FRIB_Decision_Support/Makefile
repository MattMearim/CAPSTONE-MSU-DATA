.PHONY: install test start api dashboard demo docker
install:
	python -m pip install -e ".[dev,ui]"
test:
	python -m pytest -q
start:
	python start.py
api:
	uvicorn frib_ds.api.main:app --reload --port 8000
dashboard:
	streamlit run src/frib_ds/dashboard/app.py
demo:
	python scripts/seed_demo.py
docker:
	docker compose up --build
