"""Channel behaviour: CLI prompt parsing, the Slack v0 loop, and the ABC contract."""

from __future__ import annotations

import io

import pytest

from actionguard.channels.base import ApprovalChannel
from actionguard.channels.cli import CLIChannel
from actionguard.channels.slack import SlackChannel
from actionguard.core import Action, Decision


def _action() -> Action:
    return Action(tool_name="refund", args={"amount": 4000}, tool_description="Issue a refund.")


# ---- ABC contract -----------------------------------------------------------


def test_cannot_instantiate_abstract_channel():
    with pytest.raises(TypeError):
        ApprovalChannel()  # type: ignore[abstract]


def test_custom_channel_just_implements_one_method():
    class AlwaysYes(ApprovalChannel):
        name = "always-yes"

        def request_approval(self, action: Action) -> Decision:
            return Decision(approved=True, source=self.name)

    decision = AlwaysYes().request_approval(_action())
    assert decision.approved is True
    assert decision.source == "always-yes"


# ---- CLIChannel -------------------------------------------------------------


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("y", True),
        ("Y", True),
        ("yes", True),
        ("YES", True),
        ("  y  ", True),
        ("n", False),
        ("no", False),
        ("", False),  # empty => deny (safe default)
        ("maybe", False),
        ("nonsense", False),
    ],
)
def test_cli_channel_parses_answer(answer, expected):
    stream = io.StringIO()
    channel = CLIChannel(stream=stream, input_fn=lambda _prompt: answer)
    decision = channel.request_approval(_action())
    assert decision.approved is expected
    assert decision.source == "cli"


def test_cli_channel_shows_tool_and_args():
    stream = io.StringIO()
    channel = CLIChannel(stream=stream, input_fn=lambda _prompt: "n")
    channel.request_approval(_action())
    out = stream.getvalue()
    assert "refund" in out
    assert "amount" in out
    assert "4000" in out


def test_cli_channel_survives_non_utf8_console():
    # Windows consoles are cp1252 and cannot encode the banner's emoji/box chars.
    # The prompt must degrade gracefully, never crash with UnicodeEncodeError.
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", newline="")
    channel = CLIChannel(stream=stream, input_fn=lambda _p: "y")
    decision = channel.request_approval(_action())
    stream.flush()
    assert decision.approved is True
    assert raw.getvalue() != b""  # something was written, no exception raised


def test_cli_channel_sanitizes_control_chars_in_banner():
    # A tool name / arg key carrying terminal escapes must not be able to forge or
    # hide the banner the human decides on. Values are repr'd (also safe).
    stream = io.StringIO()
    evil = Action(
        tool_name="refund\x1b[2Kspoofed",
        args={"id\rkey": "x\x1b[31m"},
        tool_description="line1\x1b[2Jhidden",
    )
    CLIChannel(stream=stream, input_fn=lambda _p: "n").request_approval(evil)
    out = stream.getvalue()
    assert "\x1b" not in out  # no raw escape bytes reach the terminal
    assert "\\x1b" in out  # escaped form is shown instead


def test_cli_channel_sanitizes_malicious_repr_value():
    # repr() escapes control chars inside str values, but an *object* argument can carry
    # a custom __repr__ with raw terminal escapes. The banner must neutralize those too.
    class Evil:
        def __repr__(self):
            return "ok\x1b[2Khidden"

    stream = io.StringIO()
    action = Action(tool_name="t", args={"payload": Evil()}, tool_description="d")
    CLIChannel(stream=stream, input_fn=lambda _p: "n").request_approval(action)
    out = stream.getvalue()
    assert "\x1b" not in out  # no raw escape reaches the terminal
    assert "\\x1b" in out  # shown in escaped form


def test_cli_channel_eof_denies():
    def raise_eof(_prompt):
        raise EOFError

    stream = io.StringIO()
    channel = CLIChannel(stream=stream, input_fn=raise_eof)
    decision = channel.request_approval(_action())
    assert decision.approved is False


# ---- SlackChannel (v0) ------------------------------------------------------


class _FakeResponse:
    """A minimal requests-style response whose raise_for_status can be made to fail."""

    def __init__(self, error: Exception | None = None):
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error


class _FakeSession:
    def __init__(self, response: _FakeResponse | None = None):
        self.posts = []
        self._response = response if response is not None else _FakeResponse()

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json, timeout))
        return self._response


def test_slack_posts_and_polls_for_decision():
    session = _FakeSession()
    answers = [None, None, Decision(approved=True)]

    def poll(_action):
        return answers.pop(0)

    channel = SlackChannel(
        "https://hooks.slack.test/abc",
        poll_fn=poll,
        timeout=5,
        poll_interval=0,  # don't actually sleep between polls
        session=session,
    )
    decision = channel.request_approval(_action())

    assert decision.approved is True
    assert decision.source == "slack"  # source backfilled
    assert len(session.posts) == 1
    url, payload, timeout = session.posts[0]
    assert url == "https://hooks.slack.test/abc"
    assert "refund" in payload["text"]
    assert timeout is not None  # a network timeout is always set on the POST


def test_slack_times_out_to_deny_by_default():
    session = _FakeSession()
    channel = SlackChannel(
        "https://hooks.slack.test/abc",
        poll_fn=lambda _a: None,  # never answers
        timeout=0,  # immediate timeout
        poll_interval=0,
        session=session,
    )
    decision = channel.request_approval(_action())
    assert decision.approved is False
    assert "no response" in (decision.comment or "")


def test_slack_timeout_can_default_to_approve():
    session = _FakeSession()
    channel = SlackChannel(
        "https://hooks.slack.test/abc",
        poll_fn=lambda _a: None,
        timeout=0,
        poll_interval=0,
        on_timeout="approve",
        session=session,
    )
    assert channel.request_approval(_action()).approved is True


def test_slack_rejects_bad_on_timeout():
    with pytest.raises(ValueError):
        SlackChannel("https://x", on_timeout="sometimes")


def test_slack_fails_closed_when_webhook_post_fails():
    # A 4xx/5xx from the webhook means the human never saw the request. We must not fall
    # through to polling/approving as if they had — raise_for_status propagates, and the
    # channel never consults poll_fn.
    session = _FakeSession(response=_FakeResponse(error=RuntimeError("HTTP 404")))
    polled = []

    def poll(_a):
        polled.append(_a)
        return Decision(approved=True)

    channel = SlackChannel(
        "https://hooks.slack.test/abc",
        poll_fn=poll,
        timeout=5,
        poll_interval=0,
        session=session,
    )
    with pytest.raises(RuntimeError, match="404"):
        channel.request_approval(_action())
    assert polled == []  # delivery failed => decision was never solicited


def test_slack_escapes_backticks_and_metachars_in_values():
    # A backtick in an argument value must not break out of its inline-code span and
    # forge the approval message; Slack metacharacters are escaped too.
    session = _FakeSession()
    evil = Action(
        tool_name="refund",
        args={"note": "`*pwned*` <script> & co"},
        tool_description="x",
    )
    SlackChannel("https://x", timeout=0, poll_interval=0, session=session).request_approval(evil)
    text = session.posts[0][1]["text"]
    assert "`*pwned*`" not in text  # raw backtick pair cannot survive into the message
    assert "&amp;" in text and "&lt;script&gt;" in text  # metacharacters escaped
