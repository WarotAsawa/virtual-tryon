"""Virtual Try-On Lambda — Clean Architecture handler.

Domain: TryOn session entity
Use Cases: create virtual try-on session using Amazon Nova Canvas
Interface: API Gateway event → response
"""
import base64
import io
import json
import os
import uuid
import time
import traceback
from datetime import datetime

import boto3
from botocore.config import Config
from PIL import Image
from shared.utils import response, get_user_id, parse_body

TRYON_TABLE = os.environ["TRYON_TABLE"]
IMAGES_BUCKET = os.environ["IMAGES_BUCKET"]
PRODUCTS_TABLE = os.environ["PRODUCTS_TABLE"]
MODEL_ID = os.environ.get("MODEL_ID", "amazon.nova-canvas-v1:0")

ddb = boto3.resource("dynamodb")
tryon_table = ddb.Table(TRYON_TABLE)
products_table = ddb.Table(PRODUCTS_TABLE)
s3 = boto3.client("s3")
bedrock = boto3.client("bedrock-runtime", region_name="us-east-1", config=Config(read_timeout=300))

# Valid garment classes for Nova Canvas VIRTUAL_TRY_ON
VALID_GARMENT_CLASSES = {
    "UPPER_BODY", "LOWER_BODY", "FULL_BODY", "FOOTWEAR",
    "LONG_SLEEVE_SHIRT", "SHORT_SLEEVE_SHIRT", "NO_SLEEVE_SHIRT",
    "OTHER_UPPER_BODY", "LONG_PANTS", "SHORT_PANTS", "OTHER_LOWER_BODY",
    "LONG_DRESS", "SHORT_DRESS", "FULL_BODY_OUTFIT", "OTHER_FULL_BODY",
    "SHOES", "BOOTS", "OTHER_FOOTWEAR",
}


# ── Domain Entity ──
def make_tryon_session(user_id: str, product_id: str, result_key: str) -> dict:
    session_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    ttl = int(time.time()) + 86400 * 7  # 7 days
    return {
        "PK": f"USER#{user_id}",
        "SK": f"TRYON#{session_id}",
        "session_id": session_id,
        "user_id": user_id,
        "product_id": product_id,
        "result_key": result_key,
        "status": "COMPLETED",
        "created_at": now,
        "ttl": ttl,
    }


# ── Use Cases ──
MAX_PIXELS = 4194304  # Nova Canvas limit

def prepare_image_b64(raw_b64: str) -> str:
    """Strip alpha channel and resize if too large, return JPEG base64."""
    data = base64.b64decode(raw_b64)
    img = Image.open(io.BytesIO(data))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    w, h = img.size
    if w * h > MAX_PIXELS:
        scale = (MAX_PIXELS / (w * h)) ** 0.5
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def invoke_virtual_tryon(source_b64: str, reference_b64: str, garment_class: str) -> bytes:
    """Call Amazon Nova Canvas VIRTUAL_TRY_ON API."""
    body = json.dumps({
        "taskType": "VIRTUAL_TRY_ON",
        "virtualTryOnParams": {
            "sourceImage": source_b64,
            "referenceImage": reference_b64,
            "maskType": "GARMENT",
            "garmentBasedMask": {
                "garmentClass": garment_class,
            },
            "mergeStyle": "SEAMLESS",
        },
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "quality": "standard",
            "cfgScale": 6.5,
        },
    })

    resp = bedrock.invoke_model(
        body=body,
        modelId=MODEL_ID,
        accept="application/json",
        contentType="application/json",
    )
    resp_body = json.loads(resp["body"].read())

    if resp_body.get("error"):
        raise RuntimeError(f"Nova Canvas error: {resp_body['error']}")

    image_b64 = resp_body["images"][0]
    return base64.b64decode(image_b64.encode("ascii"))


def create_tryon(user_id: str, data: dict):
    """Orchestrate a virtual try-on session."""
    product_id = data.get("product_id")
    source_image_b64 = data.get("source_image")  # base64 user photo

    if not product_id or not source_image_b64:
        return None, "product_id and source_image (base64) are required"

    # Fetch product to get garment image and class
    product = products_table.get_item(
        Key={"PK": f"PRODUCT#{product_id}", "SK": "METADATA"}
    ).get("Item")
    if not product:
        return None, "Product not found"

    garment_class = product.get("garment_class", "UPPER_BODY")
    if garment_class not in VALID_GARMENT_CLASSES:
        garment_class = "UPPER_BODY"

    # Get product image from S3 as base64
    image_key = product.get("image_key")
    if not image_key:
        return None, "Product has no image"

    obj = s3.get_object(Bucket=IMAGES_BUCKET, Key=image_key)
    reference_b64 = base64.b64encode(obj["Body"].read()).decode("utf-8")

    # Invoke Nova Canvas
    source_clean = prepare_image_b64(source_image_b64)
    reference_clean = prepare_image_b64(reference_b64)
    result_bytes = invoke_virtual_tryon(source_clean, reference_clean, garment_class)

    # Save result to S3
    result_key = f"tryon/{user_id}/{uuid.uuid4()}.png"
    s3.put_object(Bucket=IMAGES_BUCKET, Key=result_key, Body=result_bytes, ContentType="image/png")

    # Save session to DynamoDB
    session = make_tryon_session(user_id, product_id, result_key)
    tryon_table.put_item(Item=session)

    # Generate presigned URL for result
    session["result_url"] = s3.generate_presigned_url(
        "get_object", Params={"Bucket": IMAGES_BUCKET, "Key": result_key}, ExpiresIn=3600
    )
    return session, None


def get_tryon_session(user_id: str, session_id: str):
    resp = tryon_table.get_item(Key={"PK": f"USER#{user_id}", "SK": f"TRYON#{session_id}"})
    item = resp.get("Item")
    if item and item.get("result_key"):
        item["result_url"] = s3.generate_presigned_url(
            "get_object", Params={"Bucket": IMAGES_BUCKET, "Key": item["result_key"]}, ExpiresIn=3600
        )
    return item


# ── Interface Adapter ──
def handler(event, context):
    method = event["httpMethod"]
    path_params = event.get("pathParameters") or {}
    user_id = get_user_id(event)
    session_id = path_params.get("session_id")

    try:
        if method == "POST":
            data = parse_body(event)
            session, err = create_tryon(user_id, data)
            if err:
                return response(400, {"error": err})
            return response(201, {"tryon_session": session})

        if method == "GET" and session_id:
            session = get_tryon_session(user_id, session_id)
            if not session:
                return response(404, {"error": "Session not found"})
            return response(200, {"tryon_session": session})

        return response(405, {"error": "Method not allowed"})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return response(500, {"error": str(e)})
