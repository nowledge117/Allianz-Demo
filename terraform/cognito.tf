resource "aws_cognito_user_pool" "demo" {
  name = "demo"
}

resource "aws_cognito_user_pool_client" "demo" {
  name            = "demo"
  user_pool_id    = aws_cognito_user_pool.demo.id
  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH"
  ]
}
