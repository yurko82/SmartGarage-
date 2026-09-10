import logging
from pathlib import Path


class Logger:

    def __init__(self):

        Path("logs").mkdir(exist_ok=True)

        logging.basicConfig(
            filename="logs/smartgarage.log",
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s"
        )

    def debug(self, message):
        logging.debug(message)

    def info(self, message):
        logging.info(message)
        print(message)

    def warning(self, message):
        logging.warning(message)
        print(message)

    def error(self, message):
        logging.error(message)
        print(message)
