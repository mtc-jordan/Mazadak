variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "me-south-1"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "mzadak"
}
