# Mudrex Signal Bot 🤖

**Auto-trade Telegram signals on Mudrex Futures**

Receive trading signals in your Telegram channel and automatically execute them on Mudrex.

## Features

- ✅ **Market & Limit Orders** - Support for both order types
- ✅ **Stop Loss & Take Profit** - Automatic SL/TP placement
- ✅ **Leverage Control** - Set leverage per signal (with max limit)
- ✅ **Balance Check** - Skips trades if insufficient balance
- ✅ **Signal Tracking** - Update and close signals by ID
- ✅ **Persistence** - Signals saved to disk, survives restarts

## Quick Start

### 1. Install

```bash
# Clone the repo
git clone https://github.com/DecentralizedJM/mudrex-signal-bot.git
cd mudrex-signal-bot

# Install dependencies
pip install -e .
```

### 2. Get Your Credentials

**Mudrex API:**
1. Log into [Mudrex](https://mudrex.com)
2. Go to Settings → API Keys
3. Create a new API key with trading permissions
4. Save your API Key and Secret

**Telegram Bot:**
1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot` and follow the prompts
3. Save the bot token you receive

**Signal Channel ID:**
1. Add your bot to your signal channel/group
2. Make the bot an admin
3. Forward a message from the channel to [@userinfobot](https://t.me/userinfobot) to get the channel ID (it's a negative number like `-1001234567890`)

### 3. Configure

```bash
# Create config file
python -m signal_bot.run --init

# Edit config.json with your credentials
```

Or use environment variables:

```bash
export MUDREX_API_KEY="your_api_key"
export MUDREX_API_SECRET="your_api_secret"
export TELEGRAM_BOT_TOKEN="your_bot_token"
export SIGNAL_CHANNEL_ID="-1001234567890"
export TRADE_AMOUNT_USDT="50"
export MAX_LEVERAGE="20"
```

### 4. Run

```bash
python -m signal_bot.run
```

Or with verbose logging:

```bash
python -m signal_bot.run -v
```

## Signal Commands

### New Signal

```
/signal LONG BTCUSDT entry=50000 sl=49000 tp=52000 lev=10x
/signal SHORT ETHUSDT market sl=3800 tp=3500 lev=5x
```

**Parameters:**
- `LONG` or `SHORT` - Direction
- `BTCUSDT` - Symbol (use Mudrex symbol format)
- `entry=50000` - Entry price (omit or use `market` for market order)
- `sl=49000` - Stop loss price (required)
- `tp=52000` - Take profit price (required)
- `lev=10x` - Leverage (optional, default: 1x)

### Update Signal

```
/update SIG-20260103-001 sl=49500 tp=52500
```

Updates the stop loss and/or take profit for an active signal.

### Close Signal

```
/close SIG-20260103-001
```

Closes the position for the given signal ID.

### Partial Close

```
/partial SIG-20260103-001 50%
```

Closes 50% of the position.

## Bot Commands

When you DM the bot directly:

- `/start` - Show help message
- `/status` - Show active signals
- `/stats` - Show trading statistics
- `/balance` - Check wallet balance

## Configuration Options

| Option | Env Variable | Default | Description |
|--------|-------------|---------|-------------|
| `api_key` | `MUDREX_API_KEY` | - | Mudrex API key |
| `api_secret` | `MUDREX_API_SECRET` | - | Mudrex API secret |
| `telegram_bot_token` | `TELEGRAM_BOT_TOKEN` | - | Telegram bot token |
| `signal_channel_id` | `SIGNAL_CHANNEL_ID` | - | Channel ID to monitor |
| `trade_amount_usdt` | `TRADE_AMOUNT_USDT` | 50.0 | USDT per trade |
| `max_leverage` | `MAX_LEVERAGE` | 20 | Maximum allowed leverage |
| `data_file` | `DATA_FILE` | signals.json | Signal persistence file |

## Example Workflow

1. **You post a signal in your Telegram channel:**
   ```
   /signal LONG XRPUSDT entry=2.50 sl=2.30 tp=3.00 lev=5x
   ```

2. **Bot responds:**
   ```
   📊 Signal Received
   ━━━━━━━━━━━━━━━━━━━━
   🆔 ID: SIG-20260103-001
   📈 LONG XRPUSDT
   📋 Order: LIMIT @ 2.50
   🛑 Stop Loss: 2.30
   🎯 Take Profit: 3.00
   ⚡ Leverage: 5x
   ━━━━━━━━━━━━━━━━━━━━
   
   ✅ Trade Execution
   ━━━━━━━━━━━━━━━━━━━━
   🆔 Signal: SIG-20260103-001
   📊 Status: SUCCESS
   💬 Order placed: BUY XRPUSDT @ LIMIT
   ━━━━━━━━━━━━━━━━━━━━
   ```

3. **Later, update SL:**
   ```
   /update SIG-20260103-001 sl=2.45
   ```

4. **Close the position:**
   ```
   /close SIG-20260103-001
   ```

## Error Handling

- **Insufficient Balance**: Bot skips the trade and notifies you
- **Invalid Symbol**: Bot rejects the signal with error message
- **Leverage Limit**: Bot caps leverage at your configured maximum
- **Parse Errors**: Bot explains what's wrong with the signal format

## Project Structure

```
mudrex-signal-bot/
├── pyproject.toml
├── config.example.json
├── README.md
└── src/
    └── signal_bot/
        ├── __init__.py
        ├── config.py          # Configuration loading
        ├── run.py             # Main entry point
        ├── signal_parser.py   # Parse signal commands
        ├── trade_executor.py  # Execute trades on Mudrex
        ├── position_tracker.py # Track signals & positions
        └── telegram_bot.py    # Telegram bot handler
```

## Requirements

- Python 3.8+
- Mudrex account with API access
- Telegram bot token
- The improved Mudrex SDK (v1.1.0+)

## License

MIT License

## Disclaimer

⚠️ **Trading cryptocurrency futures involves significant risk of loss. This bot executes trades automatically based on signals. Use at your own risk. The developers are not responsible for any financial losses.**
