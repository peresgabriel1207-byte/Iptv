FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY app.py /app/app.py
ENV DATA_DIR=/data DB_DIR=/db PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
  CMD python -c "import urllib.request,sys;sys.exit(0 if b'true' in urllib.request.urlopen('http://127.0.0.1:8080/health').read() else 1)"
CMD ["python", "-I", "/app/app.py"]
