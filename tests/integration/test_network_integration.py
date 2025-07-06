import pytest
import subprocess
import time
import requests
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from empower1.network.node import Node
from empower1.blockchain.blockchain import Blockchain
from empower1.network.messages import MessageType
from empower1.blockchain.wallet import Wallet

PYTHON_EXECUTABLE = sys.executable
NODE_SCRIPT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../cmd/node/main.py'))
DEFAULT_HOST = "127.0.0.1"

def _start_node_subprocess(port: int, host: str = DEFAULT_HOST, seed_nodes: list = None, cwd=None, log_dir="logs/test_nodes"):
    if seed_nodes is None: seed_nodes = []
    os.makedirs(log_dir, exist_ok=True)
    log_file_stdout = os.path.join(log_dir, f"node_{port}_stdout.log")
    log_file_stderr = os.path.join(log_dir, f"node_{port}_stderr.log")

    cmd = [PYTHON_EXECUTABLE, NODE_SCRIPT_PATH, host, str(port)] + seed_nodes

    stdout_file = open(log_file_stdout, 'w')
    stderr_file = open(log_file_stderr, 'w')

    process = subprocess.Popen(cmd, stdout=stdout_file, stderr=stderr_file, text=True, cwd=cwd, bufsize=1, universal_newlines=True)

    process.node_log_files = {"stdout": log_file_stdout, "stderr": log_file_stderr, "stdout_handle": stdout_file, "stderr_handle": stderr_file}

    ready = False; retries = 20
    for _ in range(retries):
        time.sleep(0.5)
        try:
            if requests.get(f"http://{host}:{port}/ping", timeout=1).status_code == 200:
                ready = True; break
        except requests.exceptions.RequestException: pass

    if not ready:
        print(f"Node {port} did not become ready. Terminating. Check logs: {log_file_stdout}, {log_file_stderr}")
        # Close files before terminating
        stdout_file.close()
        stderr_file.close()
        process.terminate()
        try:
            process.wait(timeout=5) # process.communicate() cannot be used as stdout/stderr are redirected to files
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        return None
    return process

def _terminate_node_subprocess(process: subprocess.Popen, port: int):
    if hasattr(process, 'node_log_files'):
        process.node_log_files['stdout_handle'].close()
        process.node_log_files['stderr_handle'].close()

    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5) # process.communicate() cannot be used as stdout/stderr are redirected to files
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def node_api_get(port: int, endpoint: str, host: str = DEFAULT_HOST, timeout=3):
    try:
        url = f"http://{host}:{port}{endpoint}"
        response = requests.get(url, timeout=timeout)
        response.raise_for_status(); return response.json()
    except requests.exceptions.RequestException as e:
        # print(f"API GET to {url} failed: {e}")
        return None

def node_api_post(port: int, endpoint: str, data: dict, host: str = DEFAULT_HOST, timeout=3):
    try:
        url = f"http://{host}:{port}{endpoint}"
        response = requests.post(url, json=data, timeout=timeout)
        response.raise_for_status(); return response.json()
    except requests.exceptions.RequestException as e:
        # print(f"API POST to {url} (data: {data}) failed: {e}")
        return None

@pytest.fixture(scope="session")
def project_root_dir_session():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))

