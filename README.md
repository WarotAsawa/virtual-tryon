# Atelier — Fashion Virtual Try-On

A serverless fashion ecommerce platform with AI-powered virtual try-on using Amazon Nova Canvas.

## Architecture

- **Frontend** — Static SPA hosted on S3 + CloudFront (Swiss Clean design)
- **API** — API Gateway REST API with Cognito authorizer
- **Auth** — Cognito User Pool with email sign-in, password policies, token refresh
- **Compute** — Lambda functions (Python 3.12, Clean Architecture)
- **Database** — DynamoDB (Products, Orders, TryOn tables) with PAY_PER_REQUEST
- **Storage** — Private S3 bucket for product images and try-on results
- **AI** — Amazon Nova Canvas (`amazon.nova-canvas-v1:0`) for virtual try-on generation

## Project Structure

```
├── infrastructure/          # CDK stacks (Python)
│   ├── database_stack.py    # DynamoDB tables + GSI
│   ├── auth_stack.py        # Cognito User Pool + Client
│   ├── storage_stack.py     # Private S3 bucket
│   ├── api_stack.py         # API Gateway + 4 Lambda functions
│   └── frontend_stack.py    # CloudFront + S3 static hosting
├── lambda_functions/        # Lambda handlers (Clean Architecture)
│   ├── products/handler.py  # CRUD products, presigned URLs
│   ├── orders/handler.py    # Create/list/get orders
│   ├── tryon/handler.py     # Virtual try-on via Nova Canvas
│   ├── auth/handler.py      # Profile get/update via Cognito
│   └── shared/              # Shared utilities layer
├── frontend/                # Static SPA
│   ├── index.html           # Product catalog with filters
│   ├── tryon.html           # Virtual try-on page
│   ├── login.html           # Cognito auth + password challenge
│   ├── register.html        # Cognito sign-up
│   ├── app.js               # API layer, auth state, token refresh
│   └── styles.css           # Swiss Clean aesthetic
├── scripts/
│   └── seed_products.py     # Generate 100 products (Claude + Nova Canvas)
├── deploy.sh                # Deploy script with CloudFront invalidation
└── app.py                   # CDK entry point
```

## Prerequisites

- AWS CLI configured with appropriate credentials
- AWS CDK v2 installed (`npm install -g aws-cdk`)
- Python 3.9+
- [uv](https://docs.astral.sh/uv/) (for running seed script)

## Deploy

```bash
# Install dependencies
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Deploy all stacks
chmod +x deploy.sh
./deploy.sh

# Deploy only frontend or backend
./deploy.sh frontend
./deploy.sh backend
```

## Seed Products

Generate 100 fashion products with AI-generated metadata and images:

```bash
AWS_DEFAULT_REGION=ap-southeast-1 uv run scripts/seed_products.py
```

Uses Claude (APAC inference profile) for catalog metadata and Nova Canvas (us-east-1) for product images.

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/products` | Public | List all products |
| GET | `/products/{id}` | Public | Get product detail |
| POST | `/products` | Cognito | Create product |
| POST | `/tryon` | Cognito | Generate virtual try-on |
| GET | `/tryon/{session_id}` | Cognito | Get try-on result |
| POST | `/orders` | Cognito | Create order |
| GET | `/orders` | Cognito | List user orders |
| GET | `/auth/profile` | Cognito | Get user profile |
| PUT | `/auth/profile` | Cognito | Update profile |

## Security

- All S3 buckets are private (BLOCK_ALL) with SSE-S3 encryption and enforce_ssl
- No public databases — DynamoDB with PITR enabled
- Public access only through API Gateway and CloudFront
- CDK Nag (AwsSolutionsChecks) applied — all errors resolved
- Cognito with strong password policy and advanced security mode

## Tech Stack

| Layer | Technology |
|-------|-----------|
| IaC | AWS CDK (Python) |
| Frontend | Vanilla HTML/CSS/JS |
| API | API Gateway REST |
| Auth | Cognito User Pools |
| Compute | Lambda (Python 3.12) |
| Database | DynamoDB |
| Storage | S3 |
| CDN | CloudFront |
| AI | Amazon Nova Canvas |
