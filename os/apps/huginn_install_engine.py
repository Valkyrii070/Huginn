"""Huginn OS's installer engine: puts Huginn OS on a disk. Runs as root (the Installer app starts it through pkexec,
as /usr/libexec/huginn-install-engine), reads one JSON plan on stdin (passwords included, so they never touch a
disk) and writes one JSON line per step to stdout: {"step", "label", "fraction"}, then {"done": true} or
{"error": "...", "log": "..."}.

    the plan     {"mode": "erase" | "free" | "shrink" | "manual", "disk": "/dev/sda", "firmware": "uefi" | "bios",
                  "removable": false (a USB drive: GRUB only in its own fallback place, the computer's boot list untouched),
                  "shrinkPart": "/dev/sda3", "keepBytes": 200e9 (shrink: Windows' partition keeps this much; Huginn OS
                  goes in the room made after it),
                  "encrypt": false, "passphrase": "", "root": "/dev/sda3", "efi": "/dev/sda1", "formatEfi": false,
                  "hostname": "…", "user": {"name", "realName", "password", "autologin"}, "timezone": "Europe/Oslo",
                  "locale": "nb_NO.UTF-8", "keyboard": {"layout": "no", "variant": ""}, "kernelArgs": ""}
    the steps    partition (sfdisk), format (FAT32 for EFI, ext4, LUKS2 when encrypted, with a plain /boot beside
                 it), copy the system (unsquashfs from the live medium), the kernel (casper keeps it beside the
                 squashfs), settings (hostname, fstab, crypttab, locale, keyboard, time zone, the person, sign-in),
                 tidy up the live session's pieces, initramfs and GRUB (UEFI with shim for Secure Boot, or BIOS),
                 a swap file, then unmount.

Each disk action goes through Engine.run(), so tests can run the same engine against disk images.

    --probe-ntfs PART   (root) how far Windows' partition can shrink: one JSON line {"size", "min", "problem"}
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

TARGET = Path("/target")
LOG = Path("/var/log/huginn-installer.log")
MAPPER = "huginn"                     # the unlocked disk is /dev/mapper/huginn ("Please unlock disk huginn")
BIOS_GRUB = "21686148-6449-6E6F-744E-656564454649"
LIVE_ONLY = ["usr/share/applications/huginn-installer.desktop", "usr/share/polkit-1/actions/org.huginn.installer.policy",
             "etc/polkit-1/rules.d/49-huginn-live-installer.rules", "usr/libexec/huginn-install-engine", "etc/casper.conf"]
WEIGHTS = [("disk", "Preparing the disk", 0.03), ("format", "Making the disk ready", 0.04), ("copy", "Copying Huginn OS", 0.68),
           ("kernel", "Copying the kernel", 0.01), ("settings", "Setting it up for you", 0.06), ("boot", "Making it start", 0.15),
           ("finish", "Finishing", 0.03)]


class Failed(Exception):
    pass


def live_medium() -> Path:
    """Where the live system's squashfs and kernel are (casper mounts the ISO at /cdrom)."""
    for root in (Path("/cdrom"), Path("/run/live/medium"), Path("/media/cdrom")):
        if (root / "casper" / "filesystem.squashfs").exists():
            return root
    return Path("/cdrom")


def part_name(disk: str, n: int) -> str:
    """/dev/sda + 2 → /dev/sda2; /dev/nvme0n1 + 2 → /dev/nvme0n1p2 (a disk name ending in a digit takes a "p")."""
    return f"{disk}p{n}" if disk[-1].isdigit() else f"{disk}{n}"


def layout(firmware: str, encrypt: bool) -> list:
    """The partitions an erased disk gets, in order: [(role, size in MiB or 0 for the rest, sfdisk type)]."""
    parts = [("efi", 512, "U")] if firmware == "uefi" else [("bios", 1, BIOS_GRUB)]
    if encrypt:
        parts.append(("boot", 1536, "L"))
    parts.append(("root", 0, "L"))
    return parts


