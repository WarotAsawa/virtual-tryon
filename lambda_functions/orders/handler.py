"""Orders Lambda — Clean Architecture handler.

Domain: Order entity
Use Cases: create order, list user orders, get order
Interface: API Gateway event → response
"""
import json
import os
import uuid
from datetime import datetime
from decimal import Decimal

import boto3
from shared.utils import response, get_user_id, parse_body

ORDERS_TABLE = os.environ["ORDERS_TABLE"]
PRODUCTS_TABLE = os.environ["PRODUCTS_TABLE"]
ddb = boto3.resource("dynamodb")
orders_table = ddb.Table(ORDERS_TABLE)
products_table = ddb.Table(PRODUCTS_TABLE)


# ── Domain Entity ──
def make_order(user_id: str, items: list, total: Decimal) -> dict:
    order_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    return {
        "PK": f"USER#{user_id}",
        "SK": f"ORDER#{order_id}",
        "order_id": order_id,
        "user_id": user_id,
        "items": items,
        "total": str(total),
        "status": "PENDING",
        "created_at": now,
    }


# ── Use Cases ──
def create_order(user_id: str, data: dict):
    cart_items = data.get("items", [])
    if not cart_items:
        return None, "items required"

    total = Decimal("0")
    resolved = []
    for ci in cart_items:
        product = products_table.get_item(
            Key={"PK": f"PRODUCT#{ci['product_id']}", "SK": "METADATA"}
        ).get("Item")
        if not product:
            return None, f"Product {ci['product_id']} not found"
        line_total = Decimal(product["price"]) * ci.get("quantity", 1)
        total += line_total
        resolved.append({
            "product_id": ci["product_id"],
            "name": product["name"],
            "size": ci.get("size", ""),
            "color": ci.get("color", ""),
            "quantity": ci.get("quantity", 1),
            "unit_price": product["price"],
            "line_total": str(line_total),
        })

    order = make_order(user_id, resolved, total)
    orders_table.put_item(Item=order)
    return order, None


def list_orders(user_id: str):
    resp = orders_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={":pk": f"USER#{user_id}", ":sk": "ORDER#"},
        ScanIndexForward=False,
    )
    return resp.get("Items", [])


def get_order(user_id: str, order_id: str):
    resp = orders_table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"ORDER#{order_id}"})
    return resp.get("Item")


# ── Interface Adapter ──
def handler(event, context):
    method = event["httpMethod"]
    path_params = event.get("pathParameters") or {}
    user_id = get_user_id(event)
    order_id = path_params.get("order_id")

    try:
        if method == "POST":
            data = parse_body(event)
            order, err = create_order(user_id, data)
            if err:
                return response(400, {"error": err})
            return response(201, {"order": order})

        if method == "GET" and not order_id:
            orders = list_orders(user_id)
            return response(200, {"orders": orders})

        if method == "GET" and order_id:
            order = get_order(user_id, order_id)
            if not order:
                return response(404, {"error": "Order not found"})
            return response(200, {"order": order})

        return response(405, {"error": "Method not allowed"})
    except Exception as e:
        return response(500, {"error": str(e)})
