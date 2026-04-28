FROM python:3.11-slim

WORKDIR /app

COPY server.py /app/server.py
COPY memories /app/memories

EXPOSE 49999

ENV PORT=49999
ENV MEMORY_DIR=/app/memories

CMD ["python", "server.py"]
