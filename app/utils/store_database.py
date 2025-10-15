"""MongoDB storage helpers for invoice records.

This module provides a small, importable API used by the invoice
processing pipeline. It keeps a cached MongoClient and exposes
helpers to insert and retrieve invoice documents.

Environment variables:
- MONGO_URI (required)
- MONGO_DB (optional, defaults to 'invoice_ai')
- MONGO_COLLECTION (optional, defaults to 'invoices')
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from pymongo import MongoClient


MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "invoice_ai")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "invoices")

# Module-level cached client to avoid reconnecting on every call
_client: Optional[MongoClient] = None


def _get_client() -> MongoClient:
	global _client
	if _client is None:
		if not MONGO_URI:
			raise RuntimeError("MONGO_URI environment variable is required")
		_client = MongoClient(MONGO_URI)
	return _client


def _get_collection():
	client = _get_client()
	db = client.get_database(MONGO_DB)
	return db[MONGO_COLLECTION]


def sanitize_for_mongo(obj: Any) -> Any:
	"""Recursively sanitize dictionary keys so they're safe for MongoDB.

	- Replace '.' with '_' in keys
	- Avoid keys starting with '$' by prefixing with '_'
	"""
	if isinstance(obj, dict):
		new: Dict[str, Any] = {}
		for k, v in obj.items():
			new_key = k.replace(".", "_")
			if new_key.startswith("$"):
				new_key = "_" + new_key[1:]
			new[new_key] = sanitize_for_mongo(v)
		return new
	if isinstance(obj, list):
		return [sanitize_for_mongo(i) for i in obj]
	return obj


def store_invoice_data(invoice_data: Dict[str, Any], source_filename: Optional[str] = None) -> str:
	"""Insert an invoice record and return the inserted_id as string."""
	coll = _get_collection()
	sanitized = sanitize_for_mongo(invoice_data)
	
	record = {
		"invoice_data": sanitized,
		"processed_at": datetime.now(timezone.utc),
		"error": sanitized.get("error", "")  # Store error field at top level for easier querying
	}
	
	if source_filename:
		record["source_image"] = source_filename

	res = coll.insert_one(record)
	return str(res.inserted_id)


def list_invoices(limit: int = 50) -> List[Dict[str, Any]]:
	"""Return a list of recent invoice documents."""
	coll = _get_collection()
	docs = coll.find().sort("processed_at", -1).limit(limit)
	return list(docs)


def get_invoice_by_id(doc_id: Any) -> Optional[Dict[str, Any]]:
	"""Fetch a single invoice by its _id. Input should be an ObjectId or string."""
	from bson import ObjectId

	coll = _get_collection()
	try:
		oid = ObjectId(doc_id) if not isinstance(doc_id, ObjectId) else doc_id
	except Exception:
		return None
	return coll.find_one({"_id": oid})

