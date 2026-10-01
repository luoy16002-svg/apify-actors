# Testing

Offline tests use saved fixtures and make no network calls:

```sh
pip install -r requirements-dev.txt
python -m pytest -q
```

A small live run against the public sources, using local storage:

```sh
python -m src --input test-input.json
```

`sample-output.json` holds the rows from a real run of `test-input.json`.
