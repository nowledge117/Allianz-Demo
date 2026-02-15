import os
import json
import time
import uuid
import base64
import ipaddress
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from decimal import Decimal

def _json_default(o):
    # DynamoDB uses Decimal for all numbers
    if isinstance(o, Decimal):
        # ttl_epoch is an integer, so int is safe.
        # If you later store non-integers, you can switch to float(o).
        return int(o)
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

TABLE_NAME = os.environ["TABLE_NAME"]  # "demo"
QUEUE_URL = os.environ["QUEUE_URL"]    # SQS "demo" queue URL

IDEMPOTENCY_HEADER = "idempotency-key"

MAX_SUBNETS = 10
TTL_SECONDS = 24 * 60 * 60

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
sqs = boto3.client("sqs")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _now_epoch() -> int:
    return int(time.time())


def _resp(status: int, body: dict):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=_json_default),
    }


def _get_claims(event: dict) -> dict:
    rc = event.get("requestContext") or {}
    auth = rc.get("authorizer") or {}
    jwt = auth.get("jwt") or {}
    return jwt.get("claims") or {}


def _get_caller_sub(event: dict) -> str:
    sub = (_get_claims(event)).get("sub")
    if not sub:
        raise ValueError("Missing JWT subject (sub)")
    return sub


def _get_header(event: dict, name: str) -> str | None:
    headers = event.get("headers") or {}
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


def _parse_body(event: dict) -> dict:
    body = event.get("body")
    if not body:
        return {}
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    return json.loads(body)


def _validate_request(payload: dict) -> tuple[str, list[dict]]:
    if "vpc" not in payload or not isinstance(payload["vpc"], dict):
        raise ValueError("Missing 'vpc' object")

    vpc_cidr = payload["vpc"].get("cidr")
    if not vpc_cidr or not isinstance(vpc_cidr, str):
        raise ValueError("Missing 'vpc.cidr'")

    try:
        vpc_net = ipaddress.ip_network(vpc_cidr, strict=True)
    except Exception as e:
        raise ValueError(f"Invalid VPC CIDR '{vpc_cidr}': {e}")

    subnets = payload.get("subnets")
    if not subnets or not isinstance(subnets, list):
        raise ValueError("Missing 'subnets' array")
    if len(subnets) > MAX_SUBNETS:
        raise ValueError(f"Too many subnets: {len(subnets)} (max {MAX_SUBNETS})")

    parsed = []
    seen = []
    for i, s in enumerate(subnets):
        if not isinstance(s, dict):
            raise ValueError(f"Subnet at index {i} must be an object")

        cidr = s.get("cidr")
        az = s.get("az")
        name = s.get("name")

        if not cidr or not isinstance(cidr, str):
            raise ValueError(f"Subnet at index {i} missing 'cidr'")
        if not az or not isinstance(az, str):
            raise ValueError(f"Subnet at index {i} missing 'az'")
        if name is not None and not isinstance(name, str):
            raise ValueError(f"Subnet at index {i} has invalid 'name'")

        try:
            sn = ipaddress.ip_network(cidr, strict=True)
        except Exception as e:
            raise ValueError(f"Invalid subnet CIDR '{cidr}' at index {i}: {e}")

        if not sn.subnet_of(vpc_net):
            raise ValueError(f"Subnet CIDR '{cidr}' is not within VPC CIDR '{vpc_cidr}'")

        for prior in seen:
            if sn.overlaps(prior):
                raise ValueError(f"Subnet CIDR '{cidr}' overlaps with '{prior}'")
        seen.append(sn)

        parsed.append({"cidr": cidr, "az": az, "name": name})

    return vpc_cidr, parsed


def _route(event: dict) -> tuple[str, str]:
    rc = event.get("requestContext") or {}
    http = rc.get("http") or {}
    method = (http.get("method") or "").upper()
    path = http.get("path") or "/"
    return method, path


def _lock_pk(created_by: str, idem: str) -> str:
    # lock item PK is derived from caller identity + idempotency key.
    # We do NOT store created_by on the lock record.
    return f"lock#{created_by}#{idem}"


def _encode_next_token(lek: dict) -> str:
    raw = json.dumps(lek).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def _decode_next_token(token: str) -> dict:
    raw = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
    return json.loads(raw)


