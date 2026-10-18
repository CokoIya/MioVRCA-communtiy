#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only OR PolyForm-Noncommercial-1.0.0
# Copyright (c) 2026 天川澪 (Coko_Iya). Part of MioVRCA: https://github.com/CokoIya/MioVRC_AssetManager (terms in LICENSE.md)
"""社区的规则：名片、作品和链接怎样才算有效。

这是 MioVRCA 程序中 internal/socialapi/rules.go 的 Python 版：同样的上限、同样的错误码和提示文字。程序在发出名片或
作品之前用 rules.go 检查一次，收录时工作流再用这里检查一次。两边是否一致，由 tests/test_rules.py 核对程序测试写出的
用例（internal/socialapi/testdata/cases.json）。

网址按 Go 的 net/url 的方式解析和整理（同一个链接两边整理出的结果相同）。只用 Python 标准库。
"""
import binascii
import ipaddress
import re
import unicodedata

# ---------- 上限 ----------
MAX_NICKNAME = 24
MAX_BIO = 300
MAX_BIO_LINES = 8
MAX_TITLE = 60
MAX_DESC = 1000
MAX_DESC_LINES = 30
MAX_BASE_NAME = 24
MAX_BASES = 5
MAX_LANGS = 5
MAX_LINKS = 8
MAX_LINK_LABEL = 24
MAX_URL = 300
MAX_ASSETS = 30
MAX_ASSET_NAME = 80
MAX_SHOP_NAME = 40
MAX_RECIPE = 16 << 10
MAX_FOLLOWING = 2000
MAX_AVATAR_B64 = 64 << 10
MAX_COVER_B64 = 128 << 10

# ---------- 错误 ----------
ERR_BAD_REQUEST = "bad_request"
ERR_BAD_LOGIN = "bad_login"
ERR_BAD_TEXT = "bad_text"
ERR_TOO_LONG = "too_long"
ERR_BAD_LINK = "bad_link"
ERR_BAD_VIDEO = "bad_video"
ERR_BAD_RECIPE = "bad_recipe"
ERR_BAD_IMAGE = "bad_image"
ERR_RIGHTS = "rights"
ERR_BANNED_WORDS = "banned_words"

MESSAGES = {
    ERR_BAD_REQUEST: "内容有误",
    ERR_BAD_LOGIN: "GitHub 用户名不正确",
    ERR_BAD_TEXT: "内容包含无法使用的字符",
    ERR_TOO_LONG: "内容过长",
    ERR_BAD_LINK: "链接格式不正确",
    ERR_BAD_VIDEO: "视频链接需来自哔哩哔哩、YouTube、X、抖音、小红书、niconico 或 TikTok",
    ERR_BAD_RECIPE: "装配方案的分享码无效",
    ERR_BAD_IMAGE: "无法读取图片：请使用 JPG 或 PNG",
    ERR_RIGHTS: "附带网盘链接时，请确认你有权分享其中的内容",
    ERR_BANNED_WORDS: "内容包含不允许使用的词语",
}


class RuleError(ValueError):
    """规则拒绝了内容：code 是错误码，str() 是给提交者看的文字。"""

    def __init__(self, code, msg=""):
        self.code, self.msg = code, msg
        super().__init__(self.text())

    def text(self):
        return self.msg or MESSAGES.get(self.code) or self.code

    def __str__(self):
        return self.text()


def fail(code, msg=""):
    return RuleError(code, msg)


# ---------- Go 的小工具 ----------
# Go 的 strings.TrimSpace 去掉的空白（unicode.IsSpace）。Python 的 strip() 还会去掉 \x1c–\x1f，不能直接用。
GO_SPACE = "\t\n\v\f\r \x85\xa0                　"
_UPPER = {ord(c): ord(c) + 32 for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}


def go_trim(s):
    return s.strip(GO_SPACE)


def ascii_lower(s):
    return s.translate(_UPPER)


def _utf8_len(s):
    return len(s.encode("utf-8", "surrogatepass"))