@pytest.fixture
def running_nodes_manager(project_root_dir_session, request):
    processes_ports = {}
    log_dir = os.path.join(project_root_dir_session, "logs", "test_nodes", request.node.name)

    def _starter_function(nodes_config: list):
        nonlocal processes_ports, log_dir
        started_node_infos = []
        for config in nodes_config:
            port = config["port"]; seeds = config.get("seeds", []); host = config.get("host", DEFAULT_HOST)
            # Pass the specific log_dir for this test
            proc = _start_node_subprocess(port, host, seed_nodes=seeds, cwd=project_root_dir_session, log_dir=log_dir)
            if proc:
                processes_ports[port] = proc
                started_node_infos.append({
                    "host": host, "port": port, "address": f"http://{host}:{port}",
                    "log_files": proc.node_log_files # Store log file paths
                })
            else:
                # If a node fails to start, terminate already started ones by this manager
                for p, pr_to_kill in processes_ports.items():
                    _terminate_node_subprocess(pr_to_kill, p)
                pytest.fail(f"Failed to start node on port {port}. Check logs in {log_dir}")
        if not processes_ports: pytest.fail("No nodes were started by the manager.")
        return started_node_infos

    yield _starter_function

    print("\n--- Node Logs Teardown ---")
    for port, process in processes_ports.items():
        print(f"\n--- Logs for Node on port {port} ---")

        # Terminate first to allow logs to be flushed
        _terminate_node_subprocess(process, port) # This now also closes file handles

        log_files = getattr(process, 'node_log_files', None)
        if log_files:
            for log_type, log_path in log_files.items():
                if log_type.endswith("_handle"): continue # Skip file handles
                print(f"--- {log_type.upper()} for Node {port} from {log_path} ---")
                try:
                    with open(log_path, 'r') as f:
                        log_content = f.read()
                        print(log_content if log_content else "<empty log file>")
                except FileNotFoundError:
                    print("<log file not found>")
                except Exception as e:
                    print(f"<error reading log file: {e}>")
        else:
            print(f"Node {port} log files info not found on process object.")

        # Fallback ensure termination if _terminate_node_subprocess didn't run or failed before full term
        if process and process.poll() is None:
            print(f"Finalizing termination for Node {port} as it was still running.")
            # Re-call _terminate_node_subprocess, though it should have been called.
            # This path implies an issue in prior cleanup or the process object state.
            # At this point, file handles should be closed, so a more forceful kill might be needed
            # if terminate fails again. However, _terminate_node_subprocess already has this logic.
            _terminate_node_subprocess(process, port) # Safe to call again, handles are closed

def test_fixture_can_start_one_node(running_nodes_manager):
    nodes_info = running_nodes_manager([{"port": 5020}])
    assert len(nodes_info) == 1
    ping_data = node_api_get(nodes_info[0]["port"], "/ping")
    assert ping_data and ping_data["message"] == "pong"

def test_multi_node_network_formation(running_nodes_manager):
    node_a_p, node_b_p, node_c_p = 5040, 5041, 5042
    node_a_addr, node_b_addr, node_c_addr = f"http://{DEFAULT_HOST}:{node_a_p}", f"http://{DEFAULT_HOST}:{node_b_p}", f"http://{DEFAULT_HOST}:{node_c_p}"
    nodes_config_mf = [
        {"port": node_a_p, "seeds": []}, {"port": node_b_p, "seeds": [node_a_addr]}, {"port": node_c_p, "seeds": [node_b_addr]}]
    nodes_info_mf = running_nodes_manager(nodes_config_mf)
    assert len(nodes_info_mf) == 3
    time.sleep(10)
    expected_peers = {node_a_addr: {node_b_addr, node_c_addr}, node_b_addr: {node_a_addr, node_c_addr}, node_c_addr: {node_a_addr, node_b_addr}}
    for node_info in nodes_info_mf:
        curr_addr, curr_port = node_info["address"], node_info["port"]
        peers_data = node_api_get(curr_port, f"/{str(MessageType.GET_PEERS)}")
        assert peers_data is not None, f"Failed to get peers from node {curr_addr}. Response was None."
        known_peers = set(peers_data.get("peers", []))
        assert known_peers == expected_peers[curr_addr], f"Node {curr_addr} peer list mismatch. Expected: {expected_peers[curr_addr]}, Got: {known_peers}"

