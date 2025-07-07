# Manages the set of validators for Proof-of-Stake consensus.

import time
from typing import Dict, List, Optional
from empower1.consensus.validator import Validator
# from empower1.wallet import Wallet # For type hinting if manager stores Wallet objects

# For now, ValidatorManager relies on external Wallet objects for signing if needed by Blockchain.
# It primarily manages Validator data objects.

# Example minimum stake in atomic units (e.g., 100 EPC if 6 decimals = 100 * 10^6)
MIN_STAKE_TO_BE_ACTIVE_ATOMIC = 100_000_000

class ValidatorManager:
    """
    Manages the collection of validators, their stakes, and selects block producers.
    Stakes are handled in atomic units.
    """
    def __init__(self, min_stake_active: int = MIN_STAKE_TO_BE_ACTIVE_ATOMIC): # Now int
        # Stores Validator objects, keyed by their wallet_address
        self.validators: Dict[str, Validator] = {}
        self.min_stake_active: int = min_stake_active # Ensure type

        # For round-robin selection, keep a sorted list of active validator addresses
        self._active_validator_addresses_round_robin: List[str] = []
        self._last_selected_validator_index_rr = -1 # For round-robin

        print(f"ValidatorManager initialized. Min stake for active: {self.min_stake_active}")

    def get_validator(self, validator_wallet_address: str) -> Optional[Validator]:
        """Retrieves a validator by their wallet address."""
        return self.validators.get(validator_wallet_address)

    def add_or_update_validator_stake(self, validator_wallet_address: str, public_key_hex: str, stake_change: int): # stake_change is now int
        """
        Adds a new validator or updates the stake of an existing one (in atomic units).
        Args:
            validator_wallet_address (str): The validator's unique wallet address.
            public_key_hex (str): The validator's public key hex.
            stake_change (int): The amount in atomic units to add to the stake (can be negative).
        Returns:
            Optional[Validator]: The updated or new Validator object, or None if error.
        """
        if not validator_wallet_address or not public_key_hex:
            print("Error: Validator address and public key hex are required.")
            return None
        if not isinstance(stake_change, int):
            # Or attempt conversion, but stricter is better for internal consistency
            print("Error: stake_change must be an integer (atomic units).")
            return None

        validator = self.validators.get(validator_wallet_address)
        if not validator:
            if stake_change < 0:
                print(f"Error: Cannot initialize validator {validator_wallet_address} with negative stake contribution.")
                return None
            # Validator class now expects stake as int
            validator = Validator(wallet_address=validator_wallet_address, public_key_hex=public_key_hex, stake=stake_change)
            self.validators[validator_wallet_address] = validator
            print(f"New validator registered: {validator.wallet_address} with stake {validator.stake} atomic units.")
        else:
            if validator.public_key_hex != public_key_hex:
                print(f"Warning: Public key for existing validator {validator_wallet_address} does not match provided. Using existing.")

            # Validator.update_stake expects int
            validator.update_stake(additional_stake=stake_change)
            print(f"Validator {validator.wallet_address} stake updated to {validator.stake} atomic units.")

        # Update active status and rebuild round-robin list
        self._update_validator_active_status(validator)
        self._rebuild_active_validator_list_for_round_robin()
        return validator

    def _update_validator_active_status(self, validator: Validator):
        """Updates the active status of a validator based on their stake."""
        is_now_active = validator.stake >= self.min_stake_active
        if validator.is_active != is_now_active:
            validator.is_active = is_now_active
            print(f"Validator {validator.wallet_address} active status changed to: {validator.is_active} (Stake: {validator.stake})")
            # Rebuild list when any validator's active status changes
            self._rebuild_active_validator_list_for_round_robin()


    def _rebuild_active_validator_list_for_round_robin(self):
        """Rebuilds and sorts the list of active validator addresses for round-robin selection."""
        self._active_validator_addresses_round_robin = sorted([
            addr for addr, val in self.validators.items() if val.is_active
        ])
        # Reset index if current selection is out of bounds or list changed significantly
        if self._last_selected_validator_index_rr >= len(self._active_validator_addresses_round_robin):
            self._last_selected_validator_index_rr = -1
        # print(f"Active validator list for round-robin rebuilt: {len(self._active_validator_addresses_round_robin)} active validators.")


    def get_active_validators(self) -> List[Validator]:
        """Returns a list of all currently active validators."""
        return [val for val in self.validators.values() if val.is_active]

    def select_next_validator_round_robin(self) -> Optional[Validator]:
        """
        Selects the next validator using a simple round-robin scheme
        from the list of active validators.
        Returns:
            Optional[Validator]: The selected validator, or None if no active validators.
        """
        active_validators = self._active_validator_addresses_round_robin
        if not active_validators:
            # print("No active validators available for round-robin selection.")
            return None

        self._last_selected_validator_index_rr = (self._last_selected_validator_index_rr + 1) % len(active_validators)
        selected_address = active_validators[self._last_selected_validator_index_rr]
        selected_validator = self.validators.get(selected_address)

        if selected_validator:
            # print(f"Round-robin selected validator: {selected_validator.wallet_address}")
            selected_validator.record_block_production() # Update their last production time
        return selected_validator

    def select_next_validator(self, strategy: str = "round_robin") -> Optional[Validator]:
        """
        Selects the next validator based on the chosen strategy.
        Args:
            strategy (str): "round_robin" or future strategies like "weighted_random".
        Returns:
            Optional[Validator]: The selected validator.
        """
        if strategy == "round_robin":
            return self.select_next_validator_round_robin()
        # elif strategy == "weighted_random_stake":
        #     return self.select_next_validator_weighted_stake() # To be implemented
        else:
            print(f"Warning: Unknown validator selection strategy '{strategy}'. Defaulting to round-robin.")
            return self.select_next_validator_round_robin()

    def set_minimum_stake(self, min_stake_atomic: int): # now int
        """Sets a new minimum stake (in atomic units) and re-evaluates active statuses."""
        if not isinstance(min_stake_atomic, int) or min_stake_atomic < 0:
            raise ValueError("Minimum stake must be a non-negative integer (atomic units).")
        self.min_stake_active = min_stake_atomic
        print(f"Minimum stake to be active set to: {self.min_stake_active} atomic units.")
        for validator in self.validators.values():
            self._update_validator_active_status(validator)
        self._rebuild_active_validator_list_for_round_robin()


