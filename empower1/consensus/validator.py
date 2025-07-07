# Defines the Validator class for the EmPower1 Blockchain.

import time

class Validator:
    """
    Represents a validator node in the EmPower1 Proof-of-Stake system.
    """
    def __init__(self, wallet_address: str, public_key_hex: str, stake: int = 0): # stake is now int (atomic units)
        """
        Initializes a Validator.
        Args:
            wallet_address (str): The wallet address of the validator. Used for identification and receiving rewards.
            public_key_hex (str): The public key (hex string) of the validator, used for verifying block signatures.
            stake (int, optional): The amount of currency staked by this validator in atomic units. Defaults to 0.
        """
        if not wallet_address or not isinstance(wallet_address, str):
            raise ValueError("Validator wallet_address must be a non-empty string.")
        if not public_key_hex or not isinstance(public_key_hex, str): # Basic check, could validate hex format
            raise ValueError("Validator public_key_hex must be a non-empty string.")
        if not isinstance(stake, int) or stake < 0: # stake must be non-negative integer
            raise ValueError("Validator stake must be a non-negative integer (atomic units).")

        self.wallet_address = wallet_address
        self.public_key_hex = public_key_hex
        self.stake: int = stake # Ensure type

        # Timestamp of the last block this validator proposed or was chosen to propose.
        # Can be used for round-robin or other fairness mechanisms.
        # Initialized to 0, meaning they haven't produced a block recently relative to others.
        self.last_block_produced_timestamp = 0.0
        # Or self.last_block_produced_index = -1

        self.is_active = False # Determined by stake meeting minimum, registration status, etc.
        self.joined_timestamp = time.time()

        # Optional: for future slashing/reputation mechanisms
        # self.penalties = 0
        # self.jailed_until_timestamp = 0

    def update_stake(self, additional_stake: int = 0, new_total_stake: int = -1): # Amounts are now int
        """
        Updates the validator's stake in atomic units.
        Can either add to existing stake or set a new total stake.
        Args:
            additional_stake (int): Amount in atomic units to add to the current stake.
            new_total_stake (int): If provided and non-negative, sets the stake to this value in atomic units.
        """
        if new_total_stake != -1:  # Check if new_total_stake was explicitly provided
            if not isinstance(new_total_stake, int):
                raise ValueError("New total stake must be an integer (atomic units).")
            if new_total_stake < 0:
                raise ValueError("New total stake cannot be negative.")
            self.stake = new_total_stake
        elif additional_stake != 0: # Only apply additional_stake if new_total_stake was not provided
            if not isinstance(additional_stake, int):
                raise ValueError("Additional stake must be an integer (atomic units).")
            self.stake += additional_stake
            if self.stake < 0: # Ensure stake doesn't go negative
                self.stake = 0
        # If both are defaults (new_total_stake=-1, additional_stake=0), stake remains unchanged.

        # Ensure stake is not negative after any operation.
        if self.stake < 0:
            self.stake = 0

        # Note: Activating/deactivating based on stake changes would typically be handled
        # by the ValidatorManager.

    def record_block_production(self, timestamp: float = None, block_index: int = None):
        """
        Records that this validator has produced a block.
        Updates the timestamp or index for use in selection algorithms.
        """
        self.last_block_produced_timestamp = timestamp or time.time()
        # if block_index is not None:
        #    self.last_block_produced_index = block_index

    def __repr__(self):
        return (f"Validator(Addr: {self.wallet_address[:10]}..., PubKey: {self.public_key_hex[:10]}..., "
                f"Stake: {self.stake}, Active: {self.is_active}, LastProdTS: {self.last_block_produced_timestamp:.0f})")

    def __eq__(self, other):
        if isinstance(other, Validator):
            return self.wallet_address == other.wallet_address
        return False

    def __hash__(self):
        return hash(self.wallet_address)

    def to_dict(self) -> dict:
        """Returns a dictionary representation of the Validator."""
        return {
            "wallet_address": self.wallet_address,
            "public_key_hex": self.public_key_hex,
            "stake": self.stake,
            "last_block_produced_timestamp": self.last_block_produced_timestamp,
            "is_active": self.is_active,
            "joined_timestamp": self.joined_timestamp
        }

    @classmethod
    def from_dict(cls, data: dict):
        """Creates a Validator instance from a dictionary."""
        validator = cls(
            wallet_address=data['wallet_address'],
            public_key_hex=data['public_key_hex'],
            stake=data.get('stake', 0) # Default to integer 0
        )
        validator.last_block_produced_timestamp = data.get('last_block_produced_timestamp', 0.0)
        validator.is_active = data.get('is_active', False)
        validator.joined_timestamp = data.get('joined_timestamp', time.time()) # Default to now if missing
        return validator

if __name__ == '__main__':
    # Requires Wallet to be importable for a full demo with real addresses/keys
    # from empower1.wallet import Wallet # Assume this path works if run from project root

    # Dummy data for standalone run
    class DummyWallet:
        def __init__(self, num):
            self.address = f"Emp1_ValAddr_{num:03}"
            self.public_key_hex = f"04dummyPubKeyHexForValidator{num:03}" + "a" * 80 # Ensure it's long enough

    val_wallet1 = DummyWallet(1)
    val_wallet2 = DummyWallet(2)

    validator1 = Validator(wallet_address=val_wallet1.address, public_key_hex=val_wallet1.public_key_hex, stake=1000.0)
    validator1.is_active = True # Manually set for demo
    print(validator1)

    validator1.update_stake(additional_stake=500.0)
    print(f"After adding 500 stake: {validator1}")
    assert validator1.stake == 1500.0

    validator1.update_stake(new_total_stake=1200.0)
    print(f"After setting total stake to 1200: {validator1}")
    assert validator1.stake == 1200.0

    validator1.record_block_production()
    print(f"After recording block production: {validator1}")
    assert validator1.last_block_produced_timestamp > 0

    validator2 = Validator(wallet_address=val_wallet2.address, public_key_hex=val_wallet2.public_key_hex, stake=2000.0)
    print(validator2)

    # Test equality and hashing
    validator1_copy = Validator(wallet_address=val_wallet1.address, public_key_hex="differentpkh", stake=100.0)
    assert validator1 == validator1_copy # Equality based on wallet_address

    validator_set = {validator1, validator2, validator1_copy}
    assert len(validator_set) == 2 # validator1 and validator1_copy are considered the same

    print("\nValidator class demo complete.")

    try:
        Validator("test_addr", "test_pk", stake=-10)
    except ValueError as e:
        print(f"Caught expected error for negative stake: {e}")

    try:
        Validator("", "test_pk")
    except ValueError as e:
        print(f"Caught expected error for empty address: {e}")

    try:
        Validator("test_addr", "")
    except ValueError as e:
        print(f"Caught expected error for empty pubkey: {e}")
