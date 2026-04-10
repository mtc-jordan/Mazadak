terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }

  backend "s3" {
    bucket = "mzadak-terraform-state"
    key    = "infrastructure/terraform.tfstate"
    region = "me-south-1"
  }
}

provider "aws" {
  region = var.aws_region
}
