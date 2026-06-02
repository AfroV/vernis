FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    ffmpeg \
    xvfb \
    xdotool \
    python3 \
    fonts-liberation \
    fonts-noto-color-emoji \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 vernis
USER vernis
WORKDIR /home/vernis

COPY --chown=vernis:vernis entrypoint.sh server.py /home/vernis/
RUN chmod +x /home/vernis/entrypoint.sh

EXPOSE 8555

ENTRYPOINT ["/home/vernis/entrypoint.sh"]
