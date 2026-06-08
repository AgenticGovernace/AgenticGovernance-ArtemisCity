FROM mcr.microsoft.com/devcontainers/javascript-node:1-22-bookworm

# Install Python 3.11 and additional build tools
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-venv \
        python3.11-dev \
        python3-pip \
        build-essential \
        libpq-dev \
        curl \
        git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as the default python3
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# Use --break-system-packages to allow pip upgrades in Debian containers
RUN python3 -m pip install --upgrade --break-system-packages pip setuptools wheel

# Install common development tools
RUN python3 -m pip install --quiet --break-system-packages \
    black \
    pylint \
    mypy \
    isort \
    pytest \
    pytest-cov \
    ruff

# Install Node.js global tools
RUN npm install -g \
    typescript \
    ts-node \
    prettier \
    eslint
