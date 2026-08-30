"""Where a conversation happens.

A messaging platform is an interface, not the thing. The account can be lost and
the terminal can be closed; identity and memory live in one file that does not
know which is in use.
"""

from __future__ import annotations

import json
import time

from hearth_friend.adapters.qq import OneBotChannel, QQAdapter, extract_text
from hearth_friend.core.conversation import Conversation


class Recorder:
    def __init__(self):
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)


class FakeRuntime:
    def __init__(self, reply: list[str]):
        self.heard: list[str] = []
        self._reply = reply
        self.answered = False

    def ingest(self, text: str) -> None:
        self.heard.append(text)

    def unanswered(self):
        return [] if self.answered else self.heard

    def reply(self):
        self.answered = True
        return iter(self._reply)


# --- what arrives -----------------------------------------------------------


def test_a_message_arrives_as_a_string_or_as_segments():
    assert extract_text({"message": "直接是字符串"}) == "直接是字符串"
    assert extract_text({"message": [
        {"type": "text", "data": {"text": "分段的"}},
        {"type": "text", "data": {"text": "文本"}},
    ]}) == "分段的文本"


def test_an_emoticon_is_part_of_the_sentence_and_is_read():
    """「行吧[撇嘴]」 does not mean what 「行吧」 means."""
    assert extract_text({"message": [
        {"type": "text", "data": {"text": "行吧"}},
        {"type": "face", "data": {"id": "1"}},
    ]}) == "行吧[撇嘴]"
    assert "[表情]" in extract_text(
        {"message": [{"type": "face", "data": {"id": "99999"}}]}
    )


def test_a_sticker_carries_its_own_label_and_the_label_is_kept():
    assert extract_text({"message": [
        {"type": "image", "data": {"summary": "[开心]", "sub_type": "1"}}
    ]}) == "[表情包：开心]"


def test_a_photograph_is_recorded_as_arriving_and_as_unseen():
    """Dropping it silently meant he could send a picture and be met with
    nothing at all, which is worse than being told she cannot see it. Saying
    what she cannot see is honest; describing it would not be."""
    read = extract_text({"message": [
        {"type": "image", "data": {"url": "http://x/1.jpg", "sub_type": "0"}},
        {"type": "text", "data": {"text": " 你看这个"}},
    ]})
    assert "看不到内容" in read
    assert "你看这个" in read


def test_only_his_messages_are_read_at_all():
    """A friend is not a service, and this one belongs to somebody."""
    runtime = FakeRuntime(["ok"])
    conversation = Conversation(runtime, Recorder())
    adapter = QQAdapter(conversation, "ws://x", user_id=111)

    adapter._handle(json.dumps({
        "post_type": "message", "message_type": "private",
        "user_id": 111, "message": "他说的",
    }))
    adapter._handle(json.dumps({
        "post_type": "message", "message_type": "private",
        "user_id": 999, "message": "别人说的",
    }))
    adapter._handle(json.dumps({
        "post_type": "message", "message_type": "group",
        "user_id": 111, "message": "群里说的",
    }))
    adapter._handle("not json at all")

    assert runtime.heard == ["他说的"]


def test_sending_goes_out_as_a_onebot_action():
    payloads = []
    channel = OneBotChannel(payloads.append, user_id=111)
    channel.send("在的")
    channel.send("   ")

    assert len(payloads) == 1
    assert payloads[0]["action"] == "send_private_msg"
    assert payloads[0]["params"] == {"user_id": 111, "message": "在的"}


# --- the loop ---------------------------------------------------------------


def test_a_burst_gets_one_answer_once_he_has_stopped():
    runtime = FakeRuntime(["嗯", "我在"])
    recorder = Recorder()
    conversation = Conversation(
        runtime, recorder, settle_seconds=0.15, pause_seconds=0.0
    )

    for line in ("在吗", "不回我", "在忙吗"):
        conversation.heard(line)
    assert recorder.sent == [], "not while he is still talking"

    time.sleep(0.2)
    conversation.speak_once()
    assert recorder.sent == ["嗯", "我在"]
    assert runtime.heard == ["在吗", "不回我", "在忙吗"]


def test_she_does_not_start_another_block_the_moment_she_finishes():
    """Anything sent while she was composing finds the window already elapsed,
    and would land stacked on what she just said."""
    runtime = FakeRuntime(["说完了"])
    conversation = Conversation(runtime, Recorder(), settle_seconds=0.3)
    conversation.heard("一句话")
    time.sleep(0.35)

    conversation.speak_once()
    runtime.answered = False  # something arrived mid-reply
    assert not conversation._ready(), "she has only just stopped talking"


def test_a_provider_failure_does_not_take_the_conversation_down():
    class Broken(FakeRuntime):
        def reply(self):
            raise RuntimeError("provider is down")

    problems = []
    conversation = Conversation(
        Broken([]), Recorder(), on_error=problems.append
    )
    conversation.heard("在吗")
    assert conversation.speak_once() == 0
    assert problems == ["provider is down"]


# --- looking ----------------------------------------------------------------


def test_a_photograph_becomes_words_before_it_enters_the_conversation():
    """What she saw is written into the log as text, so it is remembered,
    recalled and forgotten like anything else that was said -- rather than
    being a URL that expires."""
    from hearth_friend.adapters.qq import read_message

    read = read_message(
        {"message": [
            {"type": "image", "data": {"url": "http://x/1.jpg", "sub_type": "0"}},
            {"type": "text", "data": {"text": " 这是QB"}},
        ]},
        describe=lambda url: "一只黑白花猫趴在竹床边",
    )
    assert "[他发了张图：一只黑白花猫趴在竹床边]" in read
    assert "这是QB" in read


def test_not_being_able_to_look_is_said_rather_than_hidden():
    from hearth_friend.adapters.qq import read_message

    read = read_message(
        {"message": [{"type": "image", "data": {"url": "http://x/1.jpg", "sub_type": "0"}}]},
        describe=lambda url: None,
    )
    assert "看不到内容" in read


def test_a_sticker_is_not_sent_to_be_looked_at():
    """It already says what it is, and looking costs a call."""
    from hearth_friend.adapters.qq import read_message

    looked = []
    read_message(
        {"message": [{"type": "image", "data": {"summary": "[开心]", "sub_type": "1"}}]},
        describe=lambda url: looked.append(url),
    )
    assert looked == []


def test_an_image_with_no_address_is_not_fetched():
    from hearth_friend.adapters.qq import read_message

    def explode(url):
        raise AssertionError("should not have tried to fetch")

    assert "看不到内容" in read_message(
        {"message": [{"type": "image", "data": {"sub_type": "0"}}]}, describe=explode
    )
