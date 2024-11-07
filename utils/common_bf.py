import dataclasses
import logging
import os
import sys
import argparse
import requests
import time
from typing import Optional
from utils.common import run


@dataclasses.dataclass(frozen=True)
class Result:
    out: str
    err: str
    returncode: int


logger = logging.getLogger(__name__)


def all_interfaces() -> dict[str, str]:
    out = run("lshw -c network -businfo").out
    ret = {}
    for e in out.split("\n")[2:]:
        e = e.strip()
        if not e:
            continue
        pci, dev = e.split()[0:2]
        before_network = e.split("network")[0].strip()
        desc = e[len(before_network) :].strip()[len("network") :].strip()
        ret[pci] = desc
    return ret


def find_bf_pci_addresses() -> list[str]:
    ai = all_interfaces()
    bfs = [e for e in ai.items() if "BlueField" in e[1]]
    return [k.split("@")[1] for k, v in bfs]


def find_bf_pci_addresses_or_quit(bf_id: int) -> str:
    bf_pci = find_bf_pci_addresses()
    if not bf_pci:
        print("No BF found")
        sys.exit(-1)
    if bf_id < 0 or bf_id >= len(bf_pci):
        print("Invalid ID for BF")
        sys.exit(-1)
    return bf_pci[bf_id]


def mst_flint(pci: str) -> dict[str, str]:
    out = run(f"mstflint -d {pci} q").out
    ret = {}
    for e in out.split("\n"):
        e = e.strip()
        if not e:
            continue
        esplit = e.split(":")
        if len(esplit) != 2:
            continue
        key, value = esplit

        key = key.strip()
        value = value.strip()
        ret[key] = value
    return ret


def bf_version(pci: str) -> Optional[int]:
    out = run("lshw -c network -businfo").out
    for e in out.split("\n"):
        if not e.startswith(f"pci@{pci}"):
            continue
        return int(e.split("BlueField-")[1].split()[0])
    return None


def console_bf(args: argparse.Namespace) -> None:
    _ = find_bf_pci_addresses_or_quit(args.bf_id)
    os.system(
        f"minicom --color on --baudrate 115200 --device /dev/rshim{args.bf_id//2}/console"
    )


def bf_get_mode(id: int, should_next_boot: bool) -> None:
    bf = find_bf_pci_addresses_or_quit(id)

    cfg = [
        "INTERNAL_CPU_MODEL",
        "INTERNAL_CPU_PAGE_SUPPLIER",
        "INTERNAL_CPU_ESWITCH_MANAGER",
        "INTERNAL_CPU_IB_VPORT0",
        "INTERNAL_CPU_OFFLOAD_ENGINE",
    ]
    all_cfg = " ".join(cfg)
    ret = run(f"mstconfig -e -d {bf} q {all_cfg}", capture_output=True).out

    save_next = False
    settings = {}
    for e in ret.split("\n"):
        if not e:
            continue
        if e.startswith("Configurations:"):
            save_next = True
        elif save_next:
            if "different from default/current" in e:
                save_next = False
                continue
            k, default, current, next_boot = e.lstrip("*").split()
            config = next_boot if should_next_boot else current
            settings[k] = config.split("(")[1].split(")")[0]

    dpu_mode = {
        "INTERNAL_CPU_MODEL": "1",
        "INTERNAL_CPU_PAGE_SUPPLIER": "0",
        "INTERNAL_CPU_ESWITCH_MANAGER": "0",
        "INTERNAL_CPU_IB_VPORT0": "0",
        "INTERNAL_CPU_OFFLOAD_ENGINE": "0",
    }

    nic_mode = {
        "INTERNAL_CPU_MODEL": "1",
        "INTERNAL_CPU_PAGE_SUPPLIER": "1",
        "INTERNAL_CPU_ESWITCH_MANAGER": "1",
        "INTERNAL_CPU_IB_VPORT0": "1",
        "INTERNAL_CPU_OFFLOAD_ENGINE": "1",
    }

    if dpu_mode == settings:
        logger.info("dpu")
    elif nic_mode == settings:
        logger.info("nic")
    else:
        logger.info("unknown")
    logger.debug(settings)


def bf_set_mode(id: int, mode: str) -> None:
    bf = find_bf_pci_addresses_or_quit(id)

    dpu_mode = {
        "INTERNAL_CPU_MODEL": "EMBEDDED_CPU(1)",
        "INTERNAL_CPU_PAGE_SUPPLIER": "ECPF(0)",
        "INTERNAL_CPU_ESWITCH_MANAGER": "ECPF(0)",
        "INTERNAL_CPU_IB_VPORT0": "ECPF(0)",
        "INTERNAL_CPU_OFFLOAD_ENGINE": "ENABLED(0)",
    }

    nic_mode = {
        "INTERNAL_CPU_MODEL": "EMBEDDED_CPU(1)",
        "INTERNAL_CPU_PAGE_SUPPLIER": "ECPF(1)",
        "INTERNAL_CPU_ESWITCH_MANAGER": "ECPF(1)",
        "INTERNAL_CPU_IB_VPORT0": "ECPF(1)",
        "INTERNAL_CPU_OFFLOAD_ENGINE": "ENABLED(1)",
    }

    settings = dpu_mode if mode == "dpu" else nic_mode

    joined = ""
    for k, v in settings.items():
        value = v[-3:].strip("()")
        joined += f"{k}={value} "
    run(f"mstconfig -y -d {bf} s {joined}")


def download_bfb(id: int) -> None:
    _ = find_bf_pci_addresses_or_quit(id)

    bfb_image = "DOCA_2.0.2_BSP_4.0.3_Ubuntu_22.04-8.23-04.prod.bfb"
    bfb_url = f"https://content.mellanox.com/BlueField/BFBs/Ubuntu22.04/{bfb_image}"
    print(f"Downloading bfb image from {bfb_url}")
    start = time.time()
    r = requests.get(bfb_url)
    print(f"It took {round(time.time() - start, 2)}s to download the BFB image")
    fn = f"/dev/rshim{id//2}/boot"
    print(f"Loading BFB image onto the BF using {fn}. This will take a while")
    start = time.time()
    with open(fn, "wb") as f:
        f.write(r.content)
    print(f"It took {round(time.time() - start, 2)}s to load the BFB image")
