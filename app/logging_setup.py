import logging
import sys


class RuntimeStdoutHandler(logging.Handler):
    """
    A logging handler that writes to sys.stdout at runtime.
    This ensures that even if sys.stdout is monkey-patched or redirected
    after handler creation, we write to the current sys.stdout.
    It also ensures explicit flushing.
    """

    def __init__(self):
        super().__init__()

    def emit(self, record):
        try:
            msg = self.format(record)
            # Write directly to sys.stdout and flush
            # We use sys.stdout because we want to write to the standard output
            # of the process, which Docker captures.
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()
        except Exception:
            self.handleError(record)


def setup_logging():
    """
    Configure logging to output to sys.stdout using standard logging module.
    This replaces uvicorn's default logging configuration.
    """
    # Define the format
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(log_format, date_format)

    # Create a handler that writes to sys.stdout
    handler = RuntimeStdoutHandler()
    handler.setFormatter(formatter)

    # Configure the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove all existing handlers to ensure we have full control
    if root_logger.handlers:
        root_logger.handlers.clear()

    root_logger.addHandler(handler)

    # Configure Uvicorn loggers
    # We want uvicorn logs to also go through our handler (or propagate to root)
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"]:
        log = logging.getLogger(logger_name)
        log.handlers.clear()  # Remove uvicorn's default handlers
        log.propagate = True  # Propagate to root to use our handler

    # Ensure our app's logger propagates
    logging.getLogger("app").propagate = True

    return root_logger