def _valid_text(s):
    return isinstance(s, str) and not any(0xD800 <= ord(c) <= 0xDFFF for c in s)


def _str(v, what="内容"):
    """JSON 里的一个字符串栏（null 当作空）。"""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise fail(ERR_BAD_REQUEST)
    return v


def _list(v):
    if v is None:
        return []
    if not isinstance(v, list):
        raise fail(ERR_BAD_REQUEST)
    return v


def clip(s, n):
    return s if len(s) <= n else s[:n] + "…"


# ---------- GitHub 用户名 ----------
RE_LOGIN = re.compile(r"[a-z0-9](?:[a-z0-9]|-[a-z0-9]){0,38}")


def norm_login(s):
    """用户名（文件按小写的用户名命名）。"""
    if not isinstance(s, str):
        raise fail(ERR_BAD_LOGIN)
    l = ascii_lower(go_trim(s))
    if len(l) > 39 or not RE_LOGIN.fullmatch(l):
        raise fail(ERR_BAD_LOGIN)
    return l


# ---------- 文字 ----------
def clean_text(s, most, multiline, lines):
    """去掉首尾空白、\\r\\n 换成 \\n；含有控制字符、方向控制符、BOM，超过 most 个字或（多行时）超过 lines 行时拒绝。"""
    if not _valid_text(s):
        raise fail(ERR_BAD_TEXT)
    s = go_trim(s.replace("\r\n", "\n"))
    for c in s:
        if c == "\n":
            if not multiline:
                raise fail(ERR_BAD_TEXT)
        elif c == "\t":
            pass
        elif unicodedata.category(c) == "Cc" or c == "﻿" or "‪" <= c <= "‮" or "⁦" <= c <= "⁩":
            raise fail(ERR_BAD_TEXT)
    if len(s) > most:
        raise fail(ERR_TOO_LONG)
    if multiline and lines > 0 and s.count("\n") + 1 > lines:
        raise fail(ERR_TOO_LONG)
    return s


# ---------- 网址（按 Go 的 net/url） ----------
HEX = "0123456789abcdefABCDEF"
RE_PORT = re.compile(r"[0-9]*")


class URL:
    __slots__ = ("scheme", "opaque", "user", "host", "port", "raw_path", "raw_query", "force_query", "raw_fragment")

    def __init__(self):
        self.scheme = self.opaque = self.host = self.port = self.raw_path = self.raw_query = ""
        self.user = self.force_query = False
        self.raw_fragment = None

    def escaped_path(self):
        return _escaped(self.raw_path, "path")

    def fragment(self):
        return "" if self.raw_fragment is None else _unescape(self.raw_fragment.encode("utf-8")).decode("utf-8", "surrogateescape")

    def string(self):
        out = self.scheme + "://" + self.host + self.escaped_path()
        if self.force_query or self.raw_query:
            out += "?" + self.raw_query
        if self.raw_fragment:
            out += "#" + _escaped(self.raw_fragment, "fragment")
        return out

    def query_get(self, name):
        """url.Values.Get：第一个同名参数的值。"""
        for pair in self.raw_query.split("&"):
            if ";" in pair or not pair:
                continue
            k, _, v = pair.partition("=")
            try:
                k, v = _query_unescape(k), _query_unescape(v)
            except ValueError:
                continue
            if k == name:
                return v
        return ""


def _unescape(b):
    """%XX 换成字节；% 后面不是两个十六进制数字时出错。"""
    out = bytearray()
    i = 0
    while i < len(b):
        c = b[i]
        if c == 0x25:  # %
            if i + 2 >= len(b) or chr(b[i + 1]) not in HEX or chr(b[i + 2]) not in HEX:
                raise ValueError("invalid URL escape")
            out.append(int(b[i + 1:i + 3], 16))
            i += 3
        else:
            out.append(c)
            i += 1
    return bytes(out)


def _query_unescape(s):
    b = s.encode("utf-8", "surrogateescape")
    b = b.replace(b"+", b" ")
    return _unescape(b).decode("utf-8", "surrogateescape")


