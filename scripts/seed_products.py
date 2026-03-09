#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["boto3"]
# ///
"""Generate 100 fashion product catalogs using Claude + Nova Canvas, store in DynamoDB + S3."""
import base64
import json
import os
import sys
import time
import uuid
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config

# ── Config ──
REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-1")
TABLE_NAME = os.environ.get("PRODUCTS_TABLE", "FashionDbStack-ProductsTable241ADBFF-1WAC93U2WYX7E")
BUCKET_NAME = os.environ.get("IMAGES_BUCKET", "fashionstoragestack-imagesbucket1e86afb2-j1kdoozaoqxz")
CLAUDE_MODEL = "apac.anthropic.claude-3-haiku-20240307-v1:0"
NOVA_MODEL = "amazon.nova-canvas-v1:0"
NOVA_REGION = "us-east-1"  # Nova Canvas only available here
TOTAL_PRODUCTS = 100
BATCH_SIZE = 10  # Generate catalog metadata in batches of 10

bedrock = boto3.client("bedrock-runtime", region_name=REGION, config=Config(read_timeout=300))
bedrock_nova = boto3.client("bedrock-runtime", region_name=NOVA_REGION, config=Config(read_timeout=300))
ddb = boto3.resource("dynamodb", region_name=REGION)
s3 = boto3.client("s3", region_name=REGION)
table = ddb.Table(TABLE_NAME)

CATEGORIES = ["tops", "outerwear", "bottoms", "dresses", "footwear", "accessories"]
GARMENT_MAP = {
    "tops": "UPPER_BODY",
    "outerwear": "UPPER_BODY",
    "bottoms": "LOWER_BODY",
    "dresses": "FULL_BODY",
    "footwear": "FOOTWEAR",
    "accessories": "UPPER_BODY",
}


def generate_catalog_batch(batch_num: int, batch_size: int) -> list:
    """Use Claude to generate a batch of product metadata."""
    prompt = f"""Generate exactly {batch_size} unique fashion product entries as a JSON array.
Each product must have:
- "name": creative, distinctive product name (e.g. "Riviera Linen Blazer")
- "description": 1-2 sentence product description
- "price": realistic price as integer (50-800 range)
- "category": one of {CATEGORIES}
- "sizes": array of available sizes
- "colors": array of 1-3 color names
- "image_prompt": a detailed prompt to generate a product photo (white background, studio lighting, no human model, just the garment/item flat lay or on mannequin)

Batch {batch_num} — make these distinct from other batches. Vary styles, price points, and aesthetics.
Return ONLY the JSON array, no markdown fences."""

    resp = bedrock.invoke_model(
        modelId=CLAUDE_MODEL,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }),
    )
    text = json.loads(resp["body"].read())["content"][0]["text"]
    # Extract JSON array from response
    start = text.index("[")
    end = text.rindex("]") + 1
    return json.loads(text[start:end])


def generate_image(prompt: str) -> bytes:
    """Use Nova Canvas to generate a product image."""
    body = json.dumps({
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {
            "text": prompt,
            "negativeText": "blurry, low quality, distorted, watermark, text overlay, human face",
        },
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "height": 1024,
            "width": 1024,
            "cfgScale": 8.0,
            "seed": int(time.time() * 1000) % 2147483646,
        },
    })
    resp = bedrock_nova.invoke_model(
        modelId=NOVA_MODEL, body=body, accept="application/json", contentType="application/json"
    )
    resp_body = json.loads(resp["body"].read())
    if resp_body.get("error"):
        raise RuntimeError(f"Nova Canvas error: {resp_body['error']}")
    return base64.b64decode(resp_body["images"][0].encode("ascii"))


def save_product(product: dict) -> dict:
    """Generate image, upload to S3, write to DynamoDB."""
    product_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    category = product["category"]
    image_key = f"products/{product_id}/main.png"

    # Generate and upload image
    image_bytes = generate_image(product["image_prompt"])
    s3.put_object(Bucket=BUCKET_NAME, Key=image_key, Body=image_bytes, ContentType="image/png")

    # Write to DynamoDB
    item = {
        "PK": f"PRODUCT#{product_id}",
        "SK": "METADATA",
        "GSI1PK": f"CATEGORY#{category}",
        "GSI1SK": f"PRODUCT#{now}",
        "product_id": product_id,
        "name": product["name"],
        "description": product.get("description", ""),
        "price": str(product["price"]),
        "category": category,
        "sizes": product.get("sizes", ["S", "M", "L"]),
        "colors": product.get("colors", ["Black"]),
        "image_key": image_key,
        "garment_class": GARMENT_MAP.get(category, "UPPER_BODY"),
        "created_by": "seed-script",
        "created_at": now,
        "updated_at": now,
    }
    table.put_item(Item=item)
    return item


def main():
    print(f"\n🚀 Generating {TOTAL_PRODUCTS} fashion products")
    print(f"   Table:  {TABLE_NAME}")
    print(f"   Bucket: {BUCKET_NAME}")
    print(f"   Region: {REGION}\n")

    all_products = []
    num_batches = TOTAL_PRODUCTS // BATCH_SIZE

    # Step 1: Generate all catalog metadata via Claude
    print("📝 Step 1/2 — Generating catalog metadata with Claude...\n")
    for i in range(num_batches):
        try:
            batch = generate_catalog_batch(i + 1, BATCH_SIZE)
            all_products.extend(batch)
            print(f"   ✅ Batch {i+1}/{num_batches} — {len(batch)} products generated")
        except Exception as e:
            print(f"   ❌ Batch {i+1}/{num_batches} failed: {e}")
        time.sleep(1)  # Rate limit courtesy

    print(f"\n   📦 Total metadata: {len(all_products)} products\n")

    # Step 2: Generate images + save (parallel, 3 workers to respect Bedrock limits)
    print("🎨 Step 2/2 — Generating images with Nova Canvas & saving...\n")
    success = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(save_product, p): p for p in all_products}
        for future in as_completed(futures):
            product = futures[future]
            try:
                item = future.result()
                success += 1
                print(f"   ✅ [{success+failed}/{len(all_products)}] {product['name']}")
            except Exception as e:
                failed += 1
                print(f"   ❌ [{success+failed}/{len(all_products)}] {product['name']}: {e}")

    print(f"\n{'━' * 50}")
    print(f"🎉 Done! {success} products created, {failed} failed")
    print(f"   DynamoDB: {TABLE_NAME}")
    print(f"   S3:       s3://{BUCKET_NAME}/products/\n")


if __name__ == "__main__":
    main()
