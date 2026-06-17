#!/bin/sh
set -e

mkdir -p /home/pbspy/.ssh
chown pbspy:pbspy /home/pbspy/.ssh
chmod 700 /home/pbspy/.ssh

# Copy known_hosts from the staged host .ssh directory so SSH can verify
# Gadi's host key regardless of the host file's ownership/permissions.
if [ -f /tmp/ssh_host/known_hosts ]; then
    cp /tmp/ssh_host/known_hosts /home/pbspy/.ssh/known_hosts
    chown pbspy:pbspy /home/pbspy/.ssh/known_hosts
    chmod 600 /home/pbspy/.ssh/known_hosts
fi

# If PBSPY_SSH_KEY names a key file (basename only — tilde already stripped by
# ${HOME} expansion in the mount), copy it and tell pbspy-server to use it.
if [ -n "${PBSPY_SSH_KEY}" ]; then
    key_name=$(basename "${PBSPY_SSH_KEY}")
    if [ -f "/tmp/ssh_host/${key_name}" ]; then
        cp "/tmp/ssh_host/${key_name}" /home/pbspy/.ssh/pbspy_key
        chown pbspy:pbspy /home/pbspy/.ssh/pbspy_key
        chmod 600 /home/pbspy/.ssh/pbspy_key
        set -- "$@" --ssh-arg=-i --ssh-arg=/home/pbspy/.ssh/pbspy_key
    fi
fi

exec gosu pbspy "$@"
