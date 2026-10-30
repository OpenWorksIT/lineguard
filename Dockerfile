# LineGuard as a container, for hosting the dashboard on a server.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    LINEGUARD_HOST=0.0.0.0 LINEGUARD_PORT=8750 \
    LINEGUARD_DATA_DIR=/data LINEGUARD_INBOX_DIR=/data/inbox \
    LINEGUARD_HOSTED=1 TZ=Africa/Johannesburg

WORKDIR /src
COPY pyproject.toml README.md ./
COPY lineguard ./lineguard
COPY assets ./assets
RUN pip install --no-cache-dir . && rm -rf /src \
 && useradd --system --uid 10750 --home /data lineguard \
 && mkdir -p /data && chown lineguard /data

USER lineguard
WORKDIR /data
VOLUME /data
EXPOSE 8750
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8750/healthz', timeout=4)"
CMD ["lineguard", "serve"]
