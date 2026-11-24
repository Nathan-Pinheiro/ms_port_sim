import random
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from main import _revenue_time_ticks, build_model  # noqa: E402
from model.arrival_profiles import (  # noqa: E402
    HOURLY_ARRIVAL_WEIGHTS,
    PORT_DAILY_ARRIVALS,
    build_daily_arrival_schedule,
)
from model.scenario import Scenario  # noqa: E402


class ArrivalProfileTests(unittest.TestCase):
    def test_new_simulation_starts_without_a_boat(self):
        world = build_model(Scenario(seed=42))

        self.assertEqual(world.boats, [])
        self.assertEqual(world.boats_spawned, 0)

    def test_daily_counts_follow_selected_port_ranges(self):
        for port_type, expected_ranges in PORT_DAILY_ARRIVALS.items():
            with self.subTest(port_type=port_type):
                schedule = build_daily_arrival_schedule(
                    port_type,
                    random.Random(42),
                    steps_per_hour=300,
                    simulation_start_hour=7,
                    simulation_end_hour=21,
                )
                counts = Counter(
                    size
                    for arrivals in schedule.values()
                    for size in arrivals
                )

                for size, (minimum, maximum) in expected_ranges.items():
                    self.assertGreaterEqual(counts[size], minimum)
                    self.assertLessEqual(counts[size], maximum)

    def test_arrivals_cluster_around_the_two_daily_peaks(self):
        arrivals_by_hour = [0] * 24
        for seed in range(250):
            schedule = build_daily_arrival_schedule(
                "regional",
                random.Random(seed),
                steps_per_hour=300,
                simulation_start_hour=7,
                simulation_end_hour=21,
            )
            for step, arrivals in schedule.items():
                hour = 7 + step // 300
                arrivals_by_hour[hour] += len(arrivals)

        total = sum(arrivals_by_hour)
        peak_hours = {7, 8, 15, 16, 17}
        peak_arrivals = sum(
            arrivals_by_hour[hour] for hour in peak_hours
        )
        self.assertGreater(peak_arrivals / total, 0.5)
        self.assertEqual(len(HOURLY_ARRIVAL_WEIGHTS), 24)
        self.assertEqual(sum(arrivals_by_hour[:7]), 0)
        self.assertEqual(sum(arrivals_by_hour[21:]), 0)

    def test_simulation_clock_uses_operating_window(self):
        world = build_model(Scenario(seed=42))

        self.assertEqual(world.simulation_time, "7:00am")
        world.steps = world.MAX_STEPS
        self.assertEqual(world.simulation_time, "9:00pm")
        self.assertEqual(world.SIMULATION_HOURS, 14)

    def test_revenue_axis_uses_clock_times(self):
        ticks, labels = _revenue_time_ticks(7, 14)

        self.assertEqual(ticks, [0, 2, 4, 6, 8, 10, 12, 14])
        self.assertEqual(
            labels,
            [
                "07:00",
                "09:00",
                "11:00",
                "13:00",
                "15:00",
                "17:00",
                "19:00",
                "21:00",
            ],
        )


if __name__ == "__main__":
    unittest.main()
