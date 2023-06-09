FROM quay.io/centos/centos:stream9 

RUN dnf install -y \
    rshim minicom python39 lshw mstflint wget unzip expect nfs-utils iproute httpd hwdata \
    vsftpd tftp-server dhcp-server iptables hostname tcpdump python3-pexpect iputils pciutils && \
    dnf clean all && \
    rm -rf /var/cache/* && \
    ln -s /usr/bin/pip3.9 /usr/bin/pip && \
    ln -s /usr/bin/python3.9 /usr/bin/python

COPY * /

RUN dnf install -y rust cargo python3-pip && \
    dnf clean all && \
    rm -rf /var/cache/* && \
    pip3 install --upgrade pip && \
    pip3 install setuptools-rust && \
    pip3 install bcrypt && \
    pip3 install pyasn1 && \
    pip3 install pynacl && \
    pip3 install paramiko>=2.12.0

RUN echo "echo 'running rshim'; rshim; sleep infinity" > rshim.sh && chmod +x rshim.sh
ENTRYPOINT /rshim.sh

# sudo podman run --pid host --network host --user 0 --name bf -dit --privileged -v /dev:/dev quay.io/bnemeth/bf
