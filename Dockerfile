# Tag must equal the playwright version pinned in requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.64.1-noble

# nftables: egress firewall (deploy/entrypoint.sh). iproute2: egress-check dummy addresses.
# socat: temporary Inspector bridge (README).
RUN apt-get update \
 && apt-get install -y --no-install-recommends nftables iproute2 socat \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# noble's system Python is PEP 668 "externally managed"; this image is single-purpose.
ENV PIP_BREAK_SYSTEM_PACKAGES=1 PYTHONUNBUFFERED=1
RUN pip3 install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod 0755 /app/deploy/*.sh

# Starts as root to load the firewall, then drops to pwuser.
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
