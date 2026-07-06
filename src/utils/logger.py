import logging
import sys

_LOG_FORMAT = "%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s"
_LOG_DATEFMT = "%H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    """Return a named logger; configures root handlers once if none exist."""
    logger = logging.getLogger(name)
    if not logging.root.handlers:
        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logging.root.addHandler(stream_handler)

        file_handler = logging.FileHandler("mcp_server.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        logging.root.addHandler(file_handler)

        logging.root.setLevel(logging.INFO)
    return logger
