#!/usr/bin/env bash
# Boot the newest ISO in QEMU.  scripts/test-qemu.sh [--bios] [path/to.iso]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIRMWARE=(-bios /usr/share/ovmf/OVMF.fd)
if [[ "${1:-}" == "--bios" ]]; then FIRMWARE=(); shift; fi
ISO="${1:-$(find "$ROOT/out" -name '*.iso' -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)}"
[[ -f "$ISO" ]] || { echo "No ISO found. Build one first." >&2; exit 1; }
ACCEL=(-accel tcg)
[[ -w /dev/kvm ]] && ACCEL=(-enable-kvm -cpu host)
exec qemu-system-x86_64 "${ACCEL[@]}" -m 4096 -smp 4 "${FIRMWARE[@]}" \
    -device virtio-vga-gl -display gtk,gl=on \
    -device virtio-net-pci,netdev=n0 -netdev user,id=n0 \
    -audiodev pa,id=snd -device ich9-intel-hda -device hda-duplex,audiodev=snd \
    -cdrom "$ISO" -boot d
