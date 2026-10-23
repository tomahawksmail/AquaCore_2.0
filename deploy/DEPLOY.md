# AquaCore: Nginx + Gunicorn + systemd (Linux)

Assumptions: Debian/Ubuntu/Armbian host; Gunicorn and Nginx on the **same host**; hostname `aquacore.example.com` is a placeholder. Flask handles authentication and sessions. This deploys the **web app only**; schedule automation is a separate process.

## Preparation

1. Create a dedicated non-login account and clone/copy AquaCore into `/opt/aquacore`, owned by that account.
2. Create its virtualenv and install requirements, including Gunicorn:

```sh
sudo apt update && sudo apt install -y python3-venv python3-pip nginx
sudo useradd --system --create-home --shell /usr/sbin/nologin aquacore || true
sudo mkdir -p /opt/aquacore
sudo chown -R aquacore:aquacore /opt/aquacore
# Clone/copy project files into /opt/aquacore BEFORE the following commands:
sudo -u aquacore python3 -m venv /opt/aquacore/.venv
sudo -u aquacore /opt/aquacore/.venv/bin/pip install -r /opt/aquacore/requirements.txt
sudo -u aquacore /opt/aquacore/.venv/bin/pip install 'gunicorn>=23,<25'
```

3. Provide the existing application DB and secret variables in `/opt/aquacore/.env` (readable only by aquacore) or in `/etc/aquacore/web.env` (permissions 600, root-owned). **Do not commit secrets.** Set a persistent `SECRET_KEY`; HTTPS deployment needs `COOKIE_SECURE=true`. The systemd unit sets this automatically.
4. Install and test the web service:

```sh
sudo cp /opt/aquacore/deploy/systemd/aquacore.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aquacore
sudo systemctl status aquacore --no-pager
curl -I http://127.0.0.1:5001/login
```

5. Obtain a TLS certificate for your real hostname. Adjust `server_name` and certificate paths in `deploy/nginx/aquacore.conf`. Certificate paths must exist **before** `nginx -t` succeeds. Use Certbot or another trusted certificate issuer; if staying LAN-only, use a valid internal certificate and restricted access. Do not expose plain HTTP externally.
6. Install Nginx site:

```sh
sudo cp /opt/aquacore/deploy/nginx/aquacore.conf /etc/nginx/sites-available/aquacore
sudo ln -s /etc/nginx/sites-available/aquacore /etc/nginx/sites-enabled/aquacore
sudo nginx -t && sudo systemctl reload nginx
```

7. Test https://YOUR-DOMAIN/login from your browser.

## Notes

- **Same-host** configuration: Gunicorn binds to localhost port 5001, which is not directly reachable from other computers.
- Only configure public DNS/port forwarding when HTTPS certificates, firewall restrictions, admin password, and database permissions are ready.
- Keep MariaDB inaccessible from the public Internet.
- Never start the built-in Flask dev server on the same port while Gunicorn runs.
- Hardware scheduler: if used, run `scheduler.py` under a *separate* process/service, exactly once per database, after verifying the GPIO controller responsibilities.
- Log inspection: `sudo journalctl -u aquacore -f`.
- Application variables: use the existing `.env` configuration. If using `EnvironmentFile`, ensure all required keys are present and the file is protected.
- When Nginx terminates HTTPS, Flask's `COOKIE_SECURE` flag protects session cookies on the browser-facing connection. Avoid directly exposing localhost Gunicorn through port forwarding.
