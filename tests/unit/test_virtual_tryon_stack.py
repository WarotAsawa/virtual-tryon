import aws_cdk as core
import aws_cdk.assertions as assertions

from virtual_tryon.virtual_tryon_stack import VirtualTryonStack

# example tests. To run these tests, uncomment this file along with the example
# resource in virtual_tryon/virtual_tryon_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = VirtualTryonStack(app, "virtual-tryon")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
