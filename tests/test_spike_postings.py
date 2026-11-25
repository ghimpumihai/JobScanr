"""Stage 2 postings picker (#129). No network, no database."""

import sys
from unittest.mock import patch

from scripts import spike_postings


def test_pick_caps_each_company_and_the_sample_and_is_repeatable():
    rows = [{"ats_identifier": "big", "url": f"b{i}"} for i in range(10)] + [
        {"ats_identifier": f"c{i}", "url": f"c{i}"} for i in range(4)
    ]
    picked = spike_postings.pick(rows, 6, seed=1)
    assert len(picked) == 6
    assert sum(r["ats_identifier"] == "big" for r in picked) <= spike_postings.PER_COMPANY
    assert picked == spike_postings.pick(rows, 6, seed=1)  # same seed, same sample
    assert len(spike_postings.pick(rows, 50, seed=1)) == spike_postings.PER_COMPANY + 4  # cap leaves fewer


def test_refuses_without_confirm_live():
    with patch.object(sys, "argv", ["spike_postings", "--out", "x.json"]), patch("db.queries.get_connection") as conn:
        assert spike_postings.main() == 2
    conn.assert_not_called()


def test_persona_is_fake():
    assert spike_postings.PERSONA["email"].endswith("@example.com")
    assert spike_postings.PERSONA["resume_data"]["phone"].startswith("+44 7700 900")  # Ofcom drama range
