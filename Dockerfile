FROM python:3.12.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_ROOT_USER_ACTION=ignore
ENV PIP_DEFAULT_TIMEOUT=120
WORKDIR /app

ARG INSTALL_MEDIA_TOOLS=false
ARG INSTALL_CJK_FONTS=false
ARG PIP_INDEX_URL=
ARG PIP_EXTRA_INDEX_URL=
RUN if [ "$INSTALL_MEDIA_TOOLS" = "true" ] || [ "$INSTALL_CJK_FONTS" = "true" ]; then \
      apt-get update; \
      packages=""; \
      if [ "$INSTALL_MEDIA_TOOLS" = "true" ]; then packages="$packages ffmpeg"; fi; \
      if [ "$INSTALL_CJK_FONTS" = "true" ]; then packages="$packages fonts-noto-cjk"; fi; \
      apt-get install -y --no-install-recommends $packages; \
      rm -rf /var/lib/apt/lists/*; \
    fi

COPY server/requirements.txt /app/server/requirements.txt
RUN if [ -n "$PIP_INDEX_URL" ]; then export PIP_INDEX_URL="$PIP_INDEX_URL"; fi; \
    if [ -n "$PIP_EXTRA_INDEX_URL" ]; then export PIP_EXTRA_INDEX_URL="$PIP_EXTRA_INDEX_URL"; fi; \
    pip install --retries 5 --no-cache-dir -r /app/server/requirements.txt

COPY server /app/server
COPY docs /app/docs

EXPOSE 8000
ENV PYTHONPATH=/app/server
CMD ["uvicorn", "solorecord_server.main:app", "--host", "0.0.0.0", "--port", "8000"]
