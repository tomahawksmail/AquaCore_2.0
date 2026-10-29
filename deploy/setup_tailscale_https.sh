#!/usr/bin/env bash
# STATUS: IN PRODUCTION / TESTING — not yet verified on the target Orange Pi.
# Experimental deployment script. Review output and validate HTTPS before relying on it.
set -Eeuo pipefail
EXPECTED="aquacore.orangepi.ts.net"
TARGET="http://127.0.0.1:5001"
fail(){ echo "ERROR: $*" >&2; exit 1; }
[[ "$(uname -s)" == "Linux" ]] || fail "Run on Orange Pi Linux."
for binary in sudo curl python3; do command -v "$binary" >/dev/null || fail "Missing $binary"; done

echo "Checking AquaCore on $TARGET"
curl --noproxy '*' -fsS --max-time 10 -o /dev/null "$TARGET" || fail "AquaCore backend is unreachable; start Gunicorn on port 5001 first."

if ! command -v tailscale >/dev/null; then
  echo "Installing Tailscale"
  curl -fsSL https://tailscale.com/install.sh -o /tmp/aquacore-install-tailscale.sh
  sudo sh /tmp/aquacore-install-tailscale.sh
  rm -f /tmp/aquacore-install-tailscale.sh
fi

sudo systemctl enable --now tailscaled
sudo tailscale set --hostname=aquacore
if ! sudo tailscale status >/dev/null 2>&1; then
  echo "Authenticate with your Tailscale account:"
  sudo tailscale up
fi

ACTUAL="$(sudo tailscale status --json | python3 -c 'import json,sys; print((json.load(sys.stdin).get("Self") or {}).get("DNSName","").rstrip(".").lower())')"
[[ -n "$ACTUAL" ]] || fail "MagicDNS hostname missing. Enable MagicDNS in https://login.tailscale.com/admin/dns then retry."
[[ "$ACTUAL" == "$EXPECTED" ]] || fail "Actual assigned hostname is $ACTUAL, not $EXPECTED. Set up the orangepi.ts.net tailnet suffix in Tailscale admin. No Serve configuration changed."

echo "Configuring private HTTPS (not Funnel)"
echo "If Tailscale asks for HTTPS certificates permission, approve it in your browser."
sudo tailscale serve --bg --https=443 "$TARGET" || fail "Serve failed: enable MagicDNS and HTTPS certificates in the Tailscale admin DNS settings."
sudo tailscale serve status
echo "Success: https://$EXPECTED"
echo "Connect your client PC/phone to the same Tailscale network to open it."
