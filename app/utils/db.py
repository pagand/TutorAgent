# app/utils/db.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.utils.config import settings

# Create an async engine
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,       # persistent connections kept warm
    max_overflow=15,    # extra connections allowed under burst (25 total)
    pool_timeout=30,    # seconds to wait for a free connection
    pool_pre_ping=True, # test connections on checkout (handles EC2 stop/start drops)
)

# Create a session factory
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_db() -> AsyncSession:
    """
    Dependency to get a database session.
    Ensures the session is closed after the request.
    """
    async with AsyncSessionLocal() as session:
        yield session