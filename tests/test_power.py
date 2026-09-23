"""The power source follows the cable: `pmset -g batt` parsed once, every state it prints."""
import unittest

import metrics

HEAD_AC = "Now drawing from 'AC Power'\n"
HEAD_BATT = "Now drawing from 'Battery Power'\n"
CELL = " -InternalBattery-0 (id=28115043)\t"


def parse(head, line):
    return metrics.parse_pmset_batt(head + CELL + line + "\n")


class Pmset(unittest.TestCase):

    def test_on_battery_is_not_charging(self):
        # the bug: "charging" in "discharging" read a Mac on its battery as charging
        p = parse(HEAD_BATT, "80%; discharging; 4:12 remaining present: true")
        self.assertEqual(p["source"], "battery")
        self.assertIs(p["plugged"], False)
        self.assertIs(p["charging"], False)
        self.assertEqual(p["state"], "discharging")
        self.assertEqual(p["pct"], 80)
        self.assertEqual(p["remaining"], 252)

    def test_just_unplugged_has_no_estimate(self):
        p = parse(HEAD_BATT, "100%; discharging; (no estimate) present: true")
        self.assertIs(p["plugged"], False)
        self.assertIs(p["charging"], False)
        self.assertIsNone(p["remaining"])

    def test_charging(self):
        p = parse(HEAD_AC, "85%; charging; 1:02 remaining present: true")
        self.assertEqual(p["source"], "AC")
        self.assertIs(p["plugged"], True)
        self.assertIs(p["charging"], True)
        self.assertEqual(p["remaining"], 62)

    def test_just_plugged_in(self):
        p = parse(HEAD_AC, "97%; charging; (no estimate) present: true")
        self.assertIs(p["plugged"], True)
        self.assertIs(p["charging"], True)
        self.assertIsNone(p["remaining"])

    def test_charged(self):
        p = parse(HEAD_AC, "100%; charged; 0:00 remaining present: true")
        self.assertIs(p["plugged"], True)
        self.assertIs(p["charging"], False)
        self.assertEqual(p["state"], "charged")
        self.assertIsNone(p["remaining"])

    def test_held_by_optimised_charging(self):
        p = parse(HEAD_AC, "80%; AC attached; not charging present: true")
        self.assertIs(p["plugged"], True)
        self.assertIs(p["charging"], False)
        self.assertEqual(p["state"], "not charging")

    def test_finishing_charge(self):
        p = parse(HEAD_AC, "99%; finishing charge; 0:05 remaining present: true")
        self.assertIs(p["charging"], True)
        self.assertEqual(p["state"], "finishing charge")

    def test_source_line_wins_over_a_stale_state(self):
        # the first line is the registry's answer; a battery line a beat
        # behind it must not put the Mac back on the cable
        p = parse(HEAD_BATT, "97%; charging; (no estimate) present: true")
        self.assertIs(p["plugged"], False)
        self.assertIs(p["charging"], False)

    def test_no_battery(self):
        p = metrics.parse_pmset_batt(HEAD_AC)
        self.assertEqual(p["source"], "AC")
        self.assertIs(p["plugged"], True)
        self.assertIsNone(p["pct"])
        self.assertIsNone(p["state"])

    def test_pmset_failed(self):
        # an empty answer is unknown, not "off the cable"
        for raw in ("", None):
            p = metrics.parse_pmset_batt(raw)
            self.assertIsNone(p["source"])
            self.assertIsNone(p["plugged"])
            self.assertIsNone(p["pct"])
            self.assertIs(p["charging"], False)

    def test_state_without_source_line(self):
        self.assertIs(metrics.parse_pmset_batt(CELL + "50%; discharging; 3:00 remaining")["plugged"], False)
        self.assertIs(metrics.parse_pmset_batt(CELL + "50%; charging; 1:00 remaining")["plugged"], True)

    def test_ups(self):
        p = metrics.parse_pmset_batt("Now drawing from 'UPS Power'\n")
        self.assertEqual(p["source"], "UPS")
        self.assertIs(p["plugged"], False)


if __name__ == "__main__":
    unittest.main()
