"""Regression tests for the Adara fork of the Signalpost reference agent.

Covers the three fixes/additions made for the Round 1 submission:
1. Financial records are stored newest-first (the registry API returns
   oldest-first, and the old code kept the oldest three).
2. The SSRF guard still blocks private/loopback/link-local/reserved literal
   IPs, while the egress-proxy CGNAT range is recognised as proxy-routed.
3. The news exact-title gate and the deterministic synthesis use the newest
   financial record.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.news import exact_title_match  # noqa: E402
from norway_company_agent.official import normalize_financials  # noqa: E402
from norway_company_agent.synthesis import build_synthesis  # noqa: E402
from norway_company_agent.website import _is_egress_proxy_address, assert_public_url  # noqa: E402
import ipaddress  # noqa: E402


def _record(year: int, revenue: float) -> dict:
    return {
        "id": year,
        "regnskapstype": "SELSKAP",
        "regnskapsperiode": {"fraDato": f"{year}-01-01", "tilDato": f"{year}-12-31"},
        "valuta": "NOK",
        "resultatregnskapResultat": {
            "driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": revenue}},
            "aarsresultat": revenue / 10,
        },
        "eiendeler": {"sumEiendeler": revenue * 2},
        "egenkapitalGjeld": {"gjeldOversikt": {"sumGjeld": revenue}},
    }


class FinancialOrderingTests(unittest.TestCase):
    def test_newest_first(self):
        body = [_record(2023, 100.0), _record(2024, 200.0), _record(2025, 300.0)]
        out = normalize_financials(body)
        periods = [r["period"]["tilDato"] for r in out["records"]]
        self.assertEqual(periods, ["2025-12-31", "2024-12-31", "2023-12-31"])
        self.assertEqual(out["records"][0]["revenue"], 300.0)

    def test_keeps_newest_three_when_more_exist(self):
        body = [_record(y, float(y)) for y in range(2018, 2026)]
        out = normalize_financials(body)
        self.assertEqual(len(out["records"]), 3)
        self.assertEqual(out["records"][0]["period"]["tilDato"], "2025-12-31")


class SsrfGuardTests(unittest.TestCase):
    def test_literal_private_addresses_blocked(self):
        for url in (
            "http://localhost/admin",
            "http://127.0.0.1/x",
            "http://10.0.0.5/x",
            "http://192.168.1.1/x",
            "http://169.254.169.254/latest/meta-data/",
            "http://198.18.13.106/x",
        ):
            with self.assertRaises(ValueError, msg=url):
                assert_public_url(url)

    def test_egress_proxy_range_recognised(self):
        self.assertTrue(_is_egress_proxy_address(ipaddress.ip_address("198.18.13.106")))
        self.assertTrue(_is_egress_proxy_address(ipaddress.ip_address("198.19.0.1")))
        self.assertFalse(_is_egress_proxy_address(ipaddress.ip_address("8.8.8.8")))
        self.assertFalse(_is_egress_proxy_address(ipaddress.ip_address("10.0.0.5")))


class NewsGateTests(unittest.TestCase):
    def test_exact_name_in_title(self):
        self.assertTrue(exact_title_match("Aneo Roan Vind Holding AS", "Aneo Roan Vind Holding AS henter 100 millioner - E24"))
        self.assertTrue(exact_title_match("Equinor ASA", "Equinors årsrapport for 2024 - Equinor"))
        self.assertTrue(exact_title_match("Equinor ASA", "Equinor ASA legger fram tall - DN"))
        self.assertTrue(exact_title_match("Equinor ASA", "Valg av aksjonærrepresentanter til styret i Equinor ASA - Equinor"))

    def test_short_name_needs_lowercase_continuation(self):
        # "Aneo Roan ..." is a longer company, not Aneo AS.
        self.assertFalse(exact_title_match("Aneo AS", "Aneo Roan Vind Holding AS henter 100 millioner - E24"))
        # A lowercase verb after the short name is the same company.
        self.assertTrue(exact_title_match("Aneo AS", "Aneo kjøper selskap - E24"))

    def test_unrelated_title_rejected(self):
        self.assertFalse(exact_title_match("Equinor ASA", "Oljeprisen stiger etter OPEC-møte - E24"))


class SynthesisTests(unittest.TestCase):
    def test_uses_newest_financials_and_lists_unknowns(self):
        profile = {
            "organisation_number": "123456789",
            "name": "Test AS",
            "legal_form": "AS",
            "municipality": "OSLO",
            "employees": 12,
            "evidence": {
                "financials": {"value": {"records": [
                    {"period": {"fraDato": "2025-01-01", "tilDato": "2025-12-31"}, "revenue": 300.0,
                     "annual_result": 30.0, "assets": 600.0, "debt": 300.0},
                    {"period": {"fraDato": "2024-01-01", "tilDato": "2024-12-31"}, "revenue": 200.0,
                     "annual_result": 20.0, "assets": 500.0, "debt": 200.0},
                ]}},
                "roles": {"value": {"roles": [{"name": "Ola Nordmann", "role": "Daglig leder", "inactive": False}]}},
                "locations": {"value": {"locations": [{"name": "Hovedkontor", "address": {"kommune": "OSLO"}}]}},
            },
        }
        record, _ = build_synthesis(profile)
        self.assertEqual(record["status"], "available")
        summary = record["value"]["summary"]
        self.assertIn("2025-01-01", summary)
        self.assertIn("300 NOK", summary)
        self.assertIn("Ola Nordmann", summary)
        self.assertTrue(record["value"]["unknowns"])


if __name__ == "__main__":
    unittest.main()
