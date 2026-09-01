import os
import json
import uuid
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTION_NAME = "aegis_memories"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2 vector dimension

_model_instance: Optional[SentenceTransformer] = None
_qdrant_client_instance: Optional[QdrantClient] = None

def get_embedding_model() -> SentenceTransformer:
    global _model_instance
    if _model_instance is None:
        _model_instance = SentenceTransformer("all-MiniLM-L6-v2")
    return _model_instance

def get_qdrant_client(force_new: bool = False) -> QdrantClient:
    global _qdrant_client_instance
    if force_new and _qdrant_client_instance is not None:
        try:
            _qdrant_client_instance.close()
        except Exception:
            pass
        _qdrant_client_instance = None

    if _qdrant_client_instance is None:
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        try:
            client = QdrantClient(url=qdrant_url, timeout=2.0)
            client.get_collections()
            _qdrant_client_instance = client
            print(f"[MEMORY ENGINE] Connected to containerized Qdrant at {qdrant_url}")
        except Exception:
            local_path = os.path.join(ROOT_DIR, "memory_engine", "qdrant_storage")
            os.makedirs(local_path, exist_ok=True)
            _qdrant_client_instance = QdrantClient(path=local_path)
            print(
                "WARNING: Qdrant container unreachable — falling back to embedded "
                "disk storage at memory_engine/qdrant_storage. Data will NOT persist "
                "if this fallback was unintended."
            )

        ensure_collection_exists(_qdrant_client_instance)
    return _qdrant_client_instance

def ensure_collection_exists(client: QdrantClient):
    try:
        collections = [c.name for c in client.get_collections().collections]
        if COLLECTION_NAME not in collections:
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
            )
    except Exception:
        pass

def embed_text(text: str) -> List[float]:
    model = get_embedding_model()
    vec = model.encode(text, convert_to_numpy=True)
    return vec.tolist()

def remember(
    incident_id: str,
    fault_signature: str,
    action_taken: Dict[str, Any],
    outcome: str,
    resolution_time_seconds: float
) -> Dict[str, Any]:
    """
    Embeds fault_signature and stores structured fact in Qdrant.
    """
    client = get_qdrant_client()
    vector = embed_text(fault_signature)
    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{incident_id}_{datetime.now(timezone.utc).timestamp()}"))

    payload = {
        "incident_id": incident_id,
        "fault_signature": fault_signature,
        "action_taken": action_taken,
        "outcome": outcome,
        "resolution_time_seconds": float(resolution_time_seconds),
        "hit_count": 1,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload=payload
            )
        ]
    )

    return {"point_id": point_id, "payload": payload}

def recall(fault_signature: str, similarity_threshold: float = 0.80) -> Optional[Dict[str, Any]]:
    """
    Embeds fault_signature, queries Qdrant for closest memory above similarity_threshold.
    CRITICAL SAFETY FILTER: Only returns memories with outcome == 'resolved' or 'success'.
    """
    client = get_qdrant_client()
    query_vector = embed_text(fault_signature)

    try:
        results = []
        if hasattr(client, "query_points"):
            res_obj = client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                score_threshold=similarity_threshold,
                limit=5
            )
            results = getattr(res_obj, "points", []) or []
        else:
            results = client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                score_threshold=similarity_threshold,
                limit=5
            ) or []

        for res in results:
            payload = res.payload or {}
            outcome = str(payload.get("outcome", "")).lower()
            # Safety check: only recall successful resolutions
            if outcome in ("resolved", "success"):
                result_payload = payload.copy()
                score = float(getattr(res, "score", 0.0))
                result_payload["confidence"] = score
                result_payload["similarity_score"] = score
                return result_payload

    except Exception:
        pass

    return None

def consolidate(similarity_threshold: float = 0.95) -> Dict[str, Any]:
    """
    Scans Qdrant memories, finds duplicate entries sharing high similarity (>0.95)
    and identical successful action_taken, merges them into a canonical runbook entry,
    updating hit_count and rolling average resolution_time_seconds.
    """
    client = get_qdrant_client()
    try:
        records, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=100,
            with_payload=True,
            with_vectors=True
        )

        if not records:
            return {"merged_count": 0, "remaining_count": 0}

        resolved_records = [r for r in records if str((r.payload or {}).get("outcome", "")).lower() in ("resolved", "success")]
        
        merged_point_ids = set()
        for i in range(len(resolved_records)):
            r1 = resolved_records[i]
            if r1.id in merged_point_ids:
                continue

            v1 = np.array(r1.vector)
            p1 = r1.payload or {}
            act1 = p1.get("action_taken")

            group = [r1]
            for j in range(i + 1, len(resolved_records)):
                r2 = resolved_records[j]
                if r2.id in merged_point_ids:
                    continue

                v2 = np.array(r2.vector)
                p2 = r2.payload or {}
                act2 = p2.get("action_taken")

                if act1 == act2:
                    dot = np.dot(v1, v2)
                    norm = np.linalg.norm(v1) * np.linalg.norm(v2)
                    sim = dot / norm if norm > 0 else 0.0
                    if sim >= similarity_threshold:
                        group.append(r2)

            if len(group) > 1:
                total_hits = sum(int((g.payload or {}).get("hit_count", 1)) for g in group)
                avg_time = sum(float((g.payload or {}).get("resolution_time_seconds", 0.0)) for g in group) / len(group)

                canonical = group[0]
                new_payload = canonical.payload.copy()
                new_payload["hit_count"] = total_hits
                new_payload["resolution_time_seconds"] = round(avg_time, 2)
                new_payload["consolidated"] = True

                client.upsert(
                    collection_name=COLLECTION_NAME,
                    points=[PointStruct(id=canonical.id, vector=canonical.vector, payload=new_payload)]
                )

                to_delete = [g.id for g in group[1:]]
                for d_id in to_delete:
                    merged_point_ids.add(d_id)
                client.delete(collection_name=COLLECTION_NAME, points_selector=to_delete)

        remaining_records, _ = client.scroll(collection_name=COLLECTION_NAME, limit=100)
        return {"merged_count": len(merged_point_ids), "remaining_count": len(remaining_records)}

    except Exception as e:
        return {"merged_count": 0, "error": str(e)}
