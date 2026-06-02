FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 pbspy
WORKDIR /home/pbspy

COPY --chown=pbspy:pbspy . .
RUN pip install --no-cache-dir .

USER pbspy
EXPOSE 9876
ENTRYPOINT ["pbspy-server"]
