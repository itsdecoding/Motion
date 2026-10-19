import logging
import os
import sys

import uvicorn

from webapp.server import app

if not os.environ.get("APP_PASSWORD"):
    sys.exit("Set the APP_PASSWORD environment variable before starting the website.")
logging.basicConfig(level=logging.INFO)
uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
