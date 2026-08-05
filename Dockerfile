# Gear Locker — nothing to install, so this image is just Python plus two files.

FROM python:3.12-slim

# The container writes to a folder bind-mounted from your host, so its user
# needs to match yours. Check yours with:  id -u  and  id -g
# Then build with:  UID=$(id -u) GID=$(id -g) docker compose build
ARG UID=1000
ARG GID=1000

# Without this, the startup banner and errors sit in a buffer and
# `docker logs` looks empty.
ENV PYTHONUNBUFFERED=1

RUN groupadd --gid ${GID} gear \
 && useradd --uid ${UID} --gid ${GID} --no-create-home --home-dir /app gear

WORKDIR /app
COPY gear.py index.html ./
RUN mkdir -p /app/data && chown -R ${UID}:${GID} /app

USER gear

# 127.0.0.1 would only be reachable from inside the container.
EXPOSE 8000
CMD ["python3", "gear.py", "--host", "0.0.0.0", "--port", "8000"]

# No curl in the slim image, so ask Python instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/state', timeout=4)"