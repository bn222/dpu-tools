# Dpu tools
This repository contains tools and a Containerfile to build a container which provides a conveniant way to manage DPU's such as Bluefield-2 (BF-2) and Bluefield-3 (BF-3), Intel IPU, Marvell Octeon. Make sure that the underlying system has kernel-modules-extra installed (since cuse is a dependency) and run the container as follows (a build is available on quay.io):

```
sudo podman run --pull always --replace --pid host --network host --user 0 --name bf -dit --privileged -v /dev:/dev quay.io/bnemeth/dpu-tools <SUBCOMMAND>
```

## Tools

All the tools can directly be interacted with through the dpu-tools interface. All the tools automatically find and act on the first DPU in the system.
Note: Using the console subcommand requires specifying what DPU type you are working with. Check out its help page by passing the `-h` flag.

| Tool/Subcommand         | Purpose                                                                       |
|--------------|------------------------------------------------------------------------------------------|
| `reset`      | Reboots the DPU.                                                                         |
| `list`       | List all DPUs on the system.                                                             |
| `firmware`   | Manages the firmware of the DPU. {version, reset, up}                                    |
| `console`    | Starts a minicom console to access the DPU.                                              |
| `pxeboot`    | Starts a pxe server and tells BF to boot from it. An coreos iso file needs to be passed. |
| `set_mode`   | Sets the BF mode to either dpu or nic. One argument is required                          |
| `mode`       | Gets the BF mode. Use `--set-mode` to change the mode to either dpu or nic               | 
| `utils`      | Access common or non-dpu specific utilities. {cw_fwup, bfb}                              |

The `pxeboot` tool requires an argument; It expect an iso file with coreos that should
be booted through the rshim. The iso file can optionally be on an nfs mount point.
