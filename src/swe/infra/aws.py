import boto3

from swe.infra.config import ENDPOINT_URL, REGION


# LocalStack accepts any credentials
def client(service: str):
    return boto3.client(
        service,
        endpoint_url=ENDPOINT_URL,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
