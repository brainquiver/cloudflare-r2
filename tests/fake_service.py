"""A fake S3 service at the HTTP edge, so the real signer and the real parsers run.

The fake replaces urllib.request.urlopen and nothing above it. A test declares routes, each
with a method, an exact path and the query keys that it needs. The fake records every call. A
call that matches no route fails the test, so the suite can never reach the network.
"""
import io
import urllib.error
import urllib.parse
from dataclasses import dataclass, field
from email.message import Message

NS = "http://s3.amazonaws.com/doc/2006-03-01/"


@dataclass
class Call:
    """One request as the service received it, with the header names in lower case."""

    method: str
    path: str
    query: dict
    headers: dict
    body: bytes


class Reply:
    """One scripted response: a status, a body and the headers."""

    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        self.body = body
        self.headers = Message()
        for name, value in (headers or {}).items():
            self.headers[name] = value
        self._stream = io.BytesIO(body)

    def read(self, size=-1):
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@dataclass
class Transport:
    """Routes calls to scripted replies, and keeps every call in order."""

    calls: list = field(default_factory=list)
    routes: list = field(default_factory=list)

    def on(self, method, path, reply, query=()):
        """Answer a call with this method and path that carries every key in query.

        A route with no query keys matches only a call without a query string. A route for the
        PUT of an object therefore never answers the PUT of one part of a multipart upload. A
        later route has priority over an earlier one.
        """
        self.routes.append((method, path, frozenset(query), reply))

    def __call__(self, request, timeout=None):
        url = urllib.parse.urlsplit(request.full_url)
        data = request.data.read() if hasattr(request.data, "read") else request.data
        call = Call(
            method=request.get_method(),
            path=urllib.parse.unquote(url.path),
            query=dict(urllib.parse.parse_qsl(url.query, keep_blank_values=True)),
            headers={k.lower(): v for k, v in request.header_items()},
            body=data or b"",
        )
        self.calls.append(call)
        for method, path, keys, reply in reversed(self.routes):
            if method != call.method or path != call.path:
                continue
            if keys and not keys <= call.query.keys():
                continue
            if not keys and call.query:
                continue
            answer = reply(call) if callable(reply) else reply
            if answer.status >= 400:
                raise urllib.error.HTTPError(
                    request.full_url, answer.status, "fake", answer.headers,
                    io.BytesIO(answer.body))
            return answer
        raise AssertionError(f"no route for {call.method} {request.full_url}")

    def find(self, method, path, query_key=None):
        """Every recorded call with this method and path, and the query key when one is given."""
        return [c for c in self.calls
                if c.method == method and c.path == path
                and (query_key is None or query_key in c.query)]


def listing(objects):
    """A one-page ListObjectsV2 reply that holds these (key, size) pairs."""
    rows = "".join(f"<Contents><Key>{k}</Key><Size>{s}</Size></Contents>" for k, s in objects)
    body = (f'<ListBucketResult xmlns="{NS}">{rows}'
            "<IsTruncated>false</IsTruncated></ListBucketResult>")
    return Reply(200, body.encode())


def error(status, code):
    """An S3 error reply that carries this code in its XML body."""
    return Reply(status, f"<Error><Code>{code}</Code><Message>m</Message></Error>".encode())
