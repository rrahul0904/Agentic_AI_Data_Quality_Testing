# Development

Use Python 3.11 or 3.12. Create a virtual environment, activate it, install `.[dev]`, then run:

```bash
ruff check .
pytest -q
python -m compileall -q src
```

On macOS/Homebrew, system Python is externally managed. Use `python3 -m venv .venv` followed by `source .venv/bin/activate`; do not use `--break-system-packages`.

The API stores records in `ade.db` by default. Set `ADE_DATABASE_PATH=/absolute/path/to/control-plane.db` before starting Uvicorn to choose a persistent local database.

Cloud tests must use injected fakes by default. Add a separately selected integration test only when a non-production account and explicit credentials are available.
