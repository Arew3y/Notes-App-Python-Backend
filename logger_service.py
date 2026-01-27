from enum import Enum
import logging
import sys
import os
from pathlib import Path  # Added for safe path handling


# Namespace: WHERE is the log coming from?
class LogSource(Enum):
    SYSTEM = "SYSTEM"  # Startup, shutdown, config loading
    DB = "DATABASE"  # SQL queries, connection events
    RAG = "RAG_ENGINE"  # Vector search, ingestion, inference
    API = "API_LAYER"  # Requests coming from the frontend


# Level: HOW urgent is it?
class LogLevel(Enum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class VadapavLogger:
    _instance = None

    def __new__(cls):
        # Singleton pattern: Ensure we only have one logger instance
        if cls._instance is None:
            cls._instance = super(VadapavLogger, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.logger = logging.getLogger("vadapav_core")
        self.logger.setLevel(logging.DEBUG)

        # Avoid duplicate logs if re-initialized
        if self.logger.handlers:
            return

        # 1. Format: Time | Source | Level | Message
        # Example: 2024-01-23 10:00:00 | [DATABASE] | INFO | Connected to SQLite
        formatter = logging.Formatter(
            '%(asctime)s | [%(log_source)s] | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # 2. Handler: Stream to Console (Terminal)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        # 3. Handler: Write to File (optional but recommended)
        # FIX: Use User Home Directory to ensure write permissions in production/frozen apps.
        # Saves to ~/.vadapav/vadapav.log
        log_dir = Path.home() / ".vadapav"
        try:
            os.makedirs(log_dir, exist_ok=True)
            log_file = log_dir / "vadapav.log"

            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        except Exception:
            # Fallback to console only if file creation fails
            sys.stderr.write(f"Failed to create log file at {log_dir}\n")

    def log(self, source: LogSource, level: LogLevel, message: str, meta: dict = None):
        """
        The main entry point for logging.
        """
        # Attach the 'log_source' so the formatter can use it
        extra = {'log_source': source.value}

        full_message = message
        if meta:
            full_message = f"{full_message} | Meta: {meta}"

        self.logger.log(level.value, full_message, extra=extra)


# Create a global instance to import elsewhere
sys_log = VadapavLogger()