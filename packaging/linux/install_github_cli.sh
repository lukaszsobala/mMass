#!/usr/bin/env bash
# Install the GitHub CLI from its official RPM repository, for the CI build
# container (the runner has gh, the almalinux:9 image does not). Run as root.

set -euo pipefail

curl -sSfL -o /etc/yum.repos.d/gh-cli.repo https://cli.github.com/packages/rpm/gh-cli.repo
dnf install -y -q gh
