resource "aws_sqs_queue" "demo_dlq" {
  name = "demo-dlq"
}

resource "aws_sqs_queue" "demo" {
  name                       = "demo"
  visibility_timeout_seconds = 180

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.demo_dlq.arn
    maxReceiveCount     = 5
  })
}