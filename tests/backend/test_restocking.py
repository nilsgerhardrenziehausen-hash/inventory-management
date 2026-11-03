"""
Tests for restocking API endpoints.
"""
import pytest
from datetime import datetime


def _order_payload(budget=10000, items=None):
    """Build a restocking order request body."""
    return {
        "budget": budget,
        "items": items if items is not None else [{"sku": "WDG-001", "quantity": 100}]
    }


class TestRestockingEndpoints:
    """Test suite for restocking-order endpoints."""

    def test_demand_includes_restocking_fields(self, client):
        """Test that demand forecasts carry the cost and stock fields restocking needs."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        data = response.json()
        assert len(data) > 0

        for forecast in data:
            assert isinstance(forecast["unit_cost"], (int, float))
            assert isinstance(forecast["quantity_on_hand"], int)
            assert isinstance(forecast["category"], str)
            assert forecast["unit_cost"] > 0
            assert forecast["quantity_on_hand"] >= 0

    def test_get_restocking_orders_empty(self, client):
        """Test that no restocking orders exist before anything is submitted."""
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_restocking_order(self, client):
        """Test submitting a restocking order."""
        response = client.post("/api/restocking-orders", json=_order_payload())
        assert response.status_code == 201

        order = response.json()
        assert order["id"] == "RST-0001"
        assert order["status"] == "Submitted"
        assert order["budget"] == 10000
        assert len(order["items"]) == 1

        line = order["items"][0]
        assert line["sku"] == "WDG-001"
        assert line["quantity"] == 100
        assert abs(line["line_total"] - line["quantity"] * line["unit_cost"]) < 0.01
        assert abs(order["total_cost"] - line["line_total"]) < 0.01

    def test_restocking_order_lead_time(self, client):
        """Test that lead time is the slowest line and sets the expected delivery."""
        # WDG-001 is Actuators (14 days), CTL-330 is Controllers (21 days)
        payload = _order_payload(items=[
            {"sku": "WDG-001", "quantity": 10},
            {"sku": "CTL-330", "quantity": 5}
        ])
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        line_days = {line["sku"]: line["lead_time_days"] for line in order["items"]}
        assert line_days == {"WDG-001": 14, "CTL-330": 21}
        assert order["lead_time_days"] == 21

        submitted = datetime.fromisoformat(order["submitted_at"])
        expected = datetime.fromisoformat(order["expected_delivery"])
        assert (expected - submitted).days == 21

    def test_restocking_order_uses_server_prices(self, client):
        """Test that unit cost comes from forecast data, not the request."""
        payload = _order_payload(items=[{"sku": "WDG-001", "quantity": 10, "unit_cost": 0.01}])
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 201
        assert response.json()["items"][0]["unit_cost"] == 12.5

    def test_restocking_order_exceeds_budget(self, client):
        """Test that an order above the budget is rejected."""
        response = client.post("/api/restocking-orders", json=_order_payload(budget=100))
        assert response.status_code == 400

        data = response.json()
        assert "detail" in data
        assert "budget" in data["detail"].lower()

        # Rejected orders are not stored
        assert client.get("/api/restocking-orders").json() == []

    def test_restocking_order_unknown_sku(self, client):
        """Test that an unknown SKU returns 404."""
        payload = _order_payload(items=[{"sku": "NOPE-999", "quantity": 1}])
        response = client.post("/api/restocking-orders", json=payload)
        assert response.status_code == 404

        data = response.json()
        assert "not found" in data["detail"].lower()

    @pytest.mark.parametrize("items", [
        [],
        [{"sku": "WDG-001", "quantity": 0}],
        [{"sku": "WDG-001", "quantity": -5}]
    ])
    def test_restocking_order_invalid_items(self, client, items):
        """Test that empty items or non-positive quantities fail validation."""
        response = client.post("/api/restocking-orders", json=_order_payload(items=items))
        assert response.status_code == 422

    def test_restocking_order_negative_budget(self, client):
        """Test that a negative budget fails validation."""
        response = client.post("/api/restocking-orders", json=_order_payload(budget=-1))
        assert response.status_code == 422

    def test_get_restocking_orders_newest_first(self, client):
        """Test that submitted orders are listed newest first."""
        client.post("/api/restocking-orders", json=_order_payload())
        client.post("/api/restocking-orders", json=_order_payload(items=[{"sku": "SNR-420", "quantity": 5}]))

        response = client.get("/api/restocking-orders")
        assert response.status_code == 200

        data = response.json()
        assert [order["id"] for order in data] == ["RST-0002", "RST-0001"]

    def test_restocking_orders_do_not_affect_orders_or_dashboard(self, client):
        """Test that submitting a restocking order leaves existing orders and totals unchanged."""
        orders_before = client.get("/api/orders").json()
        summary_before = client.get("/api/dashboard/summary").json()

        client.post("/api/restocking-orders", json=_order_payload())

        assert client.get("/api/orders").json() == orders_before
        assert client.get("/api/dashboard/summary").json() == summary_before
