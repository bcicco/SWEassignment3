# YOWD Delivery Management System

## Event pipeline

```
DynamoDB ─stream─> yowd-stream-publisher (Lambda) ─PutEvents─> EventBridge ─rules─> handler Lambdas
```

Only `HistoryEvent` inserts (`sk` starting `EVENT#`) are published, with `detail-type` set to the
event type. Each handler declares the events it accepts with `@handles(...)`, and that declaration
becomes its EventBridge rule. Handlers are registered in `src/swe/events/routes.py`.

## Running locally

Runs against LocalStack in Docker, which also runs each Lambda in its own container. It needs a
LocalStack auth token (the free Hobby tier works): copy `.env.example` to `.env` and fill in
`LOCALSTACK_AUTH_TOKEN`.

```sh
docker compose up -d                    # 1. LocalStack on :4566 (state is in memory; re-bootstrap after restarting)
uv run python -m swe.infra.bootstrap    # 2. build the Lambda zip and deploy everything (re-run to redeploy code)
uv run python scripts/demo.py           # 3. write a request, quote and acceptance
uv run python scripts/logs.py           # 4. see what each Lambda did
uv run pytest                           # tests, including the coding standard (no LocalStack needed)
uv run ruff format && uv run ruff check --fix   # format and fix code to the standard
uv run python scripts/dev_ui.py         # dev UI on http://127.0.0.1:8000 (add --memory to skip LocalStack)
```

