"""Unused-attribute shortcut must retain the runtime parser's exact text/state."""

import random
from html.parser import HTMLParser

import pytest

from structural_break.intelligence.evidence import _TextParser


class RuntimeTextParser(_TextParser):
    parse_starttag = HTMLParser.parse_starttag


def parse(parts: list[str], parser_type: type[_TextParser]) -> tuple[object, ...]:
    parser = parser_type()
    for part in parts:
        parser.feed(part)
    parser.close()
    return (
        parser.lines,
        parser.skip,
        parser.rawdata,
        parser.lasttag,
        parser.getpos(),
        parser.get_starttag_text(),
        parser.cdata_elem,
    )


CASES = [
    '<div CLASS="a &amp; b" disabled data-x=foo><p>Earnings &gt; forecast</p></div>',
    '<table><tr><td style="color:red">Margin</td><th>Loss</th></tr></table>',
    '<ix:hidden><ix:nonnumeric name="x">Hidden</ix:nonnumeric></ix:hidden><p>Visible</p>',
    "<head><title>Not visible &amp; text</title><meta name=x></head><body>Visible</body>",
    '<script>var a="<p>ignore &amp;</p>";</script><style>x<b</style><p>Visible</p>',
    "<textarea><b>literal &amp;</b></textarea><title>&lt;x&gt;</title><p>After</p>",
    "<noscript><div>fallback</div></noscript><plaintext><p>literal</p>",
    "<xmp><p>literal</p></xmp><iframe>hidden?</iframe><p>After</p>",
    '<div a="quoted > slash /" b=bare c= d e="" f=\'&bad;\'>Text</div>',
    "<div a=one/b><span/x=y>Text</span></div>",
    '<DIV / x=y / / ><br/><hr / ><img src="&quot;">After</DIV>',
    '<div a="bad"extra="value"><p a="x"\x00=bad>Text</p></div>',
    "<div a='unterminated><p>Text",
    '<div a="x" /garbage>text</div>',
    '<div a="x" "/">text</div>',
    '<div a="x"/ ><p>text</p></div>',
    '<div a="x" /=y>text</div>',
    '<div a="x"\u00a0b=y>text</div>',
    '<div a="x"\v b=y>text</div>',
    "<div><!----><!--broken--!><![CDATA[x]]><?test?><!DOCTYPE HTML>Text</div>",
    "<head/><p>Text</p><ix:hidden/><p>After</p>",
    '<div a="x"><br a="x"/><span><b>Text</b></span></div>trailing &amp',
]


@pytest.mark.parametrize("body", CASES)
def test_shortcut_preserves_every_feed_boundary(body: str) -> None:
    for index in range(len(body) + 1):
        parts = [body[:index], body[index:]]
        assert parse(parts, _TextParser) == parse(parts, RuntimeTextParser)
    parts = list(body)
    assert parse(parts, _TextParser) == parse(parts, RuntimeTextParser)


def test_generated_tolerant_and_malformed_attributes_match_runtime() -> None:
    randomizer = random.Random(84311)
    alphabet = "abXY012 =/\t\n\r\f\v<>'\"&;:\x00\u00a0"
    tags = ["div", "span", "ix:hidden", "p", "td", "head", "script", "textarea", "other"]
    for _ in range(4000):
        tag = randomizer.choice(tags)
        attributes = "".join(randomizer.choices(alphabet, k=randomizer.randrange(60)))
        body = f"Before<{tag} {attributes}>Revenue &amp; margin</{tag}>After"
        index = randomizer.randrange(len(body) + 1)
        parts = [body[:index], body[index:]]
        assert parse(parts, _TextParser) == parse(parts, RuntimeTextParser)
