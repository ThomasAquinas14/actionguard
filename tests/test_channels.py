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


def test_cli_channel_eof_denies():
    def raise_eof(_prompt):
        raise EOFError

    stream = io.StringIO()
    channel = CLIChannel(stream=stream, input_fn=raise_eof)
    decision = channel.request_approval(_action())
    assert decision.approved is False


# ---- SlackChannel (v0) ------------------------------------------------------


class _FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, json=None):
        self.posts.append((url, json))
        return None


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
    url, payload = session.posts[0]
    assert url == "https://hooks.slack.test/abc"
    assert "refund" in payload["text"]


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
