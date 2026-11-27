# bullwhip Docker image — provides gmake >= 4.4 for .WAIT waves,
# Python 3.12, dlt, SQLMesh, and DuckDB.

FROM python:3.12-slim

# Install GNU Make >= 4.4 (Debian's make is 4.x but verify .WAIT support).
# We build from source to guarantee >= 4.4 for the critical-path .WAIT feature.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        && rm -rf /var/lib/apt/lists/*

# Build GNU Make 4.4.1 from source.
RUN curl -fsSL https://ftp.gnu.org/gnu/make/make-4.4.1.tar.gz | tar xz \
    && cd make-4.4.1 && ./configure --prefix=/usr/local && make -j"$(nproc)" && make install \
    && cd .. && rm -rf make-4.4.1

# Verify make version.
RUN make --version | head -1

# Install Python dependencies.
COPY pyproject.toml /app/pyproject.toml
WORKDIR /app
RUN pip install --no-cache-dir -e ".[duckdb]" || pip install --no-cache-dir "dlt[duckdb]" "dlt-ops" "sqlmesh[duckdb]" "duckdb>=1.2.0,<1.3.0"

# Copy the project.
COPY . /app

# Make scripts executable.
RUN chmod +x pipeline/lib/run_workflow.sh pipeline/lib/tracking_shell.py

# Default command — run the workflow.
CMD ["bash", "pipeline/lib/run_workflow.sh"]
