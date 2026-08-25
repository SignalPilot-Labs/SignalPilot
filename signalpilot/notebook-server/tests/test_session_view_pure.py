"""Regression guards for session construction latency and API shape.

SessionView.__init__ once fetched every gateway connection schema inline
(~2s each, sequential), so each session/static-payload build stalled for
tens of seconds. And SessionImpl.document is easy to lose silently: the
Session protocol declares a ``document`` member whose default body returns
None, so a subclass that drops the property still imports and passes any
test that never reads a real document.
"""

from __future__ import annotations

import inspect


def test_session_view_constructor_is_pure() -> None:
    """SessionView() must not perform network I/O.

    Gateway connections are loaded by load_gateway_connections() from a
    background thread (see Session._prefetch_gateway_connections), never
    by the constructor.
    """
    import urllib.request
    from unittest import mock

    # Import plugins.ui first: importing session_view as the very first
    # signalpilot module trips the pre-existing get_datasets ↔ plugins.ui
    # import cycle.
    import signalpilot._plugins.ui  # noqa: F401
    from signalpilot._session.state.session_view import SessionView

    def _no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("SessionView.__init__ performed network I/O")

    with mock.patch.object(urllib.request, "urlopen", _no_network):
        view = SessionView()
    assert view.data_connectors.connections == []


def test_session_impl_document_is_a_property() -> None:
    """SessionImpl.document must be a concrete property.

    If it is lost, attribute lookup falls back to the Session protocol's
    stub and returns None, which breaks kernel-ready (WS connect fails
    with `'NoneType' object has no attribute 'cells'`).
    """
    from signalpilot._session.session import SessionImpl

    attr = inspect.getattr_static(SessionImpl, "document")
    assert isinstance(attr, property)
