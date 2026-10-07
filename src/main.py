import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config.settings import ConfigManager, get_config
from src.api.error_handlers import register_error_handlers
from src.api.middleware import MessageLengthMiddleware, RequestLoggingMiddleware
from src.api.routes import router
from src.utils.logger import logger, setup_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load configuration and configure logger
    config = get_config()
    setup_logger(
        log_level=config.gateway.log_level,
        log_file=config.gateway.log_file,
    )
    logger.info("==================================================")
    logger.info(" Starting tecWatch Configurable API Layer")
    logger.info(f" Target Server Base URL: {config.server.base_url}")
    logger.info(f" Status Endpoint:        {config.api.status_endpoint}")
    logger.info(f" Analysis Endpoint:      {config.api.result_endpoint}")
    logger.info(f" Analysis Report File:   {config.analysis.resolved_report_path}")
    logger.info(f" Analysis Scenarios:     {config.analysis.resolved_scenarios_path}")
    logger.info(f" Max Payload Bytes:      {config.api.max_payload_bytes}")
    logger.info("==================================================")
    yield
    # Shutdown
    logger.info("Shutting down tecWatch API Layer.")


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(
        title="tecWatch Configurable Status & Post-Analysis API",
        description=(
            "Dynamic API layer for communication between tecWatch, analysis components, "
            "and the DBLTAS Web GUI. Supports dynamic server configuration, dual JSON/XML payloads, "
            "and strict validation."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Middleware: CORS (Allows DBLTAS Web GUI to connect from browser)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware: Payload Size Limit & Request Logger
    app.add_middleware(MessageLengthMiddleware)
    app.add_middleware(RequestLoggingMiddleware)

    # Register standardized error handlers (validation, JSON/XML errors)
    register_error_handlers(app)

    # Mount API routes
    app.include_router(router, prefix="/api")

    @app.get("/", tags=["Health"])
    async def root():
        return {
            "service": "tecWatch Configurable API",
            "version": "1.0.0",
            "docs": "/docs",
            "active_target_server": ConfigManager.get_instance().config.server.base_url,
        }

    return app


app = create_app()


def run():
    import uvicorn
    cfg = get_config()
    uvicorn.run(
        "src.main:app",
        host=cfg.gateway.listen_host,
        port=cfg.gateway.listen_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
