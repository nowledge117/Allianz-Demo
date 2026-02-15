resource "aws_lambda_function" "demo_api" {
  function_name = "demo-api"
  role          = aws_iam_role.demo_api.arn
  runtime       = "python3.11"
  handler       = "api_handler.lambda_handler"
  timeout       = 30

  filename         = var.demo_api_zip_path
  source_code_hash = filebase64sha256(var.demo_api_zip_path)

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.demo.name
      QUEUE_URL  = aws_sqs_queue.demo.id
    }
  }
}

resource "aws_lambda_function" "demo_worker" {
  function_name = "demo-worker"
  role          = aws_iam_role.demo_worker.arn
  runtime       = "python3.11"
  handler       = "worker_handler.lambda_handler"
  timeout       = 180

  filename         = var.demo_worker_zip_path
  source_code_hash = filebase64sha256(var.demo_worker_zip_path)

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.demo.name
    }
  }
}

resource "aws_lambda_event_source_mapping" "demo_worker_sqs" {
  event_source_arn = aws_sqs_queue.demo.arn
  function_name    = aws_lambda_function.demo_worker.arn
  batch_size       = 1
  enabled          = true
}
