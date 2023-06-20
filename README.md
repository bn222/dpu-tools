# Bluefield tools
This repository contains tools and a Containerfile to build a container which provides a conveniant way to manage Buefield-2 (BF-2) and Bluefield-3 (BF-3). Make sure that the underlying system has kernel-modules-extra installed (since cuse is a dependency) and run the container as follows (a build is available on quay.io):

```
sudo podman run --pull always --replace --pid host --network host --user 0 --name bf -dit --privileged -v /dev:/dev -v /lib:/lib quay.io/bnemeth/bf
```

## Tools

All the tools can directly be ran inside the container. All the tools automatically find and act on the first BF in the system.

```
sudo podman exec -it bf <TOOL_NAME>
```

| Tool         | Purpose                                                                                  |
|--------------|------------------------------------------------------------------------------------------|
| `reset`      | Reboots the BF.                                                                          |
| `listbf`     | List all B2 on the system.                                                               |
| `fwup`       | Updates the firmware on the BF to the latest.                                            |
| `fwversion`  | Shows firmware version                                                                   |
| `console`    | Starts a minicom console to access the BF.                                               |
| `pxeboot`    | Starts a pxe server and tells BF to boot from it. An coreos iso file needs to be passed. |
| `fwdefaults` | Resets the firmware settings on the BF to defaults.                                      |
| `bfb`        | Downloads BFB images and sends it to the BF.                                             |
| `set_mode`   | Sets the BF mode to either dpu or nic. One argument is required                          |
| `get_mode`   | Gets the BF mode.                                                                        |

The only tool that requires an argument is the `pxeboot` tool. It expect an iso file with coreos that should
be booted through the rshim. The iso file can optionally be on an nfs mount point.
