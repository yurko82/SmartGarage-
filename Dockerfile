# ==============================================================================
# Isolated Python Execution Environment for Open Interpreter (Smart Garage)
# ==============================================================================
FROM python:3.11-slim

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    OPEN_INTERPRETER_DIR=/root/.config/open-interpreter

# Install essential system utilities and tools for code execution & inspection
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    git \
    jq \
    procps \
    iputils-ping \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set container working directory to project workspace
WORKDIR /workspace

# Install Open Interpreter and runtime libraries
RUN pip install --no-cache-dir \
    open-interpreter==0.4.3 \
    pyyaml \
    requests \
    pydantic \
    numpy

# Create Open Interpreter profile directory
RUN mkdir -p /root/.config/open-interpreter/profiles

# Copy interpreter configuration to container profiles
COPY config/interpreter_config.yaml /root/.config/open-interpreter/profiles/default.yaml
COPY config/interpreter_config.yaml /root/.config/open-interpreter/profiles/smart-garage.yaml

# Set default command to run Open Interpreter with custom profile
CMD ["interpreter", "--profile", "/root/.config/open-interpreter/profiles/smart-garage.yaml"]
