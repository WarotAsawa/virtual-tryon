from aws_cdk import (
    Stack,
    Duration,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_iam as iam,
    aws_cognito as cognito,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_logs as logs,
    CfnOutput,
)
from cdk_nag import NagSuppressions
from constructs import Construct


class ApiStack(Stack):
    """API Gateway + Lambda functions for the fashion ecommerce platform."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        user_pool: cognito.UserPool,
        products_table: dynamodb.Table,
        orders_table: dynamodb.Table,
        tryon_table: dynamodb.Table,
        images_bucket: s3.Bucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Shared Lambda layer for common code
        shared_layer = _lambda.LayerVersion(
            self, "SharedLayer",
            code=_lambda.Code.from_asset("lambda_functions/shared"),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_12],
            description="Shared utilities for fashion ecommerce",
        )

        lambda_defaults = dict(
            runtime=_lambda.Runtime.PYTHON_3_12,
            timeout=Duration.seconds(30),
            memory_size=256,
            layers=[shared_layer],
            tracing=_lambda.Tracing.ACTIVE,
        )

        # --- Products Lambda ---
        products_fn = _lambda.Function(
            self, "ProductsFn",
            handler="handler.handler",
            code=_lambda.Code.from_asset("lambda_functions/products"),
            environment={
                "PRODUCTS_TABLE": products_table.table_name,
                "IMAGES_BUCKET": images_bucket.bucket_name,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
            **lambda_defaults,
        )
        products_table.grant_read_write_data(products_fn)
        images_bucket.grant_read_write(products_fn)

        # --- Orders Lambda ---
        orders_fn = _lambda.Function(
            self, "OrdersFn",
            handler="handler.handler",
            code=_lambda.Code.from_asset("lambda_functions/orders"),
            environment={
                "ORDERS_TABLE": orders_table.table_name,
                "PRODUCTS_TABLE": products_table.table_name,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
            **lambda_defaults,
        )
        orders_table.grant_read_write_data(orders_fn)
        products_table.grant_read_data(orders_fn)

        # --- Virtual Try-On Lambda (longer timeout for Bedrock) ---
        # Pillow layer for image preprocessing
        pillow_layer = _lambda.LayerVersion(
            self, "PillowLayer",
            code=_lambda.Code.from_asset("layers/pillow/pillow-layer.zip"),
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_12],
            description="Pillow image processing library",
        )

        tryon_fn = _lambda.Function(
            self, "TryOnFn",
            handler="handler.handler",
            code=_lambda.Code.from_asset("lambda_functions/tryon"),
            environment={
                "TRYON_TABLE": tryon_table.table_name,
                "IMAGES_BUCKET": images_bucket.bucket_name,
                "PRODUCTS_TABLE": products_table.table_name,
                "MODEL_ID": "amazon.nova-canvas-v1:0",
            },
            timeout=Duration.minutes(5),
            memory_size=1024,
            runtime=_lambda.Runtime.PYTHON_3_12,
            layers=[shared_layer, pillow_layer],
            tracing=_lambda.Tracing.ACTIVE,
            log_retention=logs.RetentionDays.ONE_WEEK,
        )
        tryon_table.grant_read_write_data(tryon_fn)
        images_bucket.grant_read_write(tryon_fn)
        products_table.grant_read_data(tryon_fn)
        tryon_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[
                f"arn:aws:bedrock:*::foundation-model/amazon.nova-canvas-v1:0",
            ],
        ))

        # --- Auth Lambda (signup/profile helpers) ---
        auth_fn = _lambda.Function(
            self, "AuthFn",
            handler="handler.handler",
            code=_lambda.Code.from_asset("lambda_functions/auth"),
            environment={
                "USER_POOL_ID": user_pool.user_pool_id,
            },
            log_retention=logs.RetentionDays.ONE_WEEK,
            **lambda_defaults,
        )
        auth_fn.add_to_role_policy(iam.PolicyStatement(
            actions=[
                "cognito-idp:AdminGetUser",
                "cognito-idp:AdminUpdateUserAttributes",
            ],
            resources=[user_pool.user_pool_arn],
        ))

        # --- API Gateway ---
        log_group = logs.LogGroup(self, "ApiAccessLogs")

        api = apigw.RestApi(
            self, "FashionApi",
            rest_api_name="Fashion Ecommerce API",
            deploy_options=apigw.StageOptions(
                stage_name="v1",
                throttling_rate_limit=100,
                throttling_burst_limit=200,
                logging_level=apigw.MethodLoggingLevel.INFO,
                access_log_destination=apigw.LogGroupLogDestination(log_group),
                access_log_format=apigw.AccessLogFormat.json_with_standard_fields(
                    caller=True,
                    http_method=True,
                    ip=True,
                    protocol=True,
                    request_time=True,
                    resource_path=True,
                    response_length=True,
                    status=True,
                    user=True,
                ),
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization"],
            ),
        )

        authorizer = apigw.CognitoUserPoolsAuthorizer(
            self, "CognitoAuthorizer",
            cognito_user_pools=[user_pool],
        )
        auth_opts = {"authorizer": authorizer, "authorization_type": apigw.AuthorizationType.COGNITO}

        # Products endpoints
        products_resource = api.root.add_resource("products")
        products_list_method = products_resource.add_method("GET", apigw.LambdaIntegration(products_fn))
        products_resource.add_method("POST", apigw.LambdaIntegration(products_fn), **auth_opts)
        product_item = products_resource.add_resource("{product_id}")
        product_get_method = product_item.add_method("GET", apigw.LambdaIntegration(products_fn))
        product_item.add_method("PUT", apigw.LambdaIntegration(products_fn), **auth_opts)
        product_item.add_method("DELETE", apigw.LambdaIntegration(products_fn), **auth_opts)

        # Suppress CDK Nag for public product browsing endpoints (intentionally unauthenticated)
        for method in [products_list_method, product_get_method]:
            NagSuppressions.add_resource_suppressions(
                method,
                [
                    {"id": "AwsSolutions-APIG4", "reason": "Product browsing is intentionally public for ecommerce storefront"},
                    {"id": "AwsSolutions-COG4", "reason": "Product browsing is intentionally public for ecommerce storefront"},
                ],
            )

        # Orders endpoints (all authenticated)
        orders_resource = api.root.add_resource("orders")
        orders_resource.add_method("GET", apigw.LambdaIntegration(orders_fn), **auth_opts)
        orders_resource.add_method("POST", apigw.LambdaIntegration(orders_fn), **auth_opts)
        order_item = orders_resource.add_resource("{order_id}")
        order_item.add_method("GET", apigw.LambdaIntegration(orders_fn), **auth_opts)

        # Virtual Try-On endpoints (all authenticated)
        tryon_resource = api.root.add_resource("tryon")
        tryon_resource.add_method("POST", apigw.LambdaIntegration(tryon_fn), **auth_opts)
        tryon_item = tryon_resource.add_resource("{session_id}")
        tryon_item.add_method("GET", apigw.LambdaIntegration(tryon_fn), **auth_opts)

        # Auth profile endpoint
        profile_resource = api.root.add_resource("profile")
        profile_resource.add_method("GET", apigw.LambdaIntegration(auth_fn), **auth_opts)
        profile_resource.add_method("PUT", apigw.LambdaIntegration(auth_fn), **auth_opts)

        self.api_url = api.url

        CfnOutput(self, "ApiUrl", value=api.url)

        # Stack-level CDK Nag suppressions for CDK-generated IAM policies
        NagSuppressions.add_stack_suppressions(self, [
            {"id": "AwsSolutions-IAM4", "reason": "AWS managed policies (AWSLambdaBasicExecutionRole) are used by CDK-generated Lambda service roles for CloudWatch Logs access"},
            {"id": "AwsSolutions-IAM5", "reason": "Wildcard permissions are generated by CDK grant_* methods for DynamoDB index access, S3 object operations, and X-Ray tracing. These are scoped to specific resource ARNs."},
            {"id": "AwsSolutions-L1", "reason": "Python 3.12 is the latest stable runtime supported by the application dependencies. Will upgrade when 3.13 is validated."},
            {"id": "AwsSolutions-APIG2", "reason": "Request validation is handled in Lambda function code with proper error responses"},
        ])
