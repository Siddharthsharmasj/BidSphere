# This project uses standard Django WSGI deployment for maximum compatibility
# with local development and Vercel. Keeping this file valid also makes the
# project compatible with ASGI-capable servers if you choose to use one later.
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bidsphere.settings")
application = get_asgi_application()
