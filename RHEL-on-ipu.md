Installing RHEL on the Intel IPU
================================

This guide outlines the process of installing Red Hat Enterprise Linux (RHEL) on an Intel Infrastructure Processing Unit (IPU). Please note that these instructions involve various steps, primarily carried out on an ARM server and an x86 system with access to the Intel Management Controller (IMC). 

Prerequisites
-------------

*   x86 system with access to the IMC

Step-by-Step Installation Process
---------------------------------


In case anything has been left behind from previous attempts, run the following commands to clean up mount points:

```bash
mkdir -p /mnt/p4
umount /mnt/p4
kpartx -dv /dev/loop3
losetup -d /dev/loop3
```

After shutting down the virtual machine, proceed to mount the raw image to access its contents. Note that you need to replace the parition number p3 below with the root partition from the Virtual Machine:

```bash
losetup /dev/loop3 /root/disk-3.raw
kpartx -a /dev/loop3
mount /dev/mapper/loop3p4 /mnt/p4
```

Create an archive of the root filesystem:

```bash
tar cf rootfs.tar /mnt
```

### Copying and Preparing Root Filesystem on x86 System

Copy the resulting `rootfs.tar` to an x86 system that has access to the IMC:

```bash
scp rootfs.tar <x86-system>`
```

From the x86 system, transfer the `rootfs.tar` to the IMC:

```bash
scp rootfs.tar root@100.0.0.1:/work
```

### Configuring the IMC

```bash
ssh root@100.0.0.100 "date -s '$(date)'"
```

Connect to the IMC via SSH:

```bash
ssh root@100.0.0.1
date -s ...
```

Prepare the `p4` partition, assuming it's already formatted as ext4:

```bash
mkdir -p /mnt/p4
mount /dev/nvme0n1p4 /mnt/p4
rm -rf /mnt/p4
tar xf /work/rootfs.tar -C /mnt/p4
umount /mnt/p4
```

Modify `/etc/fstab` to ensure it points to the correct device:

```bash
echo "/dev/sda /                       ext4     defaults        0 0" > /mnt/p4/etc/fstab
```

### Modifying Kernel Arguments

Add `selinux=0` to the kernel arguments in `/mnt/imc/acc_variable/acc-config.json`:

```bash
{     "acc_watchdog_timer": 60,     "kernel": {         "boot_params" : "ip=192.168.0.2::192.168.0.1:255.255.255.0::enp0s1f0:off root=/dev/sda rw netroot=iscsi:192.168.0.1::::iqn.e2000:acc initrdmem=0x440c000000,0x8000000 acpi=force selinux=0"     } }
```

### Preparing the kernel and initrd

```bash
git clone https://github.com/coccinelle/coccinelle.git
cd coccinelle/
bash -c "sh <(curl -fsSL https://raw.githubusercontent.com/ocaml/opam/master/shell/install.sh)"
opam init
opam install Ocaml
eval $(opam env --switch=default)
./autogen
./configure
source env.sh
make clean
make
make install
```

### Finalizing
Reboot the IMC to cause the ACC to reboot too:

```bash
reboot
```

This process should result in the successful installation RHEL on the Intel IPU.
