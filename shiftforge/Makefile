.PHONY: install test web demo
install:
	python -m pip install -e '.[dev]'
test:
	pytest -q
web:
	uvicorn shiftforge.api:app --reload --port 8080
demo:
	shiftforge convert examples/revinate --hints examples/hints.json --output /tmp/revinate-redshift --approve
