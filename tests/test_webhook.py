"""Unit tests for the webhook/postback system."""
from __future__ import annotations

import json
import unittest
from http.client import HTTPConnection
from threading import Event

from src.core.config import AppConfig
from src.webhooks.handler import OrderStatus, OrderUpdate, WebhookHandler
from src.webhooks.server import WebhookServer


SAMPLE_PAYLOAD = {
    "dhanClientId": "1000000003",
    "orderId": "112111182198",
    "correlationId": "123abc678",
    "orderStatus": "TRADED",
    "transactionType": "BUY",
    "exchangeSegment": "NSE_EQ",
    "productType": "INTRADAY",
    "orderType": "MARKET",
    "validity": "DAY",
    "tradingSymbol": "NIFTY",
    "securityId": "11536",
    "quantity": 50,
    "disclosedQuantity": 0,
    "price": 22150.50,
    "triggerPrice": 0.0,
    "afterMarketOrder": False,
    "boProfitValue": 0.0,
    "boStopLossValue": 0.0,
    "legName": None,
    "createTime": "2025-06-15 10:30:00",
    "updateTime": "2025-06-15 10:30:01",
    "exchangeTime": "2025-06-15 10:30:01",
    "drvExpiryDate": None,
    "drvOptionType": None,
    "drvStrikePrice": 0.0,
    "omsErrorCode": None,
    "omsErrorDescription": None,
}


class TestOrderUpdate(unittest.TestCase):
    def test_parse_valid_payload(self):
        update = OrderUpdate.from_payload(SAMPLE_PAYLOAD)
        self.assertEqual(update.order_id, "112111182198")
        self.assertEqual(update.order_status, OrderStatus.TRADED)
        self.assertEqual(update.transaction_type, "BUY")
        self.assertEqual(update.quantity, 50)
        self.assertAlmostEqual(update.price, 22150.50)
        self.assertEqual(update.trading_symbol, "NIFTY")
        self.assertEqual(update.security_id, "11536")

    def test_parse_rejected_payload(self):
        payload = dict(SAMPLE_PAYLOAD)
        payload["orderStatus"] = "REJECTED"
        payload["omsErrorCode"] = "OMS_001"
        payload["omsErrorDescription"] = "Insufficient margin"
        update = OrderUpdate.from_payload(payload)
        self.assertEqual(update.order_status, OrderStatus.REJECTED)
        self.assertEqual(update.oms_error_code, "OMS_001")
        self.assertEqual(update.oms_error_description, "Insufficient margin")

    def test_parse_missing_optional_fields(self):
        minimal = {
            "dhanClientId": "100",
            "orderId": "999",
            "orderStatus": "PENDING",
            "transactionType": "SELL",
            "quantity": 10,
            "price": 100.0,
        }
        update = OrderUpdate.from_payload(minimal)
        self.assertEqual(update.order_id, "999")
        self.assertEqual(update.order_status, OrderStatus.PENDING)
        self.assertEqual(update.trading_symbol, "")


