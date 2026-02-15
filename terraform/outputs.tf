output "demo_api_url" {
  value = aws_apigatewayv2_api.demo.api_endpoint
}

output "demo_user_pool_id" {
  value = aws_cognito_user_pool.demo.id
}

output "demo_user_pool_client_id" {
  value = aws_cognito_user_pool_client.demo.id
}
