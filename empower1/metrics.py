# empower1/metrics.py
import time
from collections import defaultdict
from typing import Dict, List, Any, Optional

# Basic in-memory metrics collector for demonstration and testing.
# In a production system, this would likely integrate with a proper monitoring/metrics backend.

class MetricsCollector:
    def __init__(self):
        self.transaction_submission_times: Dict[str, float] = {} # tx_id -> submission_timestamp
        self.transaction_inclusion_times: Dict[str, Dict[str, Any]] = {} # tx_id -> {block_hash, node_id, inclusion_timestamp}

        self.block_mined_events: List[Dict[str, Any]] = []
        # Each entry: {block_hash, mined_timestamp, node_id, num_txs, processing_time_ms (optional)}

        self.block_received_events: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
        # block_hash -> node_id -> [reception_timestamp1, reception_timestamp2, ...]
        # (A block might be received multiple times if gossiped, first reception is most relevant for propagation)

        self.api_call_counts: Dict[str, int] = defaultdict(int)
        self.api_call_timings: Dict[str, List[float]] = defaultdict(list)

        self._lock = None # Placeholder for potential threading lock if needed later

    def _get_lock(self):
        # Lazy initialize lock if threading becomes a concern.
        # For now, assuming single-threaded access or careful multi-threaded use for basic collection.
        if self._lock is None:
            try:
                import threading
                self._lock = threading.Lock()
            except ImportError: # Should not happen in standard Python
                pass # No lock if threading module not available
        return self._lock

    def record_transaction_submission(self, tx_id: str):
        # lock = self._get_lock()
        # if lock: lock.acquire()
        try:
            if tx_id not in self.transaction_submission_times:
                self.transaction_submission_times[tx_id] = time.time()
        finally:
            # if lock: lock.release()
            pass

    def record_transaction_included(self, tx_id: str, block_hash: str, node_id: Optional[str] = "unknown_node"):
        # lock = self._get_lock()
        # if lock: lock.acquire()
        try:
            # Record first inclusion if multiple nodes report it for the same tx in the same block
            if tx_id not in self.transaction_inclusion_times:
                 self.transaction_inclusion_times[tx_id] = {
                    "block_hash": block_hash,
                    "node_id": node_id,
                    "inclusion_timestamp": time.time()
                }
        finally:
            # if lock: lock.release()
            pass

    def record_block_mined(self, block_hash: str, timestamp: float, node_id: str, num_txs: int, processing_time_ms: Optional[float] = None):
        # lock = self._get_lock()
        # if lock: lock.acquire()
        try:
            self.block_mined_events.append({
                "block_hash": block_hash,
                "mined_timestamp": timestamp, # Timestamp from the block itself
                "recorded_at": time.time(),   # Timestamp when this metric was recorded
                "node_id": node_id,
                "num_txs": num_txs,
                "processing_time_ms": processing_time_ms
            })
        finally:
            # if lock: lock.release()
            pass

    def record_block_received(self, block_hash: str, node_id: str):
        # lock = self._get_lock()
        # if lock: lock.acquire()
        try:
            self.block_received_events[block_hash][node_id].append(time.time())
        finally:
            # if lock: lock.release()
            pass

    def record_api_call(self, endpoint_name: str, duration_ms: float):
        # lock = self._get_lock()
        # if lock: lock.acquire()
        try:
            self.api_call_counts[endpoint_name] += 1
            self.api_call_timings[endpoint_name].append(duration_ms)
        finally:
            # if lock: lock.release()
            pass

    def get_transaction_latency(self, tx_id: str) -> Optional[float]:
        submission_time = self.transaction_submission_times.get(tx_id)
        inclusion_info = self.transaction_inclusion_times.get(tx_id)
        if submission_time and inclusion_info:
            return inclusion_info["inclusion_timestamp"] - submission_time
        return None

    def get_average_transaction_latency(self) -> Optional[float]:
        latencies = [self.get_transaction_latency(tx_id) for tx_id in self.transaction_inclusion_times if self.get_transaction_latency(tx_id) is not None]
        return sum(latencies) / len(latencies) if latencies else None

    def get_transactions_per_second(self, duration_seconds: float) -> float:
        # This is a simple TPS based on total included transactions over a period.
        # More advanced TPS would look at intervals.
        included_tx_count = len(self.transaction_inclusion_times)
        return included_tx_count / duration_seconds if duration_seconds > 0 else 0

    def get_average_block_time(self) -> Optional[float]:
        if len(self.block_mined_events) < 2:
            return None
        # Sort by recorded_at or mined_timestamp to ensure correct order
        sorted_blocks = sorted(self.block_mined_events, key=lambda x: x['mined_timestamp'])
        time_diffs = [
            sorted_blocks[i]['mined_timestamp'] - sorted_blocks[i-1]['mined_timestamp']
            for i in range(1, len(sorted_blocks))
        ]
        return sum(time_diffs) / len(time_diffs) if time_diffs else None

    def get_average_tx_per_block(self) -> Optional[float]:
        if not self.block_mined_events:
            return None
        total_txs = sum(b['num_txs'] for b in self.block_mined_events)
        return total_txs / len(self.block_mined_events)

    def get_block_propagation_times(self, block_hash: str) -> Optional[Dict[str, float]]:
        """Calculates propagation time from mining to reception by peers."""
        mined_event = next((b for b in self.block_mined_events if b['block_hash'] == block_hash), None)
        if not mined_event:
            return None

        mined_time = mined_event['mined_timestamp'] # Using block's own timestamp as reference
        propagation_times = {}
        if block_hash in self.block_received_events:
            for node_id, receptions in self.block_received_events[block_hash].items():
                if receptions:
                    first_reception_time = min(receptions)
                    propagation_times[node_id] = first_reception_time - mined_time
        return propagation_times

    def get_api_summary(self) -> Dict[str, Dict[str, Any]]:
        summary = {}
        for endpoint, timings in self.api_call_timings.items():
            summary[endpoint] = {
                "count": self.api_call_counts[endpoint],
                "avg_duration_ms": sum(timings) / len(timings) if timings else 0,
                "max_duration_ms": max(timings) if timings else 0,
                "min_duration_ms": min(timings) if timings else 0,
            }
        return summary

    def reset(self):
        self.transaction_submission_times.clear()
        self.transaction_inclusion_times.clear()
        self.block_mined_events.clear()
        self.block_received_events.clear()
        self.api_call_counts.clear()
        self.api_call_timings.clear()

