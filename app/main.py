from fastapi import FastAPI
from app.api.routes import router as api_router

app = FastAPI(title="Title Document Creator API (Pro)", version="1.0.0")
app.include_router(api_router, prefix="/v1")
