FROM ubuntu:24.04 AS builder

ARG HTTP_PROXY=
ARG HTTPS_PROXY=
ARG NO_PROXY=
ARG ALL_PROXY=
ARG http_proxy=
ARG https_proxy=
ARG no_proxy=
ARG all_proxy=
ARG ARXIV_PROXY=
ARG ARXIV_API_PROXY=
ARG ARXIV_HTTP_PROXY=
ARG ARXIV_HTTPS_PROXY=

ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}
ENV NO_PROXY=${NO_PROXY}
ENV ALL_PROXY=${ALL_PROXY}
ENV http_proxy=${http_proxy}
ENV https_proxy=${https_proxy}
ENV no_proxy=${no_proxy}
ENV all_proxy=${all_proxy}
ENV ARXIV_PROXY=${ARXIV_PROXY}
ENV ARXIV_API_PROXY=${ARXIV_API_PROXY}
ENV ARXIV_HTTP_PROXY=${ARXIV_HTTP_PROXY}
ENV ARXIV_HTTPS_PROXY=${ARXIV_HTTPS_PROXY}
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get -o Acquire::http::Proxy="false" -o Acquire::https::Proxy="false" update && \
    apt-get -o Acquire::http::Proxy="false" -o Acquire::https::Proxy="false" install -y --no-install-recommends \
    ca-certificates \
    curl \
    build-essential \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
  && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --break-system-packages --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md README_zh.md ./
COPY app.py ./
COPY paperpilot ./paperpilot
COPY static ./static
COPY templates ./templates

RUN uv sync --frozen --no-dev

FROM ubuntu:24.04 AS runtime

ARG ARXIV_PROXY=
ARG ARXIV_API_PROXY=
ARG ARXIV_HTTP_PROXY=
ARG ARXIV_HTTPS_PROXY=

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH=/opt/venv/bin:$PATH
ENV ARXIV_PROXY=${ARXIV_PROXY}
ENV ARXIV_API_PROXY=${ARXIV_API_PROXY}
ENV ARXIV_HTTP_PROXY=${ARXIV_HTTP_PROXY}
ENV ARXIV_HTTPS_PROXY=${ARXIV_HTTPS_PROXY}

RUN apt-get -o Acquire::http::Proxy="false" -o Acquire::https::Proxy="false" update && \
    apt-get -o Acquire::http::Proxy="false" -o Acquire::https::Proxy="false" install -y --no-install-recommends \
    ca-certificates \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    python3 \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY . /app

RUN mkdir -p /app/db /data/papers

EXPOSE 7191

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7191/', timeout=4).read()"

CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "7191", "--papers-dir", "/data/papers"]
