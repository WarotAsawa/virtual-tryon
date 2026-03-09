"""Auth Lambda — Clean Architecture handler.

Domain: User profile
Use Cases: get profile, update profile
Interface: API Gateway event → response
"""
import os
import boto3
from shared.utils import response, get_user_id, parse_body

USER_POOL_ID = os.environ["USER_POOL_ID"]
cognito = boto3.client("cognito-idp")


# ── Use Cases ──
def get_profile(user_id: str):
    resp = cognito.admin_get_user(UserPoolId=USER_POOL_ID, Username=user_id)
    attrs = {a["Name"]: a["Value"] for a in resp.get("UserAttributes", [])}
    return {
        "user_id": user_id,
        "email": attrs.get("email", ""),
        "name": attrs.get("name", ""),
        "email_verified": attrs.get("email_verified", "false"),
    }


def update_profile(user_id: str, data: dict):
    attributes = []
    if "name" in data:
        attributes.append({"Name": "name", "Value": data["name"]})
    if not attributes:
        return None, "No valid attributes to update"
    cognito.admin_update_user_attributes(
        UserPoolId=USER_POOL_ID, Username=user_id, UserAttributes=attributes
    )
    return get_profile(user_id), None


# ── Interface Adapter ──
def handler(event, context):
    method = event["httpMethod"]
    user_id = get_user_id(event)

    try:
        if method == "GET":
            profile = get_profile(user_id)
            return response(200, {"profile": profile})

        if method == "PUT":
            data = parse_body(event)
            profile, err = update_profile(user_id, data)
            if err:
                return response(400, {"error": err})
            return response(200, {"profile": profile})

        return response(405, {"error": "Method not allowed"})
    except Exception as e:
        return response(500, {"error": str(e)})
