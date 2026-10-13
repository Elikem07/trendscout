FROM python:3.12-slim

WORKDIR /api

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations
COPY start.sh ./

EXPOSE 8000
CMD ["./start.sh"]
