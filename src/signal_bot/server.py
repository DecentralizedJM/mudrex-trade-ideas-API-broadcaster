"""
Webhook Server - FastAPI server for Telegram webhook.

Runs on Railway and receives Telegram updates via webhook.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from telegram import Update

from .settings import get_settings
from .database import Database
from .crypto import init_crypto
from .telegram_bot import SignalBot

logger = logging.getLogger(__name__)

# Global instances
settings = None
database = None
signal_bot = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    global settings, database, signal_bot
    
    # Startup
    logger.info("Starting Mudrex TradeIdeas Bot...")
    
    try:
        # Load settings
        settings = get_settings()
        logger.info(f"Settings loaded - Admin: {settings.admin_telegram_id}")
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        logger.error("Make sure all required environment variables are set:")
        logger.error("  TELEGRAM_BOT_TOKEN, ENCRYPTION_SECRET, ADMIN_TELEGRAM_ID, SIGNAL_CHANNEL_ID")
        raise
    
    # Initialize crypto
    init_crypto(settings.encryption_secret)
    logger.info("Encryption initialized")
    
    # Connect to database
    database = Database(settings.database_path)
    await database.connect()
    
    # Initialize bot
    signal_bot = SignalBot(settings, database)
    signal_bot.build_application()
    
    # Initialize the bot application
    await signal_bot.app.initialize()
    await signal_bot.app.start()
    
    # Set up webhook
    await signal_bot.setup_webhook()
    
    subscriber_count = await database.get_subscriber_count()
    logger.info(f"Bot ready! {subscriber_count} active subscribers")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await signal_bot.app.stop()
    await signal_bot.app.shutdown()
    await database.close()


app = FastAPI(
    title="Mudrex TradeIdeas Bot",
    description="Telegram Signal Bot for Mudrex Futures Trading",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    """Health check endpoint."""
    stats = await database.get_stats() if database else {}
    return {
        "status": "running",
        "bot": "Mudrex TradeIdeas Bot",
        "version": "2.0.0",
        "subscribers": stats.get("active_subscribers", 0),
    }


@app.get("/health")
async def health():
    """Health check for Railway."""
    return {"status": "healthy"}


@app.post("/webhook")
async def webhook(request: Request):
    """
    Telegram webhook endpoint.
    
    Receives updates from Telegram and processes them.
    """
    if not signal_bot:
        return Response(status_code=503)
    
    try:
        data = await request.json()
        update = Update.de_json(data, signal_bot.bot)
        
        # Process update asynchronously
        await signal_bot.app.process_update(update)
        
        return Response(status_code=200)
    except Exception as e:
        logger.exception(f"Webhook error: {e}")
        return Response(status_code=500)


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    return app