def test_chain_synchronization_new_node(running_nodes_manager, project_root_dir_session):
    node_a_port, node_b_port = 5050, 5051
    node_a_addr = f"http://{DEFAULT_HOST}:{node_a_port}"

    # Start Node A
    node_a_infos = running_nodes_manager([{"port": node_a_port, "seeds": []}])
    assert len(node_a_infos) == 1

    try:
        node_a_wallet_addr_from_ping = node_api_get(node_a_port, "/ping")["node_id"]
        assert node_a_wallet_addr_from_ping, "Could not get Node A wallet address from ping"

        # faucet_amount = 200.0
        # faucet_resp = node_api_post(node_a_port, "/debug_faucet", data={"address": node_a_wallet_addr_from_ping, "amount": faucet_amount})
        # assert faucet_resp and "Faucet funds added" in faucet_resp.get("message",""), f"Faucet for Node A failed: {faucet_resp}"

        stake_amount = 100.0
        # Ensure node_a_wallet_addr_from_ping has enough from genesis allocation for this stake
        stake_resp = node_api_post(node_a_port, "/debug_stake_self", data={"amount": stake_amount})
        assert stake_resp and "staked" in stake_resp.get("message", ""), f"Staking Node A failed: {stake_resp}"

        for i in range(2):
            tx_data = {"receiver_address": f"Emp1_DummyReceiver_SyncTest_Block{i+1}", "amount": float(i + 1.5)}
            create_tx_resp = node_api_post(node_a_port, "/debug_create_tx", data=tx_data)
            assert create_tx_resp and "tx_id" in create_tx_resp, f"Tx creation {i+1} on Node A failed: {create_tx_resp}"
            time.sleep(0.2)

            mine_resp = node_api_post(node_a_port, "/mine_block_debug", data={})
            assert mine_resp and mine_resp.get("block_hash"), f"Node A failed to mine block {i+1}: {mine_resp}"
            time.sleep(0.5)

        node_a_chain_data = node_api_get(node_a_port, f"/{str(MessageType.GET_CHAIN)}")
        assert node_a_chain_data and node_a_chain_data.get("length") == 3, f"Node A chain length incorrect. Expected 3, Got {node_a_chain_data.get('length')}"

        node_a_public_keys = node_api_get(node_a_port, "/debug_get_user_public_keys")
        assert node_a_public_keys is not None, "Failed to get public keys from Node A"

        # Start Node B *without* Node A as a seed initially
        node_b_infos = running_nodes_manager([{"port": node_b_port, "seeds": []}])
        assert len(node_b_infos) == 1

        print(f"Injecting Node A's PKs into Node B ({node_b_port})...")
        for addr, pk_hex in node_a_public_keys.items():
            inject_resp = node_api_post(node_b_port, "/debug_add_user_public_key", data={"address": addr, "public_key_hex": pk_hex})
            assert inject_resp and "added/updated" in inject_resp.get("message",""), f"Failed to inject PK for {addr} into Node B: {inject_resp}"

        # Now, make Node B connect to Node A (e.g., by announcing Node A to Node B)
        print(f"Making Node B connect to Node A ({node_a_addr})")
        announce_A_to_B_resp = node_api_post(node_b_port, f"/{str(MessageType.NEW_PEER_ANNOUNCE)}", data={"address": node_a_addr})
        assert announce_A_to_B_resp and "Peer connection process initiated" in announce_A_to_B_resp.get("message",""), f"Announcing Node A to B failed: {announce_A_to_B_resp}"

        time.sleep(10) # Allow time for Node B to connect to A and sync

        node_b_chain_data = node_api_get(node_b_port, f"/{str(MessageType.GET_CHAIN)}")
        assert node_b_chain_data is not None, "Failed to get chain from Node B"

        if node_b_chain_data.get("length") != 3:
            print("Node A Chain Data for comparison:", json.dumps(node_a_chain_data, indent=2))
            print("Node B Chain Data for comparison:", json.dumps(node_b_chain_data, indent=2))

        assert node_b_chain_data.get("length") == 3, \
            f"Node B chain length mismatch. Expected 3, Got {node_b_chain_data.get('length')}."

        for i in range(3):
            assert node_b_chain_data["chain"][i]["hash"] == node_a_chain_data["chain"][i]["hash"], \
                f"Block hash mismatch at index {i}."

    except Exception as e:
        pytest.fail(f"Chain synchronization test failed with exception: {e}")

if __name__ == "__main__":
    print("Manual test of node subprocess helpers...")
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
    test_proc_main = None # Renamed to avoid conflict with fixture variable name
    try:
        test_proc_main = _start_node_subprocess(5099, cwd=project_root)
        if test_proc_main:
            print("Node 5099 started. Checking API...")
            time.sleep(1)
            pk_info = node_api_get(5099, "/debug_get_user_public_keys")
            print(f"PK info from node 5099: {pk_info}")
            chain = node_api_get(5099, f"/{str(MessageType.GET_CHAIN)}")
            print(f"Chain length from node 5099: {chain.get('length') if chain else 'Error'}")
        else: print("Failed to start node 5099 for manual test.")
    except Exception as e: print(f"Error during manual test: {e}")
    finally:
        if test_proc_main: _terminate_node_subprocess(test_proc_main, 5099)
    print("Manual test finished.")
