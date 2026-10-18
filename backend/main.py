import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse
from backend.routes import router

app = FastAPI(title="Comment-Analyzer API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def check_single_instance():
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
    if workers != 1:
        raise RuntimeError(
            f"WEB_CONCURRENCY={workers} detected. This application is single-instance only."
        )

app.include_router(router)

# Mount Angular Frontend SPA in production / unified deployment
frontend_dist = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend",
    "dist",
    "frontend",
    "browser",
)

if os.path.isdir(frontend_dist):
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Do not mask API or docs routes
        if full_path.startswith("api") or full_path.startswith("docs") or full_path == "openapi.json":
            raise HTTPException(status_code=404, detail="Not Found")

        file_path = os.path.join(frontend_dist, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)

        index_file = os.path.join(frontend_dist, "index.html")
        if os.path.isfile(index_file):
            return FileResponse(index_file)

        raise HTTPException(status_code=404, detail="Frontend build index.html not found")
