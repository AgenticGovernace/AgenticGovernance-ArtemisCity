FROM node:24-bookworm

# Install Python 3.11 (stable in Debian bookworm) and build tools
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-dev \
        python3-pip \
        build-essential \
        libpq-dev \
        postgresql-client \
        curl \
        wget \
        git \
        git-lfs \
        jq \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify Python is available
RUN python3 --version

# Install common development tools with pip
RUN pip3 install --no-cache-dir --break-system-packages \
    black \
    pylint \
    mypy \
    isort \
    pytest \
    pytest-cov \
    pytest-asyncio \
    ruff \
    flake8 \
    uv

# Install Node.js global tools
RUN npm install -g \
    typescript \
    ts-node \
    ts-node-dev \
    prettier \
    eslint \
    @typescript-eslint/eslint-plugin \
    @typescript-eslint/parser
