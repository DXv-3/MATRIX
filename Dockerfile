FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo libopenjp2-7 libtiff6 libraw-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml schema.sql README.md ./
COPY matrix ./matrix
COPY docs ./docs
COPY examples ./examples
COPY scripts ./scripts

RUN pip install --no-cache-dir -e ".[raw]"

ENV MATRIX_DATA_DIR=/data
VOLUME ["/data", "/archive", "/quarantine"]

EXPOSE 8765

CMD ["matrix", "serve", "--host", "0.0.0.0", "--port", "8765"]