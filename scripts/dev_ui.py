# a throwaway browser UI for poking at the commands: log requests, issue quotes and respond
# to them, and watch each request's quotes and history. Not for production; it scans the table.
#
#   uv run python scripts/dev_ui.py            # against LocalStack
#   uv run python scripts/dev_ui.py --memory   # in-memory DynamoDB via moto, no Docker needed
import argparse
import json
import os
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from swe.app import (
    AcceptQuote,
    CancelRequest,
    DeliveryManagementSystem,
    ForbiddenError,
    IssueQuote,
    LogRequest,
    RejectQuote,
    RequestQuoteRevision,
)
from swe.infra.config import TABLE_NAME
from swe.repo import ConflictError, NotFoundError, Repository
from swe.repo.schemas import event_schema_for
from swe.repo.schemas.request import DELIVERY_REQUEST, QUOTE

PAGE = Path(__file__).with_name("dev_ui.html")

COMMANDS = {
    "log_request": LogRequest,
    "issue_quote": IssueQuote,
    "accept_quote": AcceptQuote,
    "reject_quote": RejectQuote,
    "request_quote_revision": RequestQuoteRevision,
    "cancel_request": CancelRequest,
}

ERRORS = [(ForbiddenError, 403), (NotFoundError, 404), (ConflictError, 409), (ValueError, 400)] # ValueError covers DomainError and pydantic


# every request with its quotes and history, newest first
def list_requests(dynamodb) -> list[dict]:
    pages = dynamodb.get_paginator("scan").paginate(
        TableName = TABLE_NAME,
        FilterExpression = "begins_with(pk, :request) AND sk = :metadata",
        ExpressionAttributeValues = {":request": {"S": "REQUEST#"}, ":metadata": {"S": "METADATA"}},
    )
    result = []
    for item in (i for page in pages for i in page["Items"]):
        partition = dynamodb.query(
            TableName = TABLE_NAME,
            KeyConditionExpression = "pk = :pk",
            ExpressionAttributeValues = {":pk": item["pk"]},
            ConsistentRead = True,
        )["Items"]
        quotes = [QUOTE.from_item(i) for i in partition if i["sk"]["S"].startswith("QUOTE#")]
        events = [event_schema_for(i).from_item(i) for i in partition if i["sk"]["S"].startswith("EVENT#")]
        result.append({
            "request": DELIVERY_REQUEST.from_item(item).model_dump(mode = "json"),
            "quotes": [q.model_dump(mode = "json") for q in sorted(quotes, key = lambda q: q.time_of_issue, reverse = True)],
            "events": [e.model_dump(mode = "json") for e in events],
        })
    return sorted(result, key = lambda r: r["request"]["created_at"], reverse = True)


def make_handler(dms: DeliveryManagementSystem, dynamodb):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data).encode())

        def do_GET(self) -> None:
            if self.path == "/":
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/requests":
                self._json(200, list_requests(dynamodb))
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            name = self.path.removeprefix("/api/")
            if name not in COMMANDS:
                return self._json(404, {"error": f"unknown command {name!r}"})
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or "{}")
            try:
                result = getattr(dms, name)(COMMANDS[name].model_validate(body))
            except Exception as e:
                status = next((s for cls, s in ERRORS if isinstance(e, cls)), 500)
                return self._json(status, {"error": f"{type(e).__name__}: {e}"})
            self._json(200, result.model_dump(mode = "json"))

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory", action = "store_true", help = "use an in-memory DynamoDB (moto) instead of LocalStack")
    parser.add_argument("--port", type = int, default = 8000)
    args = parser.parse_args()

    if args.memory:
        from moto import mock_aws
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
        context = mock_aws()
    else:
        context = nullcontext()

    with context:
        import boto3
        from swe.infra.aws import client
        from swe.infra.bootstrap import create_table
        from swe.infra.config import REGION

        dynamodb = boto3.client("dynamodb", region_name = REGION) if args.memory else client("dynamodb")
        if args.memory:
            create_table(dynamodb)
        dms = DeliveryManagementSystem(Repository(dynamodb))
        server = HTTPServer(("127.0.0.1", args.port), make_handler(dms, dynamodb))
        print(f"dev UI on http://127.0.0.1:{args.port} ({'in-memory' if args.memory else 'LocalStack'})")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
