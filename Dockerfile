FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SEATV_DB_PATH=/data/seatv.sqlite3 \
    SEATV_DAYS_AHEAD=7 \
    SEATV_REFRESH_AT=05:00

WORKDIR /app
COPY pyproject.toml README.md ./
COPY seatv ./seatv
RUN pip install --no-cache-dir . \
    && useradd --system --home /app seatv
COPY deploy/docker-entrypoint.sh /usr/local/bin/seatv-entrypoint

VOLUME /data
EXPOSE 8000
# Il server scarica la guida all'avvio e poi ogni giorno alle SEATV_REFRESH_AT (ora italiana).
ENTRYPOINT ["seatv-entrypoint"]
CMD ["uvicorn", "seatv.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
