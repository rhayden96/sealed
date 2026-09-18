FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml /app/
COPY src /app/src
RUN pip install --no-cache-dir .

EXPOSE 8080
CMD ["uvicorn", "sealed_target.main:app", "--host", "0.0.0.0", "--port", "8080"]
