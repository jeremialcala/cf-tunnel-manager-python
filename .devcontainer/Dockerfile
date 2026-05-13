FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl jq make git postgresql-client redis-tools \
        bash-completion ca-certificates dnsutils \
    && rm -rf /var/lib/apt/lists/*

# uv for fast dependency management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv

# kafkacat / kcat for Kafka debugging
RUN apt-get update && apt-get install -y --no-install-recommends kafkacat \
    || apt-get install -y --no-install-recommends kcat \
    && rm -rf /var/lib/apt/lists/*

USER vscode
SHELL ["/bin/bash", "-lc"]
