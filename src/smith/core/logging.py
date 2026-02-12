"""
Smith Logging Utilities
------------------------
Simple logging wrapper for consistent logger creation.
"""

import logging


def get_smith_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.
    Simple wrapper for now, can be extended for structured logging.
    """
    return logging.getLogger(name)
