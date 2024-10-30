import time
import pexpect
import os
import shutil
import tempfile
import logging
from contextlib import contextmanager
from typing import Generator

logger = logging.getLogger(__name__)


def minicom_cmd(dpu_type: str) -> str:
    return (
        "minicom -b 460800 -D /dev/ttyUSB2"
        if dpu_type == "imc"
        else "minicom -b 115200 -D /dev/ttyUSB0"
    )


def pexpect_child_wait(child: pexpect.spawn, pattern: str, timeout: float) -> float:
    logger.debug(f"Waiting {timeout} sec for pattern '{pattern}'")
    start_time = time.time()
    found = False
    last_exception = None
    while timeout and not found:
        cur_wait = min(timeout, 30)
        try:
            last_exception = None
            child.expect(pattern, timeout=cur_wait)
            found = True
            break
        except Exception as e:
            last_exception = e
            timeout -= cur_wait
            pass

    if not found:
        assert last_exception
        raise last_exception
    return round(time.time() - start_time, 2)


@contextmanager
def configure_minicom() -> Generator[None, None, None]:
    minirc_path = "/root/.minirc.dfl"

    # Check if minirc_path exists and create a temporary backup if it does
    if os.path.exists(minirc_path):
        backed_up = True
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        temp_file_path = temp_file.name
        temp_file.close()
        shutil.move(minirc_path, temp_file_path)  # Backup existing file
    else:
        backed_up = False
        temp_file_path = ""

    # Write new configuration
    with open(minirc_path, "w") as new_file:
        new_file.write("pu rtscts        No\n")

    try:
        # Yield control back to the context block
        yield
    finally:
        # Clean up by restoring the backup if it exists
        if backed_up:
            shutil.move(temp_file_path, minirc_path)
        elif temp_file_path:
            os.remove(temp_file_path)
