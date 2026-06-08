FROM mcr.microsoft.com/devcontainers/javascript-node:1-24-bookworm

# Install Python 3.12 and build tools
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        python3.12-dev \
        build-essential \
        libpq-dev \
        curl \
        git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.12 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

# Install uv for fast Python dependency management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Install common development tools with uv
RUN /root/.cargo/bin/uv pip install --system --quiet \
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