def _should_escape(c, mode):
    ch = chr(c)
    if "a" <= ch <= "z" or "A" <= ch <= "Z" or "0" <= ch <= "9":
        return False
    if ch in "-_.~":
        return False
    if ch in "$&+,/:;=?@":
        if mode == "path":
            return ch == "?"
        if mode == "fragment":
            return False
    if mode == "fragment" and ch in "!()*":
        return False
    return True


def _valid_encoded(b, mode):
    for c in b:
        ch = chr(c)
        if ch in "!$&'()*+,;=:@[]%":
            continue
        if _should_escape(c, mode):
            return False
    return True


def _escape(b, mode):
    return "".join("%%%02X" % c if _should_escape(c, mode) else chr(c) for c in b)


def _escaped(raw, mode):
    b = raw.encode("utf-8", "surrogateescape")
    decoded = _unescape(b)
    if _valid_encoded(b, mode):
        return raw
    return _escape(decoded, mode)


def _get_scheme(raw):
    for i, ch in enumerate(raw):
        if "a" <= ch <= "z" or "A" <= ch <= "Z":
            continue
        if "0" <= ch <= "9" or ch in "+-.":
            if i == 0:
                return "", raw
            continue
        if ch == ":":
            if i == 0:
                raise ValueError("missing protocol scheme")
            return raw[:i], raw[i + 1:]
        return "", raw
    return "", raw


def go_url_parse(raw):
    """url.Parse 中这里用得到的部分（IPv6 地址、用户信息只认出来，不细分）。出错时 ValueError。"""
    u = URL()
    rest, sep, frag = raw.partition("#")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in rest):
        raise ValueError("invalid control character in URL")
    scheme, rest = _get_scheme(rest)
    u.scheme = ascii_lower(scheme)
    if rest.endswith("?") and rest.count("?") == 1:
        u.force_query, rest = True, rest[:-1]
    else:
        rest, _, u.raw_query = rest.partition("?")
    if not rest.startswith("/"):
        if u.scheme:
            u.opaque = rest
            return u
    if rest.startswith("//") and (u.scheme or not rest.startswith("///")):
        authority, rest = rest[2:], ""
        i = authority.find("/")
        if i >= 0:
            authority, rest = authority[:i], authority[i:]
        at = authority.rfind("@")
        if at >= 0:
            u.user = True
            authority = authority[at + 1:]
        if authority.startswith("["):
            u.host = authority  # （IPv6：不是公开的网站名）
        else:
            colon = authority.rfind(":")
            if colon >= 0:
                port = authority[colon + 1:]
                if not RE_PORT.fullmatch(port):
                    raise ValueError("invalid port")
                u.port = port
                authority = authority[:colon]
            if "%" in authority:
                _unescape(authority.encode("utf-8"))
            u.host = authority
    _unescape(rest.encode("utf-8", "surrogateescape"))  # （路径中不完整的 % 是错误）
    u.raw_path = rest
    if sep and frag:
        _unescape(frag.encode("utf-8", "surrogateescape"))
        u.raw_fragment = frag
    return u


RE_HOST_NAME = re.compile(r"(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})")
LOCAL_SUFFIXES = ["localhost", ".localhost", ".local", ".internal", ".lan", ".home", ".test", ".invalid", ".example"]


def public_host(h):
    if h == "" or "." not in h:
        return False
    try:
        ipaddress.ip_address(h.strip("[]"))
        return False
    except ValueError:
        pass
    if not RE_HOST_NAME.fullmatch(h):
        return False
    for s in LOCAL_SUFFIXES:
        if h == s.lstrip(".") or h.endswith(s):
            return False
    return True


