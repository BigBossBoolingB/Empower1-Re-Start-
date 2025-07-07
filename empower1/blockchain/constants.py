# empower1/blockchain/constants.py

# Native Currency Definitions
NATIVE_CURRENCY_NAME = "EmPowerCoin"
NATIVE_CURRENCY_SYMBOL = "EPC" # Used as asset_id for native currency transactions

# Total initial supply in atomic units.
# Example: 1,000,000 whole coins with 6 decimal places.
# 1,000,000 * (10^6) = 1,000,000,000,000
INITIAL_TOTAL_SUPPLY_EPC_ATOMIC = 1_000_000_000_000

# Number of decimal places for the native currency.
# This is for display purposes; internal calculations should use atomic units.
DECIMALS = 6

# --- Other Potential Constants ---
# STAKE_ADDRESS = "Emp1_SystemStakeAddress_XXXXXXXXXXXXXXXXXXXX" # If staking involves transfers to a special address
# MIN_STAKE_AMOUNT_ATOMIC = 100_000_000 # Example: 100 EPC
# TRANSACTION_FEE_ATOMIC = 10_000 # Example: 0.01 EPC

# Helper function (optional, but can be useful)
def to_atomic(amount_float: float) -> int:
    """Converts a float amount of the native currency to its atomic unit (integer)."""
    return int(amount_float * (10**DECIMALS))

def from_atomic(amount_atomic: int) -> float:
    """Converts an atomic unit amount (integer) of the native currency to its float representation."""
    return float(amount_atomic / (10**DECIMALS))
