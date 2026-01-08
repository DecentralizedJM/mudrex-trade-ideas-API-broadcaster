"""
Signal Broadcaster - Execute trades for all subscribers when a signal is received.

This is the core of the centralized system:
1. Receive signal from admin
2. Loop through all active subscribers
3. Execute trade on each subscriber's Mudrex account (using SDK) - IN PARALLEL
4. Notify each subscriber of result via Telegram DM
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple

from mudrex import MudrexClient
from mudrex.exceptions import MudrexAPIError
from mudrex.utils import calculate_order_from_usd

from .database import Database, Subscriber
from .signal_parser import Signal, SignalType, OrderType, SignalUpdate, SignalClose

logger = logging.getLogger(__name__)


class TradeStatus(Enum):
    SUCCESS = "SUCCESS"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
    API_ERROR = "API_ERROR"
    SKIPPED = "SKIPPED"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"


@dataclass
class TradeResult:
    """Result of a trade execution for one subscriber."""
    subscriber_id: int
    username: Optional[str]
    status: TradeStatus
    message: str
    order_id: Optional[str] = None
    quantity: Optional[str] = None
    actual_value: Optional[float] = None
    # For DB recording
    side: Optional[str] = None
    order_type: Optional[str] = None
    entry_price: Optional[float] = None
    # For insufficient balance flow
    available_balance: Optional[float] = None


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram Markdown."""
    # Characters that need escaping in Markdown: _ * [ ] ( ) ~ ` > # + - = | { } . !
    # For basic Markdown (not MarkdownV2), we mainly need to escape * and _
    escape_chars = ['*', '_', '`', '[']
    for char in escape_chars:
        text = text.replace(char, '\\' + char)
    return text


