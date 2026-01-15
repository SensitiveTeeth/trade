# FutuOpenD Dockerfile
FROM ubuntu:22.04

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    libssl3 \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# 下載並解壓 FutuOpenD
ARG FUTU_VERSION=10.0.4208
RUN wget -q https://softwaredownload.futunn.com/FutuOpenD_${FUTU_VERSION}_Ubuntu20.04.tar.gz \
    && tar -xzf FutuOpenD_${FUTU_VERSION}_Ubuntu20.04.tar.gz \
    && mv FutuOpenD/* . \
    && rm -rf FutuOpenD_${FUTU_VERSION}_Ubuntu20.04.tar.gz FutuOpenD

# 暴露端口
EXPOSE 11111 11112

CMD ["./FutuOpenD"]
