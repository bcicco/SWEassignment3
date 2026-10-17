import boto3
import pytest
from moto import mock_aws

from swe.infra.bootstrap import create_table
from swe.repo import Repository


# an in-memory DynamoDB with the real table
@pytest.fixture
def dynamodb(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-southeast-2")
        create_table(client)
        yield client


@pytest.fixture
def repo(dynamodb):
    return Repository(dynamodb)
