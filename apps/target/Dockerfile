FROM python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203

WORKDIR /app
COPY packages/runtime.lock.txt /app/packages/runtime.lock.txt
RUN pip install --no-cache-dir -r /app/packages/runtime.lock.txt
COPY apps/target/pyproject.toml /app/
COPY apps/target/src /app/src
COPY apps/target/bootstrap.py /app/bootstrap.py
RUN pip install --no-cache-dir --no-build-isolation --no-deps .

EXPOSE 8080
CMD ["python", "/app/bootstrap.py"]
