#!/usr/bin/env python3
"""
Convenience script to run the Mudrex Signal Bot.

Usage:
    python run_bot.py
    python run_bot.py -v          # Verbose mode
    python run_bot.py --init      # Create config file
"""

from signal_bot.run import main

if __name__ == '__main__':
    main()
