import pytest
import time
import json
import os
import sys

# Adjust path to import from project root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Imports for type hints and objects used in tests
from empower1.network.node import Node
from empower1.blockchain.blockchain import Blockchain
from empower1.network.messages import MessageType
from empower1.blockchain.wallet import Wallet

# Import API helpers from the integration conftest
from .conftest import node_api_get, node_api_post, DEFAULT_HOST

# Note: running_nodes_manager and project_root_dir_session fixtures are automatically available from conftest.py

def test_fixture_can_start_one_node(running_nodes_manager):
    nodes_info = running_nodes_manager([{"port": 5020}])
    assert len(nodes_info) == 1
    ping_data = node_api_get(nodes_info[0]["port"], "/ping")
    assert ping_data and ping_data["message"] == "pong"

def test_multi_node_network_formation(running_nodes_manager):
    node_a_p, node_b_p, node_c_p = 5040, 5041, 5042
    node_a_addr = f"http://{DEFAULT_HOST}:{node_a_p}"
    node_b_addr = f"http://{DEFAULT_HOST}:{node_b_p}"
    node_c_addr = f"http://{DEFAULT_HOST}:{node_c_p}"

    nodes_config_mf = [
        {"port": node_a_p, "seeds": []},
        {"port": node_b_p, "seeds": [node_a_addr]},
        {"port": node_c_p, "seeds": [node_b_addr]} # Node C seeds from B
    ]
    nodes_info_mf = running_nodes_manager(nodes_config_mf)
    assert len(nodes_info_mf) == 3

    print("Waiting for network to form (10s)...")
    time.sleep(10) # Allow time for peer discovery propagation

    # Expected: A knows B,C; B knows A,C; C knows A,B
    expected_peers = {
        node_a_addr: {node_b_addr, node_c_addr},
        node_b_addr: {node_a_addr, node_c_addr},
        node_c_addr: {node_a_addr, node_b_addr}
    }

    all_nodes_peered_correctly = True
    for node_info in nodes_info_mf:
        curr_addr, curr_port = node_info["address"], node_info["port"]
        print(f"Checking peers for node {curr_addr}...")
        peers_data = node_api_get(curr_port, f"/{str(MessageType.GET_PEERS)}")

        if peers_data is None:
            print(f"Failed to get peers from node {curr_addr}. Response was None.")
            all_nodes_peered_correctly = False
            continue # Skip further checks for this node if API fails

        known_peers = set(peers_data.get("peers", []))
        print(f"Node {curr_addr} knows peers: {known_peers}")

        if known_peers != expected_peers[curr_addr]:
            print(f"Node {curr_addr} peer list mismatch. Expected: {expected_peers[curr_addr]}, Got: {known_peers}")
            all_nodes_peered_correctly = False
            # Optionally, print more details or fail immediately
            # pytest.fail(f"Node {curr_addr} peer list mismatch. Expected: {expected_peers[curr_addr]}, Got: {known_peers}")

    assert all_nodes_peered_correctly, "One or more nodes did not have the expected peer list after network formation."


def test_chain_synchronization_new_node(running_nodes_manager, project_root_dir_session):
    node_a_port, node_b_port = 5050, 5051
    node_a_addr = f"http://{DEFAULT_HOST}:{node_a_port}"

    node_a_infos = running_nodes_manager([{"port": node_a_port, "seeds": []}])
    assert len(node_a_infos) == 1

    try:
        node_a_wallet_addr_from_ping = node_api_get(node_a_port, "/ping")["node_id"]
        assert node_a_wallet_addr_from_ping, "Could not get Node A wallet address from ping"

        stake_amount = 100.0
        stake_resp = node_api_post(node_a_port, "/debug_stake_self", data={"amount": stake_amount})
        assert stake_resp and "stake processed" in stake_resp.get("message", "").lower(), f"Staking Node A failed: {stake_resp}"

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

        node_b_infos = running_nodes_manager([{"port": node_b_port, "seeds": []}])
        assert len(node_b_infos) == 1

        print(f"Injecting Node A's PKs into Node B ({node_b_port})...")
        for addr, pk_hex in node_a_public_keys.items():
            inject_resp = node_api_post(node_b_port, "/debug_add_user_public_key", data={"address": addr, "public_key_hex": pk_hex})
            assert inject_resp and "added/updated" in inject_resp.get("message",""), f"Failed to inject PK for {addr} into Node B: {inject_resp}"

        print(f"Making Node B connect to Node A ({node_a_addr})")
        announce_A_to_B_resp = node_api_post(node_b_port, f"/{str(MessageType.NEW_PEER_ANNOUNCE)}", data={"address": node_a_addr})
        assert announce_A_to_B_resp and "Peer connection process initiated" in announce_A_to_B_resp.get("message",""), f"Announcing Node A to B failed: {announce_A_to_B_resp}"

        print("Waiting for Node B to sync (10s)...")
        time.sleep(10)

        node_b_chain_data = node_api_get(node_b_port, f"/{str(MessageType.GET_CHAIN)}")
        assert node_b_chain_data is not None, "Failed to get chain from Node B"

        if node_b_chain_data.get("length") != 3:
            print("Node A Chain Data for comparison:", json.dumps(node_a_chain_data, indent=2))
            print("Node B Chain Data for comparison:", json.dumps(node_b_chain_data, indent=2))

        assert node_b_chain_data.get("length") == 3, \
            f"Node B chain length mismatch. Expected 3, Got {node_b_chain_data.get('length')}."

        for i in range(3): # Compare all blocks including genesis
            assert node_b_chain_data["chain"][i]["hash"] == node_a_chain_data["chain"][i]["hash"], \
                f"Block hash mismatch at index {i}. Node A: {node_a_chain_data['chain'][i]['hash']}, Node B: {node_b_chain_data['chain'][i]['hash']}"

    except Exception as e:
        pytest.fail(f"Chain synchronization test failed with exception: {e}")

# Note: The __main__ block for manual testing of _start_node_subprocess was removed
# as these functions are now in conftest.py. Such manual tests could be a separate script.
