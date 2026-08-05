from __future__ import annotations

import unittest

from jang_app.services.update_polling import UpdatePollingPolicy


class UpdatePollingPolicyTests(unittest.TestCase):
    def test_active_and_inactive_intervals_are_state_aware(self) -> None:
        policy = UpdatePollingPolicy()
        self.assertEqual(policy.next_delay_ms(100.0, True), 0)
        self.assertFalse(policy.should_check_on_activation(100.0))

        policy.record_success(100.0)

        self.assertEqual(policy.next_delay_ms(130.0, True), 90_000)
        self.assertEqual(policy.next_delay_ms(130.0, False), 570_000)
        self.assertFalse(policy.should_check_on_activation(129.9))
        self.assertTrue(policy.should_check_on_activation(130.0))

    def test_failures_back_off_without_disabling_future_checks(self) -> None:
        policy = UpdatePollingPolicy()
        policy.record_failure(10.0)
        self.assertEqual(policy.interval_seconds(True), 240.0)

        for index in range(10):
            policy.record_failure(20.0 + index)

        self.assertEqual(policy.interval_seconds(True), 1800.0)
        policy.record_success(100.0)
        self.assertEqual(policy.interval_seconds(True), 120.0)


if __name__ == "__main__":
    unittest.main()
