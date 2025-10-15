import os
import base64
import json
import re
from datetime import datetime, timezone
from typing import Tuple, Dict, Any

import requests
from pymongo import MongoClient

from django.conf import settings


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")


def encode_image_file_to_base64(file_obj) -> str:
    """Read an uploaded file-like object and return a base64 data URI string."""
    content = file_obj.read()
    b64 = base64.b64encode(content).decode("utf-8")
    # We don't know the image type reliably; use jpeg as a safe default
    return f"data:image/jpeg;base64,{b64}"


def call_openai_vision(image_data_uri: str) -> str:
    """Call OpenAI's GPT-4o vision-style endpoint and return raw extracted text.

    This implementation uses the OpenAI HTTP API with a generic chat/completions
    style request that includes the image as a data URI in the user message.
    Adjust if you have an SDK available.
    """
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY environment variable is required")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}

    system = "You are an OCR assistant. Extract all visible text from the provided invoice image. Return plain text only."
    user = {
        "role": "user",
        "content": [
            {"type": "text", "text": "Extract all visible text from this invoice image."},
            {"type": "image_url", "image_url": {"url": image_data_uri}}
        ]
    }

    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user["content"])},
        ],
        "temperature": 0
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    # Try to extract a sensible text from the response structure
    try:
        # OpenAI Chat API returns choices -> message -> content
        content = data["choices"][0]["message"]["content"]
        return content
    except Exception:
        # Fallback: return full JSON string
        return json.dumps(data)


def parse_invoice_data(raw_text: str) -> Dict[str, Any]:
    """Ask the model to convert raw OCR text to a structured JSON dict.

    We send a short prompt asking for specific fields and then attempt to
    load JSON from the model's reply. If parsing fails we return an error
    field with the raw content for debugging.
    """
    prompt = (
        "You are an expert invoice parser. From the following invoice text, "
        "extract these fields and return valid JSON only:\n"
        "{\n  \"Vendor Details\": {\n    \"Name\": \"\",\n    \"Address\": \"\",\n    \"Tax Number\": \"\",\n    \"Phone Number\": \"\"\n  },\n  \"Invoice Details\": {\n    \"Invoice Number\": \"\",\n    \"Invoice Date\": \"\",\n    \"Type of Invoice\": \"\"\n  },\n  \"Invoice Items\": [\n    {\n      \"Name\": \"\",\n      \"Quantity\": \"\",\n      \"HSN_SAC_code\": \"\",\n      \"Rate\": \"\"\n    }\n  ],\n  \"Overall\": {\n    \"Total Invoice Value\": \"\",\n    \"GST Value\": \"\"\n  }\n}"
    )

    # Use the same Chat completions endpoint but with a parsing instruction
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY environment variable is required")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    messages = [
        {"role": "system", "content": "You are a helpful parser that outputs JSON only."},
        {"role": "user", "content": prompt + "\n\nHere is the extracted text:\n" + raw_text}
    ]

    resp = requests.post(url, headers=headers, json={"model": "gpt-4o", "messages": messages, "temperature": 0}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        content = json.dumps(data)

    # Strip code fences if present
    content = re.sub(r"^```(json)?", "", content)
    content = re.sub(r"```$", "", content).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"error": "Could not parse JSON", "raw": content}


def store_invoice_data(invoice_data: Dict[str, Any], source_filename: str = None) -> str:
    """Store invoice_data into MongoDB and return inserted_id as string."""
    if not MONGO_URI:
        raise RuntimeError("MONGO_URI environment variable is required")

    client = MongoClient(MONGO_URI)
    db = client.get_database("invoice_ai")
    invoices = db.invoices

    def sanitize_for_mongo(obj):
        if isinstance(obj, dict):
            new = {}
            for k, v in obj.items():
                new_key = k.replace('.', '_')
                if new_key.startswith('$'):
                    new_key = '_' + new_key[1:]
                new[new_key] = sanitize_for_mongo(v)
            return new
        if isinstance(obj, list):
            return [sanitize_for_mongo(i) for i in obj]
        return obj

    sanitized = sanitize_for_mongo(invoice_data)
    record = {"invoice_data": sanitized, "processed_at": datetime.now(timezone.utc)}
    if source_filename:
        record["source_image"] = source_filename

    res = invoices.insert_one(record)
    return str(res.inserted_id)


def process_invoice(uploaded_file) -> Tuple[Dict[str, Any], str]:
    """Full pipeline: take uploaded file (InMemoryUploadedFile or similar),
    run OCR via OpenAI, parse the invoice to structured JSON and return (data, raw_text).
    """
    image_data_uri = encode_image_file_to_base64(uploaded_file)
    raw_text = call_openai_vision(image_data_uri)
    parsed = parse_invoice_data(raw_text)
    return parsed, raw_text
