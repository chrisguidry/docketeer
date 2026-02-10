FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    bubblewrap \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy only the packages we need — avoids auto-discovery of plugins
# that require credentials we don't have (1password, rocketchat, etc.)
COPY pyproject.toml uv.lock ./
COPY docketeer/ docketeer/
COPY docketeer-tui/ docketeer-tui/
COPY docketeer-bubblewrap/ docketeer-bubblewrap/
COPY docketeer-web/ docketeer-web/
COPY .git/ .git/

# Trim the workspace to only include what we copied
RUN cat > pyproject.toml <<'EOF'
[tool.uv.workspace]
members = ["docketeer", "docketeer-tui", "docketeer-bubblewrap", "docketeer-web"]

[dependency-groups]
dev = [
    "docketeer",
    "docketeer-tui",
    "docketeer-bubblewrap",
    "docketeer-web",
]

[tool.uv.sources]
docketeer = { workspace = true }
docketeer-tui = { workspace = true }
docketeer-bubblewrap = { workspace = true }
docketeer-web = { workspace = true }
EOF

RUN uv sync

ENV DOCKETEER_CHAT=tui
ENTRYPOINT ["uv", "run", "docketeer"]
CMD ["start"]