class SignalBroadcaster:
    """
    Broadcast signals to all subscribers.
    
    Executes trades in parallel for all active subscribers using the Mudrex SDK.
    """
    
    def __init__(self, database: Database):
        self.db = database
    
    async def broadcast_signal(self, signal: Signal) -> Tuple[List[TradeResult], List[Subscriber]]:
        """
        Execute a signal for all active subscribers.
        
        Args:
            signal: The parsed trading signal
            
        Returns:
            Tuple of:
            - List of trade results for AUTO mode subscribers
            - List of MANUAL mode subscribers (for confirmation flow)
        """
        logger.info(f"Broadcasting signal {signal.signal_id} to all subscribers")
        
        # Get all active subscribers
        subscribers = await self.db.get_active_subscribers()
        
        if not subscribers:
            logger.warning("No active subscribers to broadcast to")
            return [], []
        
        logger.info(f"Found {len(subscribers)} subscribers")
        
        # Separate AUTO and MANUAL subscribers
        auto_subscribers = [s for s in subscribers if s.trade_mode == "AUTO"]
        manual_subscribers = [s for s in subscribers if s.trade_mode == "MANUAL"]
        
        logger.info(f"AUTO: {len(auto_subscribers)}, MANUAL: {len(manual_subscribers)}")
        
        # Save signal to database
        await self.db.save_signal(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            signal_type=signal.signal_type.value,
            order_type=signal.order_type.value,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            leverage=signal.leverage,
        )
        
        # Execute for AUTO subscribers in parallel
        if auto_subscribers:
            tasks = [
                self._execute_for_subscriber(signal, subscriber)
                for subscriber in auto_subscribers
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter out exceptions and log them
            trade_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Trade failed for subscriber {auto_subscribers[i].telegram_id}: {result}")
                    trade_results.append(TradeResult(
                        subscriber_id=auto_subscribers[i].telegram_id,
                        username=auto_subscribers[i].username,
                        status=TradeStatus.API_ERROR,
                        message=str(result),
                    ))
                else:
                    # Log all non-success results for debugging
                    if result.status != TradeStatus.SUCCESS:
                        logger.warning(f"Trade {result.status.value} for {result.subscriber_id}: {result.message}")
                    trade_results.append(result)
            
            # Log summary
            success_count = sum(1 for r in trade_results if r.status == TradeStatus.SUCCESS)
            logger.info(f"Signal {signal.signal_id}: {success_count}/{len(trade_results)} AUTO trades successful")
        else:
            trade_results = []
        
        return trade_results, manual_subscribers
    
    async def _execute_for_subscriber(
        self,
        signal: Signal,
        subscriber: Subscriber,
    ) -> TradeResult:
        """Execute a signal for a single subscriber using the Mudrex SDK."""
        
        # Run the blocking SDK calls in a thread pool for true parallelism
        try:
            result = await asyncio.to_thread(
                self._execute_trade_sync,
                signal,
                subscriber,
            )
        except Exception as e:
            logger.error(f"Trade execution failed for {subscriber.telegram_id}: {e}", exc_info=True)
            result = TradeResult(
                subscriber_id=subscriber.telegram_id,
                username=subscriber.username,
                status=TradeStatus.API_ERROR,
                message=str(e),
                side=signal.signal_type.value,
                order_type=signal.order_type.value,
            )
        
        # Record trade to database (async, after thread completes)
        await self.db.record_trade(
            telegram_id=subscriber.telegram_id,
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            side=result.side or signal.signal_type.value,
            order_type=result.order_type or signal.order_type.value,
            status=result.status.value,
            quantity=float(result.quantity) if result.quantity else None,
            entry_price=result.entry_price,
            error_message=result.message if result.status != TradeStatus.SUCCESS else None,
        )
        
        return result
    
    def _execute_trade_sync(
        self,
        signal: Signal,
        subscriber: Subscriber,
    ) -> TradeResult:
        """
        Synchronous trade execution - runs in thread pool.
        This allows multiple trades to execute in parallel.
        """
        logger.info(f"Executing trade for {subscriber.telegram_id}: {signal.symbol} {signal.signal_type.value}")
        
        # Create SDK client for this subscriber (only api_secret needed)
        client = MudrexClient(
            api_secret=subscriber.api_secret
        )
        
        try:
            # Get balance
            logger.info(f"Getting balance for {subscriber.telegram_id}...")
            balance_info = client.wallet.get_futures_balance()
            balance = float(balance_info.balance) if balance_info else 0.0
            logger.info(f"Balance for {subscriber.telegram_id}: {balance} USDT")
            
            # Determine trade margin (amount user wants to bet)
            target_margin = subscriber.trade_amount_usdt
            
            # Auto-adjust if balance is lower than configured margin
            if balance < target_margin:
                # Check if we have any balance at all
                if balance <= 0:
                    return TradeResult(
                        subscriber_id=subscriber.telegram_id,
                        username=subscriber.username,
                        status=TradeStatus.INSUFFICIENT_BALANCE,
                        message=f"No balance available (0 USDT)",
                        side=signal.signal_type.value,
                        order_type=signal.order_type.value,
                        available_balance=balance,
                    )
                # Use entire available balance as margin
                logger.info(f"Auto-adjusting margin from {target_margin} to {balance:.2f} USDT (using available balance)")
                target_margin = balance
            
            # Set leverage (capped at subscriber's max)
            leverage = min(signal.leverage, subscriber.max_leverage)
            logger.info(f"Setting leverage to {leverage} for {signal.symbol}...")
            client.leverage.set(
                symbol=signal.symbol,
                leverage=str(leverage),
                margin_type="ISOLATED"
            )

            # Calculate NOTIONAL amount (Total Order Value = Margin * Leverage)
            trade_amount_notional = target_margin * leverage
            logger.info(f"Target Margin: ${target_margin} x Leverage {leverage} = Notional: ${trade_amount_notional}")

            # Get asset details
            logger.info(f"Getting asset info for {signal.symbol}...")
            try:
                asset = client.assets.get(signal.symbol)
                if not asset:
                    raise ValueError(f"Asset returned None for {signal.symbol}")
            except Exception as asset_error:
                logger.error(f"Symbol lookup failed: {asset_error}")
                return TradeResult(
                    subscriber_id=subscriber.telegram_id,
                    username=subscriber.username,
                    status=TradeStatus.SYMBOL_NOT_FOUND,
                    message=f"Symbol not found: {signal.symbol}",
                    side=signal.signal_type.value,
                    order_type=signal.order_type.value,
                )
            
            # Determine Price
            price = None
            if signal.entry_price:
                price = signal.entry_price
            elif hasattr(asset, 'price') and asset.price:
                try:
                    price = float(asset.price)
                except (ValueError, TypeError):
                    pass
            
            if not price:
                logger.warning(f"Could not determine price for {signal.symbol}, using fallback 1.0")
                price = 1.0
            
            # Round price if needed (for LIMIT orders)
            if hasattr(asset, 'price_step') and asset.price_step:
                try:
                    price_step = float(asset.price_step)
                    if price_step > 0:
                        rounded_price = round(price / price_step) * price_step
                        # Precision logic
                        prec = len(str(asset.price_step).split('.')[-1]) if '.' in str(asset.price_step) else 0
                        price = round(rounded_price, prec)
                except Exception:
                    pass

            # Calculate Quantity from Notional Amount
            qty, actual_value = calculate_order_from_usd(
                usd_amount=trade_amount_notional,
                price=price,
                quantity_step=float(asset.quantity_step),
            )
            
            logger.info(f"Calculated Qty: {qty} (Value: ${actual_value:.2f})")

            # Enforce Minimum Order Value ($8 Notional)
            MIN_ORDER_VALUE = 8.0
            if actual_value < MIN_ORDER_VALUE:
                logger.info(f"Value ${actual_value:.2f} < Min ${MIN_ORDER_VALUE}. Adjusting...")
                qty, actual_value = calculate_order_from_usd(
                    usd_amount=MIN_ORDER_VALUE,
                    price=price,
                    quantity_step=float(asset.quantity_step),
                )
                
                # Check if user has enough balance for this increase
                required_margin = actual_value / leverage
                # 1% buffer
                if required_margin * 1.01 > balance:
                     return TradeResult(
                        subscriber_id=subscriber.telegram_id,
                        username=subscriber.username,
                        status=TradeStatus.INSUFFICIENT_BALANCE,
                        message=f"Balance ${balance:.2f} too low for min order val ${actual_value:.2f} (Req Margin: ~${required_margin:.2f})",
                        side=signal.signal_type.value,
                        order_type=signal.order_type.value,
                        available_balance=balance,
                    )
                logger.info(f"Adjusted to {qty} (${actual_value:.2f})")

            if qty <= 0:
                 return TradeResult(
                    subscriber_id=subscriber.telegram_id,
                    username=subscriber.username,
                    status=TradeStatus.API_ERROR,
                    message=f"Calculated quantity is 0 - amount too low",
                    side=signal.signal_type.value,
                    order_type=signal.order_type.value,
                )

            # Determine side
            side = "LONG" if signal.signal_type == SignalType.LONG else "SHORT"
            qty_str = str(qty)
            
            # Prepare SL/TP params
            sl_param = str(signal.stop_loss) if signal.stop_loss else None
            tp_param = str(signal.take_profit) if signal.take_profit else None

            logger.info(f"Placing Order: {side} {qty_str} {signal.symbol} @ {price or 'Market'}")
            
            if signal.order_type == OrderType.MARKET:
                order = client.orders.create_market_order(
                    symbol=signal.symbol,
                    side=side,
                    quantity=qty_str,
                    leverage=str(leverage),
                    stoploss_price=sl_param,
                    takeprofit_price=tp_param,
                )
            else:
                order = client.orders.create_limit_order(
                    symbol=signal.symbol,
                    side=side,
                    price=str(price),
                    quantity=qty_str,
                    leverage=str(leverage),
                    stoploss_price=sl_param,
                    takeprofit_price=tp_param,
                )
            
            logger.info(f"Order created: {order.order_id if order else 'None'}")
            
            # Success Message
            msg = f"{side} {qty_str} {signal.symbol} (~${actual_value:.2f})"
            if sl_param or tp_param:
                msg += " | SL/TP set"

            return TradeResult(
                subscriber_id=subscriber.telegram_id,
                username=subscriber.username,
                status=TradeStatus.SUCCESS,
                message=msg,
                order_id=order.order_id,
                quantity=qty_str,
                actual_value=actual_value,
                side=side,
                order_type=signal.order_type.value,
                entry_price=signal.entry_price,
            )
            
        except MudrexAPIError as e:
            # Extract more details from the API error
            error_msg = str(e)
            error_code = getattr(e, 'code', 'UNKNOWN')
            status_code = getattr(e, 'status_code', 0)
            request_id = getattr(e, 'request_id', None)
            
            logger.error(f"Mudrex API error for {subscriber.telegram_id}: {error_msg}")
            logger.error(f"  Error code: {error_code}, Status: {status_code}, Request ID: {request_id}")
            logger.error(f"  Full error: {repr(e)}")
            
            # Include more context in the error message
            detailed_msg = f"Mudrex API error: {e.message if hasattr(e, 'message') else error_msg} | Code: {error_code} | Status: {status_code}"
            
            return TradeResult(
                subscriber_id=subscriber.telegram_id,
                username=subscriber.username,
                status=TradeStatus.API_ERROR,
                message=detailed_msg,
                side=signal.signal_type.value,
                order_type=signal.order_type.value,
            )
        except Exception as e:
            logger.error(f"Unexpected error for {subscriber.telegram_id}: {e}", exc_info=True)
            return TradeResult(
                subscriber_id=subscriber.telegram_id,
                username=subscriber.username,
                status=TradeStatus.API_ERROR,
                message=f"Error: {e}",
                side=signal.signal_type.value,
                order_type=signal.order_type.value,
            )
    
    async def broadcast_close(self, close: SignalClose) -> List[TradeResult]:
        """
        Broadcast a close signal to all subscribers.
        
        Note: This is more complex as we need to track which subscribers
        have open positions for this signal. For MVP, we'll mark the signal
        as closed and subscribers can manage manually.
        """
        logger.info(f"Broadcasting close for signal {close.signal_id}")
        
        await self.db.close_signal(close.signal_id)
        
        # For MVP, just mark as closed. Position closing would require
        # tracking position IDs per subscriber, which we can add later.
        return []
    
    async def execute_single_trade(self, signal: Signal, subscriber: Subscriber) -> TradeResult:
        """
        Execute a single trade for a specific subscriber.
        Used for manual confirmation flow.
        
        Args:
            signal: The parsed trading signal
            subscriber: The subscriber who confirmed the trade
            
        Returns:
            Trade result
        """
        logger.info(f"Executing confirmed trade for {subscriber.telegram_id}: {signal.signal_id}")
        return await self._execute_for_subscriber(signal, subscriber)
    
    async def execute_with_amount(
        self, 
        signal: Signal, 
        subscriber: Subscriber, 
        override_amount: float
    ) -> TradeResult:
        """
        Execute a trade with a specific override amount.
        Used when user accepts to trade with available balance instead of configured amount.
        
        Args:
            signal: The parsed trading signal
            subscriber: The subscriber
            override_amount: The amount to use instead of subscriber.trade_amount_usdt
            
        Returns:
            Trade result
        """
        logger.info(f"Executing trade for {subscriber.telegram_id} with override amount: {override_amount} USDT")
        
        # Create a modified subscriber with the override amount
        from dataclasses import replace
        modified_subscriber = replace(subscriber, trade_amount_usdt=override_amount)
        
        return await self._execute_for_subscriber(signal, modified_subscriber)


def format_broadcast_summary(signal: Signal, results: List[TradeResult], manual_count: int = 0) -> str:
    """Format broadcast results for admin notification."""
    success = sum(1 for r in results if r.status == TradeStatus.SUCCESS)
    # Count all failure types
    failed = sum(1 for r in results if r.status in (TradeStatus.API_ERROR, TradeStatus.SYMBOL_NOT_FOUND))
    insufficient = sum(1 for r in results if r.status == TradeStatus.INSUFFICIENT_BALANCE)
    
    manual_line = f"\n👆 Manual (awaiting): {manual_count}" if manual_count > 0 else ""
    
    # Add error details for debugging (without Markdown formatting to avoid parse errors)
    error_details = ""
    failed_results = [r for r in results if r.status in (TradeStatus.API_ERROR, TradeStatus.SYMBOL_NOT_FOUND)]
    if failed_results:
        error_details = "\n\nErrors:\n"
        for r in failed_results[:3]:  # Show max 3 errors
            # Clean the message of any special characters that could break Markdown
            safe_msg = r.message[:80] if r.message else "Unknown error"
            safe_msg = safe_msg.replace('*', '').replace('_', '').replace('`', '').replace('[', '(').replace(']', ')')
            user_id = r.username or str(r.subscriber_id)
            error_details += f"- {user_id}: {safe_msg}\n"
    
    # Use simple formatting to avoid Markdown parse errors
    return f"""📡 Signal Broadcast Complete
━━━━━━━━━━━━━━━━━━━━
🆔 Signal: {signal.signal_id}
📊 {signal.signal_type.value} {signal.symbol}

Results:
✅ Success: {success}
💰 Insufficient Balance: {insufficient}
❌ Failed: {failed}{manual_line}{error_details}
━━━━━━━━━━━━━━━━━━━━
Total: {len(results) + manual_count} subscribers"""


def format_user_trade_notification(signal: Signal, result: TradeResult) -> str:
    """Format trade result notification for a subscriber."""
    if result.status == TradeStatus.SUCCESS:
        qty_info = f"\n📦 Quantity: {result.quantity}" if result.quantity else ""
        value_info = f" (~${result.actual_value:.2f})" if result.actual_value else ""
        return f"""✅ Trade Executed
━━━━━━━━━━━━━━━━━━━━
🆔 Signal: {signal.signal_id}
📊 {signal.signal_type.value} {signal.symbol}
📋 {signal.order_type.value}{qty_info}{value_info}
🛑 SL: {signal.stop_loss or "Not set"}
🎯 TP: {signal.take_profit or "Not set"}
⚡ Leverage: {signal.leverage}x
━━━━━━━━━━━━━━━━━━━━"""
    
    elif result.status == TradeStatus.INSUFFICIENT_BALANCE:
        return f"""💰 Insufficient Balance
━━━━━━━━━━━━━━━━━━━━
🆔 Signal: {signal.signal_id}
📊 {signal.signal_type.value} {signal.symbol}

{result.message}

Use /setamount to adjust your trade size.
━━━━━━━━━━━━━━━━━━━━"""
    
    elif result.status == TradeStatus.SYMBOL_NOT_FOUND:
        return f"""❌ Symbol Not Found
━━━━━━━━━━━━━━━━━━━━
🆔 Signal: {signal.signal_id}
📊 {signal.symbol}

This trading pair is not available on Mudrex.
━━━━━━━━━━━━━━━━━━━━"""
    
    else:
        # API_ERROR or other
        safe_msg = result.message[:150] if result.message else "Unknown error"
        return f"""❌ Trade Failed
━━━━━━━━━━━━━━━━━━━━
🆔 Signal: {signal.signal_id}
📊 {signal.signal_type.value} {signal.symbol}

Error: {safe_msg}
━━━━━━━━━━━━━━━━━━━━"""
