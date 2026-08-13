.PHONY: lint format typing

lint:
	uv run ruff check .
format:
	uv run ruff format --diff .
typing:
	uv run ty check .
