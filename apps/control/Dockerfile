FROM python:3.12-slim

WORKDIR /app
COPY packages/agent /packages/agent
COPY apps/control/pyproject.toml /app/
COPY apps/control/src /app/src
RUN pip install --no-cache-dir /packages/agent && pip install --no-cache-dir /app

EXPOSE 8081
CMD ["uvicorn", "sealed_control.main:app", "--host", "0.0.0.0", "--port", "8081"]
