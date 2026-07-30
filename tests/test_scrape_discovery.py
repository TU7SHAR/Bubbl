import unittest
from unittest.mock import patch

from flask import Flask, session

from routes.admin.scrape_managment import (
    _cap_to_plan,
    _discovery_limit,
    _discovery_record,
    _parse_page_limit,
    _time_estimate,
    _validate_selected_urls,
)
from tasks.scrape_tasks import async_discover_links_task
from utils.plan_limits import PLAN_LIMITS


PLAN_MATRIX = {
    'free': (50, 5),
    'starter': (200, 50),
    'growth': (500, 300),
    'pro': (None, None),
}


def urls(count):
    return [f'https://example.com/page-{index}' for index in range(count)]


class ScrapeDiscoveryTests(unittest.TestCase):
    def test_discovery_and_scrape_limits_are_independent(self):
        for plan, (discover_limit, scrape_limit) in PLAN_MATRIX.items():
            with self.subTest(plan=plan):
                self.assertEqual(PLAN_LIMITS[plan]['discover_pages'], discover_limit)
                self.assertEqual(PLAN_LIMITS[plan]['scrape_pages'], scrape_limit)

    def test_find_max_uses_discovery_limit_including_unlimited(self):
        for plan, (discover_limit, _scrape_limit) in PLAN_MATRIX.items():
            with self.subTest(plan=plan):
                self.assertEqual(
                    _discovery_limit(True, 12, discover_limit),
                    discover_limit,
                )

    def test_find_max_off_honors_entered_page_limit(self):
        for plan, (discover_limit, _scrape_limit) in PLAN_MATRIX.items():
            with self.subTest(plan=plan):
                self.assertEqual(_discovery_limit(False, 12, discover_limit), 12)
        self.assertEqual(_discovery_limit(False, 600, 50), 50)
        self.assertEqual(_discovery_limit(False, 600, 200), 200)
        self.assertEqual(_discovery_limit(False, 600, 500), 500)
        self.assertEqual(_discovery_limit(False, 600, None), 600)
        self.assertEqual(_parse_page_limit('0'), 1)

    @patch('utils.scraper.is_safe_url', return_value=(True, None))
    @patch('utils.scraper.crawl_website_links')
    def test_deep_crawl_does_not_override_entered_limit(self, crawl, _safe):
        crawl.return_value = {
            'success': True,
            'urls': urls(12),
            'remaining_queue': 40,
        }
        result = async_discover_links_task.run(
            'https://example.com', True, 12, 5, 'free'
        )
        crawl.assert_called_once_with('https://example.com', max_pages=12)
        self.assertEqual(result['total_found'], 12)
        self.assertEqual(result['discovery_limit'], 12)
        self.assertEqual(result['scrape_count'], 5)

    @patch('utils.scraper.is_safe_url', return_value=(True, None))
    @patch('utils.scraper.crawl_website_links')
    def test_finite_tiers_discover_more_than_they_may_scrape(self, crawl, _safe):
        for plan in ('free', 'starter', 'growth'):
            discover_limit, scrape_limit = PLAN_MATRIX[plan]
            crawl.return_value = {
                'success': True,
                'urls': urls(discover_limit),
                'remaining_queue': 0,
            }
            with self.subTest(plan=plan):
                result = async_discover_links_task.run(
                    'https://example.com',
                    True,
                    discover_limit,
                    scrape_limit,
                    plan,
                )
                self.assertEqual(result['total_found'], discover_limit)
                self.assertEqual(result['scrape_count'], scrape_limit)
                self.assertEqual(result['discovery_limit'], discover_limit)
                self.assertEqual(result['scrape_limit'], scrape_limit)
                self.assertFalse(result['discovery_unlimited'])
                self.assertFalse(result['scrape_unlimited'])
                self.assertTrue(result['capped'])

    @patch('utils.scraper.is_safe_url', return_value=(True, None))
    @patch('utils.scraper.crawl_website_links')
    def test_pro_discovers_and_selects_all_available_urls(self, crawl, _safe):
        available = urls(617)
        crawl.return_value = {
            'success': True,
            'urls': available,
            'remaining_queue': 0,
        }
        result = async_discover_links_task.run(
            'https://example.com', True, None, None, 'pro'
        )
        crawl.assert_called_once_with('https://example.com', max_pages=None)
        self.assertEqual(result['urls'], available)
        self.assertEqual(result['scrape_count'], len(available))
        self.assertIsNone(result['discovery_limit'])
        self.assertIsNone(result['scrape_limit'])
        self.assertTrue(result['discovery_unlimited'])
        self.assertTrue(result['scrape_unlimited'])
        self.assertFalse(result['discovery_capped'])
        self.assertFalse(result['capped'])

    def test_selection_and_start_counts_use_scrape_limit(self):
        for plan, (discover_limit, scrape_limit) in PLAN_MATRIX.items():
            discovered_count = discover_limit or 617
            expected_count = scrape_limit or discovered_count
            discovered_urls = urls(discovered_count)
            selected_urls = discovered_urls[:expected_count]
            with self.subTest(plan=plan):
                self.assertEqual(
                    _cap_to_plan(discovered_count, scrape_limit),
                    expected_count,
                )
                self.assertEqual(
                    _validate_selected_urls(
                        selected_urls,
                        scrape_limit,
                        discovered_urls,
                        'https://example.com',
                    ),
                    selected_urls,
                )
                if scrape_limit is not None:
                    with self.assertRaisesRegex(ValueError, f'up to {scrape_limit} pages'):
                        _validate_selected_urls(
                            discovered_urls[:scrape_limit + 1],
                            scrape_limit,
                            discovered_urls,
                            'https://example.com',
                        )

    def test_estimate_uses_selected_count_not_discovery_count(self):
        self.assertEqual(
            _time_estimate(5),
            {'estimated_seconds_min': 15, 'estimated_seconds_max': 35},
        )
        self.assertNotEqual(_time_estimate(5), _time_estimate(50))

    @patch('utils.scraper.is_safe_url', return_value=(True, None))
    @patch('utils.scraper.crawl_website_links')
    def test_site_estimate_does_not_inflate_scrape_count(self, crawl, _safe):
        crawl.return_value = {
            'success': True,
            'urls': urls(50),
            'remaining_queue': 198,
        }
        result = async_discover_links_task.run(
            'https://example.com', True, 50, 5, 'free'
        )
        self.assertEqual(result['total_found'], 50)
        self.assertEqual(result['estimated_total'], 248)
        self.assertEqual(result['scrape_count'], 5)
        self.assertTrue(result['discovery_capped'])
        self.assertTrue(result['capped'])

    def test_selection_is_discovery_bound_and_same_origin(self):
        allowed = ['https://example.com/', 'https://example.com/about']
        with self.assertRaisesRegex(ValueError, 'discovery result'):
            _validate_selected_urls(
                ['https://example.com/not-discovered'],
                5,
                allowed,
                'https://example.com/',
            )
        with self.assertRaisesRegex(ValueError, 'same origin'):
            _validate_selected_urls(
                ['https://other.example/about'],
                5,
                ['https://other.example/about'],
                'https://example.com/',
            )

    def test_discovery_record_is_bound_to_session_user_and_org(self):
        app = Flask(__name__)
        app.secret_key = 'test-only-secret'
        record = {
            'user_id': 7,
            'org_id': 11,
            'bot_id': 13,
            'url': 'https://example.com',
        }
        with app.test_request_context('/'):
            session['user_id'] = 7
            session['org_id'] = 11
            session['link_discoveries'] = {'owned-task': record}
            self.assertEqual(_discovery_record('owned-task'), record)
            session['user_id'] = 8
            self.assertIsNone(_discovery_record('owned-task'))
            session['user_id'] = 7
            session['org_id'] = 12
            self.assertIsNone(_discovery_record('owned-task'))


if __name__ == '__main__':
    unittest.main()
