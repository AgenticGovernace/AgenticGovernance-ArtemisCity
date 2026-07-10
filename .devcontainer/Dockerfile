FROM node:24-bookworm

# Install OS build tools and uv. Python 3.12 is supplied by the devcontainer
# feature in devcontainer.json so local containers follow the repo pin.
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
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

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv \
    && ln -s /root/.local/bin/uvx /usr/local/bin/uvx

# Install Node.js global tools
RUN npm install -g \
    typescript \
    ts-node \
    ts-node-dev \
    prettier \
    eslint \
    @typescript-eslint/eslint-plugin \
    @typescript-eslint/parser
