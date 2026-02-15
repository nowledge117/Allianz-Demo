resource "aws_dynamodb_table" "demo" {
  name         = "demo"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "request_id"

  attribute {
    name = "request_id"
    type = "S"
  }

  attribute {
    name = "created_by"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  ttl {
    attribute_name = "ttl_epoch"
    enabled        = true
  }

  global_secondary_index {
    name            = "demo-createdby-createdat"
    hash_key        = "created_by"
    range_key       = "created_at"
    projection_type = "ALL"
  }
}
