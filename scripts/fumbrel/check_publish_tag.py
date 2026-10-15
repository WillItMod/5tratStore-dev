#!/usr/bin/env python3
"""Refuse GHCR publication unless the authenticated tag lookup proves absence.

Credentials come only from GHCR_USERNAME/GHCR_PASSWORD in the process environment.
Do not print tokens, request headers, raw responses or underlying exceptions.
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

REGISTRY = 'https://ghcr.io'
MAX_RESPONSE = 64 * 1024
ACCEPT = ', '.join((
    'application/vnd.oci.image.index.v1+json',
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
    'application/vnd.docker.distribution.manifest.v2+json',
))


class PublicationBlocked(Exception):
    pass


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def request(opener, url, headers):
    try:
        return opener.open(urllib.request.Request(url, headers=headers), timeout=15)
    except urllib.error.HTTPError as error:
        # Inspect the HTTP status and bounded error document, never its text.
        return error
    except Exception:
        raise PublicationBlocked('Registry request failed; publication refused.') from None


def document(response):
    try:
        body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise ValueError()
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except Exception:
        raise PublicationBlocked('Registry response is not a valid bounded document; publication refused.') from None


def assert_tag_absent(repository, tag, username, password, opener=None):
    if (not re.fullmatch(r'[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+', repository)
            or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tag)):
        raise PublicationBlocked('Invalid candidate reference; publication refused.')
    if not username or not password:
        raise PublicationBlocked('Registry credentials are required; publication refused.')
    opener = opener or urllib.request.build_opener(NoRedirects())
    auth = base64.b64encode((username + ':' + password).encode()).decode()
    query = urllib.parse.urlencode({'service': 'ghcr.io', 'scope': 'repository:' + repository + ':pull'})
    token_response = request(opener, REGISTRY + '/token?' + query, {'Authorization': 'Basic ' + auth})
    try:
        if token_response.code != 200:
            raise PublicationBlocked('Registry authentication failed; publication refused.')
        token_document = document(token_response)
        token = token_document.get('token') or token_document.get('access_token')
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise PublicationBlocked('Registry authentication returned no valid token; publication refused.')
    finally:
        token_response.close()
    response = request(opener, REGISTRY + '/v2/' + repository + '/manifests/' + tag,
                       {'Authorization': 'Bearer ' + token, 'Accept': ACCEPT})
    try:
        if response.code == 200:
            raise PublicationBlocked('Candidate tag already exists; publication refused.')
        if response.code != 404:
            raise PublicationBlocked('Registry did not prove candidate absence; publication refused.')
        errors = document(response).get('errors')
        if (not isinstance(errors, list) or not errors
                or any(not isinstance(error, dict) or error.get('code') != 'MANIFEST_UNKNOWN' for error in errors)):
            raise PublicationBlocked('Registry did not report MANIFEST_UNKNOWN; publication refused.')
    finally:
        response.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', default='willitmod/fumbrel')
    parser.add_argument('--tag', default='0.1.2-dev')
    args = parser.parse_args(argv)
    try:
        assert_tag_absent(args.repository, args.tag, os.environ.get('GHCR_USERNAME'), os.environ.get('GHCR_PASSWORD'))
    except PublicationBlocked as error:
        print(str(error), file=sys.stderr)
        return 1
    print('Authenticated registry lookup confirmed MANIFEST_UNKNOWN; candidate tag is absent.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
