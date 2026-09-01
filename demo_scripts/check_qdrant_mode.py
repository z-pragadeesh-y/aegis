import sys
import os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def check_qdrant_mode():
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=qdrant_url, timeout=2.0)
        client.get_collections()
        print(f"[QDRANT MODE CHECK] Connected to CONTAINERIZED Qdrant at {qdrant_url}")
        sys.exit(0)
    except Exception as e:
        print(
            f"WARNING: Qdrant container unreachable at {qdrant_url} — "
            f"falling back to embedded disk storage at memory_engine/qdrant_storage. "
            f"Data will NOT persist across container restarts if this fallback was unintended. ({e})"
        )
        sys.exit(1)

if __name__ == "__main__":
    check_qdrant_mode()
