import os
import json
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ["TABLE_NAME"]  # "demo"
MAX_SUBNETS = 10

FIXED_TAGS = [
    {"Key": "Name", "Value": "demo"},
    {"Key": "Project", "Value": "demo"},
]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
ec2 = boto3.client("ec2")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _update_fields(request_id: str, *, status=None, result=None, error=None):
    """
    Single helper to update multiple fields safely.
    """
    expr = []
    names = {}
    vals = {}

    expr.append("#ua = :u")
    names["#ua"] = "updated_at"
    vals[":u"] = _now_iso()

    if status is not None:
        expr.append("#s = :s")
        names["#s"] = "status"
        vals[":s"] = status

    if result is not None:
        expr.append("#r = :r")
        names["#r"] = "result"
        vals[":r"] = result

    if error is not None:
        expr.append("#em = :e")
        names["#em"] = "error_message"
        vals[":e"] = str(error)

    table.update_item(
        Key={"request_id": request_id},
        UpdateExpression="SET " + ", ".join(expr),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=vals,
    )

def _get_request(request_id: str) -> dict:
    out = table.get_item(Key={"request_id": request_id})
    item = out.get("Item")
    if not item:
        raise ValueError(f"request_id not found: {request_id}")
    if item.get("type") != "VPC_REQUEST":
        raise ValueError(f"not a VPC_REQUEST item: {request_id}")
    return item


def _tag(resource_ids: list[str], request_id: str):
    tags = FIXED_TAGS + [{"Key": "RequestId", "Value": request_id}]
    ec2.create_tags(Resources=resource_ids, Tags=tags)


def _wait_vpc_available(vpc_id: str, timeout_seconds: int = 30):
    start = time.time()
    while time.time() - start < timeout_seconds:
        resp = ec2.describe_vpcs(VpcIds=[vpc_id])
        state = resp["Vpcs"][0].get("State")
        if state == "available":
            return
        time.sleep(2)


def handle_request(request_id: str):
    item = _get_request(request_id)

    if item.get("status") in ("CREATED", "FAILED"):
        return

    req = item.get("request") or {}
    vpc_req = req.get("vpc") or {}
    subnets_req = req.get("subnets") or []

    if len(subnets_req) > MAX_SUBNETS:
        _update_fields(request_id, status="FAILED", error=f"Too many subnets: {len(subnets_req)} (max {MAX_SUBNETS})")
        return

    current_result = item.get("result") or {}
    vpc_id = current_result.get("vpc_id")
    created_subnets = current_result.get("subnets") or []  # list of dicts
    created_by_key = {(s.get("cidr"), s.get("az")) for s in created_subnets}

    _update_fields(request_id, status="IN_PROGRESS")

    try:
        if not vpc_id:
            vpc_cidr = vpc_req["cidr"]
            vpc_resp = ec2.create_vpc(CidrBlock=vpc_cidr)
            vpc_id = vpc_resp["Vpc"]["VpcId"]
            _tag([vpc_id], request_id)
            _wait_vpc_available(vpc_id)
            current_result.update({
                "vpc_id": vpc_id,
                "vpc_cidr": vpc_cidr,
                "subnets": created_subnets,
            })
            _update_fields(request_id, result=current_result)
        for s in subnets_req:
            key = (s["cidr"], s["az"])
            if key in created_by_key:
                continue
            sn_resp = ec2.create_subnet(
                VpcId=vpc_id,
                CidrBlock=s["cidr"],
                AvailabilityZone=s["az"],
            )
            subnet_id = sn_resp["Subnet"]["SubnetId"]
            _tag([subnet_id], request_id)

            if s.get("name"):
                ec2.create_tags(
                    Resources=[subnet_id],
                    Tags=[{"Key": "SubnetName", "Value": s["name"]}],
                )

            created_subnets.append({
                "subnet_id": subnet_id,
                "cidr": s["cidr"],
                "az": s["az"],
                "name": s.get("name"),
            })
            created_by_key.add(key)
            current_result["subnets"] = created_subnets
            _update_fields(request_id, result=current_result)

        _update_fields(request_id, status="CREATED", result=current_result)

    except (ClientError, KeyError, ValueError) as e:
        _update_fields(request_id, status="FAILED", error=str(e))
        raise


def lambda_handler(event, context):
    for r in event.get("Records", []):
        body = json.loads(r["body"])
        handle_request(body["request_id"])