def sfdisk_script(parts: list, start: int = 0) -> str:
    """An sfdisk script: GPT when starting fresh (start=0), otherwise partitions appended from sector `start`."""
    names = {"efi": "EFI system", "bios": "BIOS boot", "boot": "Huginn OS boot", "root": "Huginn OS"}
    lines = ["label: gpt"] if not start else []
    for k, (role, mib, ptype) in enumerate(parts):
        bits = []
        if start and k == 0:
            bits.append(f"start={start}")
        if mib:
            bits.append(f"size={mib}MiB")
        bits += [f"type={ptype}", f'name="{names[role]}"']
        lines.append(", ".join(bits))
    return "\n".join(lines) + "\n"


def fstab(root_uuid: str, efi_uuid: str = "", boot_uuid: str = "", encrypted: bool = False, swap: bool = True) -> str:
    rows = ["# /etc/fstab: the disks Huginn OS mounts at start-up (written by the installer).",
            "# <file system>  <mount point>  <type>  <options>  <dump>  <pass>"]
    rows.append(f"{'/dev/mapper/' + MAPPER if encrypted else 'UUID=' + root_uuid}  /  ext4  errors=remount-ro  0  1")
    if boot_uuid:
        rows.append(f"UUID={boot_uuid}  /boot  ext4  defaults  0  2")
    if efi_uuid:
        rows.append(f"UUID={efi_uuid}  /boot/efi  vfat  umask=0077  0  1")
    if swap:
        rows.append("/swapfile  none  swap  sw  0  0")
    return "\n".join(rows) + "\n"


def crypttab(luks_uuid: str) -> str:
    return f"# Unlocked at start-up with the password asked on the boot screen.\n{MAPPER}  UUID={luks_uuid}  none  luks,discard\n"


def good_hostname(name: str) -> str:
    name = re.sub(r"[^a-z0-9-]+", "-", (name or "").lower()).strip("-")[:63]
    return name or "huginn"


