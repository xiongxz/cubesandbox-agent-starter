FROM ghcr.io/tencentcloud/cubesandbox-base:2026.16

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY server.py /app/server.py
COPY memories /app/memories
COPY .env.example /app/.env.example

EXPOSE 49983 49999

ENV PORT=49999
ENV MEMORY_DIR=/app/memories
ENV ENVD_PORT=49983

ENTRYPOINT ["/usr/local/bin/cube-entrypoint.sh"]
CMD ["python3", "/app/server.py"]
