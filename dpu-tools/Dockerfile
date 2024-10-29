FROM quay.io/centos/centos:stream9
RUN dnf install -y \
    procps-ng openssh-clients minicom python39 python3-pexpect python3-requests pciutils lshw iputils && \
    dnf clean all && \
    rm -rf /var/cache/* && \
    ln -s /usr/bin/pip3.9 /usr/bin/pip && \
    ln -s /usr/bin/python3.9 /usr/bin/python
COPY * /
ENTRYPOINT ["python3", "/dpu-tools"]
