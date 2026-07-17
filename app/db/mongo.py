from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app.core.config import get_settings


class GenerationStore(Protocol):
    def insert(self, document: dict[str, Any]) -> str:
        """Persist a generation payload and return its store id."""

    def get(self, document_id: str) -> dict[str, Any] | None:
        """Fetch a stored generation payload by id."""


class MongoGenerationStore:
    def __init__(self, collection: Collection):
        self._collection = collection

    def insert(self, document: dict[str, Any]) -> str:
        result = self._collection.insert_one(document)
        return str(result.inserted_id)

    def get(self, document_id: str) -> dict[str, Any] | None:
        from bson import ObjectId

        try:
            oid = ObjectId(document_id)
        except Exception:
            return None
        doc = self._collection.find_one({"_id": oid})
        if doc is None:
            return None
        doc["_id"] = str(doc["_id"])
        return doc


class InMemoryGenerationStore:
    """Test double that avoids requiring a live MongoDB."""

    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self._counter = 0

    def insert(self, document: dict[str, Any]) -> str:
        self._counter += 1
        doc_id = f"mem-{self._counter}"
        stored = dict(document)
        stored["_id"] = doc_id
        self.documents[doc_id] = stored
        return doc_id

    def get(self, document_id: str) -> dict[str, Any] | None:
        doc = self.documents.get(document_id)
        if doc is None:
            return None
        return dict(doc)


@lru_cache
def get_mongo_client() -> MongoClient:
    settings = get_settings()
    return MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=3000)


def get_mongo_db() -> Database:
    settings = get_settings()
    return get_mongo_client()[settings.mongo_db_name]


def get_generation_store() -> GenerationStore:
    collection = get_mongo_db()["qa_generations"]
    return MongoGenerationStore(collection)
