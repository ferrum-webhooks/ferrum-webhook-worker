metrics = {
    "events_processed": 0,
    "delivery_success": 0,
    "delivery_failure": 0,
    "delivery_latency": [],
}

def record_event():
    metrics["events_processed"] += 1


def record_success(latency: float):
    metrics["delivery_success"] += 1
    metrics["delivery_latency"].append(latency)


def record_failure():
    metrics["delivery_failure"] += 1


def get_metrics():
    latencies = metrics["delivery_latency"]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0

    return {
        "events_processed": metrics["events_processed"],
        "delivery_success": metrics["delivery_success"],
        "delivery_failure": metrics["delivery_failure"],
        "avg_delivery_latency": round(avg_latency, 4),
    }
