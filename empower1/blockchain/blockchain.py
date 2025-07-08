import time
from typing import Dict
from .block import Block  # Updated to relative import
from .transaction import Transaction  # Updated to relative import
from .wallet import Wallet  # Updated to relative import
import logging # Added import logging
from . import constants # Import new constants file
from empower1.metrics import metrics_collector # Import global metrics collector

USER_PUBLIC_KEYS = {}
VALIDATOR_WALLETS = {}

from empower1.consensus.manager import ValidatorManager # Remains absolute, sibling package

class Blockchain:
    # NATIVE_CURRENCY_SYMBOL = "EPC" # Define native currency symbol - Will be replaced by constants.NATIVE_CURRENCY_SYMBOL

    def __init__(self, node_wallet: Wallet, network_interface=None): # Added node_wallet parameter
        self.node_wallet = node_wallet # Store the provided node_wallet
        self.chain = []
        self.pending_transactions = []
        self.validator_manager = ValidatorManager()
        self.network_interface = network_interface

        self.balances: Dict[str, int] = {} # Store balances as integers (atomic units)
        self.total_supply_epc: int = 0    # Store total supply as integer (atomic units)

        # Set these based on the provided node_wallet
        self.genesis_validator_wallet_address = self.node_wallet.address
        self.genesis_validator_public_key_hex = self.node_wallet.get_public_key_hex()

        self._create_and_sign_genesis_block() # This will now use self.node_wallet

    def _create_and_sign_genesis_block(self):
        # No longer create a new Wallet here; use self.node_wallet
        # Ensure its PK and wallet object are in the global maps
        if self.node_wallet.address not in VALIDATOR_WALLETS: # Avoid re-adding if already there from other init
            VALIDATOR_WALLETS[self.node_wallet.address] = self.node_wallet
        if self.node_wallet.address not in USER_PUBLIC_KEYS:
            USER_PUBLIC_KEYS[self.node_wallet.address] = self.node_wallet.get_public_key_hex()

        genesis_block = Block(
            index=0,
            transactions=[],
            timestamp=time.time(),
            previous_hash="0",
            validator_address=self.node_wallet.address, # Use self.node_wallet's address
            proof={"type": "Genesis", "validator": self.node_wallet.address, "details": "initial_block_proof_v1"}
        )
        genesis_block.sign_block(self.node_wallet) # Sign with self.node_wallet
        self.chain.append(genesis_block)

        # Use atomic units for initial supply and balance
        self.balances[self.node_wallet.address] = constants.INITIAL_TOTAL_SUPPLY_EPC_ATOMIC
        self.total_supply_epc = constants.INITIAL_TOTAL_SUPPLY_EPC_ATOMIC
        logging.info(f"GENESIS_DBG: Initial {self.total_supply_epc} atomic units of {constants.NATIVE_CURRENCY_SYMBOL} allocated to genesis validator {self.node_wallet.address}. Balance: {self.balances[self.node_wallet.address]}")

        # Register genesis validator with a substantial stake (also in atomic units)
        # Example: stake half of the initial allocation. Ensure this is an integer.
        genesis_stake_amount_atomic = self.total_supply_epc // 2
        self.validator_manager.add_or_update_validator_stake(
            validator_wallet_address=self.node_wallet.address,
            public_key_hex=self.node_wallet.get_public_key_hex(),
            stake_change=genesis_stake_amount_atomic # Pass as int
        )
        logging.info(f"GENESIS_DBG: Genesis validator {self.node_wallet.address} registered with stake {genesis_stake_amount_atomic} atomic units.")
        logging.info(f"GENESIS_DBG: USER_PUBLIC_KEYS after genesis wallet init: {list(USER_PUBLIC_KEYS.keys())}")
        logging.info(f"GENESIS_DBG: VALIDATOR_WALLETS after genesis wallet init: {list(VALIDATOR_WALLETS.keys())}")

    @property
    def last_block(self) -> Block:
        return self.chain[-1] if self.chain else None # Handle empty chain case for last_block

    def _process_transaction_for_state_changes(self, transaction: Transaction) -> bool:
        """
        Processes a single transaction to update balances for the native currency.
        This method assumes the transaction's signature and basic format are already validated.
        It only checks for sufficient funds and applies balance changes.
        Args:
            transaction (Transaction): The transaction to process.
        Returns:
            bool: True if the transaction was processed successfully (sufficient funds, native currency type),
                  False otherwise.
        """
        if transaction.asset_id != constants.NATIVE_CURRENCY_SYMBOL:
            return True # Not an EPC transfer, so considered "processed" without state change for balances.

        sender_address = transaction.sender_address
        receiver_address = transaction.receiver_address
        amount = transaction.amount # Now an int (atomic units)

        sender_balance = self.balances.get(sender_address, 0) # Default to int 0

        # Validate funds (important: this check uses the current state of self.balances)
        if sender_balance < amount:
            print(f"Transaction {transaction.transaction_id} state change failed: Sender {sender_address} has insufficient balance ({sender_balance} {constants.NATIVE_CURRENCY_SYMBOL}) for amount {amount} {constants.NATIVE_CURRENCY_SYMBOL}.")
            return False

        self.balances[sender_address] = sender_balance - amount
        self.balances[receiver_address] = self.balances.get(receiver_address, 0.0) + amount

        # print(f"Processed EPC transfer: {amount} from {sender_address} to {receiver_address}. New balances: Sender={self.balances[sender_address]}, Receiver={self.balances[receiver_address]}")
        return True

    def add_transaction(self, transaction: Transaction, sender_public_key_hex: str, received_from_network: bool = False) -> bool:
        if not isinstance(transaction, Transaction):
            return False
        if not all(hasattr(transaction, attr) for attr in ['sender_address', 'receiver_address', 'amount']):
            return False

        import logging # Make sure logging is imported if not already at module top
        logging.debug(f"Add_transaction: Verifying sig for tx {transaction.transaction_id} from {transaction.sender_address} with PK {sender_public_key_hex[:10]}...")
        sig_valid = transaction.verify_signature(sender_public_key_hex)
        if not sig_valid:
            logging.error(f"Add_transaction: Invalid signature for transaction {transaction.transaction_id} from {transaction.sender_address}. PK used: {sender_public_key_hex[:10]}...")
            # For debugging, let's see what USER_PUBLIC_KEYS has for this address
            known_pk = USER_PUBLIC_KEYS.get(transaction.sender_address)
            logging.error(f"Add_transaction: For sender {transaction.sender_address}, USER_PUBLIC_KEYS has: {known_pk[:10] if known_pk else 'None'}")
            return False
        logging.debug(f"Add_transaction: Signature VERIFIED for tx {transaction.transaction_id}")

        # Pre-check for sufficient funds (against current confirmed balances) before adding to pending pool
        if transaction.asset_id == constants.NATIVE_CURRENCY_SYMBOL:
            current_sender_balance = self.balances.get(transaction.sender_address, 0) # Default to int 0
            # Consider pending outgoing transactions from this sender to prevent double spending from mempool
            pending_outgoing_amount = sum(
                tx.amount for tx in self.pending_transactions
                if tx.sender_address == transaction.sender_address and tx.asset_id == constants.NATIVE_CURRENCY_SYMBOL
            )
            available_balance = current_sender_balance - pending_outgoing_amount

            if available_balance < transaction.amount:
                print(f"Tx {transaction.transaction_id} rejected from mempool: Sender {transaction.sender_address} has insufficient available balance (Confirmed: {current_sender_balance}, Pending Out: {pending_outgoing_amount}, Available: {available_balance}) for amount {transaction.amount}.")
                return False

        if any(tx.transaction_id == transaction.transaction_id for tx in self.pending_transactions):
            return True # Already known

        self.pending_transactions.append(transaction)
        metrics_collector.record_transaction_submission(transaction.transaction_id) # Record submission

        if self.network_interface and not received_from_network:
            self.network_interface.broadcast_transaction(transaction)
        return True

    def mine_pending_transactions(self) -> Block | None:
        selected_validator_obj = self.validator_manager.select_next_validator()

        if not selected_validator_obj:
            logging.info(f"MINE_LOGIC: No active validator selected by ValidatorManager. Active list: {self.validator_manager._active_validator_addresses_round_robin}")
            return None

        selected_validator_address = selected_validator_obj.wallet_address
        logging.info(f"MINE_LOGIC: ValidatorManager selected: {selected_validator_address}")

        # Check if this node is the selected validator
        if self.node_wallet.address != selected_validator_address:
            logging.info(f"MINE_LOGIC: This node ({self.node_wallet.address}) is not the selected validator ({selected_validator_address}). Cannot mine.")
            # In a real PoS system, we might just not attempt, or another mechanism handles proposing.
            # For this simulation, if not selected, this node doesn't mine.
            return None

        validator_wallet = VALIDATOR_WALLETS.get(selected_validator_address)
        if not validator_wallet:
            logging.error(f"MINE_LOGIC: Wallet for selected validator {selected_validator_address} not found in VALIDATOR_WALLETS global. Known: {list(VALIDATOR_WALLETS.keys())}")
            return None

        if not self.pending_transactions:
            logging.info(f"MINE_LOGIC: No pending transactions for validator {selected_validator_address} to mine.")
            return None
        print(f"DEBUG MINE: {len(self.pending_transactions)} pending transactions found.")

        # Create a temporary balance snapshot to validate transactions for this block
        # This snapshot starts from the current confirmed balances.
        temp_balances_for_block = self.balances.copy()
        valid_txs_for_block = []

        for tx in list(self.pending_transactions): # Iterate over a copy
            if tx.asset_id == constants.NATIVE_CURRENCY_SYMBOL:
                sender_bal_snapshot = temp_balances_for_block.get(tx.sender_address, 0) # Default to int 0
                if sender_bal_snapshot >= tx.amount:
                    temp_balances_for_block[tx.sender_address] = sender_bal_snapshot - tx.amount
                    temp_balances_for_block[tx.receiver_address] = temp_balances_for_block.get(tx.receiver_address, 0) + tx.amount # Default to int 0
                    valid_txs_for_block.append(tx)
                else:
                    print(f"Tx {tx.transaction_id} by {tx.sender_address} for {tx.amount} {constants.NATIVE_CURRENCY_SYMBOL} invalid due to insufficient funds ({sender_bal_snapshot} atomic units) during mining. Removing from current block proposal.")
                    # Optionally, remove from self.pending_transactions permanently if invalid even against confirmed state
                    # For now, just exclude from this block.
            else: # Non-EPC transactions are included if they passed initial add_transaction checks
                valid_txs_for_block.append(tx)

        if not valid_txs_for_block: # If all pending transactions were invalid for state changes
            print(f"No valid transactions to include in block for validator {selected_validator_address}.")
            return None

        new_block = Block(
            index=len(self.chain),
            transactions=valid_txs_for_block,
            timestamp=time.time(),
            previous_hash=self.last_block.hash if self.last_block else "0",
            validator_address=selected_validator_address,
            proof={"type": "Proof-of-Stake", "validator": selected_validator_address, "details": "placeholder_pos_proof_v1"} # Updated PoS proof placeholder
        )
        new_block.sign_block(validator_wallet)

        # --- Apply state changes from this new block to the actual self.balances ---
        for tx in new_block.transactions:
            # _process_transaction_for_state_changes updates self.balances
            if not self._process_transaction_for_state_changes(tx):
                # This should not happen if pre-validation with temp_balances was correct
                print(f"CRITICAL ERROR: Transaction {tx.transaction_id} was valid with temp_balances but failed with self.balances during mining.")
                # Potentially revert any partial changes if transactional application is needed, or halt.
                # For now, this indicates a logic flaw if reached.
                return None

        self.chain.append(new_block)
        print(f"Block #{new_block.index} mined by {selected_validator_address} with {len(new_block.transactions)} txs.")

        mined_tx_ids = {tx.transaction_id for tx in new_block.transactions}
        self.pending_transactions = [ptx for ptx in self.pending_transactions if ptx.transaction_id not in mined_tx_ids]

        # The ValidatorManager's select_next_validator method already calls record_block_production on the validator object.
        # So, no explicit call needed here.

        # Record metrics for mined block and included transactions
        metrics_collector.record_block_mined(
            block_hash=new_block.hash,
            timestamp=new_block.timestamp,
            node_id=self.node_wallet.address, # Assuming node_wallet's address is the node_id for mining
            num_txs=len(new_block.transactions)
        )
        for tx in new_block.transactions:
            metrics_collector.record_transaction_included(
                tx_id=tx.transaction_id,
                block_hash=new_block.hash,
                node_id=self.node_wallet.address
            )

        if self.network_interface:
            self.network_interface.broadcast_block(new_block)
        return new_block

    def is_chain_valid(self) -> bool:
        """
        Validates the entire blockchain. Checks include:
        - Block hash integrity (recalculating hash based on content, including 'proof').
        - Previous hash linkage.
        - Validator signature on each block.
        - Transaction signatures within each block.
        - Replays transactions to ensure balance consistency.

        Returns:
            bool: True if the chain is valid, False otherwise.
        """
        temp_balances_for_validation = {}
        # Properly initialize temp_balances with the actual genesis allocation
        if self.chain:
            genesis_val_addr_on_chain = self.chain[0].validator_address
            # Find the initial allocation from self.balances that corresponds to genesis
            # This assumes self.balances was correctly initialized.
            # A more robust way would be to define genesis allocation constants.
            initial_genesis_balance = 0
            # Search for the balance that was set in _create_and_sign_genesis_block
            # This is a bit indirect. Ideally, genesis allocation is fixed.
            # For now, assume total_supply_epc was given to genesis validator.
            if self.chain[0].transactions == []: # Typical genesis
                 temp_balances_for_validation[genesis_val_addr_on_chain] = self.total_supply_epc


        for i in range(len(self.chain)):
            current_block = self.chain[i]
            # The block's hash is calculated on instantiation and stored in self.hash
            # To validate, we re-calculate based on its current content and compare.
            if current_block.hash != current_block.calculate_hash(): # Updated call
                print(f"Error: Block {current_block.index} has an invalid hash. Stored: {current_block.hash}, Recalculated: {current_block.calculate_hash()}")
                return False

            if i > 0:
                previous_block = self.chain[i-1]
                if current_block.previous_hash != previous_block.hash:
                    print(f"Error: Block {current_block.index} previous_hash mismatch.")
                    return False

                validator_public_key_hex = USER_PUBLIC_KEYS.get(current_block.validator_address)
                if not validator_public_key_hex:
                    print(f"Error: Public key for validator {current_block.validator_address} (Block {current_block.index}) not found.")
                    return False

                # Check with ValidatorManager
                validator_obj_from_manager = self.validator_manager.get_validator(current_block.validator_address)
                if not validator_obj_from_manager:
                    print(f"Error: Validator {current_block.validator_address} (Block {current_block.index}) not found in ValidatorManager.")
                    return False

                # For a strict PoS, we might check if the validator was active *at the time the block was made*.
                # For simplicity now, we check if they are *currently known* and *generally active* based on current stake.
                # A more advanced check would involve historical stake and activity status.
                # For now, we'll rely on the fact that only active validators should be able to produce blocks
                # that get accepted by the network. If a block from an inactive validator is found,
                # it might indicate an issue or a past state where they were active.
                # A simple check: if the validator is in the manager, it's "known". Active status check can be added.
                if not validator_obj_from_manager.is_active:
                     # This check might be too strict for historical blocks if a validator becomes inactive later.
                     # For now, let's log a warning instead of failing hard, unless it's the most recent block.
                     # print(f"Warning: Validator {current_block.validator_address} (Block {current_block.index}) is not currently active in manager.")
                     pass # Decided to not fail hard on this for now for simplicity of historical validation.

                if not current_block.verify_block_signature(validator_public_key_hex):
                    print(f"Error: Block {current_block.index} has an invalid validator signature.")
                    return False

            elif i == 0 and current_block.signature_hex:
                genesis_validator_public_key_hex = USER_PUBLIC_KEYS.get(current_block.validator_address)
                if not genesis_validator_public_key_hex:
                     print(f"Error: Public key for genesis validator {current_block.validator_address} not found.")
                     return False
                if not current_block.verify_block_signature(genesis_validator_public_key_hex):
                    print(f"Error: Genesis Block has an invalid validator signature.")
                    return False

            # Validate transactions and replay state changes on temp_balances
            # For genesis block (i=0), transactions (if any) would be special (e.g. initial allocations beyond validator)
            # Our current genesis has no txs, so _process_transaction_for_state_changes won't run for it here.
            for tx in current_block.transactions:
                sender_public_key_hex = USER_PUBLIC_KEYS.get(tx.sender_address)
                if not sender_public_key_hex:
                    print(f"Error: Public key for sender {tx.sender_address} (Tx {tx.transaction_id}, Block {current_block.index}) not found.")
                    return False
                if not tx.verify_signature(sender_public_key_hex):
                    print(f"Error: Transaction {tx.transaction_id} in block {current_block.index} has an invalid signature.")
                    return False

                # Replay EPC transactions on temp_balances for consistency check
                if tx.asset_id == constants.NATIVE_CURRENCY_SYMBOL:
                    sender_bal = temp_balances_for_validation.get(tx.sender_address, 0) # Default to int 0
                    if sender_bal < tx.amount:
                        print(f"Chain validation error: Tx {tx.transaction_id} in block {current_block.index} - insufficient funds for sender {tx.sender_address} during replay (Balance: {sender_bal} atomic, Amount: {tx.amount} atomic).")
                        return False
                    temp_balances_for_validation[tx.sender_address] = sender_bal - tx.amount
                    temp_balances_for_validation[tx.receiver_address] = temp_balances_for_validation.get(tx.receiver_address, 0) + tx.amount # Default to int 0

        # Compare replayed balances with actual self.balances (if chain has more than genesis)
        # This is a strong check. For very long chains, this might be slow.
        # Only compare if there's more than just the genesis block, as genesis sets the initial state.
        if len(self.chain) > 1:
            # Normalize balances by removing zero-balance accounts from both dicts for fair comparison
            norm_replayed_balances = {k: v for k, v in temp_balances_for_validation.items() if v != 0}
            norm_actual_balances = {k: v for k, v in self.balances.items() if v != 0}
            if norm_replayed_balances != norm_actual_balances:
                print("Error: Chain validation failed due to balance mismatch after replaying all transactions.")
                print(f"Expected (current) balances: {norm_actual_balances}")
                print(f"Replayed balances from chain: {norm_replayed_balances}")
                # Find differences for debugging
                # for addr in set(norm_replayed_balances.keys()) | set(norm_actual_balances.keys()):
                #     if norm_replayed_balances.get(addr) != norm_actual_balances.get(addr):
                #         print(f"  Mismatch for {addr}: Replayed={norm_replayed_balances.get(addr)}, Actual={norm_actual_balances.get(addr)}")
                return False

        print("Blockchain is valid (cryptographically, structurally, and balance states consistent).")
        return True

    def register_validator_wallet(self, validator_wallet: Wallet, stake_amount_atomic: int): # Changed to int
        if not isinstance(validator_wallet, Wallet):
            print("Error: Invalid validator wallet object.")
            return
        if not isinstance(stake_amount_atomic, int) or stake_amount_atomic <= 0:
            print("Stake amount must be a positive integer (atomic units).")
            return

        addr = validator_wallet.address
        current_balance = self.balances.get(addr, 0)

        if current_balance < stake_amount_atomic:
            print(f"Error: Insufficient balance for {addr} to stake {stake_amount_atomic} atomic units. Has: {current_balance}")
            return

        # Deduct stake from balance
        # TODO: Future - This should be part of an on-chain STAKE transaction processing.
        # For now, direct balance deduction is used. ValidatorManager handles stake accumulation.
        self.balances[addr] = current_balance - stake_amount_atomic

        pub_key_hex = validator_wallet.get_public_key_hex()
        # The add_or_update_validator_stake in ValidatorManager now expects the *change* in stake or total.
        # If it's the first time staking, stake_amount_atomic is the total.
        # If updating, it's more complex if we only pass stake_amount_atomic as a new total.
        # Let's assume add_or_update_validator_stake handles this by taking the full new stake amount.
        # The current ValidatorManager.add_or_update_validator_stake expects `stake_change`.
        # This means if a validator re-registers, it adds to existing stake in manager.
        # This is acceptable for now.
        validator_obj = self.validator_manager.add_or_update_validator_stake(addr, pub_key_hex, stake_amount_atomic)

        if validator_obj:
            VALIDATOR_WALLETS[addr] = validator_wallet
            USER_PUBLIC_KEYS[addr] = pub_key_hex
            print(f"Validator {addr} stake updated by/set to {stake_amount_atomic} atomic units. New balance: {self.balances[addr]}")
        else:
            # If validator registration/update failed, revert balance deduction
            self.balances[addr] = current_balance
            print(f"Failed to update validator {addr} in manager. Balance deduction reverted.")

        # else: # Error already printed by add_or_update_validator_stake

    def __repr__(self):
        chain_str = "Blockchain State:\n"
        chain_str += f"  Total Blocks: {len(self.chain)}\n"
        chain_str += f"  Pending Transactions: {len(self.pending_transactions)}\n"
        chain_str += "  Validators (from Manager):\n"
        if self.validator_manager and self.validator_manager.validators:
            for addr, val_obj in self.validator_manager.validators.items():
                chain_str += f"    - {addr[:15]}... Stake: {val_obj.stake}, Active: {val_obj.is_active}\n"
        else:
            chain_str += "    No validators managed.\n"
        chain_str += "Chain:\n"
        for block in self.chain:
            chain_str += f"  ┗━ {block}\n"
        return chain_str

