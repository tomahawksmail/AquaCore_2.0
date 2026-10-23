"""Gunicorn settings for a small Linux/Orange Pi installation."""
import os

bind = os.getenv("AQUACORE_BIND", "127.0.0.1:5001")
worker_class = "gthread"
workers = int(os.getenv("AQUACORE_WORKERS", "2"))
threads = int(os.getenv("AQUACORE_THREADS", "2"))
timeout = 30
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
capture_output = True
