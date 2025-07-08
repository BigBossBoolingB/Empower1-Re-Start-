import pytest
import time
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from empower1.metrics import MetricsCollector

@pytest.fixture
def collector():
    """Returns a fresh MetricsCollector instance for each test."""
    mc = MetricsCollector()
    mc.reset() # Ensure it's clean
    return mc

def test_metrics_collector_initialization(collector):
    assert not collector.transaction_submission_times
    assert not collector.transaction_inclusion_times
    assert not collector.block_mined_events
    assert not collector.block_received_events
    assert not collector.api_call_counts
    assert not collector.api_call_timings

def test_record_transaction_submission(collector):
    collector.record_transaction_submission("tx1")
    assert "tx1" in collector.transaction_submission_times
    first_ts = collector.transaction_submission_times["tx1"]
    assert isinstance(first_ts, float)

    # Recording same tx again should not change timestamp (records first)
    time.sleep(0.01)
    collector.record_transaction_submission("tx1")
    assert collector.transaction_submission_times["tx1"] == first_ts

def test_record_transaction_included(collector):
    collector.record_transaction_included("tx1", "blockA", "node1")
    assert "tx1" in collector.transaction_inclusion_times
    inclusion_info = collector.transaction_inclusion_times["tx1"]
    assert inclusion_info["block_hash"] == "blockA"
    assert inclusion_info["node_id"] == "node1"
    assert isinstance(inclusion_info["inclusion_timestamp"], float)

    # Recording same tx again should not change info
    time.sleep(0.01)
    collector.record_transaction_included("tx1", "blockB", "node2") # Attempt to overwrite
    assert collector.transaction_inclusion_times["tx1"]["block_hash"] == "blockA"

def test_record_block_mined(collector):
    ts = time.time()
    collector.record_block_mined("blockA", ts, "node1", 5, 50.0)
    assert len(collector.block_mined_events) == 1
    event = collector.block_mined_events[0]
    assert event["block_hash"] == "blockA"
    assert event["mined_timestamp"] == ts
    assert event["node_id"] == "node1"
    assert event["num_txs"] == 5
    assert event["processing_time_ms"] == 50.0
    assert "recorded_at" in event

def test_record_block_received(collector):
    collector.record_block_received("blockA", "node1")
    time.sleep(0.01)
    collector.record_block_received("blockA", "node1") # Second reception by same node
    collector.record_block_received("blockA", "node2")

    assert "blockA" in collector.block_received_events
    assert "node1" in collector.block_received_events["blockA"]
    assert len(collector.block_received_events["blockA"]["node1"]) == 2
    assert "node2" in collector.block_received_events["blockA"]
    assert len(collector.block_received_events["blockA"]["node2"]) == 1

def test_record_api_call(collector):
    collector.record_api_call("/ping", 2.5)
    collector.record_api_call("/ping", 3.1)
    collector.record_api_call("/get_chain", 10.0)

    assert collector.api_call_counts["/ping"] == 2
    assert collector.api_call_counts["/get_chain"] == 1
    assert len(collector.api_call_timings["/ping"]) == 2
    assert collector.api_call_timings["/ping"] == [2.5, 3.1]
    assert collector.api_call_timings["/get_chain"] == [10.0]

def test_get_transaction_latency(collector):
    assert collector.get_transaction_latency("tx_unknown") is None

    collector.transaction_submission_times["tx1"] = 1000.0
    collector.transaction_inclusion_times["tx1"] = {"inclusion_timestamp": 1000.5, "block_hash": "b", "node_id": "n"}
    assert collector.get_transaction_latency("tx1") == pytest.approx(0.5)

def test_get_average_transaction_latency(collector):
    assert collector.get_average_transaction_latency() is None
    collector.transaction_submission_times["tx1"] = 1000.0
    collector.transaction_inclusion_times["tx1"] = {"inclusion_timestamp": 1000.5, "block_hash": "b", "node_id": "n1"}
    collector.transaction_submission_times["tx2"] = 1001.0
    collector.transaction_inclusion_times["tx2"] = {"inclusion_timestamp": 1001.2, "block_hash": "b", "node_id": "n1"}
    # tx3 submitted but not included
    collector.transaction_submission_times["tx3"] = 1002.0

    avg_latency = collector.get_average_transaction_latency()
    assert avg_latency is not None
    assert avg_latency == pytest.approx((0.5 + 0.2) / 2)

def test_get_transactions_per_second(collector):
    assert collector.get_transactions_per_second(0) == 0
    assert collector.get_transactions_per_second(10) == 0

    collector.transaction_inclusion_times["tx1"] = {"ts": 1} # Dummy data, only count matters
    collector.transaction_inclusion_times["tx2"] = {"ts": 1}
    assert collector.get_transactions_per_second(10.0) == pytest.approx(0.2) # 2 txs / 10s

def test_get_average_block_time(collector):
    assert collector.get_average_block_time() is None
    ts = time.time()
    collector.record_block_mined("b1", ts, "n1", 1)
    assert collector.get_average_block_time() is None # Need at least 2 blocks

    collector.record_block_mined("b2", ts + 5.0, "n1", 1)
    assert collector.get_average_block_time() == pytest.approx(5.0)

    collector.record_block_mined("b3", ts + 15.0, "n1", 1) # 10s after b2
    assert collector.get_average_block_time() == pytest.approx((5.0 + 10.0) / 2)

def test_get_average_tx_per_block(collector):
    assert collector.get_average_tx_per_block() is None
    collector.record_block_mined("b1", time.time(), "n1", 5)
    collector.record_block_mined("b2", time.time() + 1, "n1", 3)
    assert collector.get_average_tx_per_block() == pytest.approx(4.0)

def test_get_block_propagation_times(collector):
    assert collector.get_block_propagation_times("unknown_block") is None

    ts_mined = time.time()
    collector.record_block_mined("blockA", ts_mined, "nodeM", 1)

    time.sleep(0.01)
    ts_recv_n1 = time.time()
    collector.record_block_received("blockA", "node1")

    time.sleep(0.01)
    ts_recv_n2 = time.time()
    collector.record_block_received("blockA", "node2")

    propagation_times = collector.get_block_propagation_times("blockA")
    assert propagation_times is not None
    assert "node1" in propagation_times
    assert "node2" in propagation_times
    assert propagation_times["node1"] == pytest.approx(ts_recv_n1 - ts_mined, abs=0.001)
    assert propagation_times["node2"] == pytest.approx(ts_recv_n2 - ts_mined, abs=0.001)

def test_get_api_summary(collector):
    assert not collector.get_api_summary()
    collector.record_api_call("/ep1", 10.0)
    collector.record_api_call("/ep1", 20.0)
    collector.record_api_call("/ep2", 5.0)
    summary = collector.get_api_summary()
    assert "/ep1" in summary
    assert summary["/ep1"]["count"] == 2
    assert summary["/ep1"]["avg_duration_ms"] == pytest.approx(15.0)
    assert summary["/ep1"]["max_duration_ms"] == pytest.approx(20.0)
    assert summary["/ep1"]["min_duration_ms"] == pytest.approx(10.0)
    assert summary["/ep2"]["count"] == 1

def test_metrics_collector_reset(collector):
    collector.record_transaction_submission("tx1")
    collector.record_api_call("/ping", 1.0)
    assert collector.transaction_submission_times
    assert collector.api_call_counts

    collector.reset()
    test_metrics_collector_initialization(collector) # Re-check initial empty state

print("tests/test_metrics.py loaded")
