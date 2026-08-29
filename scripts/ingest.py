"""Validate documents and optionally upsert them to Pinecone."""
import json
from pathlib import Path

from app.config import get_settings
from app.retrieval import local_embedding


def main() -> None:
    settings = get_settings()
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in Path("data/documents").glob("*.json")]
    required = {"department", "document_type", "access_level", "created_date"}
    for document in documents:
        missing = required - document["metadata"].keys()
        if missing:
            raise ValueError(f"{document['id']} missing metadata: {missing}")
    if not settings.pinecone_api_key:
        print(f"Validated {len(documents)} documents. Pinecone key absent; local index will be used.")
        return
    from pinecone import Pinecone

    index = Pinecone(api_key=settings.pinecone_api_key).Index(settings.pinecone_index)
    vectors = [
        {"id": doc["id"], "values": local_embedding(doc["content"]),
         "metadata": {**doc["metadata"], "title": doc["title"], "text": doc["content"]}}
        for doc in documents
    ]
    index.upsert(vectors=vectors, namespace=settings.pinecone_namespace)
    print(f"Upserted {len(vectors)} documents to namespace {settings.pinecone_namespace}.")


if __name__ == "__main__":
    main()
