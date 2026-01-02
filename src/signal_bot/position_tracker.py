"""
Position Tracker - Track active signals and their corresponding positions.

Maps signal IDs to Mudrex position/order IDs for updates and closes.
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from .signal_parser import Signal, SignalType, OrderType

logger = logging.getLogger(__name__)


@dataclass
class TrackedSignal:
    """A tracked signal with its position details."""
    signal_id: str
    symbol: str
    signal_type: str  # LONG or SHORT
    order_type: str  # MARKET or LIMIT
    entry_price: Optional[float]
    stop_loss: float
    take_profit: float
    leverage: int
    order_id: Optional[str]
    position_id: Optional[str]
    status: str  # PENDING, FILLED, CLOSED, CANCELLED
    created_at: str
    updated_at: str
    pnl: Optional[float] = None


class PositionTracker:
    """
    Track signals and their corresponding positions.
    
    Persists data to a JSON file for recovery on restart.
    """
    
    def __init__(self, data_file: str = "signals.json"):
        """
        Initialize the position tracker.
        
        Args:
            data_file: Path to the JSON file for persistence
        """
        self.data_file = Path(data_file)
        self.signals: Dict[str, TrackedSignal] = {}
        
        # Load existing data
        self._load()
    
    def _load(self):
        """Load signals from disk."""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    for signal_id, signal_data in data.items():
                        self.signals[signal_id] = TrackedSignal(**signal_data)
                logger.info(f"Loaded {len(self.signals)} tracked signals")
            except Exception as e:
                logger.error(f"Failed to load signals: {e}")
                self.signals = {}
        else:
            logger.info("No existing signals file, starting fresh")
    
    def _save(self):
        """Save signals to disk."""
        try:
            data = {
                signal_id: asdict(signal)
                for signal_id, signal in self.signals.items()
            }
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save signals: {e}")
    
    def add_signal(
        self,
        signal: Signal,
        order_id: Optional[str] = None,
        position_id: Optional[str] = None,
        status: str = "PENDING"
    ) -> TrackedSignal:
        """
        Add a new signal to tracking.
        
        Args:
            signal: The parsed signal
            order_id: Mudrex order ID (if order placed)
            position_id: Mudrex position ID (if position opened)
            status: Initial status
            
        Returns:
            The tracked signal
        """
        now = datetime.now().isoformat()
        
        tracked = TrackedSignal(
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            signal_type=signal.signal_type.value,
            order_type=signal.order_type.value,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            leverage=signal.leverage,
            order_id=order_id,
            position_id=position_id,
            status=status,
            created_at=now,
            updated_at=now,
        )
        
        self.signals[signal.signal_id] = tracked
        self._save()
        
        logger.info(f"Added signal {signal.signal_id} to tracking")
        return tracked
    
    def get_signal(self, signal_id: str) -> Optional[TrackedSignal]:
        """Get a tracked signal by ID."""
        return self.signals.get(signal_id)
    
    def update_signal(
        self,
        signal_id: str,
        order_id: Optional[str] = None,
        position_id: Optional[str] = None,
        status: Optional[str] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        pnl: Optional[float] = None,
    ) -> Optional[TrackedSignal]:
        """
        Update a tracked signal.
        
        Args:
            signal_id: The signal ID to update
            order_id: New order ID
            position_id: New position ID
            status: New status
            stop_loss: New stop loss
            take_profit: New take profit
            pnl: Realized PnL
            
        Returns:
            Updated signal or None if not found
        """
        tracked = self.signals.get(signal_id)
        if not tracked:
            logger.warning(f"Signal {signal_id} not found for update")
            return None
        
        if order_id is not None:
            tracked.order_id = order_id
        if position_id is not None:
            tracked.position_id = position_id
        if status is not None:
            tracked.status = status
        if stop_loss is not None:
            tracked.stop_loss = stop_loss
        if take_profit is not None:
            tracked.take_profit = take_profit
        if pnl is not None:
            tracked.pnl = pnl
        
        tracked.updated_at = datetime.now().isoformat()
        
        self._save()
        logger.info(f"Updated signal {signal_id}")
        return tracked
    
    def close_signal(self, signal_id: str, pnl: Optional[float] = None) -> Optional[TrackedSignal]:
        """Mark a signal as closed."""
        return self.update_signal(signal_id, status="CLOSED", pnl=pnl)
    
    def get_active_signals(self) -> Dict[str, TrackedSignal]:
        """Get all active (non-closed) signals."""
        return {
            sid: signal
            for sid, signal in self.signals.items()
            if signal.status not in ("CLOSED", "CANCELLED")
        }
    
    def get_signals_by_symbol(self, symbol: str) -> Dict[str, TrackedSignal]:
        """Get all signals for a symbol."""
        return {
            sid: signal
            for sid, signal in self.signals.items()
            if signal.symbol == symbol
        }
    
    def get_position_id(self, signal_id: str) -> Optional[str]:
        """Get the position ID for a signal."""
        tracked = self.signals.get(signal_id)
        return tracked.position_id if tracked else None
    
    def get_stats(self) -> dict:
        """Get tracking statistics."""
        active = len([s for s in self.signals.values() if s.status not in ("CLOSED", "CANCELLED")])
        closed = len([s for s in self.signals.values() if s.status == "CLOSED"])
        
        total_pnl = sum(
            s.pnl for s in self.signals.values()
            if s.pnl is not None
        )
        
        return {
            "total_signals": len(self.signals),
            "active": active,
            "closed": closed,
            "total_pnl": total_pnl,
        }


def format_tracker_stats(tracker: PositionTracker) -> str:
    """Format tracker stats for display."""
    stats = tracker.get_stats()
    
    pnl_emoji = "📈" if stats["total_pnl"] >= 0 else "📉"
    
    return f"""
📊 **Signal Statistics**
━━━━━━━━━━━━━━━━━━━━
📝 Total Signals: {stats['total_signals']}
🔄 Active: {stats['active']}
✅ Closed: {stats['closed']}
{pnl_emoji} Total PnL: ${stats['total_pnl']:.2f}
━━━━━━━━━━━━━━━━━━━━
""".strip()
