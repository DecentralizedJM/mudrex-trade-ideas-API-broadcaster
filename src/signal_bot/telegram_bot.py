"""
Telegram Bot - Centralized signal bot with webhook support.

This bot:
1. Receives signals from admin in the signal channel
2. Handles user registration via DM
3. Broadcasts trades to all subscribers
4. Notifies users of execution results
"""

import asyncio
import json
import logging
from typing import Optional

from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
)

from .signal_parser import (
    SignalParser,
    Signal,
    SignalUpdate,
    SignalClose,
    SignalLeverage,
    SignalParseError,
    format_signal_summary,
)
from .broadcaster import (
    SignalBroadcaster,
    TradeStatus,
    format_broadcast_summary,
    format_user_trade_notification,
)
from .database import Database
from .settings import Settings

logger = logging.getLogger(__name__)

# Conversation states for registration
AWAITING_API_KEY, AWAITING_API_SECRET, AWAITING_AMOUNT = range(3)


class SignalBot:
    """
    Centralized Telegram Signal Bot.
    
    - Admin posts signals in channel → executes for all subscribers
    - Users DM to register with their Mudrex API keys
    - All API keys encrypted at rest
    """
    
    def __init__(self, settings: Settings, database: Database):
        """
        Initialize the signal bot.
        
        Args:
            settings: Application settings
            database: Database instance
        """
        self.settings = settings
        self.db = database
        self.broadcaster = SignalBroadcaster(database)
        self.app: Optional[Application] = None
        self.bot: Optional[Bot] = None
        
        logger.info(f"SignalBot initialized - Admin: {settings.admin_telegram_id}")
    
    def _is_admin(self, user_id: int) -> bool:
        """Check if user is the admin."""
        return user_id == self.settings.admin_telegram_id
    
    def _is_signal_channel(self, chat_id: int) -> bool:
        """Check if message is from the signal channel."""
        return chat_id == self.settings.signal_channel_id
    
    # ==================== User Commands ====================
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        user = update.effective_user
        
        # Check if already registered
        subscriber = await self.db.get_subscriber(user.id)
        
        if subscriber and subscriber.is_active:
            await update.message.reply_text(
                f"👋 Welcome back, {user.first_name}!\n\n"
                f"You're already registered.\n\n"
                f"**Your Settings:**\n"
                f"💰 Trade Amount: {subscriber.trade_amount_usdt} USDT\n"
                f"⚡ Max Leverage: {subscriber.max_leverage}x\n"
                f"📊 Total Trades: {subscriber.total_trades}\n\n"
                f"**Commands:**\n"
                f"/status - View your settings\n"
                f"/setamount - Change trade amount\n"
                f"/setleverage - Change max leverage\n"
                f"/unregister - Stop receiving signals",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                f"🤖 **Mudrex TradeIdeas Bot**\n\n"
                f"Welcome, {user.first_name}!\n\n"
                f"I auto-execute trading signals on your Mudrex account.\n\n"
                f"**To get started:**\n"
                f"/register - Connect your Mudrex account\n\n"
                f"**You'll need:**\n"
                f"• Mudrex API Key\n"
                f"• Mudrex API Secret\n\n"
                f"🔒 Your API keys are encrypted and stored securely.",
                parse_mode="Markdown"
            )
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        user = update.effective_user
        subscriber = await self.db.get_subscriber(user.id)
        
        if not subscriber or not subscriber.is_active:
            await update.message.reply_text(
                "❌ You're not registered.\n\nUse /register to get started."
            )
            return
        
        await update.message.reply_text(
            f"📊 **Your Status**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Trade Amount: **{subscriber.trade_amount_usdt} USDT**\n"
            f"⚡ Max Leverage: **{subscriber.max_leverage}x**\n"
            f"📈 Total Trades: **{subscriber.total_trades}**\n"
            f"💵 Total PnL: **${subscriber.total_pnl:.2f}**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Status: Active",
            parse_mode="Markdown"
        )
    async def chatid_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get the current chat ID (helper for setup)."""
        chat_id = update.effective_chat.id
        await update.message.reply_text(f"🆔 Chat ID: `{chat_id}`", parse_mode="Markdown")


    async def welcome_new_chat_members(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Welcome new members and share Chat ID if bot is added."""
        if not update.message.new_chat_members:
            return

        for user in update.message.new_chat_members:
            if user.id == context.bot.id:
                chat_id = update.effective_chat.id
                await update.message.reply_text(
                    f"👋 **Mudrex Bot Added!**\n\n"
                    f"🆔 Chat ID: `{chat_id}`\n\n"
                    f"Please configure this ID in your Railway settings (`SIGNAL_CHANNEL_ID`) to use this group for signals.",
                    parse_mode="Markdown"
                )

    # ==================== Registration Flow ====================
    
    async def register_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start registration - ask for API key."""
        if not self.settings.allow_registration:
            await update.message.reply_text(
                "❌ Registration is currently closed."
            )
            return ConversationHandler.END
        
        # Check if already registered
        subscriber = await self.db.get_subscriber(update.effective_user.id)
        if subscriber and subscriber.is_active:
            await update.message.reply_text(
                "⚠️ You're already registered!\n\n"
                "Use /unregister first if you want to re-register."
            )
            return ConversationHandler.END
        
        await update.message.reply_text(
            "🔑 **Registration Step 1/3**\n\n"
            "Please send your **Mudrex API Key**.\n\n"
            "You can get your Mudrex API key from the Mudrex Website.\n"
            "**Note:** API keys can only be created via desktop.\n"
            "Login to https://mudrex.com/pro-trading via desktop and generate your key.\n\n"
            "🔒 Your API key is secured with bank-level encryption.\n\n"
            "/cancel to abort",
            parse_mode="Markdown"
        )
        return AWAITING_API_KEY
    
    async def register_api_key(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive API key, ask for secret."""
        api_key = update.message.text.strip()
        
        # Basic validation
        if len(api_key) < 10:
            await update.message.reply_text(
                "❌ That doesn't look like a valid API key.\n"
                "Please try again or /cancel"
            )
            return AWAITING_API_KEY
        
        # Store temporarily
        context.user_data['api_key'] = api_key
        
        # Delete the message with the API key for security
        try:
            await update.message.delete()
        except:
            pass
        
        await update.message.reply_text(
            "✅ API Key received!\n\n"
            "🔐 **Registration Step 2/3**\n\n"
            "Now send your **Mudrex API Secret**.\n\n"
            "🔒 Your secret is secured with bank-level encryption.\n\n"
            "/cancel to abort",
            parse_mode="Markdown"
        )
        return AWAITING_API_SECRET
    
    async def register_api_secret(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive API secret, ask for trade amount."""
        api_secret = update.message.text.strip()
        
        # Basic validation
        if len(api_secret) < 10:
            await update.message.reply_text(
                "❌ That doesn't look like a valid API secret.\n"
                "Please try again or /cancel"
            )
            return AWAITING_API_SECRET
        
        # Store temporarily
        context.user_data['api_secret'] = api_secret
        
        # Delete the message with the secret for security
        try:
            await update.message.delete()
        except:
            pass
        
        await update.message.reply_text(
            "✅ API Secret received!\n\n"
            "💰 **Registration Step 3/3**\n\n"
            "How much **USDT** do you want to trade per signal?\n\n"
            f"Default: {self.settings.default_trade_amount} USDT\n\n"
            "Send a number (e.g., `50` or `100`) or /skip for default\n\n"
            "/cancel to abort",
            parse_mode="Markdown"
        )
        return AWAITING_AMOUNT
    
    async def register_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Receive trade amount, complete registration."""
        text = update.message.text.strip()
        
        # Parse amount
        try:
            amount = float(text)
            if amount < 1:
                raise ValueError("Too small")
            if amount > 10000:
                raise ValueError("Too large")
        except ValueError:
            await update.message.reply_text(
                "❌ Please enter a valid amount between 1 and 10000.\n"
                "Or use /skip for default."
            )
            return AWAITING_AMOUNT
        
        # Complete registration
        return await self._complete_registration(update, context, amount)
    
    async def register_skip_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Skip amount, use default."""
        return await self._complete_registration(
            update, context, self.settings.default_trade_amount
        )
    
    async def _complete_registration(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        amount: float
    ):
        """Complete the registration process."""
        user = update.effective_user
        api_key = context.user_data.get('api_key')
        api_secret = context.user_data.get('api_secret')
        
        if not api_key or not api_secret:
            await update.message.reply_text(
                "❌ Registration failed. Please try again with /register"
            )
            return ConversationHandler.END
        
        # Validate API credentials by making a test call
        await update.message.reply_text("🔄 Validating your API credentials...")
        
        try:
            import asyncio
            from mudrex import MudrexClient
            
            def validate_api(secret: str):
                """Sync validation - runs in thread."""
                client = MudrexClient(api_secret=secret)
                return client.wallet.get_futures_balance()
            
            # Run in thread with 15 second timeout
            try:
                balance = await asyncio.wait_for(
                    asyncio.to_thread(validate_api, api_secret),
                    timeout=15.0
                )
            except asyncio.TimeoutError:
                await update.message.reply_text(
                    "❌ **Validation timed out!**\n\n"
                    "The API request took too long. Please check:\n"
                    "1. Your API secret is correct\n"
                    "2. Mudrex API is accessible\n\n"
                    "Try again with /register",
                    parse_mode="Markdown"
                )
                return ConversationHandler.END
            
            if balance is None:
                await update.message.reply_text(
                    "❌ **Invalid API credentials!**\n\n"
                    "Could not connect to Mudrex. Please check:\n"
                    "1. Your API secret is correct\n"
                    "2. API has Futures trading permission\n\n"
                    "Try again with /register",
                    parse_mode="Markdown"
                )
                return ConversationHandler.END
                
            logger.info(f"API validated for {user.id}: Balance = {balance.balance} USDT")
            
        except Exception as e:
            logger.error(f"API validation failed for {user.id}: {e}")
            # Don't use Markdown - error messages may contain special chars
            await update.message.reply_text(
                f"❌ API validation failed!\n\n"
                f"Error: {str(e)[:100]}\n\n"
                f"Please check your credentials and try /register again."
            )
            return ConversationHandler.END
        
        # Save to database (encrypted)
        try:
            subscriber = await self.db.add_subscriber(
                telegram_id=user.id,
                username=user.username,
                api_key=api_key,
                api_secret=api_secret,
                trade_amount_usdt=amount,
                max_leverage=self.settings.default_max_leverage,
            )
            
            # Clear temporary data
            context.user_data.clear()
            
            await update.message.reply_text(
                f"🎉 Registration Complete!\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 Trade Amount: {amount} USDT\n"
                f"⚡ Max Leverage: {self.settings.default_max_leverage}x\n"
                f"🤖 Mode: AUTO (trades execute automatically)\n"
                f"━━━━━━━━━━━━━━━━━━━━\n\n"
                f"⚠️ IMPORTANT WARNING ⚠️\n"
                f"When Mudrex Trading Team publishes a trade idea, "
                f"it will be AUTO-EXECUTED in your Mudrex Futures account!\n\n"
                f"💰 Minimum Value Requirement:\n"
                f"Mudrex requires a minimum order value of ~$7-8 per trade.\n"
                f"Assets like BTC/ETH may require higher margins at lower leverage.\n"
                f"👉 Recommendation: set at least 20-25 USDT per trade to ensure successful execution.\n\n"
                f"Trades are professionally managed by the Mudrex Research Desk and executed with your live funds. "
                f"While we aim for consistent profitability, trading carries inherent risk. Please trade responsibly and only with capital you can afford to lose.\n\n"
                f"Commands:\n"
                f"/status - View your settings\n"
                f"/setamount - Change trade amount\n"
                f"/setleverage - Change max leverage\n"
                f"/setmode - Switch between auto/manual mode\n"
                f"/unregister - Stop receiving signals"
            )
            
            logger.info(f"New subscriber registered: {user.id} (@{user.username})")
            
        except Exception as e:
            logger.error(f"Registration failed: {e}")
            await update.message.reply_text(
                f"❌ Registration failed: {e}\n\nPlease try again with /register"
            )
        
        return ConversationHandler.END
    
    async def register_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancel registration."""
        context.user_data.clear()
        await update.message.reply_text("❌ Registration cancelled.")
        return ConversationHandler.END
    
    # ==================== Settings Commands ====================
    
    async def setamount_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /setamount command."""
        user = update.effective_user
        subscriber = await self.db.get_subscriber(user.id)
        
        if not subscriber or not subscriber.is_active:
            await update.message.reply_text("❌ You're not registered. Use /register first.")
            return
        
        args = context.args
        if not args:
            await update.message.reply_text(
                f"💰 Current trade amount: **{subscriber.trade_amount_usdt} USDT**\n\n"
                f"Usage: `/setamount <amount>`\n"
                f"Example: `/setamount 100`",
                parse_mode="Markdown"
            )
            return
        
        try:
            amount = float(args[0])
            if amount < 1 or amount > 10000:
                raise ValueError("Out of range")
            
            await self.db.update_trade_amount(user.id, amount)
            await update.message.reply_text(
                f"✅ Trade amount updated to **{amount} USDT**",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid amount between 1 and 10000")
    
    async def setleverage_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /setleverage command."""
        user = update.effective_user
        subscriber = await self.db.get_subscriber(user.id)
        
        if not subscriber or not subscriber.is_active:
            await update.message.reply_text("❌ You're not registered. Use /register first.")
            return
        
        args = context.args
        if not args:
            await update.message.reply_text(
                f"⚡ Current max leverage: **{subscriber.max_leverage}x**\n\n"
                f"Usage: `/setleverage <amount>`\n"
                f"Example: `/setleverage 10`",
                parse_mode="Markdown"
            )
            return
        
        try:
            leverage = int(args[0])
            if leverage < 1 or leverage > 125:
                raise ValueError("Out of range")
            
            await self.db.update_max_leverage(user.id, leverage)
            await update.message.reply_text(
                f"✅ Max leverage updated to **{leverage}x**",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Please enter a valid leverage between 1 and 125")
    
    async def unregister_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /unregister command."""
        user = update.effective_user
        
        success = await self.db.deactivate_subscriber(user.id)
        
        if success:
            await update.message.reply_text(
                "✅ You've been unregistered.\n\n"
                "You will no longer receive trading signals.\n"
                "Use /register to sign up again."
            )
        else:
            await update.message.reply_text("❌ You're not registered.")
    
    async def setmode_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /setmode command to switch between AUTO and MANUAL trade modes."""
        user = update.effective_user
        subscriber = await self.db.get_subscriber(user.id)
        
        if not subscriber or not subscriber.is_active:
            await update.message.reply_text("❌ You're not registered. Use /register first.")
            return
        
        args = context.args
        if not args:
            mode_emoji = "🤖" if subscriber.trade_mode == "AUTO" else "👆"
            await update.message.reply_text(
                f"{mode_emoji} Current trade mode: **{subscriber.trade_mode}**\n\n"
                f"**Available modes:**\n"
                f"🤖 `AUTO` - Trades execute automatically\n"
                f"👆 `MANUAL` - You'll be asked to confirm each trade\n\n"
                f"Usage: `/setmode auto` or `/setmode manual`",
                parse_mode="Markdown"
            )
            return
        
        mode = args[0].upper()
        if mode not in ["AUTO", "MANUAL"]:
            await update.message.reply_text(
                "❌ Invalid mode. Use `/setmode auto` or `/setmode manual`",
                parse_mode="Markdown"
            )
            return
        
        await self.db.update_trade_mode(user.id, mode)
        
        if mode == "AUTO":
            await update.message.reply_text(
                "🤖 **Trade mode set to AUTO**\n\n"
                "Trades will be executed automatically when signals are published.\n\n"
                "Trades are professionally managed by the Mudrex Research Desk using your live funds. "
                "Trading carries inherent risk; please trade responsibly.",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                "👆 **Trade mode set to MANUAL**\n\n"
                "You will receive a confirmation message for each trade signal.\n"
                "The trade will only execute after you approve it.\n\n"
                "💡 You have 5 minutes to confirm each trade.",
                parse_mode="Markdown"
            )
    
    # ==================== Admin Commands ====================
    
    async def admin_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /adminstats command (admin only)."""
        if not self._is_admin(update.effective_user.id):
            return
        
        stats = await self.db.get_stats()
        
        await update.message.reply_text(
            f"📊 **Admin Stats**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Total Subscribers: {stats['total_subscribers']}\n"
            f"✅ Active: {stats['active_subscribers']}\n"
            f"📈 Total Trades: {stats['total_trades']}\n"
            f"📡 Active Signals: {stats['active_signals']}\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            parse_mode="Markdown"
        )
    
    # ==================== Signal Handling ====================
    
    async def handle_signal_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle messages that might be signals (non-command signals posted directly)."""
        message = update.message or update.channel_post
        
        if not message or not message.text:
            return
        
        text = message.text.strip()
        chat_id = message.chat_id
        
        # Skip /signal command - it's handled by signal_command handler
        if text.lower().startswith('/signal'):
            return
        
        # Debug logging
        logger.debug(f"Received message from chat {chat_id}: {text[:50]}...")
        
        # Check source
        user_id = message.from_user.id if message.from_user else None
        is_signal_channel = self._is_signal_channel(chat_id)
        is_admin_dm = user_id and self._is_admin(user_id) and message.chat.type == "private"
        
        logger.info(f"Signal check - chat_id: {chat_id}, user_id: {user_id}, is_channel: {is_signal_channel}, is_admin_dm: {is_admin_dm}")
        
        # Accept signals from:
        # 1. Admin's DM
        # 2. The designated signal channel (regardless of from_user - channel posts may not have it)
        if is_admin_dm:
            # Always allow admin DM
            pass
        elif is_signal_channel:
             # If it's a group, verify the user is an admin
             if message.chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
                 try:
                     member = await message.chat.get_member(user_id)
                     if member.status not in ['creator', 'administrator']:
                         logger.warning(f"Ignored command from non-admin {user_id} in group")
                         return
                 except Exception as e:
                     logger.error(f"Failed to check admin status: {e}")
                     return
        else:
            # Not admin DM and not signal channel
            logger.debug(f"Ignoring message - not from admin DM or signal channel")
            return
        
        try:
            parsed = SignalParser.parse(text)
            
            if parsed is None:
                return
            
            logger.info(f"Parsed signal: {type(parsed).__name__}")
            
            if isinstance(parsed, Signal):
                await self._handle_new_signal(message, parsed)
            elif isinstance(parsed, SignalClose):
                await self._handle_close_signal(message, parsed)
            elif isinstance(parsed, SignalLeverage):
                await self._handle_leverage_signal(message, parsed)
                
        except SignalParseError as e:
            await message.reply_text(f"⚠️ Signal parse error: {e}")
        except Exception as e:
            logger.exception(f"Error handling signal: {e}")
    
    async def _handle_new_signal(self, message, signal: Signal):
        """Handle a new trading signal from admin."""
        # Show signal received
        summary = format_signal_summary(signal)
        await message.reply_text(summary, parse_mode="Markdown")
        
        # Broadcast to all subscribers (returns AUTO results + MANUAL subscribers list)
        results, manual_subscribers = await self.broadcaster.broadcast_signal(signal)
        
        # Send summary to admin (including manual count)
        broadcast_summary = format_broadcast_summary(signal, results, len(manual_subscribers))
        await message.reply_text(broadcast_summary)
        
        # Notify each AUTO subscriber via DM with trade result
        for result in results:
            try:
                # Check if insufficient balance but has some available
                if (result.status == TradeStatus.INSUFFICIENT_BALANCE 
                    and result.available_balance 
                    and result.available_balance >= 1.0):
                    # Offer to trade with available balance
                    await self._send_reduced_balance_offer(signal, result)
                elif result.status != TradeStatus.SKIPPED:
                    # Notify for all non-skipped results (SUCCESS, FAILURE, ERROR)
                    # Broadcaster ensures messages are sanitized and human-readable
                    notification = format_user_trade_notification(signal, result)
                    await self.bot.send_message(
                        chat_id=result.subscriber_id,
                        text=notification,
                    )
            except Exception as e:
                logger.error(f"Failed to notify {result.subscriber_id}: {e}")
        
        # Send confirmation request to MANUAL subscribers
        for subscriber in manual_subscribers:
            try:
                await self._send_manual_confirmation(signal, subscriber)
            except Exception as e:
                logger.error(f"Failed to send confirmation to {subscriber.telegram_id}: {e}")
    
    async def _send_manual_confirmation(self, signal: Signal, subscriber):
        """Send trade confirmation request to a MANUAL mode subscriber."""
        # Use short callback data format: "c:{signal_id}" or "r:{signal_id}"
        # Telegram limit is 64 bytes
        confirm_data = f"c:{signal.signal_id}"
        reject_data = f"r:{signal.signal_id}"
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Execute Trade", callback_data=confirm_data),
                InlineKeyboardButton("❌ Skip", callback_data=reject_data),
            ]
        ])
        
        text = f"""
👆 **Trade Confirmation Required**
━━━━━━━━━━━━━━━━━━━━
🆔 Signal: `{signal.signal_id}`
📊 {signal.signal_type.value} **{signal.symbol}**
📋 Type: {signal.order_type.value}
💵 Entry: {signal.entry_price or "Market"}
🛑 SL: {signal.stop_loss or "Not set"}
🎯 TP: {signal.take_profit or "Not set"}
⚡ Leverage: {signal.leverage}x
💰 Your amount: {subscriber.trade_amount_usdt} USDT
━━━━━━━━━━━━━━━━━━━━

⏰ **You have 5 minutes to confirm.**
Click "Execute Trade" to proceed or "Skip" to ignore.
""".strip()
        
        await self.bot.send_message(
            chat_id=subscriber.telegram_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        
        logger.info(f"Sent confirmation request to {subscriber.telegram_id} for signal {signal.signal_id}")
    
    async def _send_reduced_balance_offer(self, signal: Signal, result):
        """Send an offer to trade with available balance when configured amount is insufficient."""
        available = result.available_balance
        
        # Callback data: "b:{signal_id}:{amount}" (b = balance trade)
        accept_data = f"b:{signal.signal_id}:{available:.2f}"
        reject_data = f"r:{signal.signal_id}"
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"✅ Trade with ${available:.2f}", callback_data=accept_data),
                InlineKeyboardButton("❌ Skip", callback_data=reject_data),
            ]
        ])
        
        text = f"""
💰 **Insufficient Balance**
━━━━━━━━━━━━━━━━━━━━
🆔 Signal: `{signal.signal_id}`
📊 {signal.signal_type.value} **{signal.symbol}**

Your configured amount: **${result.message.split('Requested: ')[1].split(' USDT')[0]} USDT**
Available balance: **${available:.2f} USDT**

Would you like to execute this trade with your available balance instead?
━━━━━━━━━━━━━━━━━━━━
""".strip()
        
        await self.bot.send_message(
            chat_id=result.subscriber_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        
        logger.info(f"Sent reduced balance offer to {result.subscriber_id} for signal {signal.signal_id}")
    
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback button presses (for manual trade confirmations)."""
        query = update.callback_query
        await query.answer()  # Acknowledge the button press
        
        data = query.data
        user_id = query.from_user.id
        
        # Parse callback data formats:
        # "c:{signal_id}" - confirm trade (manual mode)
        # "r:{signal_id}" - reject/skip trade
        # "b:{signal_id}:{amount}" - trade with reduced balance
        if data.startswith("c:"):
            signal_id = data[2:]
            await self._execute_confirmed_trade(query, signal_id, user_id)
        elif data.startswith("r:"):
            signal_id = data[2:]
            await query.edit_message_text(
                f"⏭️ **Trade Skipped**\n\n"
                f"Signal `{signal_id}` was not executed.\n"
                f"You can always switch to AUTO mode with /setmode auto",
                parse_mode="Markdown"
            )
        elif data.startswith("b:"):
            # Balance trade: b:{signal_id}:{amount}
            parts = data[2:].split(":")
            if len(parts) == 2:
                signal_id, amount_str = parts
                try:
                    amount = float(amount_str)
                    await self._execute_with_balance(query, signal_id, user_id, amount)
                except ValueError:
                    await query.edit_message_text("❌ Invalid amount.")
            else:
                await query.edit_message_text("❌ Invalid request.")
        else:
            await query.edit_message_text("❌ Invalid request.")
    
    async def _execute_confirmed_trade(self, query, signal_id: str, user_id: int):
        """Execute a trade after user confirms in MANUAL mode."""
        # Get subscriber
        subscriber = await self.db.get_subscriber(user_id)
        if not subscriber or not subscriber.is_active:
            await query.edit_message_text("❌ You're not registered anymore.")
            return
        
        # Get the signal from database
        signal_data = await self.db.get_signal(signal_id)
        if not signal_data:
            await query.edit_message_text(
                f"❌ Signal `{signal_id}` not found or expired.",
                parse_mode="Markdown"
            )
            return
        
        # Reconstruct Signal object
        from .signal_parser import Signal, SignalType, OrderType
        from datetime import datetime
        signal = Signal(
            signal_id=signal_data["signal_id"],
            symbol=signal_data["symbol"],
            signal_type=SignalType(signal_data["signal_type"]),
            order_type=OrderType(signal_data["order_type"]),
            entry_price=signal_data.get("entry_price"),
            stop_loss=signal_data.get("stop_loss"),
            take_profit=signal_data.get("take_profit"),
            leverage=signal_data.get("leverage", 1),
            raw_message="",  # Not stored in DB, not needed for execution
            timestamp=datetime.fromisoformat(signal_data["created_at"]) if signal_data.get("created_at") else datetime.now(),
        )
        
        # Update message to show processing
        await query.edit_message_text(
            f"⏳ **Executing trade...**\n\n"
            f"Signal: `{signal_id}`",
            parse_mode="Markdown"
        )
        
        # Execute the trade
        result = await self.broadcaster.execute_single_trade(signal, subscriber)
        
        # Notify user of result
        notification = format_user_trade_notification(signal, result)
        await query.edit_message_text(notification)
    
    async def _execute_with_balance(self, query, signal_id: str, user_id: int, amount: float):
        """Execute a trade with a specific amount (for reduced balance flow)."""
        # Get subscriber
        subscriber = await self.db.get_subscriber(user_id)
        if not subscriber or not subscriber.is_active:
            await query.edit_message_text("❌ You're not registered anymore.")
            return
        
        # Get the signal from database
        signal_data = await self.db.get_signal(signal_id)
        if not signal_data:
            await query.edit_message_text(
                f"❌ Signal `{signal_id}` not found or expired.",
                parse_mode="Markdown"
            )
            return
        
        # Reconstruct Signal object
        from .signal_parser import Signal, SignalType, OrderType
        from datetime import datetime
        signal = Signal(
            signal_id=signal_data["signal_id"],
            symbol=signal_data["symbol"],
            signal_type=SignalType(signal_data["signal_type"]),
            order_type=OrderType(signal_data["order_type"]),
            entry_price=signal_data.get("entry_price"),
            stop_loss=signal_data.get("stop_loss"),
            take_profit=signal_data.get("take_profit"),
            leverage=signal_data.get("leverage", 1),
            raw_message="",
            timestamp=datetime.fromisoformat(signal_data["created_at"]) if signal_data.get("created_at") else datetime.now(),
        )
        
        # Update message to show processing
        await query.edit_message_text(
            f"⏳ **Executing trade with ${amount:.2f}...**\n\n"
            f"Signal: `{signal_id}`",
            parse_mode="Markdown"
        )
        
        # Execute the trade with override amount
        result = await self.broadcaster.execute_with_amount(signal, subscriber, amount)
        
        # Notify user of result
        notification = format_user_trade_notification(signal, result)
        await query.edit_message_text(notification)
    
    async def _handle_close_signal(self, message, close: SignalClose):
        """Handle a close signal from admin."""
        # Broadcast close and get results
        results = await self.broadcaster.broadcast_close(close)
        
        # Notify Admin
        success_count = sum(1 for r in results if r.status == TradeStatus.SUCCESS)
        skipped_count = sum(1 for r in results if r.status == TradeStatus.SKIPPED)
        failed_count = sum(1 for r in results if r.status == TradeStatus.API_ERROR)
        
        await message.reply_text(
             f"✅ Signal `{close.signal_id}` Closed\n"
             f"━━━━━━━━━━━━━━━━━━━━\n"
             f"✅ Success: {success_count}\n"
             f"⏭️ Skipped: {skipped_count}\n"
             f"❌ Failed: {failed_count}",
             parse_mode="Markdown"
        )
        
        # Notify Users
        for result in results:
             if result.status == TradeStatus.SKIPPED:
                 continue
             
             # Notify Success or Failure
             notification = f"🔔 **Position Closed**\n" \
                            f"━━━━━━━━━━━━━━━━━━━━\n" \
                            f"🆔 Signal: `{close.signal_id}`\n" \
                            f"📊 {close.symbol}\n\n"
                            
             if result.status == TradeStatus.SUCCESS:
                 notification += f"✅ {result.message}\n"
             else:
                 notification += f"❌ Failed to close: {result.message}\n" \
                                 f"⚠️ Please check Mudrex manually."
             
             notification += "━━━━━━━━━━━━━━━━━━━━"
             
             try:
                 await self.bot.send_message(
                     chat_id=result.subscriber_id,
                     text=notification,
                     parse_mode="Markdown"
                 )
             except Exception as e:
                 logger.error(f"Failed to notify close to {result.subscriber_id}: {e}")
    
    async def _handle_leverage_signal(self, message, lev: SignalLeverage):
        """Handle a leverage update signal."""
        results = await self.broadcaster.broadcast_leverage(lev)
        
        # Notify Admin
        success_count = sum(1 for r in results if r.status == TradeStatus.SUCCESS)
        skipped_count = sum(1 for r in results if r.status == TradeStatus.SKIPPED)
        failed_count = sum(1 for r in results if r.status == TradeStatus.API_ERROR)
        
        await message.reply_text(
             f"⚡ Signal `{lev.signal_id}` Leverage Update\n"
             f"━━━━━━━━━━━━━━━━━━━━\n"
             f"✅ Success: {success_count}\n"
             f"⏭️ Skipped: {skipped_count}\n"
             f"❌ Failed: {failed_count}",
             parse_mode="Markdown"
        )
        
        # Notify Users
        for result in results:
             if result.status == TradeStatus.SKIPPED:
                 continue
             
             notification = f"⚡ **Leverage Updated**\n" \
                            f"━━━━━━━━━━━━━━━━━━━━\n" \
                            f"🆔 Signal: `{lev.signal_id}`\n" \
                            f"📊 {lev.symbol} → {lev.leverage}x\n\n"
                            
             if result.status == TradeStatus.SUCCESS:
                 notification += f"✅ Leverage set to {lev.leverage}x\n"
             else:
                 notification += f"❌ Update Failed: {result.message}\n"
             
             notification += "━━━━━━━━━━━━━━━━━━━━"
             
             try:
                 await self.bot.send_message(
                     chat_id=result.subscriber_id,
                     text=notification,
                     parse_mode="Markdown"
                 )
             except Exception as e:
                 logger.error(f"Failed to notify leverage update to {result.subscriber_id}: {e}")
    
    # ==================== Channel Signal Command ====================
    
    async def signal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handle /signal command from channel admins.
        
        Only works in the designated signal channel.
        Any admin of that channel can post signals.
        
        Format:
        /signal 
        XRPUSDT
        LONG
        Entry: 2.01
        TP: 2.10
        SL: 1.95
        Lev: 10x
        """
        message = update.message or update.channel_post
        if not message:
            return
        
        chat_id = message.chat.id
        
        # Only allow in the signal channel
        if not self._is_signal_channel(chat_id):
            # Silently ignore if not in signal channel
            return
        
        # Get the text after /signal
        if not message.text:
            await message.reply_text(
                "📡 **Signal Command**\n\n"
                "Format:\n"
                "```\n"
                "/signal \n"
                "XRPUSDT\n"
                "LONG\n"
                "Entry: 2.01\n"
                "TP: 2.10\n"
                "SL: 1.95\n"
                "Lev: 10x\n"
                "```",
                parse_mode="Markdown"
            )
            return
        
        # Extract signal text (everything after /signal on new lines)
        signal_text = message.text
        if signal_text.lower().startswith("/signal"):
            signal_text = signal_text[7:].strip()  # Remove "/signal"
        
        if not signal_text:
            await message.reply_text(
                "📡 **Signal Command**\n\n"
                "Format:\n"
                "```\n"
                "/signal \n"
                "XRPUSDT\n"
                "LONG\n"
                "Entry: 2.01\n"
                "TP: 2.10\n"
                "SL: 1.95\n"
                "Lev: 10x\n"
                "```",
                parse_mode="Markdown"
            )
            return
        
        try:
            parsed = SignalParser.parse(signal_text)
            
            if parsed is None:
                await message.reply_text(
                    "⚠️ Could not parse signal. Check the format:\n\n"
                    "```\n"
                    "/signal \n"
                    "BTCUSDT\n"
                    "LONG\n"
                    "Entry: 95000\n"
                    "TP: 98000\n"
                    "SL: 93000\n"
                    "Lev: 20x\n"
                    "```",
                    parse_mode="Markdown"
                )
                return
            
            if isinstance(parsed, Signal):
                await self._handle_new_signal(message, parsed)
            elif isinstance(parsed, SignalClose):
                await self._handle_close_signal(message, parsed)
            else:
                await message.reply_text("⚠️ Unknown signal type parsed.")
                
        except SignalParseError as e:
            await message.reply_text(f"⚠️ Signal parse error: {e}")
        except Exception as e:
            logger.exception(f"Error processing /signal command: {e}")
            await message.reply_text(f"❌ Error processing signal: {e}")
    
    # ==================== Bot Setup ====================
    
    async def _post_init(self, application: Application):
        """Called after Application.initialize() - connect database."""
        logger.info("Initializing database connection...")
        await self.db.connect()
        logger.info("Database connected successfully")
    
    async def _post_shutdown(self, application: Application):
        """Called after Application.shutdown() - close database."""
        logger.info("Closing database connection...")
        await self.db.close()
        logger.info("Database closed")
    
    def build_application(self) -> Application:
        """Build the Telegram application."""
        self.app = (
            Application.builder()
            .token(self.settings.telegram_bot_token)
            .post_init(self._post_init)
            .post_shutdown(self._post_shutdown)
            .build()
        )
        self.bot = self.app.bot
        
        # Registration conversation handler
        registration_handler = ConversationHandler(
            entry_points=[CommandHandler("register", self.register_start)],
            states={
                AWAITING_API_KEY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.register_api_key)
                ],
                AWAITING_API_SECRET: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.register_api_secret)
                ],
                AWAITING_AMOUNT: [
                    CommandHandler("skip", self.register_skip_amount),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.register_amount),
                ],
            },
            fallbacks=[CommandHandler("cancel", self.register_cancel)],
        )
        
        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(registration_handler)
        self.app.add_handler(CommandHandler("setamount", self.setamount_command))
        self.app.add_handler(CommandHandler("setleverage", self.setleverage_command))
        self.app.add_handler(CommandHandler("setmode", self.setmode_command))
        self.app.add_handler(CommandHandler("unregister", self.unregister_command))
        self.app.add_handler(CommandHandler("adminstats", self.admin_stats_command))
        self.app.add_handler(CommandHandler("chatid", self.chatid_command))
        
        # /signal command - use MessageHandler with Regex for channel/group posts
        # CommandHandler doesn't work for channel posts, and we want unified handling
        self.app.add_handler(MessageHandler(
            filters.Regex(r'^/signal') & (filters.ChatType.CHANNEL | filters.ChatType.GROUPS),
            self.signal_command
        ))
        
        # Callback handler for inline button presses (manual trade confirmations)
        self.app.add_handler(CallbackQueryHandler(self.handle_callback_query))
        
        # Signal handlers - for both private messages, channel posts, and groups
        # Use group=1 so command handlers (group=0 by default) are processed first
        self.app.add_handler(MessageHandler(
            filters.TEXT & (filters.ChatType.PRIVATE | filters.ChatType.CHANNEL | filters.ChatType.GROUPS),
            self.handle_signal_message
        ), group=1)
        
        # Welcome handler for when bot is added to group
        self.app.add_handler(MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS,
            self.welcome_new_chat_members
        ))
        
        return self.app
    
    async def setup_webhook(self):
        """Set up webhook for Telegram."""
        webhook_url = self.settings.full_webhook_url
        
        if webhook_url:
            await self.bot.set_webhook(url=webhook_url)
            logger.info(f"Webhook set: {webhook_url}")
        else:
            logger.warning("No webhook URL configured, will use polling")
    
    def run_polling(self):
        """Run bot with polling (for local development)."""
        logger.info("Starting bot in polling mode...")
        self.build_application()
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

