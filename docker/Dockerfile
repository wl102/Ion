FROM kalilinux/kali-rolling:latest

LABEL maintainer="Ion Team"
LABEL description="Ion - Cybersecurity Penetration Testing Agent"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PROJECT_ENVIRONMENT=/opt/ion/.venv
ENV ION_PORT=8000

# 替换 Kali 软件源为阿里云镜像（国内稳定）
RUN if [ -f /etc/apt/sources.list ]; then \
        sed -i 's/mirror.wane.kr/mirrors.aliyun.com/g' /etc/apt/sources.list && \
        sed -i 's/mirrors.neusoft.edu.cn/mirrors.aliyun.com/g' /etc/apt/sources.list && \
        sed -i 's/http.kali.org/mirrors.aliyun.com/g' /etc/apt/sources.list; \
    fi && \
    for f in /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do \
        if [ -f "$f" ]; then \
            sed -i 's/mirror.wane.kr/mirrors.aliyun.com/g' "$f" && \
            sed -i 's/mirrors.neusoft.edu.cn/mirrors.aliyun.com/g' "$f" && \
            sed -i 's/http.kali.org/mirrors.aliyun.com/g' "$f"; \
        fi; \
    done

# Install base system dependencies, networking tools, and Playwright system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    wget \
    git \
    unzip \
    tar \
    net-tools \
    iputils-ping \
    dnsutils \
    fonts-wqy-microhei \ 
    # CJK fonts for PDF report generation (Chinese/Japanese/Korean)
    fonts-noto-cjk \
    # Playwright Chromium runtime dependencies
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2t64 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install only the tools and wordlists actually used by Ion
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    sqlmap \
    dirb \
    wordlists \
    && rm -rf /var/lib/apt/lists/*

# Symlink dirb wordlists to the path expected by ffuf skill
# (skip if the wordlists package already provides this path on Kali)
RUN if [ ! -e /usr/share/wordlists/dirb/common.txt ]; then \
        mkdir -p /usr/share/wordlists/dirb \
        && ln -sf /usr/share/dirb/wordlists/common.txt /usr/share/wordlists/dirb/common.txt; \
    fi

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /opt/ion

# Copy dependency manifests first for layer caching
COPY pyproject.toml uv.lock README.md ./

# Install Python dependencies via uv (editable install of Ion)
COPY src/ ./src/
RUN uv sync --frozen --no-dev

# Make venv binaries available on PATH
ENV PATH="/opt/ion/.venv/bin:$PATH"

# Ensure pip is available in the venv so bash tools can run `pip install`
RUN uv pip install pip

# Install dirsearch
RUN wget -q "https://github.com/maurosoria/dirsearch/releases/download/v0.4.4/dirsearch-nuitka-linux-amd64-async" -O /tmp/dirsearch \
    && mv /tmp/dirsearch /usr/local/bin/dirsearch \
    && chmod +x /usr/local/bin/dirsearch

# Install Playwright Chromium browser binaries
RUN playwright install chromium

# Install ffuf (fast web fuzzer)
RUN wget -q "https://github.com/ffuf/ffuf/releases/download/v2.1.0/ffuf_2.1.0_linux_amd64.tar.gz" -O /tmp/ffuf.tar.gz \
    && tar -xzf /tmp/ffuf.tar.gz -C /usr/local/bin ffuf \
    && rm /tmp/ffuf.tar.gz

# Install nuclei (vulnerability scanner)
RUN wget -q "https://github.com/projectdiscovery/nuclei/releases/download/v3.4.2/nuclei_3.4.2_linux_amd64.zip" -O /tmp/nuclei.zip \
    && unzip -q /tmp/nuclei.zip -d /usr/local/bin \
    && rm /tmp/nuclei.zip \
    && nuclei -update-templates

# Create runtime directories
RUN mkdir -p /opt/ion/data /opt/ion/logs

# Copy entrypoint script
COPY docker/docker-entrypoint.sh /opt/ion/docker-entrypoint.sh
RUN chmod +x /opt/ion/docker-entrypoint.sh

EXPOSE ${ION_PORT}

ENTRYPOINT ["/opt/ion/docker-entrypoint.sh"]
CMD ["web"]
