# utils/logger.py
import logging
import os
import sys
import time
import json
from datetime import datetime
from typing import Optional, Dict, Any
import threading
from pathlib import Path

# Thread-local storage for context variables
_local_context = threading.local()


def set_context(generation_id: str = None, application_id: str = None):
    """
    Set context variables for logging.

    Args:
        generation_id: Batch generation ID
        application_id: Application ID being processed
    """
    if generation_id:
        _local_context.generation_id = generation_id
    if application_id:
        _local_context.application_id = application_id


def get_context() -> Dict[str, str]:
    """
    Get current logging context.

    Returns:
        Dictionary with current context variables
    """
    context = {}
    if hasattr(_local_context, 'generation_id'):
        context['generation_id'] = _local_context.generation_id
    if hasattr(_local_context, 'application_id'):
        context['application_id'] = _local_context.application_id
    return context


def clear_context():
    """Clear the current logging context."""
    if hasattr(_local_context, 'generation_id'):
        delattr(_local_context, 'generation_id')
    if hasattr(_local_context, 'application_id'):
        delattr(_local_context, 'application_id')


class ContextFilter(logging.Filter):
    """Filter that adds context variables to log records."""

    def filter(self, record):
        context = get_context()

        # Add context variables to the record
        if 'generation_id' in context:
            record.generation_id = context['generation_id']
        else:
            record.generation_id = 'global'

        if 'application_id' in context:
            record.application_id = context['application_id']
        else:
            record.application_id = 'global'

        return True


class ContextAwareRotatingFileHandler(logging.FileHandler):
    """
    A logging handler that writes to different files based on context.
    """

    def __init__(self, base_dir: str, level=logging.NOTSET):
        """
        Initialize with base directory instead of a specific filename.

        Args:
            base_dir: Base directory for log files
            level: Logging level
        """
        # Initialize with a dummy filename - we'll determine the actual file in emit()
        super().__init__("dummy.log", delay=True)  # delay=True prevents opening the dummy file
        self.base_dir = base_dir
        self.level = level
        self._open_handlers = {}

    def emit(self, record):
        """
        Emit a record, determining the appropriate file based on context.

        Args:
            record: LogRecord object
        """
        # Skip if record should be filtered out by level
        if record.levelno < self.level:
            return

        # Get context from the record
        generation_id = getattr(record, 'generation_id', 'global')
        application_id = getattr(record, 'application_id', 'global')

        # Create the log directory based on context
        log_dir = os.path.join(self.base_dir, generation_id, application_id)
        os.makedirs(log_dir, exist_ok=True)

        # Build the log file path
        log_file = os.path.join(log_dir, "lca_filer.log")

        # Use a different handler for each file path
        handler_key = log_file
        if handler_key not in self._open_handlers:
            # Create a new handler for this file
            try:
                self._open_handlers[handler_key] = logging.FileHandler(log_file)
                formatter = logging.Formatter(
                    '%(asctime)s - [GEN:%(generation_id)s] [APP:%(application_id)s] - %(name)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                self._open_handlers[handler_key].setFormatter(formatter)
            except Exception as e:
                sys.stderr.write(f"Error creating log handler: {str(e)}\n")
                return

        # Use the appropriate handler to emit the record
        try:
            self._open_handlers[handler_key].emit(record)
        except Exception as e:
            sys.stderr.write(f"Error writing to log: {str(e)}\n")

    def close(self):
        """Close all open handlers."""
        for handler in self._open_handlers.values():
            handler.close()
        self._open_handlers.clear()
        super().close()


def setup_logging(base_dir: str = "logs", level: int = logging.INFO) -> None:
    """
    Set up global logging configuration.

    Args:
        base_dir: Base directory for logs
        level: Logging level
    """
    # Create base log directory
    os.makedirs(base_dir, exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)

    # Create global file handler
    global_log_file = os.path.join(base_dir, "lca_filer.log")
    file_handler = logging.FileHandler(global_log_file)
    file_handler.setLevel(level)

    # Create context-aware handler
    context_handler = ContextAwareRotatingFileHandler(base_dir, level)

    # Create formatter with context variables
    formatter = logging.Formatter(
        '%(asctime)s - [GEN:%(generation_id)s] [APP:%(application_id)s] - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Add context filter to all handlers
    context_filter = ContextFilter()
    console_handler.addFilter(context_filter)
    file_handler.addFilter(context_filter)

    # Add formatter to handlers
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    # Add handlers to root logger
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(context_handler)

    # Log the initialization
    logging.info("Logging system initialized")


# Initialize logging at import time
setup_logging()


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Get a logger with the specified name and level.

    Args:
        name: Logger name
        level: Logging level

    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger


def get_application_logger(name: str, generation_id: str, application_id: str,
                           level: int = logging.INFO) -> logging.Logger:
    """
    Get a logger pre-configured for a specific application.
    Sets the context variables and returns a logger.

    Args:
        name: Logger name
        generation_id: Generation/batch ID
        application_id: Application ID
        level: Logging level

    Returns:
        Configured logger with application context
    """
    # Set context for this logger
    set_context(generation_id, application_id)

    # Get standard logger
    logger = get_logger(name, level)

    return logger


def log_exception(e: Exception, logger_name: str = None) -> None:
    """
    Log an exception with the current context.

    Args:
        e: Exception to log
        logger_name: Optional logger name (uses root logger if None)
    """
    if logger_name:
        logger = get_logger(logger_name)
    else:
        logger = logging.getLogger()

    # Get context and add to message
    context = get_context()
    context_str = " ".join([f"{k}={v}" for k, v in context.items()]) if context else "No context"

    # Log the exception with context
    logger.exception(f"Exception occurred [{context_str}]: {str(e)}")


def log_to_file(message: str, filename: str) -> None:
    """
    Log a message directly to a specific file.
    Useful for critical information that should persist regardless of context.

    Args:
        message: Message to log
        filename: Path to log file
    """
    try:
        # Create directory if needed
        os.makedirs(os.path.dirname(os.path.abspath(filename)), exist_ok=True)

        # Get context for the message
        context = get_context()
        context_str = ", ".join([f"{k}={v}" for k, v in context.items()]) if context else "No context"

        # Format the message with timestamp and context
        formatted_message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - [{context_str}] - {message}\n"

        # Append to file
        with open(filename, 'a') as f:
            f.write(formatted_message)
    except Exception as e:
        sys.stderr.write(f"Error writing to log file {filename}: {str(e)}\n")