variable "region" {
  type = string
}

variable "demo_api_zip_path" {
  type        = string
  description = "Path to demo-api.zip containing api_handler.py"
}

variable "demo_worker_zip_path" {
  type        = string
  description = "Path to demo-worker.zip containing worker_handler.py"
}