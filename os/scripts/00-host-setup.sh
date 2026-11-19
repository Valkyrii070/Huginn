#!/usr/bin/env bash
# Install everything the build host needs. Run once on Ubuntu 24.04+ (26.04 recommended).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run as root: sudo $0" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    debootstrap ubuntu-keyring squashfs-tools xorriso mtools dosfstools \
    grub-common grub-pc-bin grub-efi-amd64-bin \
    qemu-system-x86 qemu-utils ovmf \
    python3 git rsync shellcheck

# debootstrap needs a script for the target suite; older hosts may not know "resolute" yet.
if [[ ! -e /usr/share/debootstrap/scripts/resolute ]]; then
    ln -s gutsy /usr/share/debootstrap/scripts/resolute
    echo "Added debootstrap script alias for 'resolute'."
fi

echo "Host ready. Next: sudo scripts/build.sh"
