# deploys everything: table, bus, Lambdas, the stream trigger and one rule per route.
# Safe to re-run; re-running also redeploys the latest code.
import json

from swe.events.routes import ROUTES, function_name, handler_path
from swe.infra import package
from swe.infra.aws import client
from swe.infra.config import EVENT_BUS_NAME, EVENT_SOURCE, TABLE_NAME

ROLE_NAME = "yowd-lambda"
STREAM_FUNCTION = "yowd-stream-publisher"
RUNTIME = f"python{package.RUNTIME_PYTHON}"


def create_table(dynamodb) -> str:
    if TABLE_NAME not in dynamodb.list_tables()["TableNames"]:
        dynamodb.create_table(
            TableName = TABLE_NAME,
            AttributeDefinitions = [
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            KeySchema = [
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            BillingMode = "PAY_PER_REQUEST",
            StreamSpecification = {"StreamEnabled": True, "StreamViewType": "NEW_IMAGE"},
        )
        dynamodb.get_waiter("table_exists").wait(TableName = TABLE_NAME)
    return dynamodb.describe_table(TableName = TABLE_NAME)["Table"]["LatestStreamArn"]


def create_bus(events) -> None:
    if EVENT_BUS_NAME not in [b["Name"] for b in events.list_event_buses()["EventBuses"]]:
        events.create_event_bus(Name = EVENT_BUS_NAME)


# LocalStack doesn't enforce IAM, but real AWS needs these permissions
def create_role(iam) -> str:
    try:
        return iam.get_role(RoleName = ROLE_NAME)["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        pass
    arn = iam.create_role(
        RoleName = ROLE_NAME,
        AssumeRolePolicyDocument = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}],
        }),
    )["Role"]["Arn"]
    for policy in ["AWSLambdaBasicExecutionRole", "AWSLambdaDynamoDBExecutionRole"]:
        iam.attach_role_policy(RoleName = ROLE_NAME, PolicyArn = f"arn:aws:iam::aws:policy/service-role/{policy}")
    iam.put_role_policy(
        RoleName = ROLE_NAME,
        PolicyName = "put-events",
        PolicyDocument = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": "events:PutEvents", "Resource": "*"}],
        }),
    )
    return arn


def deploy_function(lambda_, name: str, handler: str, code: bytes, role_arn: str) -> str:
    config = dict(
        Runtime = RUNTIME,
        Handler = handler,
        Role = role_arn,
        Timeout = 30,
        MemorySize = 256,
        Environment = {"Variables": {"TABLE_NAME": TABLE_NAME, "EVENT_BUS_NAME": EVENT_BUS_NAME}},
    )
    try:
        lambda_.get_function(FunctionName = name)
    except lambda_.exceptions.ResourceNotFoundException:
        arn = lambda_.create_function(
            FunctionName = name, Code = {"ZipFile": code}, Architectures = ["arm64"], **config,
        )["FunctionArn"]
        lambda_.get_waiter("function_active_v2").wait(FunctionName = name)
        return arn
    lambda_.update_function_code(FunctionName = name, ZipFile = code, Architectures = ["arm64"])
    lambda_.get_waiter("function_updated_v2").wait(FunctionName = name)
    arn = lambda_.update_function_configuration(FunctionName = name, **config)["FunctionArn"]
    lambda_.get_waiter("function_updated_v2").wait(FunctionName = name)
    return arn


def connect_stream(lambda_, stream_arn: str) -> None:
    mappings = lambda_.list_event_source_mappings(FunctionName = STREAM_FUNCTION, EventSourceArn = stream_arn)
    if mappings["EventSourceMappings"]:
        return
    lambda_.create_event_source_mapping(
        FunctionName = STREAM_FUNCTION,
        EventSourceArn = stream_arn,
        StartingPosition = "LATEST",
        BatchSize = 10,
        # only history events reach the Lambda; to_event still checks
        FilterCriteria = {"Filters": [{"Pattern": json.dumps({
            "eventName": ["INSERT"],
            "dynamodb": {"NewImage": {"sk": {"S": [{"prefix": "EVENT#"}]}}},
        })}]},
    )


def create_route(events, lambda_, route: str, function_arn: str) -> None:
    name = function_name(route)
    pattern = {"source": [EVENT_SOURCE]}
    if ROUTES[route].event_types:
        pattern["detail-type"] = ROUTES[route].event_types
    rule_arn = events.put_rule(Name = name, EventBusName = EVENT_BUS_NAME, EventPattern = json.dumps(pattern))["RuleArn"]
    events.put_targets(Rule = name, EventBusName = EVENT_BUS_NAME, Targets = [{"Id": name, "Arn": function_arn}])
    try:
        lambda_.add_permission(
            FunctionName = name, StatementId = "eventbridge-invoke", Action = "lambda:InvokeFunction",
            Principal = "events.amazonaws.com", SourceArn = rule_arn,
        )
    except lambda_.exceptions.ResourceConflictException:
        pass # already granted


def main() -> None:
    lambda_, events = client("lambda"), client("events")
    stream_arn = create_table(client("dynamodb"))
    create_bus(events)
    role_arn = create_role(client("iam"))
    code = package.build()

    deploy_function(lambda_, STREAM_FUNCTION, "swe.events.stream_publisher.handler", code, role_arn)
    connect_stream(lambda_, stream_arn)
    for route in ROUTES:
        arn = deploy_function(lambda_, function_name(route), handler_path(route), code, role_arn)
        create_route(events, lambda_, route, arn)
    print(f"deployed {STREAM_FUNCTION} and routes {list(ROUTES)} on bus {EVENT_BUS_NAME}")


if __name__ == "__main__":
    main()
