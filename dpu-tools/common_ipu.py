import subprocess
import logging
from typing import IO
import requests
import sys
import tarfile
import os
import dataclasses
import threading
import re
import pexpect
from minicom import configure_minicom, pexpect_child_wait, minicom_cmd


VERSIONS = ["1.2.0.7550", "1.6.2.9418", "1.8.0.10052"]


@dataclasses.dataclass(frozen=True)
class Result:
    out: str
    err: str
    returncode: int


def setup_logging(verbose: bool) -> None:
    if verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),  # Log to stdout
        ],
    )


logger = logging.getLogger(__name__)


def run(command: str, capture_output: bool = False, dry_run: bool = False) -> Result:
    """
    This run command is able to both output to the screen and capture its respective stream into a Result, using multithreading
    to avoid the blocking operaton that comes from reading from both pipes and outputing in real time.
    """
    if dry_run:
        logger.info(f"[DRY RUN] Command: {command}")
        return Result("", "", 0)

    logger.debug(f"Executing: {command}")
    process = subprocess.Popen(
        command,
        shell=True,  # Lets the shell interpret what it should do with the command which allows us to use its features like being able to pipe commands
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )

    def stream_output(pipe: IO[str], buffer: list[str], stream_type: str) -> None:
        for line in iter(pipe.readline, ""):
            if stream_type == "stdout":
                logger.debug(line.strip())
            else:
                logger.debug(line.strip())

            if capture_output:
                buffer.append(line)
        pipe.close()

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    # Create threads to handle `stdout` and `stderr`
    stdout_thread = threading.Thread(
        target=stream_output,
        args=(process.stdout, stdout_lines, "stdout"),
    )
    stderr_thread = threading.Thread(
        target=stream_output,
        args=(process.stderr, stderr_lines, "stderr"),
    )

    stdout_thread.start()
    stderr_thread.start()

    # Wait for process to complete and for threads to finish so we can capture return its result
    process.wait()
    stdout_thread.join()
    stderr_thread.join()

    # Avoid joining operation if the output isn't captured
    if capture_output:
        stdout_str = "".join(stdout_lines)
        stderr_str = "".join(stderr_lines)
    else:
        stdout_str = ""
        stderr_str = ""

    return Result(stdout_str, stderr_str, process.returncode)


def download_file(url: str, dest_dir: str) -> str:
    """
    Download a file from the given URL and save it to the destination directory.
    """
    local_filename = os.path.join(dest_dir, url.split("/")[-1])
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:  # filter out keep-alive chunks
                    f.write(chunk)
    return local_filename


def extract_tar_gz(tar_path: str, extract_dir: str) -> list[str]:
    """
    Extract a .tar.gz file and return the list of all extracted files.
    """
    extracted_files = []
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=extract_dir)
        extracted_files = [os.path.join(extract_dir, name) for name in tar.getnames()]
    return extracted_files


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
        pexpect_child_wait(child, ".*IPU IMC MEV-HW-B1-ci-ts.release.*", 120)
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
