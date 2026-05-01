from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Workspaces API")
    return app
