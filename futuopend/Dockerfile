# FutuOpenD Dockerfile
FROM ubuntu:18.04

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    libssl1.1 \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# 下載並解壓 FutuOpenD
ARG FUTU_VERSION=9.6.5618
RUN wget -q https://softwaredownload.futunn.com/Futu_OpenD_${FUTU_VERSION}_Ubuntu18.04.tar.gz \
    && tar -xzf Futu_OpenD_${FUTU_VERSION}_Ubuntu18.04.tar.gz \
    && mv Futu_OpenD_${FUTU_VERSION}_Ubuntu18.04/Futu_OpenD_${FUTU_VERSION}_Ubuntu18.04/* . \
    && rm -rf Futu_OpenD_${FUTU_VERSION}_Ubuntu18.04.tar.gz Futu_OpenD_${FUTU_VERSION}_Ubuntu18.04

# 暴露端口
EXPOSE 11111 11112

CMD ["./FutuOpenD"]
