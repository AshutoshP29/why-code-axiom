# WhyCode evaluation: psf/requests

Measured 2026-10-30 with `scripts/evaluate.py` on the graph as it is (181 decisions). No LLM calls; every question goes through the same code as `POST /api/ask`, with no item picked.

| What | Result |
|---|---|
| Named code with a decision: matched to the right item | 72/76 (95%) |
| ... and answered | 73/76 (96%) |
| ... answers whose every evidence step links to its source | 73/73 (100%) |
| ... whose decision replaced an older one: answered naming the older one | 16/16 (100%) |
| Named code no decision explains: matched | 476/481 (99%) |
| ... refused (facts only, no reason given) | 481/481 (100%) |
| Off-topic questions refused | 10/10 (100%) |
| Cited quotes found verbatim in the original GitHub text | 261/261 (100%) |
| Supersession links (checked by hand below) | 10 |

Not measured: the LLM-only and vector-RAG baselines (they need LLM calls).

## Supersession links

| Kind | Newer decision | Older decision |
|---|---|---|
| refines (0.90) | 2014-05-12: Catch decoding errors when handling redirects by moving response content reading from Adap | 2014-03-16: Merge RuntimeError handling with other redirect exceptions in resolve_redirects |
| refines (0.95) | 2016-03-05: Move test_chunked_upload to test_lowlevel.py | 2016-03-04: Create a dedicated tests/test_lowlevel.py file for socket-level tests |
| refines (0.80) | 2016-04-11: Add a basic socket server implementation for testing chunked transfer encoding | 2015-11-25: Name the test socket server package 'testserver' instead of 'dummyserver' |
| refines (0.97) | 2016-08-11: Split combined header‑removal test into two separate tests | 2016-08-10: Add tests for header removal on redirect |
| refines (0.92) | 2016-09-05: Do not replace hasattr checks with seekable method in super_len | 2016-08-24: Require both 'seek' and 'tell' attributes together in super_len conditional |
| refines (0.80) | 2017-02-23: Make TimedCache inherit collections.MutableMapping | 2017-02-22: Replace internal storage with OrderedDict |
| refines (0.90) | 2021-07-26: Standardize the exception raised by Response.json() to a single requests.JSONDecodeError | 2021-07-03: Introduce a unified JSONDecodeError exception class |
| replaces (0.90) | 2016-12-12: Redirect handling updated to strip bodies only for GET requests after method change and re | 2016-08-12: Remove Content-Type and Transfer-Encoding headers on redirect |
| replaces (0.95) | 2021-05-28: Add an extra `use_chardet_on_py3` to allow installing chardet on Python 3 | 2021-04-22: Add a new extra `requests[lgpl]` to allow installing chardet as an optional dependency |
| reverses (0.99) | 2020-01-21: Revert to manual socket close for Python 2.7 compatibility in test server | 2019-11-27: Use a context manager to ensure accepted sockets are closed in the test server |

## Named questions matched to a different item

Most are a different item with the very same name in another file: the question
alone cannot say which one is meant (picking the item in the UI does).

- Why does Url work this way? -> Url in requests/packages/urllib3/util/url.py, not requests/packages/urllib3/util.py (same name, another file)
- Why does to_native_string work this way? -> to_native_string in src/requests/utils.py, not src/requests/_internal_utils.py (same name, another file)
- Why does SOCKSProxyManager work this way? -> SOCKSProxyManager in requests/packages/urllib3/contrib/socks.py, not src/requests/adapters.py (same name, another file)
- Why does request work this way? -> Request in src/requests/models.py, not src/requests/api.py
- Why does ConnectionError work this way? -> ConnectionError in src/requests/exceptions.py, not requests/packages/urllib3/connection.py (same name, another file)
- Why does Session work this way? -> session in src/requests/sessions.py, not src/requests/sessions.py
- Why does VerifiedHTTPSConnection.connect work this way? -> VerifiedHTTPSConnection.connect in requests/packages/urllib3/connection.py, not requests/packages/urllib3/connectionpool.py (same name, another file)
- Why does parse_url work this way? -> parse_url in requests/packages/urllib3/util/url.py, not requests/packages/urllib3/util.py (same name, another file)
- Why does u work this way? -> u in tests/test_requests.py, not tests/compat.py (same name, another file)
