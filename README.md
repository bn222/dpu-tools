# Bluefield-2 tools
This repository contains tools and a Containerfile to build a container which provides a conveniant way to manage Buefield-2 (BF-2). Make sure that the underlying system has kernel-modules-extra installed (since cuse is a dependency) and run the container as follows (a build is available on quay.io):

```
sudo podman run --pid host --network host --user 0 --name bf -dit --privileged -v /dev:/dev quay.io/bnemeth/bf
```

## Tools

All the tools can directly be ran inside the container. All the tools automatically find and act on the first BF-2 in the system.

```
sudo podman exec -it bf <TOOL_NAME>
```

| Tool         | Purpose                                                                                    |
|--------------|--------------------------------------------------------------------------------------------|
| `reset`      | Reboots the BF-2.                                                                          |
| `nic_mode`    | Switches the BF-2 to nic mode.                                                             |
| `fwup`       | Updates the firmware on the BF-2 to the latest.                                            |
| `fwversion`  | Shows firmware version                                                                     |
| `console`    | Starts a minicom console to access the BF-2.                                               |
| `pxeboot`    | Starts a pxe server and tells BF-2 to boot from it. An coreos iso file needs to be passed. |
| `defaults`   | Resets the firmware settings on the BF-2 to defaults.                                      |

The only tool that requires an argument is the `pxeboot` tool. It expect an iso file with coreos that should
be booted through the rshim. The iso file can optionally be on an nfs mount point.
