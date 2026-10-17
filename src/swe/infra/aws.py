import os

import boto3

from swe.infra.config import ENDPOINT_URL, REGION

# emulators accept any credentials; real AWS uses the normal credential chain
if ENDPOINT_URL:
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")


def client(service: str):
    return boto3.client(service, endpoint_url = ENDPOINT_URL or None, region_name = REGION)
