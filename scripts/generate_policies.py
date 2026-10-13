"""Generate least-scope AWS IoT and EC2-role policies from your non-secret IDs."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from core import device_id

p = argparse.ArgumentParser()
p.add_argument("--account-id", required=True)
p.add_argument("--region", required=True)
p.add_argument("--thing", required=True)
p.add_argument("--table", default="GreenPulseEvents")
args = p.parse_args()
thing = device_id(args.thing)
if not args.account_id.isdigit() or len(args.account_id) != 12:
    p.error("account-id must contain 12 digits")
prefix = f"arn:aws:iot:{args.region}:{args.account_id}"
base = f"greenpulse/device/{thing}"
destination = Path(__file__).resolve().parents[1] / "aws"

def save(name, client, publish, subscribe):
    statements = [{"Effect":"Allow", "Action":"iot:Connect", "Resource":f"{prefix}:client/{client}"}]
    for action, kind, topics in [("iot:Publish","topic",publish),
                                ("iot:Subscribe","topicfilter",subscribe),
                                ("iot:Receive","topic",subscribe)]:
        if topics:
            statements.append({"Effect":"Allow", "Action":action,
                               "Resource":[f"{prefix}:{kind}/{base}/{t}" for t in topics]})
    (destination / name).write_text(json.dumps({"Version":"2012-10-17","Statement":statements},indent=2))

save("device-policy.json",thing,["sensors","status"],["care","alerts"])
save("backend-policy.json","greenpulse-backend",["care","alerts","llm-input"],["sensors"])
# Node-RED subscribes to '#'; Receive uses IAM '*' resource wildcards instead.
dashboard = {"Version":"2012-10-17","Statement":[
    {"Effect":"Allow","Action":"iot:Connect","Resource":f"{prefix}:client/greenpulse-dashboard"},
    {"Effect":"Allow","Action":"iot:Subscribe","Resource":f"{prefix}:topicfilter/{base}/#"},
    {"Effect":"Allow","Action":"iot:Receive","Resource":f"{prefix}:topic/{base}/*"}]}
(destination/"dashboard-policy.json").write_text(json.dumps(dashboard,indent=2))
role = {"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["dynamodb:PutItem"],
        "Resource":f"arn:aws:dynamodb:{args.region}:{args.account_id}:table/{args.table}"}]}
(destination/"backend-role-policy.json").write_text(json.dumps(role,indent=2))
print("Generated four policy files in aws/; attach each IoT policy to the matching certificate.")
