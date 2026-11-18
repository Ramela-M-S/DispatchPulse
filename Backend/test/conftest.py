import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

# Ensure root and Backend are in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from Backend.app.database.session import get_session
from Backend.app.main import app
from Backend.test import example

# In-memory test database for fast, isolated async testing
engine = create_async_engine(url="sqlite+aiosqlite:///:memory:", echo=False)
test_session = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False,
)

async def get_session_override():
    async with test_session() as session:
        yield session


@pytest_asyncio.fixture(scope="session")
async def client():
    async with AsyncClient(
        transport=ASGITransport(app),
        base_url="http://test",
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_and_teardown():
    app.dependency_overrides[get_session] = get_session_override

    # Mock Redis calls for testing environment
    from Backend.app.database import redis as redis_module
    redis_module.is_jti_blacklisted = AsyncMock(return_value=False)
    redis_module.add_jti_to_blacklist = AsyncMock()
    redis_module.add_shipment_verification_code = AsyncMock()
    redis_module.get_shipment_verification_code = AsyncMock(return_value="123456")

    async with engine.begin() as connection:
        from Backend.app.database.models import DeliveryPartner, Seller, Shipment  # noqa: F401
        await connection.run_sync(SQLModel.metadata.create_all)

    async with test_session() as session:
        await example.create_test_data(session)

    yield

    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.drop_all)

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="session")
async def seller_token(client: AsyncClient):
    response = await client.post(
        "/seller/token",
        data={
            "grant_type": "password",
            "username": example.SELLER["email"],
            "password": example.SELLER["password"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    return data["access_token"]


@pytest_asyncio.fixture(scope="session")
async def partner_token(client: AsyncClient):
    response = await client.post(
        "/partner/token",
        data={
            "grant_type": "password",
            "username": example.DELIVERY_PARTNER["email"],
            "password": example.DELIVERY_PARTNER["password"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    return data["access_token"]