# Global instance (or could be managed by dependency injection)
# For simplicity in tests, a global instance might be easier to access.
# However, for production, DI or context-specific instances are better.
# For now, let's make it so it can be instantiated.
metrics_collector = MetricsCollector() # Global instance for easy access in this phase

if __name__ == '__main__':
    # For __main__ demo, use a local collector to not interfere with global one if module is imported
    collector = MetricsCollector()
    tx1_id = "tx123"
    tx2_id = "tx456"
    block1_hash = "blockabc"
    node1_id = "node1"
    node2_id = "node2"

    collector.record_transaction_submission(tx1_id)
    time.sleep(0.1)
    collector.record_transaction_submission(tx2_id)
    time.sleep(0.2)

    collector.record_block_mined(block1_hash, time.time(), node1_id, 2, processing_time_ms=50.5)
    collector.record_transaction_included(tx1_id, block1_hash, node1_id)
    collector.record_transaction_included(tx2_id, block1_hash, node1_id)

    time.sleep(0.05)
    collector.record_block_received(block1_hash, node2_id)

    print(f"Tx1 Latency: {collector.get_transaction_latency(tx1_id):.4f}s")
    print(f"Average Tx Latency: {collector.get_average_transaction_latency():.4f}s")
    print(f"Average Txs per Block: {collector.get_average_tx_per_block()}")

    # Simulate another block for block time
    time.sleep(1.0) # Simulate 1s block time
    block2_hash = "blockdef"
    collector.record_block_mined(block2_hash, time.time(), node2_id, 1)
    print(f"Average Block Time: {collector.get_average_block_time():.4f}s")

    print(f"Block 1 Propagation to Node2: {collector.get_block_propagation_times(block1_hash).get(node2_id):.4f}s")

    collector.record_api_call("/ping", 2.5)
    collector.record_api_call("/ping", 3.1)
    collector.record_api_call("/GET_CHAIN", 10.2)
    print(f"API Summary: {collector.get_api_summary()}")

    collector.reset()
    assert not collector.transaction_submission_times
    print("Metrics Collector demo complete.")

# Need an __init__.py in empower1 directory if not already present
# to make empower1 a package for `from empower1.metrics import ...`
# Also, need an __init__.py in empower1/utils if metrics.py is placed there.
# For now, placing in empower1/metrics.py
