import logging
import os
import re
import pexpect
import time
from minicom import configure_minicom, pexpect_child_wait, minicom_cmd
from common.common import Result, run


VERSIONS = ["1.2.0.7550", "1.6.2.9418", "1.8.0.10052"]


def find_image(
    extracted_files: list[str], bin_file_prefix: str, identifier: str = ""
) -> str:
    """
    Search through extracted files to find the binary file matching the prefix and identifier.
    """
    for root, _, files in os.walk(extracted_files[0]):  # Traverse directory
        for file in files:
            if bin_file_prefix in file and identifier in file:
                return os.path.join(root, file)
    raise FileNotFoundError(
        f"{bin_file_prefix} with identifier {identifier} not found in the extracted files."
    )


def get_current_version(
    imc_address: str, logger: logging.Logger, dry_run: bool = False
) -> Result:
    logger.debug("Getting Version via SSH")
    version = ""
    # Execute the commands over SSH with dry_run handling
    result = run(
        f"ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {imc_address} 'cat /etc/issue.net'",
        dry_run=dry_run,
        capture_output=True,
    )
    # Regular expression to match the full version (e.g., 1.8.0.10052)
    version_pattern = r"\d+\.\d+\.\d+\.\d+"

    # Search for the pattern in the input string
    match = re.search(version_pattern, result.out)

    if match:
        version = match.group(0)
    return Result(version, result.err, result.returncode)


def minicom_get_version(logger: logging.Logger) -> str:
    version = ""
    run("pkill -9 minicom")
    logger.debug("Configuring minicom")
    configure_minicom()
    logger.debug("spawn minicom")
    child = pexpect.spawn(minicom_cmd("imc"))
    child.maxread = 10000
    pexpect_child_wait(child, ".*Press CTRL-A Z for help on special keys.*", 120)
    logger.debug("Ready to enter command")
    child.sendline("cat /etc/issue.net")

    # Wait for the expected response (adjust the timeout as needed)

    try:
        pexpect_child_wait(child, ".*IPU IMC.*", 120)
    except Exception as e:
        raise e

    # Capture and print the output
    assert child.before is not None
    logger.debug(child.before.decode("utf-8"))
    logger.debug(child.after.decode("utf-8"))
    version_line = child.after.decode("utf-8")

    # Regular expression to match the full version (e.g., 1.8.0.10052)
    version_pattern = r"\d+\.\d+\.\d+\.\d+"

    # Search for the pattern in the input string
    match = re.search(version_pattern, version_line)

    if match:
        version = match.group(0)

    # Gracefully close Picocom (equivalent to pressing Ctrl-A and Ctrl-X)
    child.sendcontrol("a")
    child.sendline("x")
    # Ensure Picocom closes properly
    child.expect(pexpect.EOF)
    return version


def check_connectivity(
    address: str,
    capture_output: bool = False,
    dry_run: bool = False,
    retries: int = 3,
    delay: int = 2,
) -> bool:
    """
    Checks connectivity to the specified address by performing a ping, with retry capability.
    """
    # Extract hostname if address is in the form user@hostname
    if "@" in address:
        host = address.split("@")[-1]
    else:
        host = address

    # Attempt to ping with retry logic
    for attempt in range(1, retries + 1):
        result = run(
            f"ping -c 1 -W 1 {host}", capture_output=capture_output, dry_run=dry_run
        )

        if result.returncode == 0:
            logger.debug(f"{host} is reachable.")
            return True
        else:
            logger.debug(f"Attempt {attempt} to reach {host} failed.")
            if attempt < retries:
                logger.debug(f"Retrying in {delay} seconds...")
                time.sleep(delay)

    logger.debug(f"Failed to reach {host} after {retries} attempts.")
    return False
