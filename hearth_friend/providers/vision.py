"""Seeing.

An image becomes words before it enters the conversation, and the words are
what gets written to the turn log. Everything downstream -- memory, recall,
attention -- then works on it unchanged, and what she saw is as searchable and
as forgettable as anything else that was said.

The description is her own account of looking at it, not a caption. "他发了张
他猫趴在键盘上的照片" is something that can be remembered; "a cat on a keyboard"
is metadata.
"""

from __future__ import annotations

import base64
import urllib.error
import urllib.request

from hearth_friend.providers.base import ProviderError

MAX_IMAGE_BYTES = 8 * 1024 * 1024
FETCH_TIMEOUT = 20.0

_INSTRUCTION = """用中文说这张图里是什么，像跟朋友转述一样。

长度跟着图里的东西走，不要固定：
- 一张随手拍、一个表情包，一句话就够
- 信息密的（截图、白板、文档、图表、一堆字）就写长一点，把要紧的都说出来，
  该读的字要读出来、该抄的数要抄下来——**这句话是以后唯一留下的东西，
  这里没写的就等于没看过**
- 最多两百字

- 是照片就说看到了什么；是截图就说截的是什么；是表情包就说画的是什么、什么语气
- 不要评价、不要抒情、不要说"这张图片展示了"
只输出转述本身。"""


def fetch_image(url: str, *, timeout: float = FETCH_TIMEOUT) -> tuple[bytes, str] | None:
    """Bytes and mime type, or nothing.

    Fetched here rather than handed to the model as a link: a QQ image URL is
    not reliably reachable from outside, and this way the picture never has to
    be publicly readable for her to see it.
    """
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "hearth-friend/0.0.1"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            mime = response.headers.get_content_type() or "image/jpeg"
            data = response.read(MAX_IMAGE_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    if not mime.startswith("image/"):
        mime = "image/jpeg"
    return data, mime


def describe(provider, url: str, *, model: str) -> str | None:
    """What she sees, in a sentence. None if she could not look."""
    fetched = fetch_image(url)
    if not fetched:
        return None
    data, mime = fetched

    encoded = base64.b64encode(data).decode("ascii")
    messages = [
        {"role": "system", "content": _INSTRUCTION},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
            ],
        },
    ]
    try:
        seen = provider.generate(messages, temperature=0.2, model=model)
    except ProviderError:
        # She could not look this time. Not being able to see is a thing she
        # says, not an error to raise at him. Narrow on purpose: a bare except
        # here hid a missing dependency twice already.
        return None
    seen = (seen or "").strip().replace("\n", " ")
    return _trim(seen) or None


# Long enough to hold what a dense image contains -- a dashboard's numbers, a
# whiteboard's working. What is not in here is gone: this is the only trace the
# picture leaves, and every later turn reads it, so it cannot be unbounded
# either.
MAX_DESCRIPTION_CHARS = 500


def _trim(text: str) -> str:
    """Cut at the end of a sentence, not in the middle of a word."""
    if len(text) <= MAX_DESCRIPTION_CHARS:
        return text
    window = text[:MAX_DESCRIPTION_CHARS]
    for mark in ("。", "；", "，", " "):
        cut = window.rfind(mark)
        if cut > MAX_DESCRIPTION_CHARS * 0.6:
            return window[: cut + 1].rstrip("，； ")
    return window
