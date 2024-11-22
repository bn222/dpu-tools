import argparse
import http.server
import io
import os
import paramiko
import pexpect
import requests
import shutil
import signal
import sys
import threading
import time
import typing

from multiprocessing import Process
from typing import Union

from utils import common_bf
from utils.common import run
from utils.minicom import pexpect_child_wait


class Pxeboot:
    def __init__(self, args: argparse.Namespace):
        self.install_entry = "Install OS"
        self.children: list[Process] = []
        self.args: argparse.Namespace = args
        self.ip = "172.31.100.1"
        self.net_prefix = "24"
        self.subnet = "172.31.100.0"
        self.port = "tmfifo_net0"

    def exit(self, code: int) -> typing.NoReturn:
        for p in self.children:
            p.terminate()
        sys.exit(code)

    def wait_any_ping(self, hn: list[str], timeout: float) -> str:
        print("Waiting for response from ping")
        begin = time.time()
        end = begin
        while end - begin < timeout:
            for e in hn:
                if self.ping(e):
                    return e
            time.sleep(5)
            end = time.time()
        raise Exception(f"No response after {round(end - begin, 2)}s")

    def ping(self, hn: str) -> bool:
        ping_cmd = f"timeout 1 ping -4 -c 1 {hn}"
        return run(ping_cmd).returncode == 0

    def write_file(self, fn: str, contents: str) -> None:
        with open(fn, "w") as f:
            f.write(contents)

    def read_file(self, fn: str) -> str:
        with open(fn, "r") as f:
            return "".join(f.readlines())

    def validate_args(self) -> None:
        if ":/" not in self.args.iso and not os.path.exists(self.args.iso):
            print(f"Couldn't read iso file {self.args.iso}")
            exit(-1)

        common_bf.find_bf_pci_addresses_or_quit(self.args.id)

    def dhcp_config(self, server_ip: str, subnet: str) -> str:
        return f"""option space pxelinux;
    option pxelinux.magic code 208 = string;
    option pxelinux.configfile code 209 = text;
    option pxelinux.pathprefix code 210 = text;
    option pxelinux.reboottime code 211 = unsigned integer 32;
    option architecture-type code 93 = unsigned integer 16;
    allow booting;
    allow bootp;

    next-server {server_ip};
    always-broadcast on;

    filename "/BOOTAA64.EFI";

    subnet {subnet} netmask 255.255.255.0 {{
        range 172.31.100.10 172.31.100.20;
        option broadcast-address 172.31.100.255;
        option routers {server_ip};
        option domain-name-servers 10.19.42.41, 10.11.5.19, 10.2.32.1;
        option domain-search "anl.lab.eng.bos.redhat.com";
        option dhcp-client-identifier = option dhcp-client-identifier;
    }}

    """

    def grub_config(self, base_path: str, ip: str, is_coreos: bool) -> str:
        if is_coreos:
            opts = f"coreos.live.rootfs_url=http://{ip}/rootfs.img ignition.firstboot ignition.platform.id=metal"
            ign_opts = f"{base_path}/ignition.img"
        else:
            opts = f"inst.repo=http://{ip}/mnt inst.ks=http://{ip}/kickstart.ks"
            ign_opts = ""

        return f"""
      set timeout=5

    menuentry '{self.install_entry}' --class red --class gnu-linux --class gnu --class os {{
        linux {base_path}/vmlinuz showopts {opts} \
            console=tty0 console=tty1 console=ttyS0,115200 console=ttyS1,115200 \
            ip=dhcp console=ttyAMA1 console=hvc0 \
            console=ttyAMA0 earlycon=pl011,0x01000000
        initrd {base_path}/initrd.img {ign_opts}
    }}

    menuentry 'Reboot' --class red --class gnu-linux --class gnu --class os {{
        reboot
    }}
    """

    def rshim_base(self) -> str:
        return f"/dev/rshim{self.args.id//2}/"

    def bf_reboot(self) -> None:
        print("Rebooting bf")
        with open(f"{self.rshim_base()}/misc", "w") as f:
            f.write("SW_RESET 1")

    def get_uefiboot_img(self) -> None:
        print("Ensuring efiboot_img is downloaded or copied to the right place")
        dst = "efiboot.img"
        if self.args.efiboot_img.startswith("http://"):
            print(f"Downloading efiboot.img from {self.args.efiboot_img}")
            response = requests.get(self.args.efiboot_img)
            open(dst, "wb").write(response.content)
        else:
            print(f"Copying efiboot.img from {self.args.efiboot_img}")
            shutil.copy(self.args.efiboot_img, dst)

    def os_name(self, is_coreos: bool) -> str:
        return "CoreOS" if is_coreos else "RHEL"

    def prepare_pxe(self) -> None:
        run(f"ip a f {self.port}")
        run(f"ip a a {self.ip}/{self.net_prefix} dev {self.port}")

        iso_mount_path = "/var/ftp/mnt"
        os.makedirs(iso_mount_path, exist_ok=True)
        run(f"umount {iso_mount_path}")
        run(f"mount -t iso9660 -o loop {self.args.iso} {iso_mount_path}")

        time.sleep(10)
        self.args.is_coreos = os.path.exists("/var/ftp/mnt/coreos")

        print(f"{self.os_name(self.args.is_coreos)} detected")

        rhel_files = ["BOOTAA64.EFI", "grubaa64.efi", "mmaa64.efi"]

        if not all(map(os.path.exists, rhel_files)):
            if not os.path.exists("efiboot.img"):
                self.get_uefiboot_img()
            else:
                print("Reusing missing bootfiles")

            mount_path = "/var/ftp/efibootimg"
            os.makedirs(mount_path, exist_ok=True)
            if mount_path in run("mount").out:
                print(run(f"umount {mount_path}"))
            print(run(f"mount efiboot.img {mount_path}"))

            for file in rhel_files:
                shutil.copy(f"{mount_path}/EFI/BOOT/{file}", "/var/lib/tftpboot/")

        ftp_files = ["images/pxeboot/vmlinuz", "images/pxeboot/initrd.img"]

        if self.args.is_coreos:
            ftp_files.append("images/ignition.img")
        ftpboot_pxe_dir_name = "/var/lib/tftpboot/pxelinux"
        os.makedirs(ftpboot_pxe_dir_name, exist_ok=True)
        for file in ftp_files:
            src = os.path.join(iso_mount_path, file)
            shutil.copy(src, ftpboot_pxe_dir_name)

        fn = "/var/lib/tftpboot/grub.cfg"
        print(f"writing configuration to {fn}")
        self.write_file(fn, self.grub_config("pxelinux", self.ip, self.args.is_coreos))

        fn = "/etc/dhcp/dhcpd.conf"
        print(f"writing configuration to {fn}")
        self.write_file(fn, self.dhcp_config(self.ip, self.subnet))

    def minicom_cmd(self) -> str:
        return f"minicom --baudrate 115200 --device {self.rshim_base()}/console"

    def bf_select_pxe_entry(self) -> None:
        print("selecting pxe entry in bf")
        ESC = "\x1b"
        KEY_DOWN = "\x1b[B"
        KEY_ENTER = "\r\n"

        run("pkill -9 minicom")
        print("spawn minicom")
        child = pexpect.spawn(self.minicom_cmd())
        child.maxread = 10000
        print("waiting for instructions to enter UEFI Menu to interrupt and go to bios")
        pexpect_child_wait(child, "Press.* enter UEFI Menu.", 120)
        print("found UEFI prompt, sending 'esc'")
        child.send(ESC * 10)
        time.sleep(1)
        child.close()
        print("respawning minicom")
        child = pexpect.spawn(self.minicom_cmd())
        time.sleep(1)
        print("pressing down")
        child.send(KEY_DOWN)
        time.sleep(1)
        print("waiting on language option")
        child.expect(
            "This is the option.*one adjusts to change.*the language for the.*current system",
            timeout=3,
        )
        print("pressing down again")
        child.send(KEY_DOWN)
        print("waiting for Boot manager entry")
        child.expect("This selection will.*take you to the Boot.*Manager", timeout=3)
        print("sending enter")
        child.send(KEY_ENTER)
        child.expect("Device Path")
        retry = 30
        print(f"Trying up to {retry} times to find tmfifo pxe boot interface")
        while retry:
            child.send(KEY_DOWN)
            time.sleep(0.1)
            try:
                child.expect("MAC.001ACAFFFF..,0x1.*IPv4.0.0.0.0.", timeout=1)
                break
            except Exception:
                retry -= 1
        if not retry:
            e = Exception("Didn't find boot interface")
            print(e)
            raise e
        else:
            print(f"Found boot interface after {30 - retry} tries, sending enter")
            child.send(KEY_ENTER)
            time.sleep(1)
            timeout = 30
            print(f"Waiting {timeout} seconds for Station IP address prompt")
            try:
                child.expect("Station IP address.*", timeout=timeout)
            except Exception:
                e = Exception("Kernel boot failed to begin")
                print(e)
                raise e

            print(f"Waiting {timeout} seconds for grub")
            try:
                child.expect(f".*{self.install_entry}.*", timeout=timeout)
            except Exception:
                e = Exception("Kernel boot failed to begin")
                print(e)
                raise e

            max_tries = 10
            total_time = max_tries * 30
            print(f"Waiting {total_time} sec for EFI stub message")
            elapsed = pexpect_child_wait(child, "EFI stub: .*", total_time)
            print(f"Found EFI stub message after {elapsed}s, kernel is booting")
            time.sleep(1)
        child.close()
        print("Closing minicom")

    def run(self, cmd: str) -> Process:
        p = Process(target=run, args=(cmd,))
        p.start()
        return p

    def http_server(self) -> None:
        os.chdir("/www")
        server_address = ("", 80)
        handler = http.server.SimpleHTTPRequestHandler
        httpd = http.server.HTTPServer(server_address, handler)
        httpd.serve_forever()

    def split_nfs_path(self, n: str) -> tuple[str, str]:
        splitted = n.split(":")
        return splitted[0], ":".join(splitted[1:])

    def mount_nfs_path(self, arg: str, mount_path: str) -> str:
        os.makedirs(mount_path, exist_ok=True)
        ip, path = self.split_nfs_path(arg)

        print(f"mounting {ip}:{os.path.dirname(path)} at {mount_path}")
        run(f"umount {mount_path}")
        run(f"mount {ip}:{os.path.dirname(path)} {mount_path}")
        return os.path.join(mount_path, os.path.basename(path))

    def get_private_key(self, key: str) -> Union[paramiko.RSAKey, paramiko.Ed25519Key]:
        try:
            return paramiko.RSAKey.from_private_key(io.StringIO(key))
        except paramiko.ssh_exception.SSHException:
            return paramiko.Ed25519Key.from_private_key(io.StringIO(key))

    def wait_and_login(self, ip: str) -> None:
        with open(self.args.key, "r") as f:
            key = f.read().strip()

        while True:
            try:
                host = paramiko.SSHClient()
                host.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                pkey = self.get_private_key(key)
                host.connect(ip, username="core", pkey=pkey)
                break
            except paramiko.ssh_exception.NoValidConnectionsError as e:
                print(f"Unable to establish SSH connection: {e}")
            except Exception as e:
                print(f"Got exception {e}")
            time.sleep(10)

        print("BF is up (ssh connection established)")
        local_date = run("date").out
        print(f"setting date to {local_date}")
        host.exec_command(f"sudo date -s '{local_date}'")

    def capture_minicom(
        self,
        stop_event: threading.Event,
        output: list[bytes],
    ) -> None:
        child = pexpect.spawn(self.minicom_cmd())

        while not stop_event.is_set():
            try:
                chunk = child.read_nonblocking(size=1024, timeout=1)
                output.append(chunk)
            except pexpect.TIMEOUT:
                pass
            except pexpect.EOF:
                print("Minicom exited unexpectedly while capturing output")
                break

    def prepare_kickstart(self, ip: str) -> None:
        ks = "kickstart.ks"
        dst = os.path.join("/www", ks)
        if os.path.exists(dst):
            os.remove(dst)

        shutil.copy(f"/{ks}", dst)

        with open(dst, "r") as file:
            file_content = file.read()

        find_text = "NETWORK_INSTALL_URL"
        replace_text = f"http://{ip}/mnt"
        updated_content = file_content.replace(find_text, replace_text)

        with open(dst, "w") as file:
            file.write(updated_content)

    def try_pxy_boot(self) -> str:
        self.validate_args()

        if ":/" in self.args.iso:
            self.args.iso = self.mount_nfs_path(self.args.iso, "/mnt/nfs_iso")

        if ":/" in self.args.key:
            self.args.key = self.mount_nfs_path(self.args.key, "/mnt/nfs_key")

        self.port = "tmfifo_net0"
        self.prepare_pxe()

        if not self.args.wait_minicom:
            self.bf_reboot()
        else:
            print("Skipping BF reboot since not using minicom")

        # need to wait long enough after reboot before setting
        # ip, otherwise it will be removed again
        time.sleep(5)
        run(f"ip a a {self.ip}/{self.net_prefix} dev {self.port}")

        print("starting dhpcd")
        run("killall dhcpd")
        p = self.run(
            "/usr/sbin/dhcpd -f -cf /etc/dhcp/dhcpd.conf -user dhcpd -group dhcpd"
        )
        self.children.append(p)

        os.makedirs("/www", exist_ok=True)
        src_rootfs = "/var/ftp/mnt/images/pxeboot/rootfs.img"
        if not os.path.exists("/www/rootfs.img") and os.path.exists(src_rootfs):
            shutil.copy(src_rootfs, "/www")

        self.prepare_kickstart(self.ip)

        base = "/var/lib/tftpboot/pxelinux"
        os.makedirs("/www/", exist_ok=True)
        if not os.path.exists("/www/vmlinuz"):
            shutil.copy(os.path.join(base, "vmlinuz"), "/www/vmlinuz")
        if not os.path.exists("/www/initrd.img"):
            shutil.copy(os.path.join(base, "initrd.img"), "/www/initrd.img")
        if not os.path.exists("/www/mnt") and os.path.exists("/var/ftp/mnt/images"):
            run("ln -s /var/ftp/mnt /www/mnt")

        print("starting http server")
        p = Process(target=self.http_server)
        p.start()
        self.children.append(p)

        print("starting in.tftpd")
        run("killall in.tftpd")
        p = self.run("/usr/sbin/in.tftpd -s -L /var/lib/tftpboot")
        self.children.append(p)
        if self.args.wait_minicom:
            print("Entering indefinite wait")
            while True:
                time.sleep(1)
        else:
            self.bf_select_pxe_entry()

        stop_event = threading.Event()
        output: list[bytes] = []
        minicom_watch = threading.Thread(
            target=self.capture_minicom, args=(self.args, stop_event, output)
        )
        minicom_watch.start()

        ping_exception = None
        try:
            candidates = [f"172.31.100.{x}" for x in range(10, 21)]
            response_ip = self.wait_any_ping(candidates, 180)
            print(f"got response from {response_ip}")
        except Exception as e:
            ping_exception = e
            # keep linter happy
            response_ip = ""
        stop_event.set()
        minicom_watch.join()
        output2 = b"".join(output)
        output_str = output2.decode("utf-8", errors="replace")
        print(output_str)
        if ping_exception is not None:
            raise ping_exception

        if self.args.key:
            self.wait_and_login(response_ip)
        else:
            # avoid killing services to allow booting
            time.sleep(1000)

        print("Terminating http, ftp, and dhcpd")
        for ch in self.children:
            ch.terminate()
        print(response_ip)
        return response_ip

    def kill_existing(self) -> None:
        pids = [pid for pid in os.listdir("/proc") if pid.isdigit()]

        own_pid = os.getpid()
        for pid in filter(lambda x: int(x) != own_pid, pids):
            try:
                with open(os.path.join("/proc", pid, "cmdline"), "rb") as f:
                    # print(f.read().decode("utf-8"))
                    zb = b"\x00"
                    cmd = [x.decode("utf-8") for x in f.read().strip(zb).split(zb)]
                    if cmd[0] == "python3" and os.path.basename(cmd[1]) == "pxeboot":
                        print(f"Killing pid {pid}")
                        os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass

    def start_pxeboot(self) -> None:
        self.kill_existing()
        for retry in range(6):
            try:
                self.try_pxy_boot()
                exit(0)
            except Exception as e:
                print(e)
                print(f"pxe boot failed, retrying (count {retry + 1})")
                for p in self.children:
                    p.terminate()
                self.children.clear()
                pass
        print("pxe boot reached max retries unsuccessfully")
        exit(-1)
