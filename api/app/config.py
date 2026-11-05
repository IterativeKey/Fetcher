import os

# Fetcher's version. BUILD is when the api image was built (written by
# api/Dockerfile), so the UI shows whether the latest code is running.
VERSION = "0.4.0"
try:
    with open(os.path.join(os.path.dirname(__file__), "..", "BUILD")) as f:
        BUILD = f.read().strip()
except OSError:
    BUILD = "dev"

ARIA2_RPC_URL = os.getenv("ARIA2_RPC_URL", "http://aria2:6800/jsonrpc")
ARIA2_RPC_SECRET = os.getenv("ARIA2_RPC_SECRET", "")

# Required browser/API auth; the API refuses to start without it.
# Clients may send it as "token:<value>", same scheme as aria2.
FETCHER_API_TOKEN = os.getenv("FETCHER_API_TOKEN", "")

# Web UI folder served at /
WEB_DIR = os.getenv("WEB_DIR", "/app/web")

# Egress gateway's control endpoint: vets each link and allows its hosts.
EGRESS_URL = os.getenv("EGRESS_URL", "http://egress:8081")

# The download share, mounted at the SAME path aria2 uses, so the paths aria2
# reports can be used here as-is.
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR_IN_CONTAINER", "/downloads")

# The API's own state: the job history database (fetcher.db).
STATE_DIR = os.getenv("STATE_DIR", "/state")

# How long a "download to browser" link stays valid (seconds). The transfer
# itself may take longer: only the start of the request is checked.
LINK_TTL = int(os.getenv("FETCHER_LINK_TTL", "300"))