def handle_post_vpcs(event: dict):
    created_by = _get_caller_sub(event)
    idem = _get_header(event, IDEMPOTENCY_HEADER)
    if not idem:
        return _resp(400, {"message": "Missing Idempotency-Key header"})

    payload = _parse_body(event)
    try:
        vpc_cidr, subnets = _validate_request(payload)
    except ValueError as e:
        return _resp(400, {"message": str(e)})

    now_iso = _now_iso()
    ttl_epoch = _now_epoch() + TTL_SECONDS

    lock_key = _lock_pk(created_by, idem)
    request_id = str(uuid.uuid4())

    # Acquire idempotency lock (race-proof)
    try:
        table.put_item(
            Item={
                "request_id": lock_key,
                "ttl_epoch": ttl_epoch,
                "lock_request_id": request_id,
                "type": "IDEMPOTENCY_LOCK",
                "created_at": now_iso,
            },
            ConditionExpression="attribute_not_exists(request_id)",
        )
        won_lock = True
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        won_lock = False

    if not won_lock:
        lock = table.get_item(Key={"request_id": lock_key}).get("Item")
        if not lock or "lock_request_id" not in lock:
            return _resp(409, {"message": "Idempotency lock exists but is unreadable"})

        existing_request_id = lock["lock_request_id"]
        existing = table.get_item(Key={"request_id": existing_request_id}).get("Item")

        # Always 202 for idempotent replay
        if not existing:
            return _resp(202, {"request_id": existing_request_id, "status": "QUEUED"})

        return _resp(202, {
            "request_id": existing_request_id,
            "status": existing.get("status", "UNKNOWN"),
            "result": existing.get("result"),
            "error_message": existing.get("error_message"),
        })

    # Create the request record (includes created_by for audit)
    table.put_item(Item={
        "request_id": request_id,
        "type": "VPC_REQUEST",
        "created_by": created_by,
        "idempotency_key": idem,
        "created_at": now_iso,
        "updated_at": now_iso,
        "ttl_epoch": ttl_epoch,
        "status": "QUEUED",
        "request": {
            "vpc": {"cidr": vpc_cidr},
            "subnets": subnets,
        },
    })

    sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps({"request_id": request_id}))

    return _resp(202, {"request_id": request_id, "status": "QUEUED"})


def handle_get_vpcs(event: dict):
    _ = _get_caller_sub(event)  # authenticated users only

    qsp = event.get("queryStringParameters") or {}
    try:
        limit = int(qsp.get("limit", "20"))
    except Exception:
        limit = 20
    limit = max(1, min(50, limit))

    next_token = qsp.get("next_token")
    eks = None
    if next_token:
        try:
            eks = _decode_next_token(next_token)
        except Exception:
            return _resp(400, {"message": "Invalid next_token"})

    # Option A: list ALL requests (authenticated users can see everything).
    # Since the table PK is request_id, we use Scan with pagination.
    # We filter to return only VPC_REQUEST items (exclude idempotency lock items).
    scan_kwargs = {
        "Limit": limit,
        "FilterExpression": "attribute_exists(#t) AND #t = :v",
        "ExpressionAttributeNames": {"#t": "type"},
        "ExpressionAttributeValues": {":v": "VPC_REQUEST"},
    }
    if eks:
        scan_kwargs["ExclusiveStartKey"] = eks

    out = table.scan(**scan_kwargs)
    items = out.get("Items", [])
    lek = out.get("LastEvaluatedKey")

    resp = {"items": items}
    if lek:
        resp["next_token"] = _encode_next_token(lek)

    return _resp(200, resp)


def handle_get_vpc_by_id(event: dict, request_id: str):
    _ = _get_caller_sub(event)  # still require auth, but no per-user authorization

    item = table.get_item(Key={"request_id": request_id}).get("Item")
    if not item or item.get("type") != "VPC_REQUEST":
        return _resp(404, {"message": "Not found"})

    return _resp(200, item)


def lambda_handler(event, context):
    method, path = _route(event)

    if method == "POST" and path == "/vpcs":
        return handle_post_vpcs(event)

    if method == "GET" and path == "/vpcs":
        return handle_get_vpcs(event)

    if method == "GET" and path.startswith("/vpcs/"):
        request_id = path.split("/", 2)[2]
        if not request_id:
            return _resp(404, {"message": "Not found"})
        return handle_get_vpc_by_id(event, request_id)

    return _resp(404, {"message": "Not found"})