def good_username(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", name or "")) and name not in ("root", "daemon", "bin", "sys", "huginn-live")


def check_plan(p: dict) -> list:
    """What's wrong with a plan (empty when it's fine)."""
    problems = []
    if p.get("mode") not in ("erase", "free", "shrink", "manual"):
        problems.append("No way to use the disk was chosen.")
    if p.get("mode") in ("erase", "free", "shrink") and not str(p.get("disk", "")).startswith("/"):    # a disk, or a disk image
        problems.append("No disk was chosen.")
    if p.get("mode") == "shrink":
        if not str(p.get("shrinkPart", "")).startswith("/"):
            problems.append("No partition to make room in was chosen.")
        if int(p.get("keepBytes") or 0) <= 0:
            problems.append("How much room to leave Windows wasn't chosen.")
    if p.get("mode") == "manual":
        if not str(p.get("root", "")).startswith("/"):
            problems.append("No partition for Huginn OS was chosen.")
        if p.get("firmware") == "uefi" and not str(p.get("efi", "")).startswith("/"):
            problems.append("No EFI system partition was chosen.")
        if p.get("encrypt"):
            problems.append("Encryption needs the installer to make the partitions (erase, or use free space).")
    if p.get("encrypt") and len(p.get("passphrase", "")) < 8:
        problems.append("The disk password is too short (8 characters at least).")
    u = p.get("user") or {}
    if not good_username(u.get("name", "")):
        problems.append("The user name can only have small letters, digits, - and _, and must start with a letter.")
    if not u.get("password"):
        problems.append("A password is needed.")
    return problems


class Engine:
    def __init__(self, plan: dict, emit=None, target: Path = TARGET, medium: Path = None, log: Path = LOG):
        self.p = plan
        self.t = Path(target)
        self.medium = Path(medium) if medium else live_medium()
        self.emit = emit or (lambda d: (sys.stdout.write(json.dumps(d) + "\n"), sys.stdout.flush()))
        self.logf = log
        self.lines = []
        self.mounts = []
        self.opened = False
        self.dev = {}                 # role → device: efi, bios, boot, root (the partition), rootfs (what's formatted ext4)
        self.version = ""
        self.reuse_efi = False        # sharing the disk's EFI partition (with Windows, say): it's not formatted

    # ---------------------------------------------------------------- running things
    def log(self, text: str) -> None:
        for secret in (self.p.get("passphrase"), (self.p.get("user") or {}).get("password")):
            if secret:
                text = text.replace(secret, "••••")
        self.lines.append(text)
        try:
            with open(self.logf, "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError:
            pass

    def run(self, cmd: list, stdin: str = None, chroot: bool = False, check: bool = True, timeout: int = 3600) -> str:
        if chroot:
            cmd = ["chroot", str(self.t)] + cmd
        self.log("$ " + " ".join(cmd))
        env = dict(os.environ, LC_ALL="C", DEBIAN_FRONTEND="noninteractive")
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout, env=env)
        out = (r.stdout + r.stderr).strip()
        if out:
            self.log(out[-4000:])
        if check and r.returncode != 0:
            said = [l.strip() for l in (r.stderr or r.stdout).splitlines() if l.strip() and not l.strip().startswith("dmesg(1)")]
            if Path(cmd[0]).name == "ntfsresize":
                raise Failed(why_ntfs(out))
            raise Failed(f"{Path(cmd[2] if chroot else cmd[0]).name} failed: {said[-1] if said else 'exit ' + str(r.returncode)}")
        return r.stdout

    def step(self, key: str, within: float = 0.0, note: str = "") -> None:
        base = 0.0
        for k, label, w in WEIGHTS:
            if k == key:
                self.emit({"step": key, "label": label, "fraction": round(base + w * within, 4), "note": note})
                return
            base += w

    def part_path(self, disk: str, n: int) -> str:
        """The device for partition n of a disk, once the kernel has it (waiting for udev)."""
        path = part_name(disk, n)
        for _ in range(100):
            if Path(path).exists():
                return path
            if shutil.which("udevadm"):
                subprocess.run(["udevadm", "settle", "--timeout=2"], capture_output=True)
            time.sleep(0.1)
        raise Failed(f"The new partition {path} didn't appear")

    def reread(self, disk: str) -> None:
        if shutil.which("partx"):
            subprocess.run(["partx", "-u", disk], capture_output=True)
        if shutil.which("udevadm"):
            subprocess.run(["udevadm", "settle", "--timeout=10"], capture_output=True)

    def uuid(self, dev: str) -> str:
        return self.run(["blkid", "-s", "UUID", "-o", "value", dev]).strip()

    def mount(self, what: str, where: Path, *opts) -> None:
        where.mkdir(parents=True, exist_ok=True)
        self.run(["mount", *opts, what, str(where)])
        self.mounts.append(where)

    # ---------------------------------------------------------------- the steps
    def partition(self) -> None:
        p, disk = self.p, self.p.get("disk", "")
        self.step("disk", 0, "")
        if p["mode"] == "manual":
            self.dev["root"] = p["root"]
            if p.get("firmware") == "uefi":
                self.dev["efi"] = p["efi"]
            return
        parts = layout(p.get("firmware", "uefi"), bool(p.get("encrypt")))
        if p["mode"] == "erase":
            self.unmount_disk(disk)                               # a USB drive the live session opened, say
        if p["mode"] == "shrink":
            p["freeStart"] = self.shrink(disk, p["shrinkPart"], int(p["keepBytes"]))
        if p["mode"] in ("free", "shrink"):
            have = self.existing_esp(disk) if p.get("firmware") == "uefi" else 0
            if have:                                              # share the disk's EFI partition (Windows' too)
                self.dev["efi"], self.reuse_efi = self.part_path(disk, have), True
                parts = [x for x in parts if x[0] != "efi"]
            before = self.partition_numbers(disk)
            if not p.get("freeStart"):
                raise Failed("No free space was chosen")
            self.run(["sfdisk", "--append", "--no-reread", disk], stdin=sfdisk_script(parts, int(p["freeStart"])), timeout=120)
            after = self.partition_numbers(disk)
            numbers = [n for n in after if n not in before]
            if len(numbers) != len(parts):
                raise Failed("The new partitions didn't come out as planned")
        else:
            self.run(["wipefs", "--all", "--force", disk], check=False)
            self.run(["sfdisk", "--wipe", "always", "--wipe-partitions", "always", "--no-reread", disk], stdin=sfdisk_script(parts), timeout=120)
            numbers = list(range(1, len(parts) + 1))
        self.reread(disk)
        for (role, _mib, _t), n in zip(parts, numbers):
            self.dev[role] = self.part_path(disk, n)
        self.step("disk", 1)

    def unmount_disk(self, disk: str) -> None:
        """Everything on the disk the live session has open (a USB drive opens itself when plugged in) is closed."""
        try:
            data = json.loads(self.run(["lsblk", "-J", "-o", "PATH,MOUNTPOINTS,FSTYPE", disk], check=False) or "{}")
        except ValueError:
            return
        def walk(nodes):
            for n in nodes or []:
                yield n
                yield from walk(n.get("children"))
        for n in walk(data.get("blockdevices")):
            if n.get("fstype") == "swap":
                self.run(["swapoff", n["path"]], check=False)
            for m in n.get("mountpoints") or []:
                if m and m not in ("/", "/cdrom", "/boot", "/boot/efi") and not m.startswith("/run/live"):
                    self.run(["umount", "-l", m], check=False)

    def shrink(self, disk: str, part: str, keep: int) -> int:
        """Make room after Windows: its NTFS partition is shrunk to `keep` bytes (ntfsresize moves what it must), then
        the partition itself. Returns the first sector of the room made. Nothing is changed unless ntfsresize says
        first that it can do it."""
        self.step("disk", 0, "Checking Windows' partition")
        self.unmount_disk(part)
        self.run(["ntfsresize", "--no-action", "--size", str(keep), part], timeout=900)   # (refuses when it can't: see why_ntfs)
        self.step("disk", 0.2, "Making room beside Windows (this can take a while)")
        self.run(["ntfsresize", "--size", str(keep), part], stdin="y\n", timeout=6 * 3600)
        n = int(re.search(r"(\d+)$", part).group(1))
        sectors = ((keep + (1 << 20)) // 512 + 2047) // 2048 * 2048         # the filesystem, a margin, whole MiB
        self.run(["sfdisk", "--no-reread", "-N", str(n), disk], stdin=f", {sectors}\n", timeout=120)
        self.reread(disk)
        data = json.loads(self.run(["sfdisk", "--json", disk]))
        mine = next(q for q in data["partitiontable"]["partitions"] if q["node"].endswith(str(n)) and re.search(r"(\d+)$", q["node"]).group(1) == str(n))
        start = mine["start"] + mine["size"]
        return (start + 2047) // 2048 * 2048

    def existing_esp(self, disk: str) -> int:
        """The number of the disk's EFI system partition, 0 when it has none."""
        try:
            data = json.loads(self.run(["sfdisk", "--json", disk]))
        except (Failed, ValueError):
            return 0
        for part in data.get("partitiontable", {}).get("partitions", []):
            if part.get("type", "").upper() in ("C12A7328-F81F-11D2-BA4B-00A0C93EC93B", "EF"):
                return int(re.search(r"(\d+)$", part["node"]).group(1))
        return 0

    def partition_numbers(self, disk: str) -> list:
        """The disk's partition numbers, in the order they sit on the disk."""
        try:
            data = json.loads(self.run(["sfdisk", "--json", disk]))
        except (Failed, ValueError):
            return []
        nodes = sorted(data.get("partitiontable", {}).get("partitions", []), key=lambda q: q["start"])
        return [int(re.search(r"(\d+)$", q["node"]).group(1)) for q in nodes]

    def format(self) -> None:
        p = self.p
        self.step("format", 0)
        if "efi" in self.dev and (p["mode"] == "erase" or (p["mode"] == "free" and not self.reuse_efi) or p.get("formatEfi")):
            self.run(["mkfs.fat", "-F", "32", "-n", "EFI", self.dev["efi"]])
        if "boot" in self.dev:
            self.run(["mkfs.ext4", "-F", "-q", "-L", "boot", self.dev["boot"]])
        root = self.dev["root"]
        if p.get("encrypt"):
            self.run(["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", "--label", "Huginn OS", "--key-file=-", root], stdin=p["passphrase"], timeout=600)
            self.run(["cryptsetup", "open", "--key-file=-", root, MAPPER], stdin=p["passphrase"])
            self.opened = True
            self.dev["rootfs"] = f"/dev/mapper/{MAPPER}"
        else:
            self.dev["rootfs"] = root
        self.run(["mkfs.ext4", "-F", "-q", "-L", "Huginn OS", self.dev["rootfs"]], timeout=1800)
        self.reread(p.get("disk", ""))                            # udev names the new file systems (by-uuid, for GRUB)
        self.step("format", 1)

    def mount_target(self) -> None:
        """Huginn OS's partition (and /boot); the EFI partition goes on after the copy (FAT can't take Linux owners)."""
        self.mount(self.dev["rootfs"], self.t)
        if "boot" in self.dev:
            self.mount(self.dev["boot"], self.t / "boot")

    def copy(self) -> None:
        sq = self.medium / "casper" / "filesystem.squashfs"
        if not sq.exists():
            raise Failed(f"The live system's files aren't at {sq}")
        self.step("copy", 0, "")
        cmd = ["unsquashfs", "-f", "-d", str(self.t), "-percentage", str(sq)]
        self.log("$ " + " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        last = -1
        tail = []
        for line in proc.stdout:
            line = line.strip()
            if line.isdigit():
                pct = int(line)
                if pct != last:
                    last = pct
                    self.step("copy", pct / 100.0, f"{pct}%")
            elif line:
                tail = (tail + [line])[-20:]
        if proc.wait() != 0:
            self.log("\n".join(tail))
            raise Failed("Copying the system stopped: " + (tail[-1] if tail else "unsquashfs failed"))
        self.step("copy", 1)

    def kernel(self) -> None:
        self.step("kernel", 0)
        mods = sorted((self.t / "lib" / "modules").glob("*")) if (self.t / "lib" / "modules").is_dir() else []
        mods = mods or sorted((self.t / "usr" / "lib" / "modules").glob("*"))
        if not mods:
            raise Failed("The copied system has no kernel modules")
        self.version = mods[-1].name
        boot = self.t / "boot"
        boot.mkdir(exist_ok=True)
        kernel = boot / f"vmlinuz-{self.version}"
        if not kernel.exists():                                   # casper keeps the kernel beside the squashfs
            src = self.medium / "casper" / "vmlinuz"
            if not src.exists():
                raise Failed(f"The kernel isn't at {src}")
            shutil.copy2(src, kernel)
        for link, name in (("vmlinuz", kernel.name), ("initrd.img", f"initrd.img-{self.version}")):
            q = boot / link
            if q.is_symlink() or q.exists():
                q.unlink()
            q.symlink_to(name)
        self.step("kernel", 1)

    def bind_system(self) -> None:
        if "efi" in self.dev:
            self.mount(self.dev["efi"], self.t / "boot" / "efi")
        for what, where, opts in (("/dev", "dev", ["--bind"]), ("devpts", "dev/pts", ["-t", "devpts"]), ("proc", "proc", ["-t", "proc"]),
                                  ("sysfs", "sys", ["-t", "sysfs"]), ("/run", "run", ["--bind"])):
            self.mount(what, self.t / where, *opts)
        efivars = Path("/sys/firmware/efi/efivars")
        if self.p.get("firmware") == "uefi" and efivars.is_dir() and any(efivars.iterdir()):
            self.mount("efivarfs", self.t / "sys/firmware/efi/efivars", "-t", "efivarfs")

    def settings(self) -> None:
        p, t = self.p, self.t
        self.step("settings", 0)
        root_uuid = self.uuid(self.dev["rootfs"]) if not p.get("encrypt") else ""
        efi_uuid = self.uuid(self.dev["efi"]) if "efi" in self.dev else ""
        boot_uuid = self.uuid(self.dev["boot"]) if "boot" in self.dev else ""
        (t / "etc/fstab").write_text(fstab(root_uuid, efi_uuid, boot_uuid, bool(p.get("encrypt"))))
        if p.get("encrypt"):
            (t / "etc/crypttab").write_text(crypttab(self.uuid(self.dev["root"])))
        host = good_hostname(p.get("hostname", ""))
        (t / "etc/hostname").write_text(host + "\n")
        hosts = (t / "etc/hosts").read_text() if (t / "etc/hosts").exists() else "127.0.0.1 localhost\n"
        hosts = re.sub(r"^127\.0\.1\.1\s.*\n?", "", hosts, flags=re.M)
        (t / "etc/hosts").write_text(hosts.replace("127.0.0.1 localhost", f"127.0.0.1 localhost\n127.0.1.1 {host}", 1) if "127.0.0.1 localhost" in hosts
                                     else f"127.0.0.1 localhost\n127.0.1.1 {host}\n" + hosts)
        # the time zone
        zone = p.get("timezone") or "UTC"
        if (t / "usr/share/zoneinfo" / zone).exists():
            lt = t / "etc/localtime"
            if lt.exists() or lt.is_symlink():
                lt.unlink()
            lt.symlink_to(f"/usr/share/zoneinfo/{zone}")
            (t / "etc/timezone").write_text(zone + "\n")
        # language
        loc = p.get("locale") or "en_US.UTF-8"
        (t / "etc/default/locale").write_text(f"LANG={loc}\n")
        gen = t / "etc/locale.gen"
        if gen.exists() and loc not in ("C.UTF-8",):
            txt = gen.read_text()
            txt = re.sub(rf"^#\s*({re.escape(loc)}\s)", r"\1", txt, flags=re.M)
            if not re.search(rf"^{re.escape(loc)}\s", txt, flags=re.M):
                txt += f"{loc} UTF-8\n"
            gen.write_text(txt)
        self.step("settings", 0.2)
        self.run(["locale-gen", loc], chroot=True, check=False, timeout=600)
        # the keyboard, for the console, the sign-in screen and the desktop
        kb = p.get("keyboard") or {}
        lay, var = re.sub(r"[^a-z0-9_-]", "", kb.get("layout", "us")) or "us", re.sub(r"[^A-Za-z0-9_-]", "", kb.get("variant", ""))
        (t / "etc/default").mkdir(parents=True, exist_ok=True)
        (t / "etc/default/keyboard").write_text(f'XKBMODEL="pc105"\nXKBLAYOUT="{lay}"\nXKBVARIANT="{var}"\nXKBOPTIONS=""\n\nBACKSPACE="guess"\n')
        x11 = t / "etc/X11/xorg.conf.d"
        x11.mkdir(parents=True, exist_ok=True)
        (x11 / "00-keyboard.conf").write_text('Section "InputClass"\n    Identifier "system-keyboard"\n    MatchIsKeyboard "on"\n'
                                              f'    Option "XkbLayout" "{lay}"\n' + (f'    Option "XkbVariant" "{var}"\n' if var else "") + "EndSection\n")
        self.step("settings", 0.4)
        # the person
        u = p["user"]
        groups = self.groups(["sudo", "adm", "cdrom", "dip", "plugdev", "lpadmin", "users", "audio", "video", "netdev", "bluetooth", "scanner"])
        self.run(["useradd", "--create-home", "--shell", "/bin/bash", "--comment", (u.get("realName") or u["name"]).replace(":", " "),
                  "--groups", ",".join(groups), u["name"]], chroot=True)
        self.run(["chpasswd"], stdin=f"{u['name']}:{u['password']}\n", chroot=True)
        home = t / "home" / u["name"]
        (home / ".config").mkdir(parents=True, exist_ok=True)
        (home / ".config" / "kxkbrc").write_text(f"[Layout]\nLayoutList={lay}\nVariantList={var}\nUse=true\n")
        self.run(["chown", "-R", f"{u['name']}:{u['name']}", f"/home/{u['name']}/.config"], chroot=True)
        sddm = t / "etc/sddm.conf.d"
        sddm.mkdir(parents=True, exist_ok=True)
        auto = sddm / "20-autologin.conf"
        if u.get("autologin"):
            auto.write_text(f"[Autologin]\nUser={u['name']}\nSession=huginn\nRelogin=false\n")
        elif auto.exists():
            auto.unlink()
        live = t / "etc/sddm.conf"                               # casper's live sign-in setting, if it got copied
        if live.exists() and "Autologin" in live.read_text():
            live.unlink()
        self.step("settings", 0.7)
        # the live session's own pieces don't belong on the installed system
        for rel in LIVE_ONLY:
            q = t / rel
            if q.exists() or q.is_symlink():
                q.unlink()
        self.run(["apt-get", "-y", "purge", "casper"], chroot=True, check=False, timeout=900)
        for f in (t / "etc/machine-id", t / "var/lib/dbus/machine-id"):
            if f.exists():
                f.write_text("") if f.name == "machine-id" and f.parent.name == "etc" else f.unlink()
        self.swapfile()
        self.step("settings", 1)

    def groups(self, wanted: list) -> list:
        names = {line.split(":")[0] for line in (self.t / "etc/group").read_text().splitlines() if line}
        return [g for g in wanted if g in names]

    def swapfile(self) -> None:
        try:
            ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (ValueError, OSError):
            ram = 4 << 30
        gib = max(1, min(4, round(ram / (1 << 30))))
        free = shutil.disk_usage(self.t).free
        while gib > 1 and free < (gib << 30) * 4:                # a swap file never takes more than a quarter of what's free
            gib -= 1
        if free < (gib << 30) * 4:                                # a small disk keeps its space
            text = (self.t / "etc/fstab").read_text().replace("/swapfile  none  swap  sw  0  0\n", "")
            (self.t / "etc/fstab").write_text(text)
            return
        sw = self.t / "swapfile"
        self.run(["fallocate", "-l", f"{gib}G", str(sw)])
        os.chmod(sw, 0o600)
        self.run(["mkswap", str(sw)])

    def bootloader(self) -> None:
        p, t = self.p, self.t
        self.step("boot", 0)
        grub = t / "etc/default/grub"
        if not grub.exists():
            grub.parent.mkdir(parents=True, exist_ok=True)
            grub.write_text('# GRUB, as the installer set it up. Run update-grub after changing it.\nGRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX=""\n')
        if grub.exists():
            g = grub.read_text()
            want = {"GRUB_DISTRIBUTOR": '"Huginn OS"', "GRUB_CMDLINE_LINUX_DEFAULT": f'"quiet splash{(" " + p["kernelArgs"]) if p.get("kernelArgs") else ""}"',
                    "GRUB_TIMEOUT_STYLE": "hidden" if p["mode"] == "erase" else "menu", "GRUB_TIMEOUT": "0" if p["mode"] == "erase" else "5",
                    "GRUB_DISABLE_OS_PROBER": "true" if p["mode"] == "erase" else "false"}
            for k, v in want.items():
                g, n = re.subn(rf"^#?\s*{k}=.*$", f"{k}={v}", g, flags=re.M)
                if not n:
                    g += f"{k}={v}\n"
            grub.write_text(g)
        self.run(["update-initramfs", "-c", "-k", self.version] if not (t / f"boot/initrd.img-{self.version}").exists()
                 else ["update-initramfs", "-u", "-k", self.version], chroot=True, timeout=1800)
        self.step("boot", 0.4)
        # GRUB's package for this computer's firmware (it keeps GRUB up to date later); the ISO carries both
        pkg = "grub-efi-amd64" if p.get("firmware") == "uefi" else "grub-pc"
        debs = sorted((self.medium / "pool").glob(f"{pkg}_*.deb")) if (self.medium / "pool").is_dir() else []
        if debs:
            shutil.copy2(debs[-1], t / "tmp" / debs[-1].name)
            if pkg == "grub-pc":
                self.run(["debconf-set-selections"], stdin=f"grub-pc grub-pc/install_devices multiselect {p['disk']}\n", chroot=True, check=False)
            self.run(["dpkg", "-i", f"/tmp/{debs[-1].name}"], chroot=True, check=False, timeout=600)
            (t / "tmp" / debs[-1].name).unlink(missing_ok=True)
        else:
            self.log(f"(no {pkg} package on the medium: GRUB is installed, its package isn't)")
        self.step("boot", 0.5)
        if p.get("firmware") == "uefi":
            nvram = os.path.ismount(t / "sys/firmware/efi/efivars")
            base = ["grub-install", "--target=x86_64-efi", "--efi-directory=/boot/efi", "--bootloader-id=ubuntu", "--recheck"]
            if (t / "usr/lib/shim").is_dir() or (t / "usr/lib/grub/x86_64-efi-signed").is_dir():
                base.append("--uefi-secure-boot")
            if p.get("removable"):
                # A USB drive: GRUB goes only where any computer looks on a drive it's given (EFI/BOOT/BOOTX64.EFI),
                # and the computer's own list of things to start (and Windows on its disk) are left as they were.
                self.run(base + ["--removable", "--no-nvram"], chroot=True, timeout=600)
            else:
                self.run(base + ([] if nvram else ["--no-nvram"]), chroot=True, timeout=600)
            # Firmware that forgets its boot entries starts EFI/BOOT/BOOTX64.EFI. On a disk of its own Huginn OS puts
            # itself there too (GRUB may already have); beside another system, that system's fallback is left alone.
            if p["mode"] == "erase" and not p.get("removable") and not (t / "boot/efi/EFI/BOOT/BOOTX64.EFI").exists():
                self.run(base + ["--removable", "--no-nvram"], chroot=True, timeout=600)
        else:
            self.run(["grub-install", "--target=i386-pc", "--recheck", p["disk"]], chroot=True, timeout=600)
        self.run(["update-grub"], chroot=True, timeout=900)
        self.step("boot", 1)

    def unmount(self) -> None:
        for where in reversed(self.mounts):
            subprocess.run(["umount", "-l" if where.name in ("dev", "run", "sys", "proc") else "-R", str(where)], capture_output=True)
        self.mounts = []
        if self.opened:
            subprocess.run(["cryptsetup", "close", MAPPER], capture_output=True)
            self.opened = False
        subprocess.run(["sync"])

    def save_log(self) -> None:
        try:
            dest = self.t / "var/log/huginn-installer.log"
            if dest.parent.is_dir():
                dest.write_text("\n".join(self.lines) + "\n")
        except OSError:
            pass

    def install(self) -> bool:
        problems = check_plan(self.p)
        if problems:
            self.emit({"error": " ".join(problems), "log": ""})
            return False
        try:
            self.partition()
            self.format()
            self.mount_target()
            self.copy()
            self.kernel()
            self.bind_system()
            self.settings()
            self.bootloader()
            self.step("finish", 0)
            self.save_log()
            self.unmount()
            self.step("finish", 1)
            self.emit({"done": True, "hostname": good_hostname(self.p.get("hostname", ""))})
            return True
        except (Failed, OSError, subprocess.SubprocessError, KeyError, ValueError) as err:
            self.log(f"stopped: {err}")
            self.save_log()
            self.unmount()
            self.emit({"error": str(err), "log": "\n".join(self.lines[-40:])})
            return False


def why_ntfs(text: str) -> str:
    """ntfsresize's refusals, said so a person knows what to do in Windows."""
    low = text.lower()
    if "hibernat" in low:
        return ("Windows didn't shut down completely (Fast Startup). Start Windows, hold Shift while you choose Shut Down "
                "(or turn off Fast Startup in Power Options), then try again.")
    if "chkdsk" in low or "inconsistent" in low or "dirty" in low or "corrupt" in low:
        return "Windows wants to check this disk first. In Windows, run \u201cchkdsk C: /f\u201d and restart, then try again."
    if "bitlocker" in low or "encrypted" in low:
        return "This Windows partition is locked with BitLocker. Turn BitLocker off (or shrink it in Windows) first."
    line = [l for l in text.splitlines() if l.strip()]
    return line[-1].strip() if line else "Windows' partition couldn't be read."


def probe_ntfs(part: str) -> dict:
    r = subprocess.run(["ntfsresize", "--info", "--no-progress-bar", part], capture_output=True, text=True, timeout=900,
                       env=dict(os.environ, LC_ALL="C"))
    out = r.stdout + r.stderr
    size = re.search(r"Current volume size:\s*(\d+) bytes", out)
    least = re.search(r"You might resize at (\d+) bytes", out)
    if r.returncode != 0 or not size or not least:
        return {"size": int(size.group(1)) if size else 0, "min": 0, "problem": why_ntfs(out)}
    return {"size": int(size.group(1)), "min": int(least.group(1)), "problem": ""}


def main() -> int:
    if os.geteuid() != 0:
        print(json.dumps({"error": "The installer engine needs to run as root."}))
        return 1
    if len(sys.argv) == 3 and sys.argv[1] == "--probe-ntfs" and re.fullmatch(r"/dev/[A-Za-z0-9/_-]+", sys.argv[2]):
        print(json.dumps(probe_ntfs(sys.argv[2])))
        return 0
    try:
        plan = json.loads(sys.stdin.read())
    except ValueError:
        print(json.dumps({"error": "The plan couldn't be read."}))
        return 1
    LOG.parent.mkdir(parents=True, exist_ok=True)
    return 0 if Engine(plan).install() else 1


if __name__ == "__main__":
    sys.exit(main())
