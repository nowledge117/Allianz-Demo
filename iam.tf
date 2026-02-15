#
# IAM - demo-api
#
resource "aws_iam_role" "demo_api" {
  name = "demo-api"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "demo_api_basic" {
  role       = aws_iam_role.demo_api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_policy" "demo_api" {
  name = "demo-api"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "TableRw"
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:GetItem",
          "dynamodb:UpdateItem",
          "dynamodb:Scan"
        ]
        Resource = aws_dynamodb_table.demo.arn
      },
      {
        Sid      = "ListIndexQueryOnly"
        Effect   = "Allow"
        Action   = ["dynamodb:Query"]
        Resource = "${aws_dynamodb_table.demo.arn}/index/demo-createdby-createdat"
      },
      {
        Sid      = "EnqueueWork"
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.demo.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "demo_api_attach" {
  role       = aws_iam_role.demo_api.name
  policy_arn = aws_iam_policy.demo_api.arn
}

#
# IAM - demo-worker
#
resource "aws_iam_role" "demo_worker" {
  name = "demo-worker"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "demo_worker_basic" {
  role       = aws_iam_role.demo_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_policy" "demo_worker" {
  name = "demo-worker"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DdbReadWriteStatus"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.demo.arn
      },
      {
        Sid    = "Ec2VpcSubnetCreate"
        Effect = "Allow"
        Action = [
          "ec2:CreateVpc",
          "ec2:CreateSubnet",
          "ec2:CreateTags",
          "ec2:DescribeVpcs",
          "ec2:DescribeSubnets"
        ]
        Resource = "*"
      },
      {
        Sid    = "SqsConsume"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility"
        ]
        Resource = aws_sqs_queue.demo.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "demo_worker_attach" {
  role       = aws_iam_role.demo_worker.name
  policy_arn = aws_iam_policy.demo_worker.arn
}