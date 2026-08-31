def get_current_metrics(incident_id: str) -> dict:
    """
    Returns a stubbed metrics and logs payload for a given incident_id.
    Simulates target system telemetry for Detective agent analysis.
    """
    id_lower = incident_id.lower()
    if "memory" in id_lower or "oom" in id_lower:
        return {
            "incident_id": incident_id,
            "cpu_percent": 45.2,
            "memory_percent": 96.8,
            "error_rate": 0.12,
            "active_connections": 450,
            "recent_log_lines": [
                "ERROR: OutOfMemoryError: Java heap space",
                "WARNING: Worker process memory usage exceeded threshold (95%)",
                "ERROR: Service checkout-v1 health check failed (timeout)"
            ]
        }
    elif "cpu" in id_lower or "spike" in id_lower:
        return {
            "incident_id": incident_id,
            "cpu_percent": 98.4,
            "memory_percent": 55.0,
            "error_rate": 0.05,
            "active_connections": 1200,
            "recent_log_lines": [
                "WARNING: CPU usage 98.4% high contention on pool worker thread",
                "ERROR: Response latency 5200ms exceeds 500ms SLA limit"
            ]
        }
    else:
        return {
            "incident_id": incident_id,
            "cpu_percent": 82.0,
            "memory_percent": 88.5,
            "error_rate": 0.08,
            "active_connections": 600,
            "recent_log_lines": [
                "ERROR: Connection pool exhaustion detected in DB driver",
                "WARNING: Response time spike on /api/v1/checkout - 4200ms",
                "ERROR: Database query timeout after 30s"
            ]
        }
