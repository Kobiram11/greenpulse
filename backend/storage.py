import json
from decimal import Decimal


class Store:
    def __init__(self, region, name):
        import boto3
        from botocore.config import Config
        self.table = boto3.resource("dynamodb", region_name=region,
            config=Config(connect_timeout=5, read_timeout=10,
                          retries={"max_attempts": 3, "mode": "standard"})).Table(name)

    def put(self, device, event_id, kind, timestamp, payload):
        # DynamoDB resource rejects Python floats; JSON->Decimal also rejects NaN.
        item = json.loads(json.dumps({"pk": f"DEVICE#{device}",
            "sk": f"{kind}#{timestamp:010d}#{event_id}", "kind": kind,
            "received_ts": timestamp, "payload": payload}, allow_nan=False), parse_float=Decimal)
        self.table.put_item(Item=item)
