import os
import uvicorn
from reactor_backend.bootstrap.config import Settings

if __name__ == "__main__":
    Settings.from_env()  # Validate before opening a socket; never accepts multiworker CLI flags.
    uvicorn.run("reactor_backend.bootstrap.app:create_app", factory=True,
                host=os.environ.get("REACTOR_BACKEND_HOST", "127.0.0.1"),
                port=int(os.environ.get("REACTOR_BACKEND_PORT", "8101")), workers=1)
