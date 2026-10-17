import os

# everything runs on LocalStack. Inside its Lambda containers LocalStack sets
# AWS_ENDPOINT_URL; from your machine it's on localhost
ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
REGION = "ap-southeast-2"

TABLE_NAME = os.environ.get("TABLE_NAME", "yowd")
EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "yowd")
EVENT_SOURCE = "yowd.delivery"
