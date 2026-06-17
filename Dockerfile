FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client gosu \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 pbspy
WORKDIR /home/pbspy

COPY --chown=pbspy:pbspy . .
RUN pip install --no-cache-dir .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 9876
ENTRYPOINT ["/entrypoint.sh"]
CMD ["pbspy-server"]
