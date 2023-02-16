from collections import namedtuple
import subprocess
import os
import sys
import shlex


def run(cmd: str, env: dict = os.environ.copy()):
    Result = namedtuple("Result", "out err returncode")
    args = shlex.split(cmd)
    pipe = subprocess.PIPE
    with subprocess.Popen(args, stdout=pipe, stderr=pipe, env=env) as proc:
        out = proc.stdout.read().decode("utf-8")
        err = proc.stderr.read().decode("utf-8")
        proc.communicate()
        ret = proc.returncode
    return Result(out, err, ret)

def all_interfaces():
    out = run("lshw -c network -businfo").out
    ret = {}
    for e in out.split("\n")[2:]:
        e = e.strip()
        if not e:
            continue
        pci, dev = e.split()[0:2]
        before_network = e.split("network")[0].strip()
        desc = e[len(before_network):].strip()[len("network"):].strip()
        ret[pci] = desc
    return ret

def find_bf2_pci_addresses():
    ai = all_interfaces()
    bfs = [e for e in ai.items() if "BlueField-2" in e[1]]
    return [k.split("@")[1] for k, v in bfs]

def find_bf2_pci_addresses_or_quit(bf_id):
    bf_pci = find_bf2_pci_addresses()
    if not bf_pci:
        print("No BF-2 found")
        sys.exit(-1)
    if bf_id < 0 or bf_id >= len(bf_pci):
        print("Invalid ID for BF-2")
        sys.exit(-1)
    return bf_pci[bf_id]

def mst_flint(pci):
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
