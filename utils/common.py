import subprocess
import logging
from typing import IO
import requests
import sys
import tarfile
import os
import re
import dataclasses
import threading
import argparse

from enum import Enum


class DPUType(Enum):
    IPU = "Intel IPU"
    BF = "NVIDIA BlueField"
    OCTEON = "Marvell OCTEON"


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


def find_bus_pci_address(address: str) -> str:
    pattern = r"(\d+):(\d+)\.(\d+)"

    match = re.match(pattern, address)

    if match:
        bus = match.group(1)
        new_address = f"{bus}:00.0"
        return new_address
    else:
        return "Invalid PCI address format"


def list_dpus(args: argparse.Namespace) -> None:


def scan_for_dpus() -> dict[str, tuple[str, str]]:
    devs = {}
    for e in run("lspci", capture_output=True).out.split("\n"):
        if "Intel Corporation Device 145" in e:
            addr = find_bus_pci_address(e.split()[0])
            for line in run("lshw -c network -businfo", capture_output=True).out.split(
                "\n"
            ):
                if addr in line:
                    dev = line.split()[1]
                    devs[dev] = (addr, "IPU")
        if "BlueField" in e:
            addr = find_bus_pci_address(e.split()[0])
            for line in run("lshw -c network -businfo", capture_output=True).out.split(
                "\n"
            ):
                if addr in line:
                    dev = line.split()[1]
                    devs[dev] = (addr, "BF")
    return devs


def detect_dpu_type() -> Result:
    devs = scan_for_dpus()
    kinds = {kind for (_, (_, kind)) in devs.items()}
    if len(kinds) > 1:
        return Result(
            "",
            "Multiple DPU types detected on this machine. Automatic detection is not possible. Please specify the platform manually.",
            returncode=1,
        )

    if len(kinds) < 1:
        return Result(
            "",
            "No DPU devices found.",
            returncode=-1,
        )
    return Result(next(iter(kinds)), "", 0)
