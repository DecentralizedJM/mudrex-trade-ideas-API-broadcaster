"""
Telegram Bot - Listen to signal channel and execute trades.

This bot:
1. Monitors a Telegram channel/group for signal commands
2. Parses the signals
3. Executes trades on Mudrex
4. Tracks positions for updates/closes
5. Notifies user of execution results
"""

import asyncio
import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .signal_parser import (
    SignalParser,
    Signal,
    SignalUpdate,
    SignalClose,
    SignalParseError,
    format_signal_summary,
)
from .trade_executor import (
    TradeExecutor,
    ExecutionStatus,
    format_execution_result,
)
from .position_tracker import (
    PositionTracker,
    format_tracker_stats,
)

logger = logging.getLogger(__name__)


class SignalBot:
    """
    Telegram Signal Bot for Mudrex Trading.
    
    Listens to a channel for trading signals and auto-executes them.
    """
    
    def __init__(
        self,
        telegram_token: str,
        signal_channel_id: int,
        api_key: str,
        api_secret: str,
        trade_amount_usdt: float = 50.0,
        max_leverage: int = 20,
        data_file: str = "signals.json",
    ):
        """
        Initialize the signal bot.
        
        Args:
            telegram_token: Telegram bot token from @BotFather
            signal_channel_id: Channel/group ID to monitor for signals
            api_key: Mudrex API key
            api_secret: Mudrex API secret
            trade_amount_usdt: Amount in USDT per trade
            max_leverage: Maximum allowed leverage
            data_file: File to persist signal tracking data
        """
        self.telegram_token = telegram_token
        self.signal_channel_id = signal_channel_id
        
        # Initialize components
        self.executor = TradeExecutor(
            api_key=api_key,
            api_secret=api_secret,
            trade_amount_usdt=trade_amount_usdt,
            max_leverage=max_leverage,
        )
        
        self.tracker = PositionTracker(data_file=data_file)
        
        # Telegram application
        self.app: Optional[Application] = None
        
        logger.info(f"SignalBot initialized - Channel: {signal_channel_id}")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        await update.message.reply_text(
            "🤖 **Mudrex Signal Bot**\n\n"
            "I'm listening for trading signals and will auto-execute them on Mudrex.\n\n"
            "**Commands:**\n"
            "/start - Show this message\n"
            "/status - Show active signals\n"
            "/stats - Show trading statistics\n"
            "/balance - Check wallet balance\n\n"
            "**Signal Format:**\n"
            "`/signal LONG BTCUSDT entry=50000 sl=49000 tp=52000 lev=10x`\n"
            "`/signal SHORT ETHUSDT market sl=3800 tp=3500 lev=5x`\n"
            "`/update SIG-XXXXXXXX-XXX sl=49500`\n"
            "`/close SIG-XXXXXXXX-XXX`\n"
            "`/partial SIG-XXXXXXXX-XXX 50%`",
            parse_mode="Markdown"
        )
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command - show active signals."""
        active = self.tracker.get_active_signals()
        
        if not active:
            await update.message.reply_text("📭 No active signals")
            return
        
        msg = "📊 **Active Signals**\n━━━━━━━━━━━━━━━━━━━━\n"
        for sig in active.values():
            emoji = "📈" if sig.signal_type == "LONG" else "📉"
            msg += f"{emoji} `{sig.signal_id}` {sig.symbol} {sig.signal_type}\n"
            msg += f"   SL: {sig.stop_loss} | TP: {sig.take_profit}\n"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command - show statistics."""
        stats_text = format_tracker_stats(self.tracker)
        await update.message.reply_text(stats_text, parse_mode="Markdown")
    
    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /balance command - check wallet balance."""
        try:
            balance = self.executor._check_balance()
            await update.message.reply_text(
                f"💰 **Wallet Balance**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Available: **{balance:.2f} USDT**",
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Failed to get balance: {e}")
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages - parse and execute signals."""
        message = update.message
        
        if not message or not message.text:
            return
        
        # Only process messages from the signal channel (or private messages for testing)
        chat_id = message.chat_id
        if chat_id != self.signal_channel_id and message.chat.type != "private":
            return
        
        text = message.text.strip()
        
        # Skip if not a signal command
        if not text.startswith('/'):
            return
        
        try:
            parsed = SignalParser.parse(text)
            
            if parsed is None:
                # Not a signal command we recognize
                return
            
            if isinstance(parsed, Signal):
                await self._handle_new_signal(message, parsed)
            elif isinstance(parsed, SignalUpdate):
                await self._handle_update(message, parsed)
            elif isinstance(parsed, SignalClose):
                await self._handle_close(message, parsed)
                
        except SignalParseError as e:
            await message.reply_text(f"⚠️ Signal parse error: {e}")
        except Exception as e:
            logger.exception(f"Error handling message: {e}")
            await message.reply_text(f"❌ Error: {e}")
    
    async def _handle_new_signal(self, message, signal: Signal):
        """Handle a new trading signal."""
        # Show signal received
        summary = format_signal_summary(signal)
        await message.reply_text(summary, parse_mode="Markdown")
        
        # Execute the trade
        result = self.executor.execute_signal(signal)
        
        # Track the signal
        if result.status == ExecutionStatus.SUCCESS:
            order_id = result.order.order_id if result.order else None
            self.tracker.add_signal(signal, order_id=order_id, status="FILLED")
        elif result.status == ExecutionStatus.INSUFFICIENT_BALANCE:
            # Still track it but as skipped
            self.tracker.add_signal(signal, status="SKIPPED")
        else:
            self.tracker.add_signal(signal, status="FAILED")
        
        # Send result
        result_text = format_execution_result(result)
        await message.reply_text(result_text, parse_mode="Markdown")
    
    async def _handle_update(self, message, update: SignalUpdate):
        """Handle a signal update."""
        # Get the tracked signal
        tracked = self.tracker.get_signal(update.signal_id)
        if not tracked:
            await message.reply_text(f"❓ Signal not found: {update.signal_id}")
            return
        
        if tracked.status == "CLOSED":
            await message.reply_text(f"⚠️ Signal {update.signal_id} is already closed")
            return
        
        # Update the position
        if tracked.position_id:
            result = self.executor.update_position(update, tracked.position_id)
            result_text = format_execution_result(result)
            await message.reply_text(result_text, parse_mode="Markdown")
        
        # Update tracker
        self.tracker.update_signal(
            update.signal_id,
            stop_loss=update.stop_loss,
            take_profit=update.take_profit,
        )
        
        await message.reply_text(
            f"✅ Signal `{update.signal_id}` updated\n"
            f"SL: {update.stop_loss or tracked.stop_loss}\n"
            f"TP: {update.take_profit or tracked.take_profit}",
            parse_mode="Markdown"
        )
    
    async def _handle_close(self, message, close: SignalClose):
        """Handle a signal close."""
        # Get the tracked signal
        tracked = self.tracker.get_signal(close.signal_id)
        if not tracked:
            await message.reply_text(f"❓ Signal not found: {close.signal_id}")
            return
        
        if tracked.status == "CLOSED":
            await message.reply_text(f"⚠️ Signal {close.signal_id} is already closed")
            return
        
        # Close the position
        if tracked.position_id:
            result = self.executor.close_position(close, tracked.position_id)
            result_text = format_execution_result(result)
            await message.reply_text(result_text, parse_mode="Markdown")
        
        # Update tracker
        if close.partial_percent and close.partial_percent < 100:
            await message.reply_text(
                f"✅ Partial close {close.partial_percent}% for `{close.signal_id}`",
                parse_mode="Markdown"
            )
        else:
            self.tracker.close_signal(close.signal_id)
            await message.reply_text(
                f"✅ Signal `{close.signal_id}` closed",
                parse_mode="Markdown"
            )
    
    def run(self):
        """Start the bot."""
        logger.info("Starting Signal Bot...")
        
        # Create application
        self.app = Application.builder().token(self.telegram_token).build()
        
        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("balance", self.balance_command))
        
        # Handle signal commands
        self.app.add_handler(CommandHandler("signal", self.handle_message))
        self.app.add_handler(CommandHandler("update", self.handle_message))
        self.app.add_handler(CommandHandler("close", self.handle_message))
        self.app.add_handler(CommandHandler("partial", self.handle_message))
        
        # Also handle messages (for channel posts)
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.handle_message
        ))
        
        logger.info("Bot is running. Press Ctrl+C to stop.")
        
        # Run the bot
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)
