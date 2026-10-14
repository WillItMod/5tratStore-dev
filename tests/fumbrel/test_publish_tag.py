"""Exercise registry error distinctions without real credentials or network IO."""
import base64
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('fumbrel_publish_tag', ROOT / 'scripts/fumbrel/check_publish_tag.py')
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)
SECRET = 'test-password-do-not-echo'
TOKEN = 'test-bearer-token-do-not-echo'


class Response:
    def __init__(self, code, value):
        self.code = code
        self.body = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.closed = False

    def read(self, limit):
        return self.body[:limit]

    def close(self):
        self.closed = True


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class PublishTagTests(unittest.TestCase):
    def invoke(self, manifest):
        token = Response(200, {'token': TOKEN})
        opener = Opener(token, manifest)
        checker.assert_tag_absent('willitmod/fumbrel', '0.1.1-dev', 'test-user', SECRET, opener)
        self.assertTrue(token.closed)
        if isinstance(manifest, Response):
            self.assertTrue(manifest.closed)
        return opener

    def test_only_explicit_manifest_unknown_allows_publication(self):
        opener = self.invoke(Response(404, {'errors': [{'code': 'MANIFEST_UNKNOWN', 'message': 'manifest unknown'}]}))
        self.assertEqual(len(opener.requests), 2)
        auth = 'Basic ' + base64.b64encode(('test-user:' + SECRET).encode()).decode()
        self.assertEqual(opener.requests[0].get_header('Authorization'), auth)
        self.assertEqual(opener.requests[1].get_header('Authorization'), 'Bearer ' + TOKEN)
        self.assertIn('repository%3Awillitmod%2Ffumbrel%3Apull', opener.requests[0].full_url)
        self.assertEqual(opener.requests[1].full_url, 'https://ghcr.io/v2/willitmod/fumbrel/manifests/0.1.1-dev')
        for request in opener.requests:
            self.assertNotIn(SECRET, request.full_url)
            self.assertNotIn(TOKEN, request.full_url)

    def test_http_200_existing_tag_is_refused_without_reading_manifest(self):
        response = Response(200, b'not-needed-for-existing-tag-check')
        with patch.object(response, 'read', side_effect=AssertionError('Existing manifest body should not be read')):
            with self.assertRaisesRegex(checker.PublicationBlocked, 'already exists'):
                self.invoke(response)
        self.assertTrue(response.closed)

    def test_other_http_statuses_are_not_absence(self):
        for code in (201, 204, 301, 302, 307, 400, 401, 403, 429, 500, 503):
            with self.subTest(code=code), self.assertRaises(checker.PublicationBlocked):
                self.invoke(Response(code, {'errors': [{'code': 'MANIFEST_UNKNOWN'}]}))

    def test_other_404_documents_are_not_absence(self):
        for body in ({'errors': [{'code': 'NAME_UNKNOWN'}]}, {'errors': [{'code': 'DENIED'}]},
                     {'errors': [{'code': 'MANIFEST_UNKNOWN'}, {'code': 'DENIED'}]}, {'errors': []},
                     {'errors': [{}]}, {'errors': 'MANIFEST_UNKNOWN'}, {}, [], b'not-json',
                     b' ' * (checker.MAX_RESPONSE + 1)):
            with self.subTest(body=str(body)[:80]), self.assertRaises(checker.PublicationBlocked):
                self.invoke(Response(404, body))

    def test_token_errors_stop_before_manifest_lookup(self):
        for response in (Response(401, {'message': SECRET}), Response(403, {}), Response(429, {}),
                         Response(500, {}), Response(200, {}), Response(200, {'token': ''}),
                         Response(200, {'token': ['invalid']}), Response(200, {'token': 'bad token'}),
                         Response(200, b'not-json')):
            opener = Opener(response)
            with self.subTest(response=response.code), self.assertRaises(checker.PublicationBlocked) as caught:
                checker.assert_tag_absent('willitmod/fumbrel', '0.1.1-dev', 'test-user', SECRET, opener)
            self.assertEqual(len(opener.requests), 1)
            self.assertTrue(response.closed)
            self.assertNotIn(SECRET, str(caught.exception))

    def test_network_errors_at_either_request_fail_closed_without_secret_output(self):
        for failure in (urllib.error.URLError('network failed ' + SECRET), TimeoutError(SECRET), OSError(TOKEN)):
            for stage in ('token', 'manifest'):
                opener = Opener(failure) if stage == 'token' else Opener(Response(200, {'token': TOKEN}), failure)
                with self.subTest(stage=stage, failure=type(failure).__name__), self.assertRaises(checker.PublicationBlocked) as caught:
                    checker.assert_tag_absent('willitmod/fumbrel', '0.1.1-dev', 'test-user', SECRET, opener)
                self.assertNotIn(SECRET, str(caught.exception))
                self.assertNotIn(TOKEN, str(caught.exception))

    def test_urllib_http_error_404_is_classified_by_status_and_json(self):
        unknown = urllib.error.HTTPError('https://ghcr.io/v2/willitmod/fumbrel/manifests/0.1.1-dev', 404,
                                        'not-found ' + SECRET, {}, io.BytesIO(json.dumps({'errors': [{'code': 'MANIFEST_UNKNOWN'}]}).encode()))
        self.invoke(unknown)
        denied = urllib.error.HTTPError('https://ghcr.io/v2/willitmod/fumbrel/manifests/0.1.1-dev', 401,
                                       SECRET, {}, io.BytesIO(b'private-response'))
        with self.assertRaises(checker.PublicationBlocked):
            self.invoke(denied)

    def test_redirects_are_not_followed_with_credentials(self):
        self.assertIsNone(checker.NoRedirects().redirect_request(None, None, 302, 'redirect', {}, 'https://untrusted.example'))

    def test_missing_credentials_or_invalid_references_do_not_make_requests(self):
        cases = [('willitmod/fumbrel', '0.1.1-dev', '', SECRET), ('willitmod/fumbrel', '0.1.1-dev', 'test-user', ''),
                 ('willitmod/fumbrel/../other', '0.1.1-dev', 'test-user', SECRET), ('willitmod/fumbrel', '../old', 'test-user', SECRET)]
        for repository, tag, username, password in cases:
            opener = Opener()
            with self.subTest(repository=repository, tag=tag), self.assertRaises(checker.PublicationBlocked):
                checker.assert_tag_absent(repository, tag, username, password, opener)
            self.assertEqual(opener.requests, [])

    def test_cli_uses_environment_credentials_and_prints_only_sanitized_errors(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(checker.os.environ, {'GHCR_USERNAME': 'test-user', 'GHCR_PASSWORD': SECRET}), \
                patch.object(checker, 'assert_tag_absent', side_effect=checker.PublicationBlocked('Registry request failed; publication refused.')) as absent, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = checker.main(['--repository', 'willitmod/fumbrel', '--tag', '0.1.1-dev'])
        self.assertEqual(code, 1)
        absent.assert_called_once_with('willitmod/fumbrel', '0.1.1-dev', 'test-user', SECRET)
        self.assertEqual(stdout.getvalue(), '')
        for secret in (SECRET, TOKEN):
            self.assertNotIn(secret, stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
