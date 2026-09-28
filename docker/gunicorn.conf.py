"""Gunicorn settings for the production web container. Override with env vars."""

import os

bind = "0.0.0.0:8000"
# WEB_CONCURRENCY is also read by gunicorn itself; 3 suits a small 2-CPU host.
workers = int(os.environ.get("WEB_CONCURRENCY", "3"))
# Uploads (up to MATERIAL_MAX_UPLOAD_MB) must finish within this; heavy work runs
# in the background worker, not in requests.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 30
# Recycle workers now and then to keep memory in check.
max_requests = 1000
max_requests_jitter = 100
# Trust X-Forwarded-* from the reverse proxy in front of the container.
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "*")
accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(M)sms "%(a)s"'
