import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitor import target_url, sku_for, sources, run

class WatchTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "target_product_codes": ["H086418CKAC", "H086418CKAA", "H086418CKAF"],
            "target_names": {"H086418CKAC": "黑白", "H086418CKAA": "米白深灰", "H086418CKAF": "米白蓝灰"},
            "target_product_urls": {},
            "category_pages": [],
            "sitemap_index": "https://www.hermes.com/ca/en/sitemap_index.xml",
            "max_notifications_per_run": 3,
            "minimum_product_check_interval_minutes": 60,
        }

    def test_whitelist(self):
        for sku in self.cfg["target_product_codes"]:
            self.assertEqual(sku_for(f"https://www.hermes.com/ca/en/product/neo-garden-23-bag-{sku}/", self.cfg), sku)
        for sku in ["H086418CKAB", "H086418CKAK", "H086418CKACX"]:
            self.assertIsNone(sku_for(f"https://www.hermes.com/ca/en/product/neo-garden-23-bag-{sku}/", self.cfg))

    def test_scope_restrictions(self):
        self.assertIsNone(target_url("https://other.example/ca/en/product/neo-garden-23-bag-H086418CKAC/", self.cfg))
        self.assertIsNone(target_url("https://www.hermes.com/api/products", self.cfg))
        self.assertIsNone(target_url("http://www.hermes.com/ca/en/product/neo-garden-23-bag-H086418CKAC/", self.cfg))
        self.assertIsNone(target_url("https://www.hermes.com/us/en/product/neo-garden-23-bag-H086418CKAC/", self.cfg))

    def test_baseline_no_alert_and_new_link_alert(self):
        sku = "H086418CKAC"
        original = f"https://www.hermes.com/ca/en/product/neo-garden-23-bag-{sku}/"
        fresh = f"https://www.hermes.com/ca/en/product/neo-garden-23-new-bag-{sku}/"
        state = {}
        with patch("monitor.Site.setup"), patch("monitor.sources", return_value=({original: sku}, {})), \
             patch("monitor.Site.allowed", return_value=True), patch("monitor.bark") as push:
            run(self.cfg, state)
            push.assert_not_called()
        self.assertTrue(state["initialized"])
        with patch("monitor.Site.setup"), patch("monitor.sources", return_value=({original: sku, fresh: sku}, {})), \
             patch("monitor.product_status", return_value="accessible"), \
             patch("monitor.bark", return_value=True) as push:
            run(self.cfg, state)
            push.assert_called_once()
        self.assertTrue(state["known"][fresh]["notified"])
        with patch("monitor.Site.setup"), patch("monitor.sources", return_value=({original: sku, fresh: sku}, {fresh: sku})), \
             patch("monitor.bark") as push:
            run(self.cfg, state)
            push.assert_not_called()
        self.assertTrue(state["known"][fresh]["category_first_seen"])

    def test_new_unknown_link_not_pushed(self):
        sku = "H086418CKAC"
        url = f"https://www.hermes.com/ca/en/product/new-{sku}/"
        state = {"targets": self.cfg["target_product_codes"], "initialized": True, "known": {}}
        with patch("monitor.Site.setup"), patch("monitor.sources", return_value=({url: sku}, {})), \
             patch("monitor.product_status", return_value="unknown"), \
             patch("monitor.bark") as push:
            run(self.cfg, state)
            push.assert_not_called()

    def test_invalid_target_rejected(self):
        cfg = dict(self.cfg)
        cfg["target_product_codes"] = ["H086418CKAB"]
        with self.assertRaises(ValueError):
            run(cfg, {})

if __name__ == "__main__":
    unittest.main()
