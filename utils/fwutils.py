#!/usr/bin/env python3
from logger import logger
from os import makedirs
import sys
import pexpect
import json
import re
import tempfile
from typing import Optional
from utils.minicom import minicom_cmd, pexpect_child_wait, configure_minicom
from utils.common_ipu import (
    check_connectivity,
    find_image,
    get_current_version,
    VERSIONS,
    minicom_get_version,
)
from utils.common_bf import find_bf_pci_addresses_or_quit, mst_flint, bf_version
from utils.common import (
    extract_tar_gz,
    download_file,
    run,
    Result,
    list_http_directory,
    ssh_run,
)
from utils.remote_api import RemoteAPI


class IPUFirmware:
    def __init__(
        self,
        imc_address: str,
        version: str = "",
        repo_url: str = "",
        steps_to_run: list[str] = [],
        dry_run: bool = False,
        verbose: bool = False,
    ):
        self.verbose = verbose
        self.imc_address = imc_address
        self.dry_run = dry_run
        self.version_to_flash = version or VERSIONS[-1]
        self.repo_url = repo_url or "wsfd-advnetlab-amp04.anl.eng.bos2.dc.redhat.com"
        if not steps_to_run:
            steps_to_run = [
                "clean_up_imc",
                "flash_ssd_image",
                "flash_spi_image",
                "apply_fixboard",
            ]
        self.steps_to_run = steps_to_run if not dry_run else []
        if self.dry_run:
            logger.info(
                "DRY RUN, This is just a preview of the actions that will be taken"
            )
            logger.debug(f"version_to_flash: {self.version_to_flash}")
            logger.debug(f"imc_address: {self.imc_address}")
            logger.debug(f"steps_to_run: {self.steps_to_run}")
            logger.debug(f"repo_url: {self.repo_url}")
            logger.debug(f"dry_run: {self.dry_run}")
            logger.debug(f"verbose: {self.verbose}")

    def should_run(self, step_name: str) -> bool:
        """Check if the step should be run"""
        return step_name in self.steps_to_run

    def reflash_ipu(self) -> None:
        logger.info("Reflashing the firmware of IPU.")

        if not self.dry_run:
            logger.info("Detecting version")
            result = get_current_version(imc_address=self.imc_address)
            if result.returncode:
                current_version = minicom_get_version()
            else:
                current_version = result.out
            logger.info(f"Version: '{self.version_to_flash}'")
            if current_version == "1.2.0.7550":
                self.steps_to_run.insert(0, "ipu_runtime_access")
        else:
            logger.info("[DRY RUN] Detecting version")

        # Retrieve images if not a dry run
        logger.info("Retrieving images.....")
        ssd_image_path, spi_image_path = (
            self.get_images() if not self.dry_run else ("", "")
        )
        logger.info("Done Retrieving images")

        # Step 1: ipu_runtime_access
        logger.info("Step 1: ipu_runtime_access")
        if self.should_run("ipu_runtime_access"):
            self.ipu_runtime_access()
        else:
            logger.info("Skipping ipu_runtime_access")

        # Step 2: clean_up_imc
        logger.info("Step 2: clean_up_imc")
        if self.should_run("clean_up_imc"):
            self.clean_up_imc()
        else:
            logger.info("Skipping clean_up_imc")

        # Step 3: Flash SSD image using dd
        logger.info("Step 3: flash_ssd_image")
        if self.should_run("flash_ssd_image"):
            result = run(
                f"dd bs=16M if={ssd_image_path} | ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {self.imc_address} 'dd bs=16M of=/dev/nvme0n1' status=progress",
                dry_run=self.dry_run,
            )
            if result.returncode:
                logger.error("Failed to flash_ssd_image")
                sys.exit(result.returncode)

            logger.info("Tidy up file system")
            # sync at IMC to refresh the partition tables
            run(
                f"ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {self.imc_address} 'sync ; sync ; sync'",
                dry_run=self.dry_run,
            )
            # write the in-memory partition table to disk
            run(
                f"ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {self.imc_address} 'echo -e \"w\" | fdisk /dev/nvme0n1'",
                dry_run=self.dry_run,
            )
            run(
                f"ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {self.imc_address} 'parted -sf /dev/nvme0n1 print'",
                dry_run=self.dry_run,
            )

        else:
            logger.info("Skipping flash_ssd_image")

        # Step 4: Flash SPI image
        logger.info("Step 4: flash_spi_image")
        if self.should_run("flash_spi_image"):
            result = run(
                f"ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {self.imc_address} 'flash_erase /dev/mtd0 0 0'",
                dry_run=self.dry_run,
            )
            if result.returncode:
                logger.error("Failed to erase SPI image")
                sys.exit(result.returncode)

            result = run(
                f"dd bs=16M if={spi_image_path} | ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {self.imc_address} 'dd bs=16M of=/dev/mtd0 status=progress'",
                dry_run=self.dry_run,
            )
            if result.returncode:
                logger.error("Failed to flash_spi_image")
                sys.exit(result.returncode)
        else:
            logger.info("Skipping flash_spi_image")

        logger.info("Step 5: apply_fixboard")
        if self.should_run("apply_fixboard"):
            if self.fixboard_is_needed():
                logger.info("Applying fixboard!")
                self.apply_fixboard()
            else:
                logger.info("Fixboard not needed!")
        else:
            logger.info("Skipping applying_fixboard")
        # Step 5: Reboot IMC
        logger.info("Done!")
        logger.info(f"Please cold reboot IMC at {self.imc_address}")

    def ipu_runtime_access(self) -> None:
        if self.dry_run:

            logger.debug("[DRY RUN] pkill -9 minicom")
            logger.debug(
                "[DRY RUN] Wait for 'Press CTRL-A Z for help on special keys.'"
            )
            logger.debug("[DRY RUN] Ready to enter command")
            logger.debug("[DRY RUN] Send '/etc/ipu/ipu_runtime_access'")
            logger.debug("[DRY RUN] Wait for '.*#'")
            logger.debug("[DRY RUN] Capturing and printing output")
            logger.debug("[DRY RUN] Send Ctrl-A and 'x' to exit minicom")
            logger.debug("[DRY RUN] Expect EOF")
        else:
            logger.debug(
                f"Checking that ipu runtime access is up by sshing into {self.imc_address}"
            )
            connected = check_connectivity(self.imc_address)
            if not connected:
                logger.debug(
                    f"Couldn't ssh into {self.imc_address}, enabling runtime access through minicom"
                )
                run("pkill -9 minicom")
                logger.debug("Configuring minicom")
                with configure_minicom():
                    logger.debug("spawn minicom")
                    child = pexpect.spawn(minicom_cmd("imc"))
                    child.maxread = 10000
                    pexpect_child_wait(
                        child, ".*Press CTRL-A Z for help on special keys.*", 120
                    )
                    logger.debug("Ready to enter command")
                    child.sendline("/etc/ipu/ipu_runtime_access")
                    # Wait for the expected response (adjust the timeout as needed)
                    pexpect_child_wait(child, ".*Enabling network and sshd.*", 120)

                    # Capture and logger.debug the output
                    assert child.before is not None
                    logger.debug(child.before.decode("utf-8"))
                    logger.debug(child.after.decode("utf-8"))
                    # Gracefully close Picocom (equivalent to pressing Ctrl-A and Ctrl-X)
                    child.sendcontrol("a")
                    child.sendline("x")
                    # Ensure Picocom closes properly
                    child.expect(pexpect.EOF)

    def clean_up_imc(self) -> None:
        logger.info("Cleaning up IMC via SSH")

        # Execute the commands over SSH with dry_run handling
        run(
            f"ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {self.imc_address} 'umount -l /dev/loop0'",
            dry_run=self.dry_run,
        )
        run(
            f"ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {self.imc_address} 'umount -l /dev/nvme0n1p*'",
            dry_run=self.dry_run,
        )
        run(
            f"ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {self.imc_address} 'killall -9 tgtd'",
            dry_run=self.dry_run,
        )

        logger.debug("Filling nvme0n1 with zeros")
        run(
            f"ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {self.imc_address} 'dd if=/dev/zero of=/dev/nvme0n1 bs=64k status=progress'",
            dry_run=self.dry_run,
        )
        logger.debug("Done filling nvme0n1 with zeros")

    def get_images(self) -> tuple[str, str]:
        """
        Download and extract the SSD image and recovery firmware for the given version.
        Return the paths for both files.
        """
        base_url = f"http://{self.repo_url}/intel-ipu-mev-{self.version_to_flash}"
        download_dir = "/tmp"  # Or any preferred directory for temp storage

        # URLs for the tar.gz files based on self.version
        ssd_tar_url = (
            f"{base_url}/intel-ipu-eval-ssd-image-{self.version_to_flash}.tar.gz"
        )
        recovery_tar_url = f"{base_url}/intel-ipu-recovery-firmware-and-tools-{self.version_to_flash}.tar.gz"

        # Download both tar.gz files
        ssd_tar_path = download_file(ssd_tar_url, download_dir)
        recovery_tar_path = download_file(recovery_tar_url, download_dir)

        # Extract both tar.gz files
        extracted_ssd_files = extract_tar_gz(ssd_tar_path, download_dir)
        extracted_recovery_files = extract_tar_gz(recovery_tar_path, download_dir)

        # Assume the identifier is 1001 for recovery firmware, but this could be passed as an argument
        identifier = "1001"

        # Find the required .bin files
        ssd_bin_file = find_image(extracted_ssd_files, "ssd-image-mev.bin")
        recovery_bin_file = find_image(
            extracted_recovery_files, "intel-ipu-recovery-firmware", identifier
        )

        return ssd_bin_file, recovery_bin_file

    def ensure_fixboard_image_on_imc(self) -> str:
        """
        Download and extract the SSD image and recovery firmware for the given version.
        Return the paths for both files.
        """
        # Regex to capture the number after the first `-` and a word
        pattern = r"^[a-zA-Z0-9]+-[a-zA-Z]+(\d+)"

        # Search for the number in the hostname
        match = re.search(pattern, self.imc_address)

        if match:
            number = match.group(1)
            logger.debug(f"Extracted number: {number}")
        else:
            logger.error(
                "No number found in the hostname. Can't proceed with detecting pre-built images"
            )
            exit(1)

        base_url = f"http://{self.repo_url}/fixboard"
        server_dirs = list_http_directory(base_url)
        logger.debug(f"server_dirs:{server_dirs}")
        if any(number in dir for dir in server_dirs):
            base_url = f"http://{self.repo_url}/fixboard/{number}"
            with tempfile.TemporaryDirectory() as temp_dir:
                download_dir = f"{temp_dir}/{self.repo_url}/fixboard/{number}"  # Or any preferred directory for temp storage
                makedirs(download_dir, exist_ok=True)
                fixboard_files = list_http_directory(base_url)
                fixboard_local_file_paths: list[str] = []
                for file in fixboard_files:
                    fixboard_local_file_paths.append(
                        download_file(f"{base_url}/{file}", download_dir)
                    )

                # Find the required .bin files
                logger.debug(f"fixboard_local_file_paths: {fixboard_local_file_paths}")
                for fixboard_file in fixboard_local_file_paths:
                    if fixboard_file.endswith(".bin.board_config"):

                        full_address = f"root@{self.imc_address}"

                        file_name = fixboard_file.split("/")[-1]
                        result = run(
                            f"scp -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {fixboard_file} {full_address}:/tmp/{file_name}",
                            dry_run=self.dry_run,
                        )
                        if result.returncode:
                            logger.error(
                                f"Couldn't transfer file using scp, Error: {result.err}"
                            )
                            exit(1)
                        return f"/tmp/{file_name}"

                logger.error("Couldn't find the board_config file, exitting...")
                exit(1)
        else:
            logger.error(
                f"server {self.imc_address} with number {number} doesn't have pre built fixboard images yet, please add the necessary files to the repo"
            )
            exit(1)

    def apply_fixboard(self) -> None:
        fixboard_bin_board_config_file = self.ensure_fixboard_image_on_imc()
        full_address = f"root@{self.imc_address}"
        result = ssh_run(
            "flash_erase /dev/mtd0 0x30000 1",
            full_address,
            dry_run=self.dry_run,
        )
        if result.returncode:
            logger.error(f"Couldn't flash_erase, Error: {result.err}")
            exit(1)

        result = ssh_run(
            f"nandwrite --start=0x30000 --input-size=0x1000 -p /dev/mtd0 {fixboard_bin_board_config_file}",
            full_address,
            dry_run=self.dry_run,
        )
        if result.returncode:
            logger.error(f"Couldn't nandwrite, Error: {result.err}")
            exit(1)
        logger.info("Rebooting IMC now!")
        result = ssh_run(
            "reboot",
            full_address,
            dry_run=self.dry_run,
        )

    def fixboard_is_needed(self) -> bool:
        full_address = f"root@{self.imc_address}"
        try:
            result = ssh_run(
                "iset-cli get-board-config",
                full_address,
                dry_run=self.dry_run,
            )
            if result.returncode:
                logger.error(
                    f"Couldn't retrieve get board config using iset-cli, Error: {result.err}"
                )
                exit(1)
            # Parse the JSON from the command output
            logger.debug(f"Board Config command output: {result.out}")
            board_config: dict[str, str] = json.loads(result.out)
            logger.debug(f"Json Board Config: {board_config}")
            for key, value in board_config.items():
                if "MAC Address" in key:
                    if value in ["00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"]:
                        return True
                if "PBA" in key:
                    if value in [
                        "000000000000000000000000",
                        "FFFFFFFFFFFFFFFFFFFFFFFF",
                    ]:
                        logger.debug(f"PBA check failed for {key}: {value}")
                        return True
                if "Serial Number" in key:
                    if value == "":
                        return True

            return False

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            exit(1)

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            exit(1)


