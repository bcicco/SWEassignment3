import os

# Outside Lambda, default to the local emulator. Inside Lambda, use whatever the
# runtime provides: LocalStack sets AWS_ENDPOINT_URL, real AWS sets nothing.
# Set AWS_ENDPOINT_URL to empty to target real AWS from your machine.
_IN_LAMBDA = "AWS_LAMBDA_FUNCTION_NAME" in os.environ
ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL", None if _IN_LAMBDA else "http://localhost:4566")
REGION = os.environ.get("AWS_REGION", "ap-southeast-2")

TABLE_NAME = os.environ.get("TABLE_NAME", "yowd")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "yowd")
EVENT_SOURCE = "yowd.delivery"