class TestWebhookHandler(unittest.TestCase):
    def test_process_and_dispatch(self):
        handler = WebhookHandler()
        received = []
        handler.subscribe(OrderStatus.TRADED, lambda u: received.append(u))

        update = handler.process(SAMPLE_PAYLOAD)
        self.assertIsNotNone(update)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].order_id, "112111182198")

    def test_catch_all_subscriber(self):
        handler = WebhookHandler()
        all_updates = []
        handler.subscribe_all(lambda u: all_updates.append(u))

        handler.process(SAMPLE_PAYLOAD)
        payload2 = dict(SAMPLE_PAYLOAD)
        payload2["orderId"] = "222222"
        payload2["orderStatus"] = "REJECTED"
        handler.process(payload2)

        self.assertEqual(len(all_updates), 2)

    def test_duplicate_suppression(self):
        handler = WebhookHandler()
        count = []
        handler.subscribe(OrderStatus.TRADED, lambda u: count.append(1))

        handler.process(SAMPLE_PAYLOAD)
        handler.process(SAMPLE_PAYLOAD)  # same order_id + same status
        handler.process(SAMPLE_PAYLOAD)

        self.assertEqual(len(count), 1, "Duplicate updates should be suppressed")

    def test_status_transition_not_suppressed(self):
        handler = WebhookHandler()
        statuses = []
        handler.subscribe_all(lambda u: statuses.append(u.order_status.value))

        handler.process(SAMPLE_PAYLOAD)  # TRADED

        pending = dict(SAMPLE_PAYLOAD)
        pending["orderStatus"] = "PENDING"
        handler.process(pending)  # same order_id, different status

        self.assertEqual(len(statuses), 2)
        self.assertEqual(statuses, ["TRADED", "PENDING"])

    def test_get_order_status(self):
        handler = WebhookHandler()
        handler.process(SAMPLE_PAYLOAD)
        self.assertEqual(handler.get_order_status("112111182198"), "TRADED")
        self.assertIsNone(handler.get_order_status("nonexistent"))

    def test_get_history(self):
        handler = WebhookHandler()
        handler.process(SAMPLE_PAYLOAD)

        payload2 = dict(SAMPLE_PAYLOAD)
        payload2["orderId"] = "333333"
        payload2["orderStatus"] = "CANCELLED"
        handler.process(payload2)

        all_history = handler.get_history()
        self.assertEqual(len(all_history), 2)

        filtered = handler.get_history("112111182198")
        self.assertEqual(len(filtered), 1)

    def test_subscriber_exception_isolation(self):
        handler = WebhookHandler()
        good_results = []

        def bad_callback(u):
            raise ValueError("intentional test error")

        handler.subscribe(OrderStatus.TRADED, bad_callback)
        handler.subscribe(OrderStatus.TRADED, lambda u: good_results.append(u))

        handler.process(SAMPLE_PAYLOAD)
        self.assertEqual(len(good_results), 1, "Good subscriber should still fire after bad one throws")


class TestWebhookServer(unittest.TestCase):
    def setUp(self):
        self.config = AppConfig.load()
        self.config.webhook.enabled = True
        self.config.webhook.host = "127.0.0.1"
        self.config.webhook.port = 19876  # use a high port unlikely to conflict
        self.config.webhook.auth_token = ""
        self.handler = WebhookHandler()
        self.server = WebhookServer(self.config, self.handler)
        self.server.start()

    def tearDown(self):
        self.server.stop()

    def test_health_endpoint(self):
        conn = HTTPConnection("127.0.0.1", 19876, timeout=5)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.read())
        self.assertEqual(body["status"], "healthy")
        conn.close()

    def test_post_valid_payload(self):
        received = []
        self.handler.subscribe(OrderStatus.TRADED, lambda u: received.append(u))

        conn = HTTPConnection("127.0.0.1", 19876, timeout=5)
        conn.request(
            "POST", "/",
            body=json.dumps(SAMPLE_PAYLOAD),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.read())
        self.assertEqual(body["status"], "ok")
        self.assertEqual(len(received), 1)
        conn.close()

    def test_post_invalid_json(self):
        conn = HTTPConnection("127.0.0.1", 19876, timeout=5)
        conn.request(
            "POST", "/",
            body="not json at all",
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_post_empty_body(self):
        conn = HTTPConnection("127.0.0.1", 19876, timeout=5)
        conn.request("POST", "/", body="", headers={"Content-Length": "0"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_auth_token_enforcement(self):
        self.server.stop()
        self.config.webhook.auth_token = "secret123"
        self.server = WebhookServer(self.config, self.handler)
        self.server.start()

        conn = HTTPConnection("127.0.0.1", 19876, timeout=5)

        # Without token — should be rejected
        conn.request(
            "POST", "/",
            body=json.dumps(SAMPLE_PAYLOAD),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        self.assertEqual(resp.status, 401)
        conn.close()

        # With correct token — should succeed
        conn = HTTPConnection("127.0.0.1", 19876, timeout=5)
        conn.request(
            "POST", "/",
            body=json.dumps(SAMPLE_PAYLOAD),
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Token": "secret123",
            },
        )
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        conn.close()


if __name__ == "__main__":
    unittest.main()
