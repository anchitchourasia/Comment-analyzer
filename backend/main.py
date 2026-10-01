import os
from fastapi import FastAPI
from backend.routes import router

app = FastAPI(title="Comment-Analyzer API", version="0.2.0")

@app.on_event("startup")
def check_single_instance():
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
    if workers != 1:
        raise RuntimeError(
            f"WEB_CONCURRENCY={workers} detected. This application is single-instance only."
        )

app.include_router(router)
