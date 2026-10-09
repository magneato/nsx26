# The Windows builds of CPython and Tesseract, run under Wine, for checking the Windows code paths
# (cmd wrappers, backslash paths, cp1252 console, font download, the test suite) from Linux.
# It is not Windows 11; CI's windows-latest jobs are. Build and run with tools/windows-check/run.sh.
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive WINEDEBUG=-all WINEARCH=win64 WINEPREFIX=/wine
RUN dpkg --add-architecture i386 && apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg xvfb xauth \
 && mkdir -pm755 /etc/apt/keyrings && curl -fsSL https://dl.winehq.org/wine-builds/winehq.key | gpg --dearmor -o /etc/apt/keyrings/winehq-archive.key \
 && curl -fsSL -o /etc/apt/sources.list.d/winehq-noble.sources https://dl.winehq.org/wine-builds/ubuntu/dists/noble/winehq-noble.sources \
 && apt-get update && apt-get install -y --install-recommends winehq-stable && rm -rf /var/lib/apt/lists/*
RUN wineboot --init 2>/dev/null; wineserver -w; true
RUN mkdir /dl && curl -fsSLo /dl/python-3.12.10-amd64.exe https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe \
 && curl -fsSLo /dl/tesseract-setup.exe https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe
COPY install.sh /install.sh
RUN bash /install.sh
