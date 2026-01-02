"""
Config - Load and validate configuration.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    """Bot configuration."""
    api_key: str
    api_secret: str
    telegram_bot_token: str
    signal_channel_id: int
    trade_amount_usdt: float = 50.0
    max_leverage: int = 20
    testnet: bool = False
    data_file: str = "signals.json"


class ConfigError(Exception):
    """Configuration error."""
    pass


def load_config(config_path: Optional[str] = None) -> Config:
    """
    Load configuration from file or environment variables.
    
    Priority:
    1. Environment variables (MUDREX_API_KEY, MUDREX_API_SECRET, etc.)
    2. Config file (config.json)
    
    Args:
        config_path: Path to config file. Defaults to config.json in current dir.
        
    Returns:
        Config object
        
    Raises:
        ConfigError: If required config is missing
    """
    config_data = {}
    
    # Try to load from file first
    if config_path is None:
        config_path = "config.json"
    
    config_file = Path(config_path)
    if config_file.exists():
        try:
            with open(config_file, 'r') as f:
                config_data = json.load(f)
        except Exception as e:
            raise ConfigError(f"Failed to load config file: {e}")
    
    # Override with environment variables
    env_mapping = {
        'api_key': 'MUDREX_API_KEY',
        'api_secret': 'MUDREX_API_SECRET',
        'telegram_bot_token': 'TELEGRAM_BOT_TOKEN',
        'signal_channel_id': 'SIGNAL_CHANNEL_ID',
        'trade_amount_usdt': 'TRADE_AMOUNT_USDT',
        'max_leverage': 'MAX_LEVERAGE',
        'testnet': 'TESTNET',
        'data_file': 'DATA_FILE',
    }
    
    for config_key, env_key in env_mapping.items():
        env_value = os.environ.get(env_key)
        if env_value:
            # Type conversion
            if config_key == 'signal_channel_id':
                config_data[config_key] = int(env_value)
            elif config_key == 'trade_amount_usdt':
                config_data[config_key] = float(env_value)
            elif config_key == 'max_leverage':
                config_data[config_key] = int(env_value)
            elif config_key == 'testnet':
                config_data[config_key] = env_value.lower() in ('true', '1', 'yes')
            else:
                config_data[config_key] = env_value
    
    # Validate required fields
    required = ['api_key', 'api_secret', 'telegram_bot_token', 'signal_channel_id']
    missing = [f for f in required if f not in config_data or not config_data[f]]
    
    if missing:
        raise ConfigError(
            f"Missing required configuration: {', '.join(missing)}\n"
            f"Set via config.json or environment variables:\n"
            f"  MUDREX_API_KEY, MUDREX_API_SECRET, TELEGRAM_BOT_TOKEN, SIGNAL_CHANNEL_ID"
        )
    
    # Check for placeholder values
    if config_data.get('api_key', '').startswith('YOUR_'):
        raise ConfigError("Please replace YOUR_MUDREX_API_KEY with your actual API key")
    
    return Config(**config_data)


def create_example_config(path: str = "config.json"):
    """Create an example config file."""
    example = {
        "api_key": "YOUR_MUDREX_API_KEY",
        "api_secret": "YOUR_MUDREX_API_SECRET",
        "telegram_bot_token": "YOUR_TELEGRAM_BOT_TOKEN",
        "signal_channel_id": -1001234567890,
        "trade_amount_usdt": 50.0,
        "max_leverage": 20,
        "testnet": False,
    }
    
    with open(path, 'w') as f:
        json.dump(example, f, indent=4)
    
    print(f"Created example config at {path}")
    print("Please edit the file with your actual credentials.")
