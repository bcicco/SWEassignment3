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
uv run python scripts/seed_users.py     #    create the accounts below (re-run after restarting LocalStack)
uv run python scripts/demo.py           # 3. write a request, quote and acceptance
uv run python scripts/logs.py           # 4. see what each Lambda did
uv run pytest                           # tests, including the coding standard (no LocalStack needed)
uv run ruff format && uv run ruff check --fix   # format and fix code to the standard
uv run uvicorn swe.api:create_app --factory --reload --port 8001   # HTTP API, docs at /docs
uv run python scripts/dev_ui.py         # dev UI on :8000 (add --memory to skip LocalStack)
```


## Web client

A React app (Vite + TypeScript) in `web/`, talking to the HTTP API on :8001. There's no login:
the header picks which account you're acting as, sent in the `X-User-Id` header. The API looks
it up in the UserDirectory, so the id must be an existing, active account and its role comes
from the account: `cust-1`, `cust-2` (customers), `staff-1` (office staff), `owner-1`
(business owner), `driver-1` (delivery staff), from `scripts/seed_users.py`.

```sh
cd web && npm install    # once
npm run dev              # http://localhost:5173 (needs the API running)
```

Set `VITE_API_URL` to point it at the API elsewhere.
