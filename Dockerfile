# The model is not baked in. It is a couple of gigabytes and it changes far less
# often than the code, so it lives in a volume and is fetched once.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY hearth_friend ./hearth_friend

# CPU torch: there is no GPU on the sort of machine this runs on, and the CUDA
# build is several gigabytes of nothing useful.
RUN pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -e . sentence-transformers websocket-client

ENV HF_HOME=/models \
    HEARTH_DB_PATH=/data/hearth.db \
    HEARTH_PERSONA=/persona/example.yaml \
    PYTHONUNBUFFERED=1

VOLUME ["/data", "/models"]
CMD ["hearth", "serve"]
