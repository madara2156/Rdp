import os
import sys
import types
import unittest


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
# The production requirements provide these modules.  Stub them here so the
# response-normalization tests can run in the lightweight source workspace
# without installing the full bot runtime.
sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
sys.modules.setdefault("requests", types.ModuleType("requests"))
import zapupi


class ZapupiResponseTests(unittest.TestCase):
    def test_flat_create_order_response(self):
        response = {
            "status": "Success",
            "order_id": "ORD-1",
            "payment_url": "https://pay.example/ORD-1",
        }
        self.assertTrue(zapupi.response_ok(response))
        self.assertEqual(zapupi.order_id(response), "ORD-1")
        self.assertEqual(zapupi.payment_url(response), "https://pay.example/ORD-1")

    def test_documented_nested_paid_response(self):
        response = {
            "status": "success",
            "data": {
                "order_id": "ORD-2",
                "status": "Success",
                "amount": "900.00",
                "pay_amount": "900.00",
                "txn_id": "TXN-2",
                "utr": "UTR-2",
                "environment": "cashier",
            },
        }
        self.assertTrue(zapupi.response_ok(response))
        self.assertEqual(zapupi.order_id(response), "ORD-2")
        self.assertEqual(zapupi.payment_status(response), "success")
        self.assertEqual(zapupi.amount(response), 900.0)
        self.assertEqual(zapupi.txn_id(response), "TXN-2")
        self.assertEqual(zapupi.utr(response), "UTR-2")

    def test_camel_case_and_payment_link_are_supported(self):
        response = {
            "status": "ok",
            "data": {
                "orderId": "ORD-3",
                "paymentStatus": "paid",
                "paidAmount": "450",
                "transactionId": "TXN-3",
                "utrNumber": "UTR-3",
                "paymentLink": "https://pay.example/ORD-3",
            },
        }
        self.assertTrue(zapupi.response_ok(response))
        self.assertEqual(zapupi.order_id(response), "ORD-3")
        self.assertEqual(zapupi.payment_status(response), "paid")
        self.assertEqual(zapupi.amount(response), 450.0)
        self.assertEqual(zapupi.txn_id(response), "TXN-3")
        self.assertEqual(zapupi.utr(response), "UTR-3")
        self.assertEqual(zapupi.payment_url(response), "https://pay.example/ORD-3")

    def test_status_request_failure_is_not_treated_as_success(self):
        response = {"status": "success", "data": {"status": "Failed"}}
        self.assertTrue(zapupi.response_ok(response))
        self.assertEqual(zapupi.payment_status(response), "failed")
        self.assertFalse(zapupi.response_ok({"status": "Failed"}))

    def test_explicit_api_error_is_rejected(self):
        self.assertFalse(zapupi.response_ok({"status": "error", "message": "bad key"}))

    def test_documented_flat_webhook_fields(self):
        webhook = {
            "order_id": "ORD-4",
            "status": "Success",
            "txn_id": "TXN-4",
            "amount": "1200",
            "utr": "UTR-4",
            "environment": "cashier",
        }
        self.assertTrue(zapupi.response_ok(webhook))
        self.assertEqual(zapupi.order_id(webhook), "ORD-4")
        self.assertEqual(zapupi.payment_status(webhook), "success")
        self.assertEqual(zapupi.amount(webhook), 1200.0)
        self.assertEqual(zapupi.txn_id(webhook), "TXN-4")
        self.assertEqual(zapupi.utr(webhook), "UTR-4")
        self.assertEqual(zapupi.environment(webhook), "cashier")

    def test_deep_nested_status_payload_is_supported(self):
        response = {
            "status": "success",
            "result": {
                "order": {
                    "order_id": "ORD-5",
                    "status": "Success",
                    "pay_amount": "150",
                    "txn_id": "TXN-5",
                    "utr": "UTR-5",
                }
            },
        }
        self.assertEqual(zapupi.order_id(response), "ORD-5")
        self.assertEqual(zapupi.payment_status(response), "success")
        self.assertEqual(zapupi.amount(response), 150.0)
        self.assertEqual(zapupi.txn_id(response), "TXN-5")
        self.assertEqual(zapupi.utr(response), "UTR-5")

    def test_failed_webhook_never_looks_paid(self):
        webhook = {
            "order_id": "ORD-6",
            "status": "Failed",
            "txn_id": "",
            "amount": "900",
            "utr": "",
            "environment": "cashier",
        }
        self.assertFalse(zapupi.response_ok(webhook))
        self.assertEqual(zapupi.payment_status(webhook), "failed")

    def test_non_2xx_response_is_never_accepted(self):
        response = {
            "status": "success",
            "payment_url": "https://pay.example/invalid",
            "_http_status": 401,
        }
        self.assertFalse(zapupi.response_ok(response))


if __name__ == "__main__":
    unittest.main()