#!/usr/bin/env python3
import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from infrastructure.database_stack import DatabaseStack
from infrastructure.auth_stack import AuthStack
from infrastructure.storage_stack import StorageStack
from infrastructure.api_stack import ApiStack
from infrastructure.frontend_stack import FrontendStack

app = cdk.App()

db_stack = DatabaseStack(app, "FashionDbStack")
auth_stack = AuthStack(app, "FashionAuthStack")
storage_stack = StorageStack(app, "FashionStorageStack")

api_stack = ApiStack(
    app, "FashionApiStack",
    user_pool=auth_stack.user_pool,
    products_table=db_stack.products_table,
    orders_table=db_stack.orders_table,
    tryon_table=db_stack.tryon_table,
    images_bucket=storage_stack.images_bucket,
)
api_stack.add_dependency(db_stack)
api_stack.add_dependency(auth_stack)
api_stack.add_dependency(storage_stack)

frontend_stack = FrontendStack(app, "FashionFrontendStack", api_url=api_stack.api_url)
frontend_stack.add_dependency(api_stack)

cdk.Aspects.of(app).add(AwsSolutionsChecks())

app.synth()
