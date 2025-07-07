import sys
import os
import time
import threading
import json

# Adjust path to import from parent directory (empower1)
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, parent_dir)

from empower1.blockchain.blockchain import Blockchain, USER_PUBLIC_KEYS, VALIDATOR_WALLETS
from empower1.blockchain.wallet import Wallet
from empower1.blockchain.transaction import Transaction
from empower1.network.network import Network
from empower1.network.messages import MessageType
from empower1.blockchain import constants as blockchain_constants # Import constants

# NATIVE_CURRENCY_SYMBOL = Blockchain.NATIVE_CURRENCY_SYMBOL # Old way
NATIVE_CURRENCY_SYMBOL = blockchain_constants.NATIVE_CURRENCY_SYMBOL # New way

def print_help():
    print("\nEmPower1 Blockchain Node CLI")
    print(f"Usage: python {os.path.join('cmd', 'node', 'main.py')} [host] [port] [seed_node_http_address...]")
    print(f"Example: python {os.path.join('cmd', 'node', 'main.py')} 127.0.0.1 5000 http://127.0.0.1:5001")
    print("\nCommands during runtime (if interactive):")
    print(f"  transfer <receiver_addr> <amount> [{NATIVE_CURRENCY_SYMBOL}|asset_id] [metadata_json] - Create & broadcast transaction")
    print("  getbalance <address>                         - Display EPC balance of an address")
    print(f"  faucet <address> <amount>                    - (Test Only) Mint {NATIVE_CURRENCY_SYMBOL} to an address")
    print("  mine                                         - Attempt to mine a new block")
    print("  chain                                        - Display the current blockchain")
    print("  pending                                      - Display pending transactions")
    print("  peers                                        - Display known peers")
    print("  addpeer <http_address>                       - Manually add and connect to a peer")
    print("  mywallet                                     - Display this node's wallet info")
    print("  stake <amount>                               - Register/update stake for this node's wallet")
    print("  validators                                   - Display current validator set information")
    print("  help                                         - Show this help message")
    print("  exit                                         - Shutdown the node")
    print("-" * 40)

