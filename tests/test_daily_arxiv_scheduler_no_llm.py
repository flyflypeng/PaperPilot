import json
import os
import tempfile
import unittest
from unittest.mock import patch


from paperpilot.tools.basic_tools.daily_arxiv import DailyArxivManager


class TestDailyArxivSchedulerNoLLM(unittest.TestCase):
    def test_scheduled_fetch_runs_without_llm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_file = os.path.join(tmpdir, "daily_arxiv_settings.json")
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "enabled": True,
                        "categories": ["cs.CV"],
                        "retentionDays": 1,
                        "checkIntervalMinutes": 30,
                    },
                    f,
                )

            manager = DailyArxivManager(base_dir=tmpdir, settings_file=settings_file)
            manager.set_llm_config_callback(lambda: {})

            called = []
            manager.get_available_dates = lambda: []
            manager.cleanup_old_papers = lambda retention_days=7: None

            def fake_fetch_papers(category, date_str=None, force=False):
                called.append((category, date_str, force))
                return []

            manager.fetch_papers = fake_fetch_papers

            with patch("paperpilot.tools.basic_tools.daily_arxiv.time.sleep", lambda _: None):
                manager._do_scheduled_fetch()

            self.assertTrue(called)


if __name__ == "__main__":
    unittest.main()

