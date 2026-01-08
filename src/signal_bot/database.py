"""
Database - Subscriber management with encrypted API key storage.

Uses SQLite with aiosqlite for async operations.
API keys are encrypted using Fernet before storage.
"""

import aiosqlite
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from .crypto import encrypt, decrypt, CryptoError

logger = logging.getLogger(__name__)

# Database schema version for migrations
SCHEMA_VERSION = 1


@dataclass
class Subscriber:
    """A registered subscriber."""
    telegram_id: int
    username: Optional[str]
    api_key: str  # Decrypted
    api_secret: str  # Decrypted
    trade_amount_usdt: float
    max_leverage: int
    is_active: bool
    trade_mode: str  # 'auto' or 'manual'
    created_at: datetime
    updated_at: datetime
    total_trades: int = 0
    total_pnl: float = 0.0


class Database:
    """
    Async SQLite database for subscriber management.
    
    All API keys are encrypted at rest.
    """
    
    def __init__(self, db_path: str = "subscribers.db"):
        """
        Initialize the database.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self._connection: Optional[aiosqlite.Connection] = None
    
    async def connect(self):
        """Connect to the database and initialize schema."""
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._init_schema()
        logger.info(f"Database connected: {self.db_path}")
    
    async def close(self):
        """Close the database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("Database connection closed")
    
    async def _init_schema(self):
        """Initialize database schema."""
        await self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS subscribers (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                api_key_encrypted TEXT NOT NULL,
                api_secret_encrypted TEXT NOT NULL,
                trade_amount_usdt REAL DEFAULT 50.0,
                max_leverage INTEGER DEFAULT 10,
                is_active INTEGER DEFAULT 1,
                trade_mode TEXT DEFAULT 'auto',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                total_trades INTEGER DEFAULT 0,
                total_pnl REAL DEFAULT 0.0
            );
            
            CREATE TABLE IF NOT EXISTS trade_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                signal_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                quantity REAL,
                entry_price REAL,
                status TEXT NOT NULL,
                error_message TEXT,
                executed_at TEXT NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES subscribers(telegram_id)
            );
            
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                order_type TEXT NOT NULL,
                entry_price REAL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                leverage INTEGER NOT NULL,
                status TEXT DEFAULT 'ACTIVE',
                created_at TEXT NOT NULL,
                closed_at TEXT
            );
            
            CREATE INDEX IF NOT EXISTS idx_trade_history_telegram_id 
                ON trade_history(telegram_id);
            CREATE INDEX IF NOT EXISTS idx_trade_history_signal_id 
                ON trade_history(signal_id);
            CREATE INDEX IF NOT EXISTS idx_signals_status 
                ON signals(status);
        """)
        await self._connection.commit()
    
    async def add_subscriber(
        self,
        telegram_id: int,
        username: Optional[str],
        api_key: str,
        api_secret: str,
        trade_amount_usdt: float = 50.0,
        max_leverage: int = 10,
    ) -> Subscriber:
        """
        Add or update a subscriber.
        
        API keys are encrypted before storage.
        """
        now = datetime.now().isoformat()
        
        # Encrypt API credentials
        api_key_encrypted = encrypt(api_key)
        api_secret_encrypted = encrypt(api_secret)
        
        await self._connection.execute("""
            INSERT INTO subscribers (
                telegram_id, username, api_key_encrypted, api_secret_encrypted,
                trade_amount_usdt, max_leverage, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                api_key_encrypted = excluded.api_key_encrypted,
                api_secret_encrypted = excluded.api_secret_encrypted,
                trade_amount_usdt = excluded.trade_amount_usdt,
                max_leverage = excluded.max_leverage,
                is_active = 1,
                updated_at = excluded.updated_at
        """, (
            telegram_id, username, api_key_encrypted, api_secret_encrypted,
            trade_amount_usdt, max_leverage, now, now
        ))
        await self._connection.commit()
        
        logger.info(f"Subscriber added/updated: {telegram_id} (@{username})")
        
        return Subscriber(
            telegram_id=telegram_id,
            username=username,
            api_key=api_key,
            api_secret=api_secret,
            trade_amount_usdt=trade_amount_usdt,
            max_leverage=max_leverage,
            is_active=True,
            trade_mode='auto',
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
        )
    
    async def get_subscriber(self, telegram_id: int) -> Optional[Subscriber]:
        """Get a subscriber by Telegram ID. Decrypts API keys."""
        async with self._connection.execute(
            "SELECT * FROM subscribers WHERE telegram_id = ?",
            (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            
        if not row:
            return None
        
        try:
            return Subscriber(
                telegram_id=row["telegram_id"],
                username=row["username"],
                api_key=decrypt(row["api_key_encrypted"]),
                api_secret=decrypt(row["api_secret_encrypted"]),
                trade_amount_usdt=row["trade_amount_usdt"],
                max_leverage=row["max_leverage"],
                is_active=bool(row["is_active"]),
                trade_mode=row.get("trade_mode", "auto") if hasattr(row, 'get') else (row["trade_mode"] if "trade_mode" in row.keys() else "auto"),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                total_trades=row["total_trades"],
                total_pnl=row["total_pnl"],
            )
        except CryptoError as e:
            logger.error(f"Failed to decrypt keys for {telegram_id}: {e}")
            return None
    
    async def get_active_subscribers(self) -> List[Subscriber]:
        """Get all active subscribers with decrypted API keys."""
        subscribers = []
        
        async with self._connection.execute(
            "SELECT * FROM subscribers WHERE is_active = 1"
        ) as cursor:
            async for row in cursor:
                try:
                    subscribers.append(Subscriber(
                        telegram_id=row["telegram_id"],
                        username=row["username"],
                        api_key=decrypt(row["api_key_encrypted"]),
                        api_secret=decrypt(row["api_secret_encrypted"]),
                        trade_amount_usdt=row["trade_amount_usdt"],
                        max_leverage=row["max_leverage"],
                        is_active=True,
                        trade_mode=row["trade_mode"] if "trade_mode" in row.keys() else "auto",
                        created_at=datetime.fromisoformat(row["created_at"]),
                        updated_at=datetime.fromisoformat(row["updated_at"]),
                        total_trades=row["total_trades"],
                        total_pnl=row["total_pnl"],
                    ))
                except CryptoError as e:
                    logger.error(f"Failed to decrypt keys for {row['telegram_id']}: {e}")
        
        return subscribers
    
    async def update_trade_amount(self, telegram_id: int, amount: float) -> bool:
        """Update a subscriber's trade amount."""
        now = datetime.now().isoformat()
        
        result = await self._connection.execute(
            "UPDATE subscribers SET trade_amount_usdt = ?, updated_at = ? WHERE telegram_id = ?",
            (amount, now, telegram_id)
        )
        await self._connection.commit()
        
        return result.rowcount > 0
    
    async def update_max_leverage(self, telegram_id: int, leverage: int) -> bool:
        """Update a subscriber's max leverage."""
        now = datetime.now().isoformat()
        
        result = await self._connection.execute(
            "UPDATE subscribers SET max_leverage = ?, updated_at = ? WHERE telegram_id = ?",
            (leverage, now, telegram_id)
        )
        await self._connection.commit()
        
        return result.rowcount > 0
    
    async def update_trade_mode(self, telegram_id: int, mode: str) -> bool:
        """Update a subscriber's trade mode ('AUTO' or 'MANUAL')."""
        mode = mode.upper()
        if mode not in ('AUTO', 'MANUAL'):
            raise ValueError("Mode must be 'AUTO' or 'MANUAL'")
        
        now = datetime.now().isoformat()
        
        result = await self._connection.execute(
            "UPDATE subscribers SET trade_mode = ?, updated_at = ? WHERE telegram_id = ?",
            (mode, now, telegram_id)
        )
        await self._connection.commit()
        
        logger.info(f"Trade mode updated for {telegram_id}: {mode}")
        return result.rowcount > 0
    
    async def deactivate_subscriber(self, telegram_id: int) -> bool:
        """Deactivate a subscriber (soft delete)."""
        now = datetime.now().isoformat()
        
        result = await self._connection.execute(
            "UPDATE subscribers SET is_active = 0, updated_at = ? WHERE telegram_id = ?",
            (now, telegram_id)
        )
        await self._connection.commit()
        
        logger.info(f"Subscriber deactivated: {telegram_id}")
        return result.rowcount > 0
    
    async def delete_subscriber(self, telegram_id: int) -> bool:
        """Permanently delete a subscriber and their API keys."""
        result = await self._connection.execute(
            "DELETE FROM subscribers WHERE telegram_id = ?",
            (telegram_id,)
        )
        await self._connection.commit()
        
        logger.info(f"Subscriber deleted: {telegram_id}")
        return result.rowcount > 0
    
    async def record_trade(
        self,
        telegram_id: int,
        signal_id: str,
        symbol: str,
        side: str,
        order_type: str,
        status: str,
        quantity: Optional[float] = None,
        entry_price: Optional[float] = None,
        error_message: Optional[str] = None,
    ):
        """Record a trade execution."""
        now = datetime.now().isoformat()
        
        await self._connection.execute("""
            INSERT INTO trade_history (
                telegram_id, signal_id, symbol, side, order_type,
                quantity, entry_price, status, error_message, executed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            telegram_id, signal_id, symbol, side, order_type,
            quantity, entry_price, status, error_message, now
        ))
        
        # Update subscriber stats
        if status == "SUCCESS":
            await self._connection.execute(
                "UPDATE subscribers SET total_trades = total_trades + 1 WHERE telegram_id = ?",
                (telegram_id,)
            )
        
        await self._connection.commit()
    
    async def save_signal(
        self,
        signal_id: str,
        symbol: str,
        signal_type: str,
        order_type: str,
        entry_price: Optional[float],
        stop_loss: float,
        take_profit: float,
        leverage: int,
    ):
        """Save a signal to the database."""
        now = datetime.now().isoformat()
        
        await self._connection.execute("""
            INSERT OR REPLACE INTO signals (
                signal_id, symbol, signal_type, order_type,
                entry_price, stop_loss, take_profit, leverage, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?)
        """, (
            signal_id, symbol, signal_type, order_type,
            entry_price, stop_loss, take_profit, leverage, now
        ))
        await self._connection.commit()
    
    async def close_signal(self, signal_id: str):
        """Mark a signal as closed."""
        now = datetime.now().isoformat()
        
        await self._connection.execute(
            "UPDATE signals SET status = 'CLOSED', closed_at = ? WHERE signal_id = ?",
            (now, signal_id)
        )
        await self._connection.commit()
    
    async def get_signal(self, signal_id: str) -> Optional[dict]:
        """Get a signal by ID."""
        async with self._connection.execute(
            "SELECT * FROM signals WHERE signal_id = ?",
            (signal_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None
    
    async def get_subscriber_count(self) -> int:
        """Get total active subscriber count."""
        async with self._connection.execute(
            "SELECT COUNT(*) as count FROM subscribers WHERE is_active = 1"
        ) as cursor:
            row = await cursor.fetchone()
            return row["count"] if row else 0
    
    async def get_stats(self) -> dict:
        """Get overall statistics."""
        async with self._connection.execute("""
            SELECT 
                COUNT(*) as total_subscribers,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_subscribers,
                SUM(total_trades) as total_trades,
                SUM(total_pnl) as total_pnl
            FROM subscribers
        """) as cursor:
            row = await cursor.fetchone()
        
        async with self._connection.execute(
            "SELECT COUNT(*) as count FROM signals WHERE status = 'ACTIVE'"
        ) as cursor:
            signals_row = await cursor.fetchone()
        
        return {
            "total_subscribers": row["total_subscribers"] or 0,
            "active_subscribers": row["active_subscribers"] or 0,
            "total_trades": row["total_trades"] or 0,
            "total_pnl": row["total_pnl"] or 0.0,
            "active_signals": signals_row["count"] or 0,
        }
