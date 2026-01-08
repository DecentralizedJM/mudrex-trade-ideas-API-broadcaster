
import logging
from dataclasses import dataclass

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Mocking the SDK Utils ---
def calculate_order_from_usd(usd_amount: float, price: float, quantity_step: float):
    raw_quantity = usd_amount / price
    if quantity_step > 0:
        rounded_quantity = round(raw_quantity / quantity_step) * quantity_step
        # Determine precision
        precision = len(str(quantity_step).split('.')[-1]) if '.' in str(quantity_step) else 0
        rounded_quantity = round(rounded_quantity, precision)
    else:
        rounded_quantity = raw_quantity
        
    actual_value = rounded_quantity * price
    return rounded_quantity, actual_value

@dataclass
class Asset:
    quantity_step: str
    min_quantity: str

# --- Test Functions ---

def test_scenario(symbol, price, trade_amount, balance, asset_q_step, asset_min_qty, leverage=15):
    print(f"\n--- Testing {symbol} ---")
    print(f"Price: {price}, Trade Amount: ${trade_amount}, Balance: ${balance}")
    print(f"Asset: Step={asset_q_step}, MinQty={asset_min_qty}")
    
    # 1. Initial Calculation
    qty, actual_value = calculate_order_from_usd(
        usd_amount=trade_amount,
        price=price,
        quantity_step=float(asset_q_step),
    )
    print(f"Initial: Qty={qty}, Value=${actual_value:.4f}")
    
    # 2. Min Value Logic
    MIN_ORDER_VALUE = 8.0
    if actual_value < MIN_ORDER_VALUE:
        print(f"Value ${actual_value:.2f} < ${MIN_ORDER_VALUE}. Adjusting...")
        
        qty, actual_value = calculate_order_from_usd(
            usd_amount=MIN_ORDER_VALUE,
            price=price,
            quantity_step=float(asset_q_step),
        )
        print(f"Adjusted: Qty={qty}, Value=${actual_value:.4f}")
        
        required_margin = actual_value / leverage
        print(f"Required Margin: ${required_margin:.4f}")
        
        if required_margin * 1.01 > balance:
            print("❌ INSUFFICIENT_BALANCE")
        else:
            print("✅ Adjustment OK")
    else:
        print("✅ Value OK")

# --- Run Scenarios ---

# Scenario 1: WLFIUSDT (The reported issue)
# Price ~0.1714, Amount $2.0, Balance $7.79 (should fail), Balance $11 (should pass)
test_scenario(
    symbol="WLFIUSDT", 
    price=0.1714, 
    trade_amount=2.0, 
    balance=7.79, 
    asset_q_step="1", 
    asset_min_qty="1",
    leverage=15
)

test_scenario(
    symbol="WLFIUSDT", 
    price=0.1714, 
    trade_amount=2.0, 
    balance=12.0, 
    asset_q_step="1", 
    asset_min_qty="1",
    leverage=15
)

# Scenario 2: High Price Asset (BTC)
# Price 95000, Amount $20 (OK) vs $5 (Fail -> Adjust)
test_scenario(
    symbol="BTCUSDT", 
    price=95000.0, 
    trade_amount=5.0, 
    balance=50.0, 
    asset_q_step="0.001", 
    asset_min_qty="0.001",
    leverage=20
)

# Scenario 3: Small Step
test_scenario(
    symbol="XRPUSDT", 
    price=2.5, 
    trade_amount=5.0, 
    balance=100.0, 
    asset_q_step="0.1", 
    asset_min_qty="1",
    leverage=10
)
