FROM python:3.11-slim

WORKDIR /app

COPY server.py /app/server.py

EXPOSE 49999

ENV PORT=49999

CMD ["python", "server.py"]
