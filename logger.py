import logging
import sys


def setup_logging(verbose: bool = False) -> None:
    log_level = logging.DEBUG if verbose else logging.INFO

    # Clear existing handlers to prevent duplicates
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


setup_logging(verbose=False)

logger = logging.getLogger(__name__)
