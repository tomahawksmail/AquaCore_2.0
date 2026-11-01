#!/usr/bin/env bash
# AquaCore native Armbian installer — STAGING/TESTING.
# Installs system packages, project, virtualenv, and systemd unit files.
# DOES NOT initialize or overwrite the database, configure credentials,
# enable Tailscale, start the scheduler, or activate any relay GPIO.
set -Eeuo pipefail
REPO="https://github.com/tomahawksmail/AquaCore_2.0.git"
DEST="/opt/aquacore"
fail(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }
info(){ printf '\n==> %s\n' "$*"; }
[[ "$(uname -s)" == Linux ]] || fail "Run on Orange Pi / Armbian Linux."
[[ "$(id -u)" -eq 0 ]] || fail "Run as root: sudo bash deploy/install_native.sh"
[[ -f /etc/os-release ]] || fail "Cannot detect Linux distribution."
. /etc/os-release
command -v apt-get >/dev/null || fail "This installer requires Debian/Ubuntu/Armbian apt."
info "Installing native dependencies"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y git curl ca-certificates \
  python3 python3-pip python3-venv python3-dev pkg-config build-essential \
  gpiod libgpiod-dev i2c-tools mariadb-server mariadb-client
if ! id aquacore >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin aquacore
fi
if [[ -e "$DEST/.git" ]]; then
  info "Existing checkout found; leaving source files unchanged. Update manually using git pull."
elif [[ -e "$DEST" ]]; then
  fail "$DEST already exists without a Git checkout; refusing to overwrite it."
else
  info "Cloning AquaCore to $DEST"
  git clone "$REPO" "$DEST"
fi
chown -R aquacore:aquacore "$DEST"
if [[ ! -f "$DEST/.venv/bin/python" ]]; then
  info "Creating Python virtual environment"
  runuser -u aquacore -- python3 -m venv "$DEST/.venv"
fi
info "Installing project Python dependencies"
runuser -u aquacore -- "$DEST/.venv/bin/python" -m pip install -r "$DEST/requirements.txt"
info "Installing systemd unit files (NOT starting or enabling them)"
for name in aquacore aquacore-telegram aquacore-scheduler aquacore-relays; do
  install -m 0644 "$DEST/deploy/systemd/$name.service" "/etc/systemd/system/$name.service"
done
systemctl daemon-reload
systemctl enable --now mariadb
info "Checking I2C devices"
ls /dev/i2c-* 2>/dev/null || true
info "Installation stage finished"
echo "Project: $DEST"
echo "Next: restore database, configure /etc/aquacore/web.env, then test sensors:"
echo "  i2cdetect -l"
echo "  $DEST/.venv/bin/python $DEST/sensorstest.py --bus BUS --once"
echo "Services were NOT started. Relays remain untouched."
echo "Follow deploy/NATIVE_ARMBIAN.md after testing sensors."
