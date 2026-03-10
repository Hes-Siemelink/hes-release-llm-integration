# Dockerfile for code-agent Release plugin container
#
# Hybrid Python + Node.js image with all tools needed to:
#   1. Run the Release SDK wrapper (Python entrypoint)
#   2. Sync beads via Dolt remote (bd + dolt)
#   3. Clone a GitHub repo and create PRs (git + gh)
#   4. Run OpenCode headlessly (Node.js + opencode-ai)
#
# Multi-stage build:
#   Stage 1:  Install bd (beads CLI) from GitHub release
#   Stage 1b: Install dolt binary
#   Stage 2:  Main image (Python 3.11-slim + Node.js + tools)

# ---------------------------------------------------------------------------
# Stage 1: Install bd (beads CLI) from GitHub release
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim AS bd-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG BD_VERSION=0.59.0
ARG TARGETARCH

RUN ARCH="${TARGETARCH:-amd64}" && \
    curl -fsSL "https://github.com/steveyegge/beads/releases/download/v${BD_VERSION}/beads_${BD_VERSION}_linux_${ARCH}.tar.gz" \
    | tar xz -C /usr/local/bin bd && \
    chmod +x /usr/local/bin/bd

# ---------------------------------------------------------------------------
# Stage 1b: Install dolt binary
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim AS dolt-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG DOLT_VERSION=1.83.4
ARG TARGETARCH

RUN ARCH="${TARGETARCH:-amd64}" && \
    curl -fsSL "https://github.com/dolthub/dolt/releases/download/v${DOLT_VERSION}/dolt-linux-${ARCH}.tar.gz" \
    | tar xz -C /tmp && \
    cp -f /tmp/dolt-linux-${ARCH}/bin/dolt /usr/local/bin/dolt && \
    chmod +x /usr/local/bin/dolt && \
    rm -rf /tmp/dolt-linux-${ARCH}

# ---------------------------------------------------------------------------
# Stage 2: Main image
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm

# Prevent Python from writing bytecode files and run in unbuffered mode
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    jq \
    openssh-client \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 (for OpenCode)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Install OpenCode globally
RUN npm install -g opencode-ai@latest

# Install AI SDK provider for custom/local models (Docker Model Runner, Ollama, etc.)
RUN npm install -g @ai-sdk/openai-compatible@latest

# Copy bd binary from builder stage
COPY --from=bd-builder /usr/local/bin/bd /usr/local/bin/bd

# Copy dolt binary from builder stage (required by bd for local database)
COPY --from=dolt-builder /usr/local/bin/dolt /usr/local/bin/dolt

# ---------------------------------------------------------------------------
# Application files
# ---------------------------------------------------------------------------
WORKDIR /app

# Copy requirements.txt first to leverage Docker cache
COPY requirements.txt ./

# Install Python dependencies (Release SDK)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the source code
COPY . .

# Create workspace directory
RUN mkdir -p /workspace

# Set git config to avoid warnings
RUN git config --system init.defaultBranch main

# ---------------------------------------------------------------------------
# Runtime entrypoint
# ---------------------------------------------------------------------------
# The Release SDK wrapper discovers task classes in src/ and dispatches
# based on type-definitions.yaml
CMD ["python", "-m", "digitalai.release.integration.wrapper"]
