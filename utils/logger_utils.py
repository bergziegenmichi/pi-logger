import logging
from datetime import datetime
from pathlib import Path

from config import configuration


class DirectDateFileHandler(logging.FileHandler):
    """
        Writes directly to a file named 'service.log.YYYY-MM-DD'.
        Switches to a new file automatically when the date changes.
        """

    def __init__(self, log_dir: Path, service_name: str, date_fmt: str):
        self.log_dir = log_dir
        self.service_name = service_name
        self.date_fmt = date_fmt
        self.current_date = datetime.now().strftime(date_fmt)

        # Calculate initial filename
        filename = self._get_filename()

        # Initialize standard FileHandler
        super().__init__(filename)

    def _get_filename(self):
        """Generates the filename based on current date."""
        return self.log_dir / f"service.log.{self.current_date}"

    def emit(self, record):
        """
        Overridden emit: Checks if date changed before writing.
        """
        try:
            new_date = datetime.now().strftime(self.date_fmt)

            # If the day has rolled over since the last log
            if new_date != self.current_date:
                self.current_date = new_date

                # 1. Close the current file stream
                self.close()

                # 2. Update the target filename
                self.baseFilename = str(self._get_filename())

                # 3. Open the new stream (FileHandler._open returns the stream)
                self.stream = self._open()

            # Proceed with standard logging
            super().emit(record)
        except Exception:
            self.handleError(record)


def get_service_logger(service_name: str) -> logging.Logger:
    logger = logging.getLogger(f"monitor.{service_name}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Only add handler if it doesn't exist yet to prevent duplicate logs
    if not logger.handlers:
        # Create directory
        log_dir = configuration.BASE_LOG_DIR / service_name
        log_dir.mkdir(parents=True, exist_ok=True)

        # Log to file: service.log (Rotates at midnight, keeps 30 days)
        log_file = log_dir / "service.log"
        handler = DirectDateFileHandler(
            log_dir=log_dir,
            service_name=service_name,
            date_fmt=configuration.LOG_SUFFIX_FORMAT
        )

        formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt=configuration.TIMESTAMP_FORMAT)
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