def parse_https(raw):
    """一个 https 地址（没有用户名、端口，网站名为公开的名字，转为小写），否则 None。"""
    if not isinstance(raw, str) or not _valid_text(raw):
        return None
    raw = go_trim(raw)
    if raw == "" or _utf8_len(raw) > MAX_URL or any(c in raw for c in " \t\r\n<>\"'`\\"):
        return None
    try:
        u = go_url_parse(raw)
    except ValueError:
        return None
    if u.scheme != "https" or u.user or u.port or u.opaque:
        return None
    h = ascii_lower(u.host)
    if not public_host(h):
        return None
    u.host = h
    return u


# ---------- 链接 ----------
LINK_BOOTH_SHOP = "booth_shop"
LINK_BOOTH_ITEM = "booth_item"
LINK_XIANYU = "xianyu"
LINK_NETDISK = "netdisk"
LINK_GUMROAD = "gumroad"
LINK_JINXXY = "jinxxy"
LINK_BILIBILI = "bilibili"
LINK_YOUTUBE = "youtube"
LINK_X = "x"
LINK_PIXIV = "pixiv"
LINK_XIAOHONGSHU = "xiaohongshu"
LINK_DOUYIN = "douyin"
LINK_DISCORD = "discord"
LINK_QQ_GROUP = "qq_group"
LINK_GITHUB = "github"
LINK_WEBSITE = "website"

# 名片和作品各自可以带的链接种类（网盘链接只能放在作品上：作品先经维护者查看）
PROFILE_LINKS = [LINK_BOOTH_SHOP, LINK_XIANYU, LINK_GUMROAD, LINK_JINXXY, LINK_BILIBILI, LINK_YOUTUBE, LINK_X,
                 LINK_PIXIV, LINK_XIAOHONGSHU, LINK_DOUYIN, LINK_DISCORD, LINK_QQ_GROUP, LINK_GITHUB, LINK_WEBSITE]
WORK_LINKS = [LINK_BOOTH_SHOP, LINK_BOOTH_ITEM, LINK_XIANYU, LINK_NETDISK, LINK_GUMROAD, LINK_JINXXY, LINK_BILIBILI,
              LINK_YOUTUBE, LINK_X, LINK_PIXIV, LINK_WEBSITE]

