"""Vercel serverless entry point."""

import os
import sys

# Add project root to Python path
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root not in sys.path:
    sys.path.insert(0, root)

# Set Vercel flag for /tmp DB path
os.environ["VERCEL"] = "1"

from src.growth.server import app
