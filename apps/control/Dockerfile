FROM python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203

WORKDIR /app
COPY packages/runtime.lock.txt /app/packages/runtime.lock.txt
RUN pip install --no-cache-dir -r /app/packages/runtime.lock.txt
COPY packages/agent /packages/agent
COPY apps/control/pyproject.toml /app/
COPY apps/control/src /app/src
RUN pip install --no-cache-dir --no-build-isolation --no-deps /packages/agent /app

EXPOSE 8081
CMD ["uvicorn", "sealed_control.main:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1"]
