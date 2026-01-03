"""
Signal Parser - Parse trading signals from Telegram messages.

Signal Formats:
    /signal LONG BTCUSDT entry=50000 sl=49000 tp=52000 lev=10x
    /signal SHORT ETHUSDT market sl=3800 tp=3500 lev=5x
    
Signal ID Format: SIG-DDMMYY-SYMBOL (e.g., SIG-030126-BTCUSDT)

Update/Close Commands:
    /update SIG-030126-BTCUSDT sl=49500
    /close SIG-030126-BTCUSDT
    /partial SIG-030126-BTCUSDT 50%
"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class SignalType(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class Signal:
    """Parsed trading signal."""
    signal_id: str
    signal_type: SignalType
    symbol: str
    order_type: OrderType
    entry_price: Optional[float]  # None for market orders
    stop_loss: float
    take_profit: float
    leverage: int
    raw_message: str
    timestamp: datetime


@dataclass
class SignalUpdate:
    """Update to an existing signal."""
    signal_id: str
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    entry_price: Optional[float] = None


@dataclass
class SignalClose:
    """Close signal command."""
    signal_id: str
    partial_percent: Optional[float] = None  # None = close 100%


class SignalParseError(Exception):
    """Raised when signal parsing fails."""
    pass


class SignalParser:
    """Parse trading signals from Telegram messages."""
    
    # Signal ID pattern: SIG-DDMMYY-SYMBOL (e.g., SIG-030126-BTCUSDT)
    SIGNAL_ID_PATTERN = r"SIG-\d{6}-[A-Z0-9]+"
    
    # Regex patterns
    SIGNAL_PATTERN = re.compile(
        r"/signal\s+(LONG|SHORT)\s+([A-Z0-9]+)\s+(.+)",
        re.IGNORECASE
    )
    
    UPDATE_PATTERN = re.compile(
        rf"/update\s+({SIGNAL_ID_PATTERN})\s+(.+)",
        re.IGNORECASE
    )
    
    CLOSE_PATTERN = re.compile(
        rf"/close\s+({SIGNAL_ID_PATTERN})",
        re.IGNORECASE
    )
    
    PARTIAL_PATTERN = re.compile(
        rf"/partial\s+({SIGNAL_ID_PATTERN})\s+(\d+)%?",
        re.IGNORECASE
    )
    
    # Parameter patterns
    PARAM_PATTERNS = {
        'entry': re.compile(r'entry[=:]?\s*([\d.]+)', re.IGNORECASE),
        'sl': re.compile(r'sl[=:]?\s*([\d.]+)', re.IGNORECASE),
        'tp': re.compile(r'tp[=:]?\s*([\d.]+)', re.IGNORECASE),
        'lev': re.compile(r'lev(?:erage)?[=:]?\s*(\d+)x?', re.IGNORECASE),
    }
    
    @classmethod
    def _generate_signal_id(cls, symbol: str) -> str:
        """
        Generate a unique signal ID.
        
        Format: SIG-DDMMYY-SYMBOL
        Example: SIG-030126-BTCUSDT
        """
        date_str = datetime.now().strftime("%d%m%y")
        return f"SIG-{date_str}-{symbol.upper()}"
    
    @classmethod
    def _extract_param(cls, text: str, param_name: str) -> Optional[float]:
        """Extract a parameter value from text."""
        pattern = cls.PARAM_PATTERNS.get(param_name)
        if not pattern:
            return None
        
        match = pattern.search(text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None
    
    @classmethod
    def _is_market_order(cls, params_text: str) -> bool:
        """Check if this is a market order."""
        return 'market' in params_text.lower() or cls._extract_param(params_text, 'entry') is None
    
    @classmethod
    def parse_signal(cls, message: str) -> Optional[Signal]:
        """
        Parse a /signal command.
        
        Examples:
            /signal LONG BTCUSDT entry=50000 sl=49000 tp=52000 lev=10x
            /signal SHORT ETHUSDT market sl=3800 tp=3500 lev=5x
        """
        match = cls.SIGNAL_PATTERN.match(message.strip())
        if not match:
            return None
        
        signal_type_str = match.group(1).upper()
        symbol = match.group(2).upper()
        params_text = match.group(3)
        
        # Parse signal type
        signal_type = SignalType.LONG if signal_type_str == "LONG" else SignalType.SHORT
        
        # Determine order type
        is_market = cls._is_market_order(params_text)
        order_type = OrderType.MARKET if is_market else OrderType.LIMIT
        
        # Extract parameters
        entry_price = None if is_market else cls._extract_param(params_text, 'entry')
        stop_loss = cls._extract_param(params_text, 'sl')
        take_profit = cls._extract_param(params_text, 'tp')
        leverage = cls._extract_param(params_text, 'lev')
        
        # Validate required fields
        if stop_loss is None:
            raise SignalParseError("Stop loss (sl) is required")
        if take_profit is None:
            raise SignalParseError("Take profit (tp) is required")
        if not is_market and entry_price is None:
            raise SignalParseError("Entry price is required for limit orders")
        
        # Default leverage if not specified
        if leverage is None:
            leverage = 1
        
        return Signal(
            signal_id=cls._generate_signal_id(symbol),
            signal_type=signal_type,
            symbol=symbol,
            order_type=order_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            leverage=int(leverage),
            raw_message=message,
            timestamp=datetime.now()
        )
    
    @classmethod
    def parse_update(cls, message: str) -> Optional[SignalUpdate]:
        """
        Parse a /update command.
        
        Example:
            /update SIG-030126-BTCUSDT sl=49500 tp=52500
        """
        match = cls.UPDATE_PATTERN.match(message.strip())
        if not match:
            return None
        
        signal_id = match.group(1).upper()
        params_text = match.group(2)
        
        return SignalUpdate(
            signal_id=signal_id,
            stop_loss=cls._extract_param(params_text, 'sl'),
            take_profit=cls._extract_param(params_text, 'tp'),
            entry_price=cls._extract_param(params_text, 'entry'),
        )
    
    @classmethod
    def parse_close(cls, message: str) -> Optional[SignalClose]:
        """
        Parse a /close command.
        
        Example:
            /close SIG-030126-BTCUSDT
        """
        match = cls.CLOSE_PATTERN.match(message.strip())
        if match:
            return SignalClose(signal_id=match.group(1).upper())
        return None
    
    @classmethod
    def parse_partial(cls, message: str) -> Optional[SignalClose]:
        """
        Parse a /partial close command.
        
        Example:
            /partial SIG-030126-BTCUSDT 50%
        """
        match = cls.PARTIAL_PATTERN.match(message.strip())
        if match:
            percent = float(match.group(2))
            return SignalClose(
                signal_id=match.group(1).upper(),
                partial_percent=percent
            )
        return None
    
    @classmethod
    def extract_symbol_from_id(cls, signal_id: str) -> Optional[str]:
        """
        Extract the trading symbol from a signal ID.
        
        Example:
            SIG-030126-BTCUSDT -> BTCUSDT
            SIG-030126-XRPUSDT -> XRPUSDT
        """
        parts = signal_id.split("-")
        if len(parts) >= 3:
            return parts[2].upper()
        return None
    
    @classmethod
    def parse(cls, message: str) -> Optional[Signal | SignalUpdate | SignalClose]:
        """
        Parse any signal command.
        
        Returns the appropriate dataclass based on command type.
        """
        message = message.strip()
        
        if message.lower().startswith('/signal'):
            return cls.parse_signal(message)
        elif message.lower().startswith('/update'):
            return cls.parse_update(message)
        elif message.lower().startswith('/close'):
            return cls.parse_close(message)
        elif message.lower().startswith('/partial'):
            return cls.parse_partial(message)
        
        return None


def format_signal_summary(signal: Signal) -> str:
    """Format a signal for display."""
    order_type_str = "MARKET" if signal.order_type == OrderType.MARKET else f"LIMIT @ {signal.entry_price}"
    
    return f"""
📊 **Signal Received**
━━━━━━━━━━━━━━━━━━━━
🆔 ID: `{signal.signal_id}`
📈 {signal.signal_type.value} {signal.symbol}
📋 Order: {order_type_str}
🛑 Stop Loss: {signal.stop_loss}
🎯 Take Profit: {signal.take_profit}
⚡ Leverage: {signal.leverage}x
━━━━━━━━━━━━━━━━━━━━
""".strip()
