"""Products Lambda — Clean Architecture handler.

Domain: Product entity
Use Cases: list, get, create, update, delete products
Interface: API Gateway event → response
"""
import json
import os
import uuid
from datetime import datetime

import boto3
from shared.utils import response, get_user_id, parse_body

TABLE_NAME = os.environ["PRODUCTS_TABLE"]
BUCKET = os.environ["IMAGES_BUCKET"]
ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE_NAME)
s3 = boto3.client("s3")


# ── Domain Entity ──
def make_product(data: dict, user_id: str) -> dict:
    product_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    return {
        "PK": f"PRODUCT#{product_id}",
        "SK": "METADATA",
        "GSI1PK": f"CATEGORY#{data.get('category', 'general')}",
        "GSI1SK": f"PRODUCT#{now}",
        "product_id": product_id,
        "name": data["name"],
        "description": data.get("description", ""),
        "price": str(data["price"]),
        "category": data.get("category", "general"),
        "sizes": data.get("sizes", []),
        "colors": data.get("colors", []),
        "image_key": data.get("image_key", ""),
        "garment_class": data.get("garment_class", "UPPER_BODY"),
        "created_by": user_id,
        "created_at": now,
        "updated_at": now,
    }


# ── Use Cases ──
def list_products(category: str = None):
    if category:
        resp = table.query(
            IndexName="GSI1",
            KeyConditionExpression="GSI1PK = :pk",
            ExpressionAttributeValues={":pk": f"CATEGORY#{category}"},
        )
    else:
        resp = table.scan(FilterExpression="SK = :sk", ExpressionAttributeValues={":sk": "METADATA"})
    items = resp.get("Items", [])
    for item in items:
        if item.get("image_key"):
            item["image_url"] = s3.generate_presigned_url(
                "get_object", Params={"Bucket": BUCKET, "Key": item["image_key"]}, ExpiresIn=3600
            )
    return items


def get_product(product_id: str):
    resp = table.get_item(Key={"PK": f"PRODUCT#{product_id}", "SK": "METADATA"})
    item = resp.get("Item")
    if item and item.get("image_key"):
        item["image_url"] = s3.generate_presigned_url(
            "get_object", Params={"Bucket": BUCKET, "Key": item["image_key"]}, ExpiresIn=3600
        )
    return item


def create_product(data: dict, user_id: str):
    item = make_product(data, user_id)
    table.put_item(Item=item)
    # Generate presigned upload URL if no image yet
    upload_url = None
    if not item["image_key"]:
        key = f"products/{item['product_id']}/main.jpg"
        item["image_key"] = key
        table.update_item(
            Key={"PK": item["PK"], "SK": "METADATA"},
            UpdateExpression="SET image_key = :k",
            ExpressionAttributeValues={":k": key},
        )
        upload_url = s3.generate_presigned_url(
            "put_object", Params={"Bucket": BUCKET, "Key": key, "ContentType": "image/jpeg"}, ExpiresIn=3600
        )
    return item, upload_url


def update_product(product_id: str, data: dict):
    now = datetime.utcnow().isoformat()
    expr_parts, values = ["updated_at = :now"], {":now": now}
    for field in ("name", "description", "price", "category", "sizes", "colors", "garment_class"):
        if field in data:
            expr_parts.append(f"{field} = :{field}")
            values[f":{field}"] = str(data[field]) if field == "price" else data[field]
    table.update_item(
        Key={"PK": f"PRODUCT#{product_id}", "SK": "METADATA"},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeValues=values,
    )
    return get_product(product_id)


def delete_product(product_id: str):
    table.delete_item(Key={"PK": f"PRODUCT#{product_id}", "SK": "METADATA"})


# ── Interface Adapter ──
def handler(event, context):
    method = event["httpMethod"]
    path_params = event.get("pathParameters") or {}
    qs = event.get("queryStringParameters") or {}
    product_id = path_params.get("product_id")

    try:
        if method == "GET" and not product_id:
            items = list_products(qs.get("category"))
            return response(200, {"products": items})

        if method == "GET" and product_id:
            item = get_product(product_id)
            if not item:
                return response(404, {"error": "Product not found"})
            return response(200, {"product": item})

        if method == "POST":
            data = parse_body(event)
            if not data.get("name") or data.get("price") is None:
                return response(400, {"error": "name and price are required"})
            item, upload_url = create_product(data, get_user_id(event))
            body = {"product": item}
            if upload_url:
                body["upload_url"] = upload_url
            return response(201, body)

        if method == "PUT" and product_id:
            item = update_product(product_id, parse_body(event))
            return response(200, {"product": item})

        if method == "DELETE" and product_id:
            delete_product(product_id)
            return response(200, {"message": "Deleted"})

        return response(405, {"error": "Method not allowed"})
    except Exception as e:
        return response(500, {"error": str(e)})
