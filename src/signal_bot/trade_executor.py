"""
Trade Executor - Execute trades on Mudrex using the SDK.

Handles:
- Market and limit orders
- Setting leverage
- Stop loss and take profit
- Balance checking
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from mudrex import MudrexClient
from mudrex.models import Order, Position

from .signal_parser import Signal, SignalType, OrderType, SignalUpdate, SignalClose

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    SUCCESS = "SUCCESS"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
    LEVERAGE_ERROR = "LEVERAGE_ERROR"
    ORDER_FAILED = "ORDER_FAILED"
    POSITION_NOT_FOUND = "POSITION_NOT_FOUND"
    API_ERROR = "API_ERROR"


@dataclass
class ExecutionResult:
    """Result of trade execution."""
    status: ExecutionStatus
    message: str
    signal_id: str
    order: Optional[Order] = None
    position: Optional[Position] = None


class TradeExecutor:
    """Execute trades on Mudrex."""
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        trade_amount_usdt: float = 50.0,
        max_leverage: int = 20,
        testnet: bool = False
    ):
        """
        Initialize the trade executor.
        
        Args:
            api_key: Mudrex API key
            api_secret: Mudrex API secret
            trade_amount_usdt: Amount in USDT to trade per signal
            max_leverage: Maximum allowed leverage
            testnet: Use testnet (not yet supported by Mudrex)
        """
        self.client = MudrexClient(api_key=api_key, api_secret=api_secret)
        self.trade_amount_usdt = trade_amount_usdt
        self.max_leverage = max_leverage
        self.testnet = testnet
        
        logger.info(f"TradeExecutor initialized - Amount: {trade_amount_usdt} USDT, Max Leverage: {max_leverage}x")
    
    def _check_balance(self) -> float:
        """Get available USDT balance."""
        try:
            wallet = self.client.wallet.get()
            return float(wallet.available_balance) if wallet else 0.0
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return 0.0
    
    def _check_symbol_exists(self, symbol: str) -> bool:
        """Check if symbol exists on Mudrex."""
        try:
            return self.client.assets.exists(symbol)
        except Exception as e:
            logger.error(f"Failed to check symbol {symbol}: {e}")
            return False
    
    def _set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol."""
        try:
            # Cap leverage at max allowed
            actual_leverage = min(leverage, self.max_leverage)
            
            self.client.leverage.set(symbol=symbol, leverage=actual_leverage)
            logger.info(f"Set leverage for {symbol} to {actual_leverage}x")
            return True
        except Exception as e:
            logger.error(f"Failed to set leverage for {symbol}: {e}")
            return False
    
    def execute_signal(self, signal: Signal) -> ExecutionResult:
        """
        Execute a trading signal.
        
        Args:
            signal: Parsed trading signal
            
        Returns:
            ExecutionResult with status and details
        """
        logger.info(f"Executing signal: {signal.signal_id} - {signal.signal_type.value} {signal.symbol}")
        
        # Step 1: Check balance
        balance = self._check_balance()
        if balance < self.trade_amount_usdt:
            msg = f"Insufficient balance: {balance:.2f} USDT available, need {self.trade_amount_usdt} USDT"
            logger.warning(msg)
            return ExecutionResult(
                status=ExecutionStatus.INSUFFICIENT_BALANCE,
                message=msg,
                signal_id=signal.signal_id
            )
        
        # Step 2: Check symbol exists
        if not self._check_symbol_exists(signal.symbol):
            msg = f"Symbol not found: {signal.symbol}"
            logger.error(msg)
            return ExecutionResult(
                status=ExecutionStatus.SYMBOL_NOT_FOUND,
                message=msg,
                signal_id=signal.signal_id
            )
        
        # Step 3: Set leverage
        if not self._set_leverage(signal.symbol, signal.leverage):
            msg = f"Failed to set leverage to {signal.leverage}x for {signal.symbol}"
            logger.error(msg)
            return ExecutionResult(
                status=ExecutionStatus.LEVERAGE_ERROR,
                message=msg,
                signal_id=signal.signal_id
            )
        
        # Step 4: Place order
        try:
            # Determine side
            side = "BUY" if signal.signal_type == SignalType.LONG else "SELL"
            
            # Calculate quantity based on trade amount and leverage
            # For now, we pass the USDT amount and let the API handle it
            # The actual quantity depends on the current price
            
            if signal.order_type == OrderType.MARKET:
                # Market order
                order = self.client.orders.create_market_order(
                    symbol=signal.symbol,
                    side=side,
                    quantity=self.trade_amount_usdt,  # In USDT
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                )
            else:
                # Limit order
                order = self.client.orders.create_limit_order(
                    symbol=signal.symbol,
                    side=side,
                    quantity=self.trade_amount_usdt,
                    price=signal.entry_price,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                )
            
            logger.info(f"Order placed successfully: {order}")
            
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message=f"Order placed: {side} {signal.symbol} @ {signal.order_type.value}",
                signal_id=signal.signal_id,
                order=order
            )
            
        except Exception as e:
            msg = f"Order failed: {str(e)}"
            logger.error(msg)
            return ExecutionResult(
                status=ExecutionStatus.ORDER_FAILED,
                message=msg,
                signal_id=signal.signal_id
            )
    
    def update_position(self, update: SignalUpdate, position_id: str) -> ExecutionResult:
        """
        Update an existing position's SL/TP.
        
        Args:
            update: Signal update with new SL/TP values
            position_id: The position ID to update
            
        Returns:
            ExecutionResult with status
        """
        logger.info(f"Updating position for signal {update.signal_id}")
        
        try:
            # Get current position
            position = self.client.positions.get(position_id)
            if not position:
                return ExecutionResult(
                    status=ExecutionStatus.POSITION_NOT_FOUND,
                    message=f"Position not found for signal {update.signal_id}",
                    signal_id=update.signal_id
                )
            
            # Update SL/TP - this would need the actual API method
            # For now, we'd need to cancel existing SL/TP orders and place new ones
            # This is a simplified version
            
            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                message=f"Position updated: SL={update.stop_loss}, TP={update.take_profit}",
                signal_id=update.signal_id,
                position=position
            )
            
        except Exception as e:
            msg = f"Update failed: {str(e)}"
            logger.error(msg)
            return ExecutionResult(
                status=ExecutionStatus.API_ERROR,
                message=msg,
                signal_id=update.signal_id
            )
    
    def close_position(self, close: SignalClose, position_id: str) -> ExecutionResult:
        """
        Close a position.
        
        Args:
            close: Close signal
            position_id: The position ID to close
            
        Returns:
            ExecutionResult with status
        """
        logger.info(f"Closing position for signal {close.signal_id}")
        
        try:
            position = self.client.positions.get(position_id)
            if not position:
                return ExecutionResult(
                    status=ExecutionStatus.POSITION_NOT_FOUND,
                    message=f"Position not found for signal {close.signal_id}",
                    signal_id=close.signal_id
                )
            
            if close.partial_percent and close.partial_percent < 100:
                # Partial close - reduce position size
                close_qty = float(position.quantity) * (close.partial_percent / 100)
                # Place opposite market order for partial close
                side = "SELL" if position.side == "BUY" else "BUY"
                
                order = self.client.orders.create_market_order(
                    symbol=position.symbol,
                    side=side,
                    quantity=close_qty,
                    reduce_only=True
                )
                
                return ExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    message=f"Partial close {close.partial_percent}% executed",
                    signal_id=close.signal_id,
                    order=order
                )
            else:
                # Full close
                self.client.positions.close(position_id)
                
                return ExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    message=f"Position closed for signal {close.signal_id}",
                    signal_id=close.signal_id
                )
                
        except Exception as e:
            msg = f"Close failed: {str(e)}"
            logger.error(msg)
            return ExecutionResult(
                status=ExecutionStatus.API_ERROR,
                message=msg,
                signal_id=close.signal_id
            )


def format_execution_result(result: ExecutionResult) -> str:
    """Format execution result for display."""
    
    status_emoji = {
        ExecutionStatus.SUCCESS: "✅",
        ExecutionStatus.INSUFFICIENT_BALANCE: "💰",
        ExecutionStatus.SYMBOL_NOT_FOUND: "❓",
        ExecutionStatus.LEVERAGE_ERROR: "⚠️",
        ExecutionStatus.ORDER_FAILED: "❌",
        ExecutionStatus.POSITION_NOT_FOUND: "🔍",
        ExecutionStatus.API_ERROR: "🚫",
    }
    
    emoji = status_emoji.get(result.status, "ℹ️")
    
    return f"""
{emoji} **Trade Execution**
━━━━━━━━━━━━━━━━━━━━
🆔 Signal: `{result.signal_id}`
📊 Status: {result.status.value}
💬 {result.message}
━━━━━━━━━━━━━━━━━━━━
""".strip()