def main():
    # print_help() # Print help only if interactive or specifically requested

    default_host = "127.0.0.1"
    default_port = 5000

    host = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("http") else default_host

    port_candidate_idx = 2 if (len(sys.argv) > 1 and not sys.argv[1].startswith("http")) else 1
    try:
        port = int(sys.argv[port_candidate_idx]) if len(sys.argv) > port_candidate_idx and not sys.argv[port_candidate_idx].startswith("http") else default_port
    except (ValueError, IndexError):
        port = default_port

    seed_nodes_str_start_idx = port_candidate_idx + 1 if (len(sys.argv) > port_candidate_idx and not sys.argv[port_candidate_idx].startswith("http")) else port_candidate_idx
    seed_nodes_str = sys.argv[seed_nodes_str_start_idx:] if len(sys.argv) > seed_nodes_str_start_idx else []

    seed_nodes = set()
    for sn_addr in seed_nodes_str:
        if sn_addr.startswith("http://") and ":" in sn_addr.split("http://")[1]:
            seed_nodes.add(sn_addr)
        # else: print(f"Warning: Invalid seed node format '{sn_addr}'. Skipping.")

    node_wallet = Wallet()
    # print(f"\nInitializing Node Wallet for {host}:{port}")
    # print(f"  Address: {node_wallet.address}")
    USER_PUBLIC_KEYS[node_wallet.address] = node_wallet.get_public_key_hex()

    blockchain = Blockchain(node_wallet=node_wallet) # Pass node_wallet
    # Pass node_wallet to Network constructor for debug operations
    network_manager = Network(blockchain=blockchain, host=host, port=port, node_id=node_wallet.address, seed_nodes=seed_nodes, node_wallet=node_wallet)

    # --- Added Debug Logging for Node A Initial State ---
    if port == 5050: # Assuming Node A in the test runs on port 5050
        print(f"CMD_MAIN_DBG Node {port}: Node Wallet Address: {node_wallet.address}", flush=True)
        print(f"CMD_MAIN_DBG Node {port}: Blockchain Genesis Validator: {blockchain.genesis_validator_wallet_address}", flush=True)
        print(f"CMD_MAIN_DBG Node {port}: Balance of Node Wallet: {blockchain.balances.get(node_wallet.address)}", flush=True)
        print(f"CMD_MAIN_DBG Node {port}: Balance of Genesis Validator: {blockchain.balances.get(blockchain.genesis_validator_wallet_address)}", flush=True)
        print(f"CMD_MAIN_DBG Node {port}: Is Node Wallet the Genesis Validator? {node_wallet.address == blockchain.genesis_validator_wallet_address}", flush=True)
    # --- End Added Debug Logging ---

    # blockchain.network_interface = network_manager # Network constructor handles this now

    network_manager.start_server(threaded=True)
    time.sleep(0.5)

    if seed_nodes:
        network_manager.connect_to_seed_nodes()
    # elif len(blockchain.chain) <=1 and not seed_nodes and sys.stdin.isatty(): # Only print if interactive
    #      print(f"[{network_manager.self_node.node_id}] No seed nodes provided. Node started with its genesis block.")


    if sys.stdin.isatty(): # Check if running in an interactive terminal
        print_help() # Print help now for interactive mode
        print(f"\nNode {network_manager.self_node.node_id} listening on {network_manager.self_node.address}")
        print(f"Known peers: {network_manager.get_known_peers_addresses()}")
        running = True
        while running:
            try:
                cmd_input_str = input(f"Node {port}> ").strip()
                if not cmd_input_str: continue
                cmd_input = cmd_input_str.split()
                command = cmd_input[0].lower()

                if command == "exit": running = False; print("Shutting down node...")
                elif command == "help": print_help()
                elif command == "mywallet":
                    print(f"  Address: {node_wallet.address}")
                    print(f"  Public Key: {node_wallet.get_public_key_hex(compressed=True)}")
                    balance_atomic = blockchain.balances.get(node_wallet.address, 0)
                    balance_formatted = blockchain_constants.from_atomic(balance_atomic)
                    print(f"  {NATIVE_CURRENCY_SYMBOL} Balance: {balance_formatted:.{blockchain_constants.DECIMALS}f} ({balance_atomic} atomic units)")
                elif command == "stake":
                    if len(cmd_input) > 1:
                        try:
                            stake_amount_float = float(cmd_input[1])
                            if stake_amount_float <= 0:
                                print("Stake amount must be positive.")
                            else:
                                stake_amount_atomic = blockchain_constants.to_atomic(stake_amount_float)
                                # blockchain.register_validator_wallet now expects atomic units (int)
                                blockchain.register_validator_wallet(node_wallet, stake_amount_atomic)
                                # Method blockchain.register_validator_wallet prints its own confirmations/errors.
                                print(f"Stake command for {stake_amount_float} {NATIVE_CURRENCY_SYMBOL} ({stake_amount_atomic} atomic) processed.")
                        except ValueError:
                            print("Invalid stake amount format. Please enter a number.")
                    else:
                        print("Usage: stake <amount>")
                elif command == "transfer":
                    if len(cmd_input) >= 3:
                        receiver_addr = cmd_input[1]
                        try:
                            amount_float = float(cmd_input[2])
                            if amount_float <= 0: print("Transfer amount must be positive."); continue
                            amount_atomic = blockchain_constants.to_atomic(amount_float)

                            asset_id = cmd_input[3] if len(cmd_input) > 3 else NATIVE_CURRENCY_SYMBOL
                            metadata_str = " ".join(cmd_input[4:]) if len(cmd_input) > 4 else "{}"
                            metadata = json.loads(metadata_str) if metadata_str else {}

                            new_tx = Transaction(
                                sender_address=node_wallet.address,
                                receiver_address=receiver_addr,
                                amount=amount_atomic,  # Use atomic amount
                                asset_id=asset_id,
                                metadata=metadata
                                # Fee defaults to 0 (atomic) in Transaction constructor
                            )
                            new_tx.sign(node_wallet)
                            if blockchain.add_transaction(new_tx, node_wallet.get_public_key_hex()):
                                 print(f"Transaction {new_tx.transaction_id[:10]}... (Amount: {amount_atomic} atomic {asset_id}) submitted.")
                            # else: add_transaction prints errors
                        except ValueError: print("Invalid amount format. Please enter a number.")
                        except json.JSONDecodeError: print("Invalid metadata JSON string.")
                    else: print(f"Usage: transfer <receiver_addr> <amount> [{NATIVE_CURRENCY_SYMBOL}|asset_id] [metadata_json]")
                elif command == "getbalance":
                    if len(cmd_input) > 1:
                        addr_to_check = cmd_input[1]
                        balance_atomic = blockchain.balances.get(addr_to_check, 0) # Balances are atomic
                        balance_formatted = blockchain_constants.from_atomic(balance_atomic)
                        print(f"Balance of {addr_to_check}: {balance_formatted:.{blockchain_constants.DECIMALS}f} {NATIVE_CURRENCY_SYMBOL} ({balance_atomic} atomic units)")
                    else: print("Usage: getbalance <address>")
                elif command == "faucet":
                    if len(cmd_input) > 2:
                        try:
                            faucet_addr = cmd_input[1]
                            faucet_amount_float = float(cmd_input[2])
                            if faucet_amount_float <= 0: print("Faucet amount must be positive."); continue
                            faucet_amount_atomic = blockchain_constants.to_atomic(faucet_amount_float)

                            blockchain.balances[faucet_addr] = blockchain.balances.get(faucet_addr, 0) + faucet_amount_atomic
                            blockchain.total_supply_epc += faucet_amount_atomic # Ensure total_supply is also atomic

                            print(f"Added {faucet_amount_float} {NATIVE_CURRENCY_SYMBOL} ({faucet_amount_atomic} atomic units) to {faucet_addr}.")
                            print(f"New total supply: {blockchain_constants.from_atomic(blockchain.total_supply_epc):.{blockchain_constants.DECIMALS}f} {NATIVE_CURRENCY_SYMBOL} ({blockchain.total_supply_epc} atomic units).")
                            if faucet_addr not in USER_PUBLIC_KEYS and faucet_addr.startswith("Emp1"):
                                 print(f"Warning: {faucet_addr} may not have a known public key for typical transactions.")
                        except ValueError: print("Invalid amount for faucet.")
                    else: print(f"Usage: faucet <address> <amount>")
                elif command == "mine":
                    # mine_pending_transactions now checks if this node is the selected validator
                    mined_block = blockchain.mine_pending_transactions()
                    if mined_block:
                        print(f"Successfully Mined Block #{mined_block.index} by {mined_block.validator_address[:10]}... Hash: {mined_block.hash[:10]}...")
                    else:
                        # Blockchain.mine_pending_transactions already logs reasons for not mining
                        # (e.g., not selected, no pending tx, no active validators)
                        print("Mining attempt complete. Check logs for details if no block was mined.")
                elif command == "chain":
                    print("\nCurrent Blockchain:"); [print(f"  {b!r}") for i, b in enumerate(blockchain.chain)]; print("-" * 40)
                elif command == "pending":
                    print("\nPending Transactions:")
                    if blockchain.pending_transactions: [print(f"  {tx!r}") for tx in blockchain.pending_transactions]
                    else: print("  No pending transactions.")
                    print("-" * 40)
                elif command == "peers":
                    print("\nKnown Peers:")
                    peers_list = network_manager.get_known_peers_addresses()
                    if peers_list: [print(f"  - {p_addr}") for p_addr in peers_list]
                    else: print("  No known peers.")
                    print("-" * 40)
                elif command == "addpeer":
                    if len(cmd_input) > 1: network_manager.connect_to_peer(cmd_input[1])
                    else: print("Usage: addpeer <http_address_of_peer>")
                elif command == "validators":
                    print("\nValidators from ValidatorManager:")
                    if blockchain.validator_manager and blockchain.validator_manager.validators:
                        for addr, val_obj in blockchain.validator_manager.validators.items():
                            print(f"  - Address: {val_obj.wallet_address}")
                            print(f"    Stake: {val_obj.stake}, Active: {val_obj.is_active}")
                            print(f"    Last Produced TS: {val_obj.last_block_produced_timestamp}")
                            print(f"    Public Key (short): {val_obj.public_key_hex[:15]}...")
                        if not blockchain.validator_manager.validators:
                            print("  No validators currently registered in the manager.")
                    else:
                        print("  ValidatorManager not available or no validators.")
                    print("-" * 40)
                else: print(f"Unknown command: {command}. Type 'help'.")
            except EOFError: running = False; print("\nShutting down (EOF)...")
            except KeyboardInterrupt: running = False; print("\nShutting down (Ctrl+C)...")
    else: # Not a TTY, likely a test subprocess. Keep alive for tests.
        try:
            while True: time.sleep(1) # Keep daemon server thread alive
        except KeyboardInterrupt:
            pass # Allow tests to terminate it
            # print(f"\nNode {network_manager.self_node.node_id} (subprocess) received KI, shutting down...")

    print(f"Node at {host}:{port} stopped.")

if __name__ == "__main__":
    main()