BOOTH_SYSTEM = {"www", "accounts", "manage", "checkout", "api", "s", "asset", "help", "docs", "about", "pass", "admin", "static"}
RE_BOOTH_SHOP_HOST = re.compile(r"([a-z0-9][a-z0-9-]{0,62})\.booth\.pm")
RE_BOOTH_ITEM_PATH = re.compile(r"/(?:[a-z]{2}(?:-[a-z]{2,4})?/)?items/(\d{1,12})/?", re.A)
RE_SHOP_ITEM_PATH = re.compile(r"/items/(\d{1,12})/?", re.A)
RE_VRCHAT_USER = re.compile(r"https://vrchat\.com/home/user/usr_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def host_is(h, *names):
    for n in names:
        if n.startswith("."):
            if h.endswith(n) or h == n[1:]:
                return True
        elif h == n:
            return True
    return False


def _kind_ok(kind, u, h):
    p = u.escaped_path()
    if kind == LINK_BOOTH_SHOP:
        m = RE_BOOTH_SHOP_HOST.fullmatch(h)
        return bool(m) and m.group(1) not in BOOTH_SYSTEM and p in ("", "/", "/items")
    if kind == LINK_BOOTH_ITEM:
        if h == "booth.pm":
            return bool(RE_BOOTH_ITEM_PATH.fullmatch(p))
        m = RE_BOOTH_SHOP_HOST.fullmatch(h)
        return bool(m) and m.group(1) not in BOOTH_SYSTEM and bool(RE_SHOP_ITEM_PATH.fullmatch(p))
    if kind == LINK_XIANYU:
        return host_is(h, ".goofish.com", "2.taobao.com", "m.tb.cn")
    if kind == LINK_NETDISK:
        return host_is(h, "pan.baidu.com", "yun.baidu.com") and (p.startswith("/s/") or p.startswith("/share/init"))
    if kind == LINK_GUMROAD:
        return host_is(h, ".gumroad.com")
    if kind == LINK_JINXXY:
        return host_is(h, ".jinxxy.com")
    if kind == LINK_BILIBILI:
        return host_is(h, "space.bilibili.com", "www.bilibili.com", "m.bilibili.com", "live.bilibili.com", "b23.tv")
    if kind == LINK_YOUTUBE:
        return host_is(h, "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be")
    if kind == LINK_X:
        return host_is(h, "x.com", "twitter.com", "www.x.com", "mobile.twitter.com", "mobile.x.com")
    if kind == LINK_PIXIV:
        return host_is(h, "www.pixiv.net", "pixiv.net", "pixiv.me")
    if kind == LINK_XIAOHONGSHU:
        return host_is(h, "www.xiaohongshu.com", "xiaohongshu.com", "xhslink.com")
    if kind == LINK_DOUYIN:
        return host_is(h, "www.douyin.com", "douyin.com", "v.douyin.com")
    if kind == LINK_DISCORD:
        return host_is(h, "discord.gg") or (host_is(h, "discord.com") and p.startswith("/invite/"))
    if kind == LINK_QQ_GROUP:
        return host_is(h, "qm.qq.com")
    if kind == LINK_GITHUB:
        return host_is(h, "github.com")
    if kind == LINK_WEBSITE:
        return True
    return False


KIND_ORDER = [LINK_BOOTH_ITEM, LINK_BOOTH_SHOP, LINK_XIANYU, LINK_NETDISK, LINK_GUMROAD, LINK_JINXXY, LINK_BILIBILI,
              LINK_YOUTUBE, LINK_X, LINK_PIXIV, LINK_XIAOHONGSHU, LINK_DOUYIN, LINK_DISCORD, LINK_QQ_GROUP, LINK_GITHUB, LINK_WEBSITE]


def known_site(h):
    return host_is(h, "booth.pm", ".booth.pm", ".goofish.com", "2.taobao.com", "m.tb.cn", "pan.baidu.com", "yun.baidu.com",
                   ".gumroad.com", ".jinxxy.com", ".bilibili.com", "b23.tv", "youtube.com", ".youtube.com", "youtu.be", "x.com",
                   ".x.com", "twitter.com", ".twitter.com", ".pixiv.net", "pixiv.me", ".xiaohongshu.com", "xhslink.com",
                   ".douyin.com", "discord.gg", ".discord.com", "qm.qq.com", "github.com")


def link_kind_of(raw, allowed):
    """地址属于 allowed 中的哪一种（先认更具体的：商品先于店铺，已知的网站先于「网站」）；都不是时返回 ""。"""
    u = parse_https(raw)
    if u is None:
        return ""
    for k in KIND_ORDER:
        if k in allowed and _kind_ok(k, u, u.host):
            if k == LINK_WEBSITE and known_site(u.host):
                return ""
            return k
    return ""


def check_link(l, allowed):
    """整理好的链接 {kind, url[, label]}；种类不在 allowed 中或地址不是那一种时拒绝。"""
    if not isinstance(l, dict):
        raise fail(ERR_BAD_REQUEST)
    kind, raw, label = _str(l.get("kind")), _str(l.get("url")), _str(l.get("label"))
    if kind not in allowed:
        raise fail(ERR_BAD_LINK)
    u = parse_https(raw)
    if u is None or not _kind_ok(kind, u, u.host) or (kind == LINK_WEBSITE and known_site(u.host)):
        raise fail(ERR_BAD_LINK, "链接格式不正确：" + clip(raw, 60))
    label = clean_text(label, MAX_LINK_LABEL, False, 0)
    out = {"kind": kind, "url": u.string()}
    if label:
        out["label"] = label
    return out


def check_links(ls, allowed):
    """每个链接都检查，最多 MAX_LINKS 个，同一地址只留一个。"""
    ls = _list(ls)
    if len(ls) > MAX_LINKS:
        raise fail(ERR_TOO_LONG, "链接最多 8 个")
    out, seen = [], set()
    for l in ls:
        c = check_link(l, allowed)
        if c["url"] not in seen:
            seen.add(c["url"])
            out.append(c)
    return out


def has_netdisk(ls):
    return any(l.get("kind") == LINK_NETDISK for l in ls)


def booth_item_id(raw):
    """Booth 商品页的商品编号（不是商品页时为 ""）。"""
    u = parse_https(raw)
    if u is None:
        return ""
    p = u.escaped_path()
    if u.host == "booth.pm":
        m = RE_BOOTH_ITEM_PATH.fullmatch(p)
        return m.group(1) if m else ""
    m = RE_BOOTH_SHOP_HOST.fullmatch(u.host)
    if m and m.group(1) not in BOOTH_SYSTEM:
        m2 = RE_SHOP_ITEM_PATH.fullmatch(p)
        if m2:
            return m2.group(1)
    return ""


def check_vrchat(s):
    s = go_trim(_str(s))
    if s == "" or RE_VRCHAT_USER.fullmatch(s):
        return s
    raise fail(ERR_BAD_LINK, "VRChat 主页链接应为 https://vrchat.com/home/user/usr_… 的形式")


# ---------- 视频 ----------
def video_kind(raw):
    """视频链接所在的网站；不是这些网站的视频页时为 ""。"""
    u = parse_https(raw)
    if u is None:
        return ""
    h, p = u.host, u.escaped_path()
    if host_is(h, "www.bilibili.com", "m.bilibili.com") and p.startswith("/video/") or host_is(h, "b23.tv") and len(p) > 1:
        return "bilibili"
    if host_is(h, "youtube.com", "www.youtube.com", "m.youtube.com") and (p == "/watch" and u.query_get("v") != "" or p.startswith("/shorts/")) \
            or host_is(h, "youtu.be") and len(p) > 1:
        return "youtube"
    if host_is(h, "x.com", "twitter.com", "mobile.twitter.com") and "/status/" in p:
        return "x"
    if host_is(h, "www.douyin.com", "douyin.com") and p.startswith("/video/") or host_is(h, "v.douyin.com") and len(p) > 1:
        return "douyin"
    if host_is(h, "www.xiaohongshu.com", "xiaohongshu.com") and (p.startswith("/explore/") or p.startswith("/discovery/item/")) \
            or host_is(h, "xhslink.com") and len(p) > 1:
        return "xiaohongshu"
    if host_is(h, "www.nicovideo.jp", "sp.nicovideo.jp") and p.startswith("/watch/") or host_is(h, "nico.ms") and len(p) > 1:
        return "nicovideo"
    if host_is(h, "www.tiktok.com", "tiktok.com") and "/video/" in p or host_is(h, "vt.tiktok.com", "vm.tiktok.com") and len(p) > 1:
        return "tiktok"
    return ""


# ---------- 名片 ----------
LANGS = ["zh", "ja", "en", "ko", "other"]


def jpeg_b64(s, most):
    """base64 编码的 JPEG（开头为 FF D8 FF），不超过 most 个字符。"""
    if not isinstance(s, str) or _utf8_len(s) > most:
        return False
    try:
        b = binascii.a2b_base64(s.replace("\r", "").replace("\n", "").encode("ascii"), strict_mode=True)
    except (binascii.Error, ValueError, UnicodeEncodeError):
        return False
    return len(b) > 4 and b[0] == 0xFF and b[1] == 0xD8 and b[2] == 0xFF


def date_ok(m, d):
    days = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return isinstance(m, int) and isinstance(d, int) and not isinstance(m, bool) and not isinstance(d, bool) and 1 <= m <= 12 and 1 <= d <= days[m]


def check_card(r):
    """整理好的名片（MioVRCA 发出的 CardReq），或拒绝的原因（RuleError）。头像只检查是 JPEG，由工作流重新绘制。"""
    if not isinstance(r, dict):
        raise fail(ERR_BAD_REQUEST)
    out = {}
    out["nickname"] = clean_text(_str(r.get("nickname")), MAX_NICKNAME, False, 0)
    if out["nickname"] == "":
        raise fail(ERR_BAD_TEXT, "昵称不能为空")
    bio = clean_text(_str(r.get("bio")), MAX_BIO, True, MAX_BIO_LINES)
    if bio:
        out["bio"] = bio
    langs = []
    for l in _list(r.get("langs")):
        if l in LANGS and l not in langs and len(langs) < MAX_LANGS:
            langs.append(l)
    if langs:
        out["langs"] = langs
    vr = check_vrchat(r.get("vrchat"))
    if vr:
        out["vrchat"] = vr
    links = check_links(r.get("links"), PROFILE_LINKS)
    if links:
        out["links"] = links
    bases_in = _list(r.get("bases"))
    if len(bases_in) > MAX_BASES:
        raise fail(ERR_TOO_LONG, "常用素体最多 5 个")
    bases = []
    for b in bases_in:
        c = clean_text(_str(b), MAX_BASE_NAME, False, 0)
        if c and c not in bases:
            bases.append(c)
    if bases:
        out["bases"] = bases
    bd = r.get("birthday")
    if bd is not None:
        if not isinstance(bd, dict):
            raise fail(ERR_BAD_REQUEST)
        m, d = bd.get("month", 0), bd.get("day", 0)
        if not date_ok(m, d):
            raise fail(ERR_BAD_REQUEST, "生日日期不正确")
        out["birthday"] = {"month": m, "day": d}
    fl_in = _list(r.get("following"))
    if len(fl_in) > MAX_FOLLOWING:
        raise fail(ERR_TOO_LONG, "公开的关注最多 2000 个")
    fl = []
    for f in fl_in:
        l = norm_login(f)
        if l not in fl:
            fl.append(l)
    if fl:
        out["following"] = fl
    av = _str(r.get("avatar"))
    if av:
        if not jpeg_b64(av, MAX_AVATAR_B64):
            raise fail(ERR_BAD_IMAGE)
        out["avatar"] = av
    showcase = check_showcase(r.get("showcase"))
    if showcase:
        out["showcase"] = showcase
    return out


MAX_SHOWCASE = 60


def check_showcase(items):
    """Validate the public Booth asset list with the same limits as Go."""
    items = _list(items)
    if len(items) > MAX_SHOWCASE:
        raise fail(ERR_TOO_LONG, "素材展示柜最多 60 件")
    out, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise fail(ERR_BAD_REQUEST)
        bid = _str(item.get("booth_id"))
        if not re.fullmatch(r"[0-9]{1,12}", bid):
            raise fail(ERR_BAD_REQUEST, "素材展示柜的 Booth 商品编号无效")
        if bid in seen:
            raise fail(ERR_BAD_REQUEST, "素材展示柜中有重复的 Booth 商品")
        seen.add(bid)
        name = clean_text(_str(item.get("name")), MAX_ASSET_NAME, False, 0)
        if not name:
            raise fail(ERR_BAD_TEXT, "素材名称不能为空")
        shop = clean_text(_str(item.get("shop")), MAX_SHOP_NAME, False, 0)
        row = {"booth_id": bid, "name": name}
        if shop:
            row["shop"] = shop
        out.append(row)
    return out


# ---------- 作品 ----------
RE_RECIPE_HEAD = re.compile(r"MIOVRCA-RECIPE-[0-9]{1,3}[\t\n\f\r ]*[:：]", re.I | re.A)
RE_WORK_ID = re.compile(r"w[0-9]{1,9}")


def work_id_ok(s):
    return isinstance(s, str) and bool(RE_WORK_ID.fullmatch(s))


def recipe_code_ok(s):
    """s 中有装配方案的分享码（可以带聊天软件加上的前后文字），且没有无法显示的字符。"""
    if not _valid_text(s) or _utf8_len(s) > MAX_RECIPE or not RE_RECIPE_HEAD.search(s):
        return False
    return not any(unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in s)


def check_work(r):
    """整理好的作品（MioVRCA 发出的 WorkReq），或拒绝的原因。"""
    if not isinstance(r, dict):
        raise fail(ERR_BAD_REQUEST)
    rights = r.get("rights_ok")
    if rights is not None and not isinstance(rights, bool):
        raise fail(ERR_BAD_REQUEST)
    out = {}
    rep = _str(r.get("replace"))
    based = _str(r.get("based_on"))
    if based:
        if not work_id_ok(based) or based == rep:
            raise fail(ERR_BAD_REQUEST, "参考的作品编号无效，或与当前作品相同")
        out["based_on"] = based
    if rep:
        if not work_id_ok(rep):
            raise fail(ERR_BAD_REQUEST)
    cover = _str(r.get("cover"))
    if cover and not jpeg_b64(cover, MAX_COVER_B64):
        raise fail(ERR_BAD_IMAGE)
    out["title"] = clean_text(_str(r.get("title")), MAX_TITLE, False, 0)
    if out["title"] == "":
        raise fail(ERR_BAD_TEXT, "请填写标题")
    desc = clean_text(_str(r.get("desc")), MAX_DESC, True, MAX_DESC_LINES)
    if desc:
        out["desc"] = desc
    v = go_trim(_str(r.get("video")))
    if v:
        if video_kind(v) == "":
            raise fail(ERR_BAD_VIDEO)
        out["video"] = parse_https(v).string()
    base = clean_text(_str(r.get("base")), MAX_BASE_NAME, False, 0)
    if base:
        out["base"] = base
    assets_in = _list(r.get("assets"))
    if len(assets_in) > MAX_ASSETS:
        raise fail(ERR_TOO_LONG, "同款素材最多 30 件")
    assets = []
    for a in assets_in:
        if not isinstance(a, dict):
            raise fail(ERR_BAD_REQUEST)
        c = {"name": clean_text(_str(a.get("name")), MAX_ASSET_NAME, False, 0)}
        if c["name"] == "":
            raise fail(ERR_BAD_TEXT, "素材名称不能为空")
        shop = clean_text(_str(a.get("shop")), MAX_SHOP_NAME, False, 0)
        raw = _str(a.get("url"))
        if go_trim(raw) != "":
            if link_kind_of(raw, [LINK_BOOTH_ITEM, LINK_GUMROAD, LINK_JINXXY]) == "":
                raise fail(ERR_BAD_LINK, "素材链接应为 Booth、Gumroad 或 Jinxxy 的商品页：" + clip(raw, 60))
            c["url"] = parse_https(raw).string()
        if shop:
            c["shop"] = shop
        assets.append(c)
    if assets:
        out["assets"] = assets
    links = check_links(r.get("links"), WORK_LINKS)
    if links:
        out["links"] = links
    if has_netdisk(links) and not rights:
        raise fail(ERR_RIGHTS)
    rc = go_trim(_str(r.get("recipe")))
    if rc:
        if not recipe_code_ok(rc):
            raise fail(ERR_BAD_RECIPE)
        out["recipe"] = rc
    if rights:
        out["rights_ok"] = True
    if cover:
        out["cover"] = cover
    if rep:
        out["replace"] = rep
    return out


def work_req_json_order(w):
    """作品按 MioVRCA 程序写出的栏目顺序排列（只影响 JSON 的样子）。"""
    keys = ["based_on", "title", "desc", "video", "base", "assets", "links", "recipe", "rights_ok", "cover", "replace"]
    return {k: w[k] for k in keys if k in w}


# ---------- 不允许使用的词语（可选：scripts/banned.txt，每行一个，# 开头的是注释） ----------
def banned_words(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [w.strip().lower() for w in f if w.strip() and not w.strip().startswith("#")]
    except FileNotFoundError:
        return []


def check_banned(texts, words):
    """texts 中有 words 中的词语时拒绝（不区分大小写）。"""
    for t in texts:
        low = (t or "").lower()
        for w in words:
            if w in low:
                raise fail(ERR_BANNED_WORDS)
