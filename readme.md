# Demo VPC Provisioning API (AWS, Python, Authenticated)

This repository implements an authenticated API that provisions an AWS VPC with multiple subnets, stores the results, and provides retrieval endpoints.

## Requirements (from exercise)

- Create an API based on AWS services that can:
  - Create a VPC with multiple subnets
  - Store results of created resources
  - Retrieve stored results via API
- Code in **Python**
- API protected with **authentication**
- Authorization: **open to all authenticated users**

---

## Architecture

**API Gateway (HTTP API)** → **Lambda (demo-api)** → **DynamoDB (demo)** → **SQS (demo)** → **Lambda (demo-worker)** → **EC2 VPC/Subnet APIs**

**Services**
- **API Gateway HTTP API**  
  Routes:
  - `POST /vpcs` submit provisioning request
  - `GET /vpcs` list all requests (paginated)
  - `GET /vpcs/{id}` retrieve a request by `request_id`
- **Cognito User Pool** for authentication (JWT tokens)
- **Lambda `demo-api`** handles HTTP requests, validates payload, writes request records, enqueues SQS job
- **SQS Queue `demo`** decouples API from provisioning (async)
- **Lambda `demo-worker`** consumes SQS and calls EC2 APIs to create VPC/subnets, tagging resources and checkpointing progress in DynamoDB
- **DynamoDB Table `demo`** stores:
  - request items (`type=VPC_REQUEST`)
  - idempotency lock items (`type=IDEMPOTENCY_LOCK`)

**Why async (SQS + worker)?**
Provisioning VPCs/subnets can exceed typical HTTP API timeouts and has long-tail latency. Using SQS + worker:
- avoids API Gateway/Lambda timeout pressure on `POST /vpcs`
- provides retry behavior (at-least-once) with DLQ
- separates request handling from provisioning logic

---

### Security model
- **Authentication required**: requests must include `Authorization: Bearer <JWT>`
- **Authorization open to all authenticated users**:
  - Any authenticated user can submit `POST /vpcs`
  - Any authenticated user can read any request record via `GET /vpcs` and `GET /vpcs/{request_id}`

---

## Data model (DynamoDB)

Partition key: `request_id` (string)

Two item types are stored in the same table:
1. `type = VPC_REQUEST`
   - request payload, status, and provisioning results
2. `type = IDEMPOTENCY_LOCK`
   - lock record keyed by `request_id = lock#<user_sub>#<idempotency_key>`
   - TTL to bound the idempotency window

TTL attribute: `ttl_epoch` (seconds since epoch)
Lock items **do not store `created_by`**, so they don’t appear in list queries.

---

## Tagging
All created AWS resources are tagged with:
- `Name=demo`
- `Project=demo`
- `RequestId=<request_id>` (traceability)

Optionally, if subnet input contains `name`, the subnet also gets:
- `SubnetName=<name>`

---

## API

### POST `/vpcs`
Creates an async provisioning request.

Headers:
- `Authorization: Bearer <Cognito ID token>`
- `Idempotency-Key: <string>` (required)

Body example:
```json
{
  "vpc": { "cidr": "10.30.0.0/16" },
  "subnets": [
    { "cidr": "10.30.1.0/24", "az": "us-east-1a", "name": "apps-a" },
    { "cidr": "10.30.2.0/24", "az": "us-east-1b", "name": "apps-b" }
  ]
}
```

Response:
- `202 Accepted` with `{ "request_id": "...", "status": "QUEUED|IN_PROGRESS|..." }`

### GET `/vpcs`
Lists all requests (authenticated users only). Paginated via `next_token`.

Query params:
- `limit` (1..50, default 20)
- `next_token` (optional)

### GET `/vpcs/{request_id}`
Returns one request record (authenticated users only).

---

## Deployment (Terraform)

### 1) Prereqs
- Terraform `>= 1.5`
- AWS CLI configured:
  ```bash
  aws sts get-caller-identity
  ```
- Python runtime not required locally (Lambda uses managed runtime), but useful for parsing JSON in shell examples.

### 2) Package Lambdas
From the directory containing `api_handler.py` and `worker_handler.py`:

```bash
zip -j demo-api.zip api_handler.py
zip -j demo-worker.zip worker_handler.py
```

### 3) Configure Terraform inputs
Create `terraform.tfvars`:

```hcl
region               = "us-east-1"
demo_api_zip_path     = "./demo-api.zip"
demo_worker_zip_path  = "./demo-worker.zip"
```

### 3) Apply Configurations
```bash
terraform init
terraform fmt
terraform validate
terraform apply
```

Terraform outputs:
- `demo_api_url`
- `demo_user_pool_id`
- `demo_user_pool_client_id`

---

## Create a Cognito user and obtain a JWT (CLI)

> API Gateway JWT authorizer expects an **ID token** (`IdToken`), not the access token.

