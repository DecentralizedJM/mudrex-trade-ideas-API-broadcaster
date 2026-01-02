"""
Run Script - Main entry point for the Signal Bot.
"""

import argparse
import logging
import sys

from .config import load_config, create_example_config, ConfigError
from .telegram_bot import SignalBot


def setup_logging(verbose: bool = False):
    """Set up logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    
    logging.basicConfig(
        level=level,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    
    # Quiet down some noisy loggers
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Mudrex Signal Bot - Auto-trade Telegram signals on Mudrex"
    )
    
    parser.add_argument(
        '-c', '--config',
        default='config.json',
        help='Path to config file (default: config.json)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    parser.add_argument(
        '--init',
        action='store_true',
        help='Create example config.json file'
    )
    
    args = parser.parse_args()
    
    # Set up logging
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    # Handle --init
    if args.init:
        create_example_config(args.config)
        return
    
    # Load config
    try:
        config = load_config(args.config)
    except ConfigError as e:
        logger.error(str(e))
        logger.info("Run with --init to create an example config file")
        sys.exit(1)
    
    # Print startup banner
    print("""
╔═══════════════════════════════════════════════════════════╗
║           🤖 MUDREX SIGNAL BOT v1.0.0                    ║
║                                                           ║
║   Auto-trade Telegram signals on Mudrex Futures          ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    logger.info(f"Trade Amount: {config.trade_amount_usdt} USDT")
    logger.info(f"Max Leverage: {config.max_leverage}x")
    logger.info(f"Signal Channel: {config.signal_channel_id}")
    
    # Create and run the bot
    bot = SignalBot(
        telegram_token=config.telegram_bot_token,
        signal_channel_id=config.signal_channel_id,
        api_key=config.api_key,
        api_secret=config.api_secret,
        trade_amount_usdt=config.trade_amount_usdt,
        max_leverage=config.max_leverage,
        data_file=config.data_file,
    )
    
    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.exception(f"Bot crashed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
