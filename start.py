#!/usr/bin/env python3
"""
Railway startup script with debugging.
"""
import os
import sys

print("=" * 60)
print("MUDREX SIGNAL BOT - RAILWAY STARTUP")
print("=" * 60)

# Check required environment variables
required_vars = [
    "TELEGRAM_BOT_TOKEN",
    "ADMIN_TELEGRAM_ID", 
    "SIGNAL_CHANNEL_ID",
    "ENCRYPTION_SECRET",
]

missing = []
for var in required_vars:
    value = os.environ.get(var)
    if value:
        # Mask sensitive values
        if "TOKEN" in var or "SECRET" in var:
            print(f"✅ {var} = {value[:10]}...{value[-4:]}")
        else:
            print(f"✅ {var} = {value}")
    else:
        print(f"❌ {var} = NOT SET")
        missing.append(var)

# Show optional vars
print("\nOptional variables:")
for var in ["WEBHOOK_URL", "DATABASE_PATH", "PORT"]:
    value = os.environ.get(var, "(not set)")
    print(f"   {var} = {value}")

if missing:
    print(f"\n❌ ERROR: Missing required variables: {missing}")
    print("Please set these in Railway dashboard -> Variables")
    sys.exit(1)

print("\n✅ All required variables present. Starting bot...")
print("=" * 60)

# Import and run the actual bot
from signal_bot.run import main
main()
