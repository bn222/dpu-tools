FROM quay.io/centos/centos:stream9 

RUN dnf install -y \
    rshim minicom python3.11 python3.11-pip lshw mstflint wget unzip expect nfs-utils iproute httpd hwdata \
    vsftpd tftp-server dhcp-server iptables hostname tcpdump iputils pciutils rust cargo \
    procps-ng openssh-clients minicom && \
    dnf clean all && \
    rm -rf /var/cache/* && \
    ln -s /usr/bin/pip3.11 /usr/bin/pip && \
    ln -s /usr/bin/python3.11 /usr/bin/python

RUN dnf install -y rust cargo && \
    dnf clean all && \
    rm -rf /var/cache/* && \
    pip install --upgrade pip && \
    pip install pexpect \
    setuptools-rust \
    bcrypt \
    pyasn1 \
    pynacl \
    requests \
    paramiko>=2.12.0

RUN wget https://www.mellanox.com/downloads/firmware/mlxup/4.26.0/SFX/linux_x64/mlxup

COPY . .

COPY entry.sh /entry.sh

# Ensure the script is executable
RUN chmod +x /entry.sh

ENTRYPOINT ["/entry.sh"]
# sudo podman run --pid host --network host --user 0 --name bf -dit --privileged -v /dev:/dev quay.io/bnemeth/bf
