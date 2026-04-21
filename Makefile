.PHONY: test run-local push live-scan

test:
	pytest tests/ -v

run-local:
	python src/main.py

live-scan:
	python scripts/live_scan.py

push:
	apify push
