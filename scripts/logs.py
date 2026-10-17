# prints each Lambda's log output from the emulator's CloudWatch Logs
from swe.events.routes import ROUTES, function_name
from swe.infra.aws import client
from swe.infra.bootstrap import STREAM_FUNCTION

RUNTIME_LINES = ("START", "END", "REPORT", "INIT")


def main() -> None:
    logs = client("logs")
    for name in [STREAM_FUNCTION, *map(function_name, ROUTES)]:
        print(f"--- {name}")
        try:
            events = logs.filter_log_events(logGroupName = f"/aws/lambda/{name}")["events"]
        except logs.exceptions.ResourceNotFoundException:
            continue # not invoked yet
        for event in events:
            if not event["message"].startswith(RUNTIME_LINES):
                print("  ", event["message"].strip())


if __name__ == "__main__":
    main()
