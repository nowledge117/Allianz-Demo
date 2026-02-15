resource "aws_apigatewayv2_api" "demo" {
  name          = "demo"
  protocol_type = "HTTP"

  cors_configuration {
    allow_headers = ["authorization", "content-type", "idempotency-key"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_origins = ["*"]
  }
}

resource "aws_apigatewayv2_authorizer" "demo" {
  api_id           = aws_apigatewayv2_api.demo.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "demo"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.demo.id]
    issuer   = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.demo.id}"
  }
}

resource "aws_apigatewayv2_integration" "demo_api" {
  api_id                 = aws_apigatewayv2_api.demo.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.demo_api.arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "post_vpcs" {
  api_id             = aws_apigatewayv2_api.demo.id
  route_key          = "POST /vpcs"
  target             = "integrations/${aws_apigatewayv2_integration.demo_api.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.demo.id
}

resource "aws_apigatewayv2_route" "get_vpcs" {
  api_id             = aws_apigatewayv2_api.demo.id
  route_key          = "GET /vpcs"
  target             = "integrations/${aws_apigatewayv2_integration.demo_api.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.demo.id
}

resource "aws_apigatewayv2_route" "get_vpcs_id" {
  api_id             = aws_apigatewayv2_api.demo.id
  route_key          = "GET /vpcs/{proxy+}"
  target             = "integrations/${aws_apigatewayv2_integration.demo_api.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.demo.id
}

resource "aws_apigatewayv2_stage" "demo" {
  api_id      = aws_apigatewayv2_api.demo.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "allow_apigw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.demo_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.demo.execution_arn}/*/*/*"
}