if __name__ == '__main__':
    # Assuming constants.DECIMALS is accessible or defined for to_atomic
    # For standalone __main__, let's define a simple to_atomic or use large integers directly.
    # For simplicity, we'll use large integers representing atomic units.
    # MIN_STAKE_TO_BE_ACTIVE_ATOMIC is already defined in the module.
    manager = ValidatorManager(min_stake_active=MIN_STAKE_TO_BE_ACTIVE_ATOMIC) # Uses atomic

    # Dummy data for standalone run
    class DemoWallet:
        def __init__(self, num):
            self.address = f"Emp1_ValAddr_{num:03d}"
            self.public_key_hex = f"04dummyPubKeyHexForVal{num:03d}" + "f" * 78

    wallet_val1 = DemoWallet(1)
    wallet_val2 = DemoWallet(2)
    wallet_val3 = DemoWallet(3)

    # Add validators with atomic units for stake
    # Assuming 6 decimals for display consistency if these were from floats:
    # 150.0 -> 150_000_000
    # 50.0  -> 50_000_000
    # 200.0 -> 200_000_000
    manager.add_or_update_validator_stake(wallet_val1.address, wallet_val1.public_key_hex, 150_000_000)
    manager.add_or_update_validator_stake(wallet_val2.address, wallet_val2.public_key_hex, 50_000_000)
    manager.add_or_update_validator_stake(wallet_val3.address, wallet_val3.public_key_hex, 200_000_000)

    print("\nActive validators:", [v.wallet_address for v in manager.get_active_validators()])
    assert len(manager.get_active_validators()) == 2

    print("\n--- Round-Robin Selection ---")
    selections = []
    for i in range(5):
        selected = manager.select_next_validator()
        if selected:
            selections.append(selected.wallet_address)
            print(f"Selection {i+1}: {selected.wallet_address} (Stake: {selected.stake}, LastProd: {selected.last_block_produced_timestamp:.0f})")
        else:
            print("No validator selected.")
            break

    # Expected: Emp1_ValAddr_001, Emp1_ValAddr_003, Emp1_ValAddr_001, Emp1_ValAddr_003, Emp1_ValAddr_001 (or similar based on sort order)
    print("Selections:", selections)
    assert selections.count(wallet_val1.address) >= 2
    assert selections.count(wallet_val3.address) >= 2


    print("\n--- Updating Stake for Validator 2 to become active ---")
    manager.add_or_update_validator_stake(wallet_val2.address, wallet_val2.public_key_hex, 100_000_000) # 50M + 100M = 150M (active)
    assert manager.get_validator(wallet_val2.address).is_active is True
    print("Active validators:", [v.wallet_address for v in manager.get_active_validators()])
    assert len(manager.get_active_validators()) == 3

    print("\n--- Round-Robin Selection (with 3 active) ---")
    manager._last_selected_validator_index_rr = -1 # Reset for predictable sequence
    selections_3val = [manager.select_next_validator().wallet_address for _ in range(6)]
    print("Selections (3 active):", selections_3val)
    # Expected: Val1, Val2, Val3, Val1, Val2, Val3 (or permutation based on sort of addresses)
    assert selections_3val.count(wallet_val1.address) == 2
    assert selections_3val.count(wallet_val2.address) == 2
    assert selections_3val.count(wallet_val3.address) == 2


    print("\n--- Reducing Stake for Validator 1 to become inactive ---")
    manager.add_or_update_validator_stake(wallet_val1.address, wallet_val1.public_key_hex, -100_000_000) # 150M - 100M = 50M (inactive)
    assert manager.get_validator(wallet_val1.address).is_active is False
    print("Active validators:", [v.wallet_address for v in manager.get_active_validators()])
    assert len(manager.get_active_validators()) == 2

    print("\nValidatorManager demo complete.")
