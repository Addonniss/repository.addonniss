"""Kodi-free regression coverage: python -m unittest discover -s tests -v."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        'xbmc': types.SimpleNamespace(Monitor=object, Player=object, LOGINFO=1, LOGDEBUG=0, log=Mock()),
        'xbmcaddon': types.SimpleNamespace(Addon=Mock(return_value=Mock())),
        'xbmcgui': types.SimpleNamespace(WindowXMLDialog=object),
        'requests': types.SimpleNamespace(post=Mock()),
    }):
        spec.loader.exec_module(module)
    return module


nexton = load('nexton', 'service.nextonlibrary/service.py')
translator = load('translator', 'service.translatarr/translator.py')


class ToggleTests(unittest.TestCase):
    def service(self):
        service = nexton.NextOnLibraryService.__new__(nexton.NextOnLibraryService)
        service.player = Mock()
        service.overlay = None
        service.reset_session()
        service.current_file = 'episode.mkv'
        service.current_episode = {'episodeid': 1}
        service.current_movie = None
        service.session_matches_current_playback = Mock(return_value=True)
        service.refresh_chapter_markers = Mock()
        service.bootstrap_session = Mock()
        service.abortRequested = Mock(return_value=False)
        service.waitForAbort = Mock(side_effect=[False, True])
        service.player.getTime.return_value = 30
        service.player.getTotalTime.return_value = 100
        service.trigger_time = 20
        return service

    def test_three_independent_feature_combinations(self):
        # Each feature remains reachable when the other two are disabled.
        for intro, next_on, stinger in [(True, False, False), (False, True, False), (False, False, True)]:
            with self.subTest(intro=intro, next_on=next_on, stinger=stinger):
                settings = {'enable_skip_intro': intro, 'service_enabled': next_on, 'enable_stinger_movies': stinger}
                service = self.service()
                if stinger:
                    service.current_episode = None
                    service.current_movie = {'title': 'Movie'}
                service.handle_skip_intro = Mock(side_effect=lambda *args: nexton.get_setting_bool('enable_skip_intro'))
                service.prompt_for_next_episode = Mock()
                service.handle_movie_stinger = Mock()
                with patch.object(nexton, 'get_setting_bool', side_effect=lambda key: settings.get(key, False)):
                    service.run()
                service.handle_skip_intro.assert_called_once_with(30, 100)
                self.assertEqual(service.prompt_for_next_episode.call_count, int(next_on))
                self.assertEqual(service.handle_movie_stinger.call_count, int(stinger))

    def test_skip_intro_overlay_and_seek_with_next_on_disabled(self):
        service = self.service()
        service.skip_intro_allowed = True
        service.skip_intro_start = 10
        service.skip_intro_target = 60
        overlay = Mock()
        with patch.object(nexton, 'get_setting_bool', side_effect=lambda key: key == 'enable_skip_intro'), patch.object(nexton, 'get_setting_int', return_value=2), patch.object(nexton, 'NextOnLibraryOverlay', return_value=overlay):
            self.assertTrue(service.handle_skip_intro(12, 100))
            self.assertEqual(service.overlay_action, 'skip_intro')
            overlay.show.assert_called_once()
            service.handle_overlay_action()
        service.player.seekTime.assert_called_once_with(60)

    def test_session_bootstraps_with_next_on_disabled(self):
        service = self.service()
        service.player.getPlayingFile.return_value = 'new.mkv'
        service.get_current_playback_item = Mock(return_value={'title': 'Episode'})
        service.get_library_episode = Mock(return_value={'episodeid': 1})
        service.get_library_movie = Mock(return_value=None)
        service.is_tv_show_playback = Mock(return_value=True)
        service.get_chapter_markers = Mock(return_value=([], []))
        with patch.object(nexton, 'get_setting_bool', return_value=False):
            nexton.NextOnLibraryService.bootstrap_session(service)
        self.assertEqual(service.current_file, 'new.mkv')
        self.assertTrue(service.skip_intro_allowed)

    def test_disable_during_playback_closes_overlay_and_cancels_countdown(self):
        service = self.service()
        overlay = Mock()
        service.overlay = overlay
        service.overlay_action = 'next_episode'
        service.auto_play_active = True
        service.auto_play_started_at = 0
        with patch.object(nexton, 'get_setting_bool', return_value=False):
            service.run()
        overlay.close.assert_called_once()
        self.assertIsNone(service.overlay)
        self.assertFalse(service.auto_play_active)
        self.assertIsNone(service.auto_play_started_at)
        service.player.play.assert_not_called()

    def test_disabled_next_on_guards_all_entry_points(self):
        service = self.service()
        service.get_next_episode = Mock()
        with patch.object(nexton, 'get_setting_bool', return_value=False), patch.object(nexton, 'jsonrpc') as rpc:
            service.prompt_for_next_episode()
            service.start_auto_play_countdown({'episodeid': 2}, 0)
            service.handle_auto_play(100)
            service.show_overlay('next_episode')
            service.play_next_episode()
        service.get_next_episode.assert_not_called()
        rpc.assert_not_called()
        self.assertIsNone(service.overlay)
        self.assertFalse(service.auto_play_active)

    def test_disabling_next_on_preserves_other_overlays(self):
        for action in ['skip_intro', 'stinger']:
            service = self.service()
            service.overlay = Mock()
            service.overlay_action = action
            with patch.object(nexton, 'get_setting_bool', return_value=False):
                self.assertFalse(service.check_next_on_enabled())
            service.overlay.close.assert_not_called()


class TheIntroDBTests(unittest.TestCase):
    def service(self):
        service = nexton.NextOnLibraryService.__new__(nexton.NextOnLibraryService)
        service.remote_intro_cache = {}
        service.overlay = None
        service.reset_session()
        return service

    def assert_v4_request(self, fetch, identifier):
        url, source = fetch.call_args.args
        parsed = urlsplit(url)
        self.assertEqual((parsed.scheme, parsed.netloc, parsed.path),
                         ('https', 'api.theintrodb.org', '/v4/media'))
        self.assertEqual(source, 'TheIntroDB')
        # Kodi supplies season/episode, with no media-server display-order input.
        self.assertEqual(parse_qs(parsed.query),
                         {'season': ['0'], 'episode': ['1'], **identifier})

    def test_intro_and_recap_v4_urls_and_tvdb_response(self):
        for context, identifier in [
            ({'season': 0, 'episode': 1, 'tmdb_id': 123}, {'tmdb_id': ['123']}),
            ({'season': 0, 'episode': 1, 'imdb_id': 'tt1234567'}, {'imdb_id': ['tt1234567']}),
        ]:
            for segment in ['intro', 'recap']:
                with self.subTest(identifier=identifier, segment=segment):
                    service = self.service()
                    # v4 has tvdb_id, with no tmdb_id in the body.
                    service.fetch_remote_json = Mock(return_value={
                        'tvdb_id': 456, 'type': 'tv', 'season': 0, 'episode': 1,
                        segment: [{'start_ms': 10000, 'end_ms': 60000}],
                    })
                    self.assertEqual(service.fetch_skip_intro_from_theintrodb(context, 100), (10, 60))
                    self.assert_v4_request(service.fetch_remote_json, identifier)

    def test_credits_v4_url_and_tvdb_response(self):
        for ids, identifier in [
            ({'tmdb_id': 123}, {'tmdb_id': ['123']}),
            ({'imdb_id': 'tt1234567'}, {'imdb_id': ['tt1234567']}),
        ]:
            with self.subTest(identifier=identifier):
                service = self.service()
                service.build_skip_intro_remote_context = Mock(return_value={
                    'season': 0, 'episode': 1, **ids,
                })
                service.fetch_remote_json = Mock(return_value={
                    'tvdb_id': 456, 'type': 'tv',
                    'credits': [{'start_ms': 80000, 'end_ms': None}],
                })
                self.assertEqual(service.get_remote_next_trigger(100), 80)
                self.assert_v4_request(service.fetch_remote_json, identifier)

    def test_empty_and_alternate_v4_shapes_keep_fallback(self):
        for payload in [None, {'tvdb_id': 456, 'intro': [], 'credits': []},
                        {'tvdb_id': 456, 'episodes': []},
                        {'tvdb_id': 456, 'versions': []}]:
            with self.subTest(payload=payload):
                service = self.service()
                context = {'season': 0, 'episode': 1, 'tmdb_id': 123}
                service.build_skip_intro_remote_context = Mock(return_value=context)
                service.fetch_remote_json = Mock(return_value=payload)
                service.fetch_next_trigger_from_introdb = Mock(return_value=90)
                self.assertIsNone(service.fetch_skip_intro_from_theintrodb(context, 100))
                self.assertEqual(service.get_remote_next_trigger(100), 90)
                service.fetch_next_trigger_from_introdb.assert_called_once_with(context, 100)


class OpenAITests(unittest.TestCase):
    def make_translator(self, model, effort='Minimal'):
        settings = {'openai_model': model, 'openai_reasoning_effort': effort, 'openai_api_key': 'test', 'temp_openai': '0.2'}
        with patch.object(translator.ADDON, 'getSetting', side_effect=lambda key: settings.get(key, '')):
            return translator.OpenAITranslator()

    def test_selector_mapping_defaults_and_prices(self):
        setting = ET.parse(ROOT / 'service.translatarr/resources/settings.xml').find(".//setting[@id='openai_model']")
        self.assertEqual(setting.findtext('default'), 'gpt-5.4-nano')
        models = [option.text for option in setting.findall('.//option')]
        self.assertEqual(set(models), {'gpt-6-luna', 'gpt-5.6-luna', 'gpt-5.4-nano', 'gpt-5-mini', 'gpt-4o-mini'})
        for model in models:
            self.assertEqual(self.make_translator(model).model, model)
        self.assertEqual(self.make_translator('unknown').model, 'gpt-5.4-nano')
        luna = self.make_translator('gpt-6-luna')
        self.assertAlmostEqual(luna.calculate_cost(1_000_000, 0), .10)
        self.assertAlmostEqual(luna.calculate_cost(0, 1_000_000), .50)
        self.assertAlmostEqual(luna.calculate_cost(2_000_000, 3_000_000), 1.70)
        self.assertEqual(luna.calculate_cost(0, 0), 0)

    def test_request_reasoning_and_temperature(self):
        languages = types.SimpleNamespace(get_lang_params=lambda _: ('English', 'en'), get_active_language_setting=lambda *args: 'English')
        for model in ['gpt-6-luna', 'gpt-5.6-luna', 'gpt-5.4-nano', 'gpt-5-mini', 'gpt-4o-mini']:
            for effort in ['Minimal', 'Low', 'Medium', 'High']:
                with self.subTest(model=model, effort=effort):
                    client = self.make_translator(model, effort)
                    response = Mock(status_code=200)
                    response.json.return_value = {'choices': [{'message': {'content': 'L000: Hello'}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
                    with patch.dict(sys.modules, {'languages': languages}), patch.object(translator.requests, 'post', return_value=response) as post:
                        result = client.translate_batch(['Hello'], 1)
                    self.assertEqual(result, (['Hello'], 10, 5))
                    payload = post.call_args.kwargs['json']
                    self.assertEqual(payload['model'], model)
                    if model == 'gpt-4o-mini':
                        self.assertEqual(payload['temperature'], .2)
                        self.assertNotIn('reasoning_effort', payload)
                    else:
                        expected = effort.lower()
                        if effort == 'Minimal' and model != 'gpt-5-mini':
                            expected = 'none'
                        self.assertEqual(payload['reasoning_effort'], expected)
                        self.assertNotIn('temperature', payload)


if __name__ == '__main__':
    unittest.main()
