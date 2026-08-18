#!/usr/bin/env sh
set -eu

install -d -m 0755 /etc/onec-attendance-agent
install -d -m 0755 /var/log/onec-attendance-agent
install -m 0755 onec-attendance-agent /usr/local/bin/onec-attendance-agent
install -m 0644 onec-attendance-agent.service /etc/systemd/system/onec-attendance-agent.service

if [ -f config.json ]; then
  install -m 0600 config.json /etc/onec-attendance-agent/config.json
  chown root:root /etc/onec-attendance-agent/config.json
fi

systemctl daemon-reload
systemctl enable onec-attendance-agent
systemctl restart onec-attendance-agent
