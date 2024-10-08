#!/usr/bin/env python3
import logging
import sys
import pexpect
from minicom import minicom_cmd, pexpect_child_wait, configure_minicom
from common_ipu import (
    extract_tar_gz,
    run,
    download_file,
    find_image,
    get_current_version,
    VERSIONS,
    minicom_get_version,
)


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
        self.logger = logging.getLogger(__name__)
        self.imc_address = imc_address
        self.dry_run = dry_run
        self.version_to_flash = version or VERSIONS[-1]
        self.repo_url = repo_url or "wsfd-advnetlab-amp04.anl.eng.bos2.dc.redhat.com"
        if not steps_to_run:
            steps_to_run = [
                "clean_up_imc",
                "flash_ssd_image",
                "flash_spi_image",
            ]
        self.steps_to_run = steps_to_run
        if self.dry_run:
            self.logger.info(
                "DRY RUN, This is just a preview of the actions that will be taken"
            )
            self.logger.debug(f"version_to_flash: {self.version_to_flash}")
            self.logger.debug(f"imc_address: {self.imc_address}")
            self.logger.debug(f"steps_to_run: {self.steps_to_run}")
            self.logger.debug(f"repo_url: {self.repo_url}")
            self.logger.debug(f"dry_run: {self.dry_run}")
            self.logger.debug(f"verbose: {self.verbose}")

    def should_run(self, step_name: str) -> bool:
        """Check if the step should be run"""
        return step_name in self.steps_to_run

    def reflash_ipu(self) -> None:
        self.logger.info("Reflashing the firmware of IPU.")

        if not self.dry_run:
            self.logger.info("Detecting version")
            result = get_current_version(
                imc_address=self.imc_address, logger=self.logger
            )
            if result.returncode:
                current_version = minicom_get_version(self.logger)
            else:
                current_version = result.out
            self.logger.info(f"Version: '{self.version_to_flash}'")
            if current_version == "1.2.0.7550":
                self.steps_to_run.insert(0, "ipu_runtime_access")
        else:
            self.logger.info("[DRY RUN] Detecting version")

        # Retrieve images if not a dry run
        self.logger.info("Retrieving images.....")
        ssd_image_path, spi_image_path = (
            self.get_images() if not self.dry_run else ("", "")
        )
        self.logger.info("Done Retrieving images")

        # Step 1: ipu_runtime_access
        self.logger.info("Step 1: ipu_runtime_access")
        if self.should_run("ipu_runtime_access"):
            self.ipu_runtime_access()
        else:
            logging.info("Skipping ipu_runtime_access")

        # Step 2: clean_up_imc
        self.logger.info("Step 2: clean_up_imc")
        if self.should_run("clean_up_imc"):
            self.clean_up_imc()
        else:
            logging.info("Skipping clean_up_imc")

        # Step 3: Flash SSD image using dd
        self.logger.info("Step 3: flash_ssd_image")
        if self.should_run("flash_ssd_image"):
            result = run(
                f"dd bs=16M if={ssd_image_path} | ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null {self.imc_address} 'dd bs=16M of=/dev/nvme0n1' status=progress",
                dry_run=self.dry_run,
            )
            if result.returncode:
                self.logger.error("Failed to flash_ssd_image")
                sys.exit(result.returncode)
        else:
            self.logger.info("Skipping flash_ssd_image")

        # Step 4: Flash SPI image
        self.logger.info("Step 4: flash_spi_image")
        if self.should_run("flash_spi_image"):
            result = run(
                f"ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {self.imc_address} 'flash_erase /dev/mtd0 0 0'",
                dry_run=self.dry_run,
            )
            if result.returncode:
                self.logger.error("Failed to erase SPI image")
                sys.exit(result.returncode)

            result = run(
                f"dd bs=16M if={spi_image_path} | ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {self.imc_address} 'dd bs=16M of=/dev/mtd0 status=progress'",
                dry_run=self.dry_run,
            )
            if result.returncode:
                self.logger.error("Failed to flash_spi_image")
                sys.exit(result.returncode)
        else:
            self.logger.info("Skipping flash_spi_image")

        # Step 5: Reboot IMC
        self.logger.info("Done!")
        self.logger.info(f"Please cold reboot IMC at {self.imc_address}")

    def ipu_runtime_access(self) -> None:
        if self.dry_run:

            self.logger.debug("[DRY RUN] pkill -9 minicom")
            self.logger.debug(
                "[DRY RUN] Wait for 'Press CTRL-A Z for help on special keys.'"
            )
            self.logger.debug("[DRY RUN] Ready to enter command")
            self.logger.debug("[DRY RUN] Send '/etc/ipu/ipu_runtime_access'")
            self.logger.debug("[DRY RUN] Wait for '.*#'")
            self.logger.debug("[DRY RUN] Capturing and printing output")
            self.logger.debug("[DRY RUN] Send Ctrl-A and 'x' to exit minicom")
            self.logger.debug("[DRY RUN] Expect EOF")
        else:
            run("pkill -9 minicom")
            self.logger.debug("Configuring minicom")
            configure_minicom()
            self.logger.debug("spawn minicom")
            child = pexpect.spawn(minicom_cmd("imc"))
            child.maxread = 10000
            pexpect_child_wait(
                child, ".*Press CTRL-A Z for help on special keys.*", 120
            )
            self.logger.debug("Ready to enter command")
            child.sendline("/etc/ipu/ipu_runtime_access")
            # Wait for the expected response (adjust the timeout as needed)
            pexpect_child_wait(child, ".*Enabling network and sshd.*", 120)

            # Capture and self.logger.debug the output
            assert child.before is not None
            self.logger.debug(child.before.decode("utf-8"))
            self.logger.debug(child.after.decode("utf-8"))
            # Gracefully close Picocom (equivalent to pressing Ctrl-A and Ctrl-X)
            child.sendcontrol("a")
            child.sendline("x")
            # Ensure Picocom closes properly
            child.expect(pexpect.EOF)

    def clean_up_imc(self) -> None:
        self.logger.info("Cleaning up IMC via SSH")

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

        self.logger.debug("Filling nvme0n1 with zeros")
        run(
            f"ssh -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' {self.imc_address} 'dd if=/dev/zero of=/dev/nvme0n1 bs=64k status=progress'",
            dry_run=self.dry_run,
        )
        self.logger.debug("Done filling nvme0n1 with zeros")

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
