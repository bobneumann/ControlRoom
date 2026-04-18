FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends snmp \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-daemon.txt .
RUN pip install --no-cache-dir -r requirements-daemon.txt

COPY . .

EXPOSE 8765

CMD ["python", "daemon.py"]