```bash
USER_POOL_ID="$(terraform output -raw demo_user_pool_id)"
CLIENT_ID="$(terraform output -raw demo_user_pool_client_id)"

aws cognito-idp admin-create-user \
  --user-pool-id "$USER_POOL_ID" \
  --username "demo-user" \
  --user-attributes Name=email,Value=bibekpanigrahi13@gmail.com \
  --message-action SUPPRESS

aws cognito-idp admin-set-user-password \
  --user-pool-id "$USER_POOL_ID" \
  --username "demo-user" \
  --password 'TempPassw0rd!234' \
  --permanent

TOKENS_JSON=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id "$CLIENT_ID" \
  --auth-parameters USERNAME=demo-user,PASSWORD='TempPassw0rd!234')

ID_TOKEN=$(echo "$TOKENS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['AuthenticationResult']['IdToken'])")
```

---

## Running jobs (API calls)

Set:
```bash
API_URL="$(terraform output -raw demo_api_url)"
```

### Submit a request
```bash
curl -i -X POST "$API_URL/vpcs" \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-req-001" \
  -d '{
    "vpc": { "cidr": "10.40.0.0/16" },
    "subnets": [
      { "cidr": "10.40.1.0/24", "az": "us-east-1a", "name": "apps-a" },
      { "cidr": "10.40.2.0/24", "az": "us-east-1b", "name": "apps-b" }
    ]
  }'
```

### Poll a request
```bash
REQUEST_ID="<request_id_from_post>"

curl -s "$API_URL/vpcs/<request_id>" \
  -H "Authorization: Bearer $ID_TOKEN" | python3 -m json.tool
```

### List all requests (pagination)
```bash
curl -s "$API_URL/vpcs?limit=20" \
  -H "Authorization: Bearer $ID_TOKEN" | python3 -m json.tool

curl -s "$API_URL/vpcs?limit=20&next_token=<token>" \
  -H "Authorization: Bearer $ID_TOKEN" | python3 -m json.tool
```

### Idempotency replay
Re-run the same POST with the same `Idempotency-Key` and expect the same `request_id`.

---

## Operational checks

### Lambda logs
```bash
aws logs tail /aws/lambda/demo-api --follow --region us-east-1
aws logs tail /aws/lambda/demo-worker --follow --region us-east-1
```

### Check SQS queue depth
```bash
QUEUE_URL=$(aws sqs get-queue-url --queue-name demo --region us-east-1 --query QueueUrl --output text)
aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
  --region us-east-1
```

### Common failure: VPC quota exceeded
If worker logs show `VpcLimitExceeded`, delete unused VPCs or request a quota increase.

## Cleanup (delete created VPCs)
Deletes all VPCs tagged `Project=demo` (subnets first):

```bash
for vpc in $(aws ec2 describe-vpcs --filters "Name=tag:Project,Values=demo" --query 'Vpcs[].VpcId' --output text); do
  echo "Deleting subnets in $vpc"
  for subnet in $(aws ec2 describe-subnets --filters "Name=vpc-id,Values=$vpc" --query 'Subnets[].SubnetId' --output text); do
    echo "  delete-subnet $subnet"
    aws ec2 delete-subnet --subnet-id "$subnet"
  done

  echo "Deleting VPC $vpc"
  aws ec2 delete-vpc --vpc-id "$vpc"
done

terraform destroy
```


---

## Why Terraform over CloudFormation (for this exercise)

Both are valid. Terraform was chosen as the primary deliverable because:

1. **Readability & review speed**: API Gateway v2 + Cognito JWT authorizer wiring is verbose in CloudFormation. Terraform expresses it more concisely.
2. **Developer ergonomics**:  `terraform plan/apply` feedback loops are typically quicker for exercises; diffs are easier to interpret.
3. **Cross-service consistency**: resources like Lambda, API Gateway, Cognito, DynamoDB, SQS can be expressed in a uniform way.
3. **Modular file layout**: easy to split by service (`apigw.tf`, `lambda.tf`, etc.) without introducing advanced scaffolding.

A CloudFormation template is also provided below as an alternative for AWS-native environments.

---

## Why this design (vs simplest synchronous Lambda)

A minimal synchronous design (API Lambda directly creates VPC/subnets) meets the base prompt but has drawbacks:
- **High chance of request timeout** during VPC/subnet provisioning.
- Harder to retry safely without creating duplicates.

This implementation uses:
- **Async processing (SQS + worker)**: API returns quickly (`202`), worker handles provisioning.
- **Idempotency lock**: client retries do not create duplicate VPCs (important for real-world reliability).
- **DynamoDB checkpointing**: worker stores `vpc_id` as soon as it’s created, so retries won’t create multiple VPCs.

---

## Note: CloudFormation Template is added for reference

CloudFormation is included **for reference only**.

CloudFormation requires Lambda deployment packages to be uploaded to S3 and referenced via:

- `CodeS3Bucket`
- `ApiZipKey`
- `WorkerZipKey`

Additionally, a few small adjustments (for example, IAM actions like `dynamodb:Scan` for the `GET /vpcs` “list all” endpoint) are necessary for the Lambda functionality to work exactly as implemented and to satisfy the exercise requirements.

For this exercise, **Terraform is the primary deployment mechanism**.
