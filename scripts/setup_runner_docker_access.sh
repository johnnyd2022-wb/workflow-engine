#!/bin/bash
# Run as root inside the existing deploy-target runner container after recreating it.
set -euo pipefail
runner_user=${1:-gitlab-runner}
if [ "$(id -u)" -ne 0 ]; then
    echo 'Run this setup as root inside the deployment runner container.' >&2
    exit 2
fi
if [ ! -S /var/run/docker.sock ]; then
    echo 'The deployment runner must have the host Docker socket mounted.' >&2
    exit 2
fi
id "$runner_user" >/dev/null
socket_gid=$(stat -c '%g' /var/run/docker.sock)
socket_group=$(getent group "$socket_gid" | cut -d: -f1 || true)
if [ -z "$socket_group" ]; then
    socket_group="workflow-docker-$socket_gid"
    groupadd --gid "$socket_gid" "$socket_group"
fi
case " $(id -G "$runner_user") " in
    *" $socket_gid "*) ;;
    *) usermod --append --groups "$socket_group" "$runner_user" ;;
esac
# A fresh su session picks up the new supplementary group without restarting jobs.
su -s /bin/sh -c 'DOCKER_API_VERSION=1.43 docker version --format "{{.Server.Version}}"' "$runner_user"
echo "Docker access verified for $runner_user through socket group $socket_group."
