import unittest
from unittest.mock import patch

from routes.admin.scrape_managment import (
    _discovery_limit,
    _parse_page_limit,
    _time_estimate,
)
from tasks.scrape_tasks import async_discover_links_task
from utils.plan_limits import PLAN_LIMITS


class ScrapeDiscoveryTests(unittest.TestCase):
    def test_plan_page_limits_match_product_tiers(self):
        self.assertEqual(PLAN_LIMITS['free']['scrape_pages'], 50)
        self.assertEqual(PLAN_LIMITS['starter']['scrape_pages'], 200)
        self.assertEqual(PLAN_LIMITS['growth']['scrape_pages'], 500)
        self.assertGreaterEqual(PLAN_LIMITS['pro']['scrape_pages'], 999999)

    def test_find_max_uses_plan_limit(self):
        self.assertEqual(_discovery_limit(True, 12, 200), 200)

    def test_limited_mode_honors_page_limit_and_plan_cap(self):
        self.assertEqual(_discovery_limit(False, 12, 200), 12)
        self.assertEqual(_discovery_limit(False, 300, 200), 200)
        self.assertEqual(_parse_page_limit('0'), 1)

    def test_estimate_uses_selectable_page_count(self):
        self.assertEqual(
            _time_estimate(50),
            {'estimated_seconds_min': 150, 'estimated_seconds_max': 350},
        )

    @patch('utils.scraper.is_safe_url', return_value=(True, None))
    @patch('utils.scraper.crawl_website_links')
    def test_site_estimate_does_not_inflate_scrape_count(self, crawl, _safe):
        crawl.return_value = {
            'success': True,
            'urls': [f'https://example.com/{index}' for index in range(50)],
            'remaining_queue': 198,
        }

        result = async_discover_links_task.run(
            'https://example.com', True, 50, 50, 'free'
        )

        self.assertEqual(result['total_found'], 50)
        self.assertEqual(result['estimated_total'], 248)
        self.assertEqual(result['scrape_count'], 50)
        self.assertTrue(result['capped'])


if __name__ == '__main__':
    unittest.main()