if __name__ == '__main__':
    from unittest.mock import patch # For __main__ example to work without network

    bc = Blockchain()
    print(bc)
    print("\nBalances after genesis:", bc.balances)
    print("Total EPC supply:", bc.total_supply_epc)

    wallet1 = Wallet()
    wallet2 = Wallet()
    genesis_validator_addr = bc.chain[0].validator_address

    USER_PUBLIC_KEYS[wallet1.address] = wallet1.get_public_key_hex()
    USER_PUBLIC_KEYS[wallet2.address] = wallet2.get_public_key_hex()

    genesis_validator_wallet = VALIDATOR_WALLETS[genesis_validator_addr] # Get the actual wallet

    # Amounts are now atomic units. Assuming constants.DECIMALS for conversion.
    tx1_amount_atomic = constants.to_atomic(1000.0)
    tx1 = Transaction(genesis_validator_addr, wallet1.address, tx1_amount_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx1.sign(genesis_validator_wallet)

    print(f"\nAttempting to add Tx1: {tx1.amount} atomic units of {tx1.asset_id} from {tx1.sender_address[:10]} to {wallet1.address[:10]}")
    if bc.add_transaction(tx1, USER_PUBLIC_KEYS[genesis_validator_addr]):
        print("Tx1 added to pending pool.")
    else:
        print("Tx1 failed to add.")
    print("Balances before mining:", bc.balances) # Should be unchanged yet

    node_cli_wallet = wallet1
    stake_amount_atomic = constants.to_atomic(200.0)
    # The register_validator_wallet in Blockchain calls ValidatorManager.add_or_update_validator_stake,
    # which now expects int for stake_change.
    # However, Blockchain.register_validator_wallet itself still has type hint float for stake_amount.
    # This needs to be harmonized. For now, let's assume register_validator_wallet will handle conversion or be updated.
    # Let's update register_validator_wallet to expect int.
    bc.register_validator_wallet(node_cli_wallet, stake_amount_atomic)
    print(f"Node wallet {node_cli_wallet.address[:10]} staked {stake_amount_atomic} atomic units.")

    # Ensure the validator manager knows about the genesis validator if it might be selected
    # (though typically genesis validator doesn't participate beyond genesis)
    # For this test, we'll ensure node_cli_wallet (wallet1) is selected for mining.

    print("\nAttempting to mine block...")
    # Patch select_next_validator to ensure node_cli_wallet is chosen
    # Need to get the Validator object for node_cli_wallet from the manager
    validator_obj_for_node_cli = bc.validator_manager.get_validator(node_cli_wallet.address)
    if not validator_obj_for_node_cli:
        print(f"ERROR: Test setup issue, {node_cli_wallet.address} not in validator manager after staking.")
    else:
        with patch.object(bc.validator_manager, 'select_next_validator', return_value=validator_obj_for_node_cli):
            mined_block = bc.mine_pending_transactions()

        if mined_block:
            print(f"Mined block {mined_block.index} by {mined_block.validator_address[:10]}")
        else:
            print("Mining failed.")

    print("\nBalances after mining:", bc.balances)
    print(f"Chain valid: {bc.is_chain_valid()}")
    print(bc)

    # Test another transaction
    tx2_amount_atomic = constants.to_atomic(50.0)
    tx2 = Transaction(wallet1.address, wallet2.address, tx2_amount_atomic, asset_id=constants.NATIVE_CURRENCY_SYMBOL)
    tx2.sign(wallet1)
    print(f"\nAttempting to add Tx2: {tx2.amount} atomic units of {tx2.asset_id} from {wallet1.address[:10]} to {wallet2.address[:10]}")
    if bc.add_transaction(tx2, USER_PUBLIC_KEYS[wallet1.address]):
        print("Tx2 added to pending pool.")
    else:
        print("Tx2 failed to add.")

    print("\nAttempting to mine second block...")
    # Assume wallet1 (node_cli_wallet) is still the only staker or will be selected again by round-robin
    validator_obj_for_node_cli = bc.validator_manager.get_validator(node_cli_wallet.address)
    with patch.object(bc.validator_manager, 'select_next_validator', return_value=validator_obj_for_node_cli):
        mined_block_2 = bc.mine_pending_transactions()

    if mined_block_2:
        print(f"Mined block {mined_block_2.index} by {mined_block_2.validator_address[:10]}")
    else:
        print("Second mining failed.")

    print("\nBalances after second mining (atomic units):", bc.balances)
    print(f"Chain valid: {bc.is_chain_valid()}")
    print(bc)

    # Balances are now in atomic units
    expected_genesis_bal_atomic = constants.INITIAL_TOTAL_SUPPLY_EPC_ATOMIC - tx1_amount_atomic
    expected_wallet1_bal_atomic = tx1_amount_atomic - tx2_amount_atomic
    expected_wallet2_bal_atomic = tx2_amount_atomic

    print(f"\nExpected Balances Check (atomic units):")
    print(f"Genesis ({genesis_validator_addr[:10]}): Expected={expected_genesis_bal_atomic}, Actual={bc.balances.get(genesis_validator_addr)}")
    print(f"Wallet1 ({wallet1.address[:10]}): Expected={expected_wallet1_bal_atomic}, Actual={bc.balances.get(wallet1.address)}")
    print(f"Wallet2 ({wallet2.address[:10]}): Expected={expected_wallet2_bal_atomic}, Actual={bc.balances.get(wallet2.address)}")

    assert bc.balances.get(genesis_validator_addr) == expected_genesis_bal_atomic
    assert bc.balances.get(wallet1.address) == expected_wallet1_bal_atomic
    assert bc.balances.get(wallet2.address) == expected_wallet2_bal_atomic
