FROM quay.io/centos/centos:stream9 

RUN dnf install -y \
    rshim minicom python39 lshw mstflint wget unzip expect nfs-utils iproute httpd hwdata \
    vsftpd tftp-server dhcp-server iptables hostname tcpdump python3-pexpect iputils pciutils \
    procps-ng openssh-clients minicom python3-requests && \
    dnf clean all && \
    rm -rf /var/cache/* && \
    ln -s /usr/bin/pip3.9 /usr/bin/pip && \
    ln -s /usr/bin/python3.9 /usr/bin/python

RUN dnf install -y rust cargo python3-pip && \
    dnf clean all && \
    rm -rf /var/cache/* && \
    pip3 install --upgrade pip && \
    pip3 install setuptools-rust && \
    pip3 install bcrypt && \
    pip3 install pyasn1 && \
    pip3 install pynacl && \
    pip3 install requests && \
    pip3 install paramiko>=2.12.0

RUN wget https://www.mellanox.com/downloads/firmware/mlxup/4.26.0/SFX/linux_x64/mlxup

COPY . .

COPY entry.sh /entry.sh

# Ensure the script is executable
RUN chmod +x /entry.sh

ENTRYPOINT ["/entry.sh"]
# sudo podman run --pid host --network host --user 0 --name bf -dit --privileged -v /dev:/dev quay.io/bnemeth/bf
