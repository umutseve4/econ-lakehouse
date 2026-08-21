# econ-lakehouse pipeline image
# Build:  docker build -t econ-lakehouse .
# Run:    docker run --rm econ-lakehouse                       (fixture mode)
#         docker run --rm -e EVDS_API_KEY=... econ-lakehouse   (live mode)
FROM python:3.12-slim

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DBT_PROFILES_DIR=/app \
    PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "orchestrate.py"]
