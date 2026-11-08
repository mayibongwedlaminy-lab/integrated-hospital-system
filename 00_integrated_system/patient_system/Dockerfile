# One image, three languages: Python (gateway, broker, hospital, specialist), Java (laboratory, analyzer) and Node.js (pharmacy).
# NOT TESTED where this was written (no Docker there); the same steps were run by hand without Docker.
FROM node:22-bookworm-slim
ENV PYTHONUNBUFFERED=1 PPS_DATA=/data PPS_HOST=0.0.0.0 PIP_BREAK_SYSTEM_PACKAGES=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip default-jdk-headless \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt
COPY . .
# install the npm packages and compile the laboratory's Java sources now (the analyzer compiles itself when it starts), so the first start is quick and needs no internet
RUN cd pharmacy_service && npm ci --omit=dev --no-audit --no-fund \
 && cd .. && python3 lab_service/run.py --prepare
# run as an ordinary user; databases live in the /data volume
RUN useradd --system --uid 10001 app && mkdir /data && chown app /data && chown -R app /app/lab_service /app/analyzer
USER app
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD python3 -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/ui/').status == 200 else 1)"
CMD ["python3", "run.py"]
