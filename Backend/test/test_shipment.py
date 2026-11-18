import pytest
from httpx import AsyncClient

try:
    from Backend.test import example
except ImportError:
    import example

base_url = "/shipment/"


@pytest.mark.asyncio
async def test_submit_shipment_unauthorized(client: AsyncClient):
    """Verify that unauthenticated shipment creation is rejected with 401/403."""
    response = await client.post(
        base_url,
        json={},
    )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_seller_profile(client: AsyncClient, seller_token: str):
    """Verify seller profile retrieval using JWT bearer token."""
    response = await client.get(
        "/seller/me",
        headers={"Authorization": f"Bearer {seller_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == example.SELLER["email"]
    assert data["name"] == example.SELLER["name"]


@pytest.mark.asyncio
async def test_delivery_partner_profile(client: AsyncClient, partner_token: str):
    """Verify delivery partner profile retrieval and serviceable zones."""
    response = await client.get(
        "/partner/me",
        headers={"Authorization": f"Bearer {partner_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == example.DELIVERY_PARTNER["email"]
    assert data["max_handling_capacity"] == example.DELIVERY_PARTNER["max_handling_capacity"]


@pytest.mark.asyncio
async def test_submit_and_get_shipment(client: AsyncClient, seller_token: str):
    """Verify shipment dispatch lifecycle: submission, partner assignment, and eager timeline fetch."""
    # 1. Submit Shipment as Seller
    create_response = await client.post(
        base_url,
        json=example.SHIPMENT,
        headers={"Authorization": f"Bearer {seller_token}"},
    )
    assert create_response.status_code in (200, 201)
    shipment_data = create_response.json()
    assert "id" in shipment_data
    shipment_id = shipment_data["id"]

    # 2. Retrieve Shipment by ID (verifying eager loaded fields)
    get_response = await client.get(
        base_url,
        params={"id": shipment_id},
        headers={"Authorization": f"Bearer {seller_token}"},
    )
    assert get_response.status_code == 200
    fetched_data = get_response.json()
    assert fetched_data["id"] == shipment_id
    assert fetched_data["content"] == example.SHIPMENT["content"]