class BFFirmware:
    def __init__(self, id: int, version_to_flash: Optional[str] = None):
        self.id = id
        bf = find_bf_pci_addresses_or_quit(self.id)
        self.version_to_flash = version_to_flash
        self.detected_version = bf_version(bf)

    def firmware_version(self) -> None:
        bf = find_bf_pci_addresses_or_quit(self.id)
        print(mst_flint(bf)["FW Version"])

    def firmware_up(self) -> Result:
        bf = find_bf_pci_addresses_or_quit(self.id)
        target_psid = mst_flint(bf)["PSID"]
        print(f"Bluefield-{self.detected_version} detected")

        assert self.detected_version is not None
        r = RemoteAPI(self.detected_version)
        if self.version_to_flash:
            version = self.version_to_flash
            print("Installing specified version: %s" % version)
        else:
            version = r.get_latest_version()
            print("Installing latest version: %s" % version)
        if mst_flint(bf)["FW Version"] == version:
            print(f"currently already on {version}")
            return Result("", "", 0)

        d = r.get_distros(version)
        print("Distros: %s" % d)

        for e in d:
            os_param = r.get_os(version, e)
            print(os_param)

            if os_param != target_psid:
                continue

            url = r.get_download_info(version, e, os_param)["files"][0]["url"]
            print(url)

            run(f"wget -q {url} -O fw.zip")
            ret = run("unzip -o fw.zip", capture_output=True)
            bin_name = [x for x in ret.out.split(" ") if ".bin" in x]
            print(f"bin_name: {bin_name}")
            if len(bin_name) != 1:
                print("unexpected number of binaries to download")
            run(f"mstflint -y -d {bf} -i {bin_name[0]} burn")
            run(f"mstfwreset -y -d {bf} r")
        return Result("", "", 0)

    def firmware_reset(self) -> None:
        bf = find_bf_pci_addresses_or_quit(self.id)
        run(f"mstconfig -y -d {bf} r")


def cx_fwup() -> None:
    run("chmod +x mlxup")
    r = run("/mlxup -y")
    exit(r.returncode)
