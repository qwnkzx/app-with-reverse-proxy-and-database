FROM python:3.12-slim AS full

WORKDIR /app

COPY requirements.txt . 

RUN apt-get update && apt-get install -y gcc libpq-dev

RUN python -m venv venv && \
    ./venv/bin/pip install --no-cache-dir -r requirements.txt


#-------------------------------------
FROM python:3.12-slim 

WORKDIR /app

RUN groupadd -r appgroup && useradd -r -g appgroup appuser

COPY --from=full /app/venv ./venv

COPY . . 

COPY requirements.txt .

RUN chown -R appuser:appgroup  /app

USER appuser

ENV PATH="/app/venv/bin:$PATH"

EXPOSE 8000

CMD [ "python3", "server.py"]