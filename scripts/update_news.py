#!/usr/bin/env python3
"""Fetch RSS news and update data/news.json for the static GitHub Pages site.

The script intentionally uses only Python's standard library so it can run in
GitHub Actions without dependency installation.
"""
from __future__ import annotations

import argparse
import email.utils
import html
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "news.json"
USER_AGENT = "DailyNewsUpdater/1.0 (+https://qunqin219.github.io/html/)"
DEFAULT_FEEDS = [
    "https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
]

PINYIN = {
    "新": "xin", "闻": "wen", "标": "biao", "题": "ti", "中": "zhong", "国": "guo",
    "科": "ke", "技": "ji", "财": "cai", "经": "jing", "人": "ren", "工": "gong",
    "智": "zhi", "能": "neng", "大": "da", "模": "mo", "型": "xing", "市": "shi",
    "场": "chang", "全": "quan", "球": "qiu", "政": "zheng", "策": "ce", "监": "jian",
    "管": "guan", "产": "chan", "业": "ye", "公": "gong", "司": "si", "发": "fa",
    "布": "bu", "美": "mei", "欧": "ou", "日": "ri", "韩": "han", "投": "tou",
    "资": "zi", "银": "yin", "行": "xing", "股": "gu", "份": "fen", "收": "shou",
    "购": "gou", "合": "he", "作": "zuo", "增": "zeng", "长": "zhang", "数": "shu",
    "据": "ju", "云": "yun", "硬": "ying", "件": "jian", "软": "ruan", "源": "yuan",
    "开": "kai", "放": "fang", "安": "an", "危": "wei", "机": "ji", "贸": "mao",
    "易": "yi", "法": "fa", "庭": "ting", "基": "ji", "础": "chu", "设": "she",
    "备": "bei", "竞": "jing", "争": "zheng", "创": "chuang", "初": "chu", "企": "qi",
}

@dataclass(frozen=True)
class RawNews:
    title: str
    source: str
    url: str
    summary: str
    published: datetime


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def clean_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(html.unescape(url or ""))
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(k, v) for k, v in query if not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), ""))


def parse_date(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def split_title_source(title: str, fallback_source: str = "RSS") -> tuple[str, str]:
    title = strip_html(title)
    for sep in (" - ", " — ", " | "):
        if sep in title:
            left, right = title.rsplit(sep, 1)
            if left.strip() and right.strip():
                return left.strip(), right.strip()
    return title, fallback_source


NOISE_TAIL = re.compile(
    r"(在Google 新闻上查看更多头条新闻和观点.*$)|(\s*全文\s*$)|(\s*\d+\s*条相关报道\s*$)"
)


def clean_description(value: str) -> str:
    """Strip Google News RSS boilerplate ('... 在Google 新闻上查看更多头条新闻和观点',
    trailing anchor URLs, and أa list of related-story titles)."""
    text = strip_html(value)
    text = NOISE_TAIL.sub(" ", text)
    # Google News 会把相关新闻的标题堆进 description；取第一句/第一段即可
    for sep in ("  ", "\n"):
        text = text.split(sep)[0].strip()
    # 去掉拼进来站的裸 URL（如 https://www.tlfw.net/）
    text = re.sub(r"https?://\S+", "", text).strip(" -–—")
    return text


def score_item(title: str, summary: str, source: str) -> float:
    """0–100 的相关度/质量分，用于排序选头条。"""
    text = f"{title} {summary}".lower()
    score = 0.0
    important_users = [
        "openai", "anthropic", "deepseek", "google", "gemini", "qwen", "千问",
        "智谱", "glm", "kimi", "月之暗面", "meta", "mistral", "grok", "xai",
        "通义", "claude", "gpt-", "llm", "人工智能", "大模型", "算力", "芯片",
        "nvidia", "英伟达", "台积电", "数据中心",
    ]
    for word in important_users:
        if word in text:
            score += 12.0
    # 一般AI词
    for word in ("ai", "模型", "智能"):
        if word in text:
            score += 3.0
    # 大厂官方源直接加权
    trusted = ["openai.com", "research.google", "mistral.ai", "huggingface",
               "qbitai", "leiphone", "ithome", "solidot", "geekpark",
               "techcrunch", "arstechnica", "theverge", "wired",
               "simonwillison", "hnrss"]
    if any(t in (source or "").lower() for t in trusted):
        score += 25.0
    # 标题短（<45 字）加分：更可能是纯资讯而不是整段软文
    if len(title) < 45:
        score += 8.0
    # 政务头条/软文降权（但不禁）
    spam = ["新闻上查看更多", "弘扬", "综述", "大会并发表重要讲话", "强调"]
    for word in spam:
        if word in title + summary:
            score -= 15.0
    return max(0.0, min(100.0, score))


ATOM_NS = "{http://www.w3.org/2005/Atom}"


def parse_rss_items(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items: list[dict] = []
    is_atom = root.tag == ATOM_NS + "feed"
    entries = (
        root.findall(f".//{ATOM_NS}entry") if is_atom else root.findall(".//item")
    )
    for item in entries:
        if is_atom:
            raw_title = item.findtext(f"{ATOM_NS}title") or ""
            link_el = item.find(f"{ATOM_NS}link")
            url = (link_el.get("href") if link_el is not None else "") or (
                item.findtext(f"{ATOM_NS}link") or ""
            )
            summary = (
                item.findtext(f"{ATOM_NS}content")
                or item.findtext(f"{ATOM_NS}summary")
                or raw_title
            )
            published = parse_date(
                item.findtext(f"{ATOM_NS}published") or item.findtext(f"{ATOM_NS}updated")
            )
        else:
            raw_title = item.findtext("title") or ""
            url = item.findtext("link") or item.findtext("guid") or ""
            summary = (
                item.findtext("description") or item.findtext("summary") or raw_title
            )
            published = parse_date(
                item.findtext("pubDate")
                or item.findtext("published")
                or item.findtext("updated")
            )
        title, source = split_title_source(raw_title)
        url = clean_url(url)
        summary = clean_description(summary)
        if title and url:
            items.append({
                "title": title,
                "source": source,
                "url": url,
                "summary": summary,
                "published": published,
            })
    return items


def fetch_url(url: str, timeout: int = 25) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_news(feeds: Iterable[str]) -> list[dict]:
    collected: list[dict] = []
    for feed in feeds:
        try:
            collected.extend(parse_rss_items(fetch_url(feed)))
        except (urllib.error.URLError, TimeoutError, ET.ParseError) as exc:
            print(f"warning: failed to fetch {feed}: {exc}", file=sys.stderr)
    return collected


def slugify(value: str, used: set[str] | None = None) -> str:
    used = used if used is not None else set()
    tokens: list[str] = []
    for char in unicodedata.normalize("NFKC", value.lower()):
        if char.isascii() and char.isalnum():
            tokens.append(char)
        elif char in PINYIN:
            tokens.append("-" + PINYIN[char] + "-")
        elif char.isdigit():
            tokens.append(char)
        else:
            tokens.append("-")
    slug = re.sub(r"-+", "-", "".join(tokens)).strip("-")[:72] or "news"
    base = slug
    counter = 2
    while slug in used:
        slug = f"{base}-{counter}"
        counter += 1
    used.add(slug)
    return slug


def infer_tags(title: str, summary: str, source: str) -> list[str]:
    text = f"{title} {summary}".lower()
    rules = [
        ("AI", ["ai", "人工智能", "大模型", "openai", "芯片", "智能"]),
        ("科技", ["科技", "互联网", "芯片", "软件", "数据", "云"]),
        ("财经", ["市场", "投资", "股", "经济", "金融", "基金", "财报"]),
        ("国际", ["美国", "欧洲", "全球", "外交", "战争", "总统", "政府"]),
        ("中国", ["中国", "北京", "上海", "深圳", "杭州"]),
    ]
    tags = [label for label, words in rules if any(word in text for word in words)]
    if source and source not in tags:
        tags.append(source[:18])
    return tags[:4] or ["新闻"]


def trim_summary(summary: str, title: str) -> str:
    summary = strip_html(summary)
    if not summary or len(summary) < 18:
        summary = f"{title}。该新闻来自公开 RSS 源，页面会在每日自动更新时重新整理。"
    return summary[:180].rstrip() + ("…" if len(summary) > 180 else "")


def make_analysis(item: RawNews, summary: str, tags: list[str], date: datetime) -> tuple[list[str], str, str]:
    topic = "、".join(tags[:3]) if tags else "公共议题"
    source = item.source or "相关媒体"
    published_time = date.strftime("%H:%M GMT")
    points = [
        f"报道聚焦“{item.title}”，核心信息来自 {source} 的公开报道。",
        f"从关键词看，这条新闻主要关联 {topic} 等方向，适合继续跟踪后续进展。",
        "如果需要更完整的事实细节和上下文，应点击原始报道查看全文。",
    ]
    background = (
        f"这条新闻发生在 {topic} 持续受到关注的背景下。"
        f"公开报道显示，事件涉及的主体、政策环境和市场预期仍在变化，"
        f"因此需要结合原文和后续报道理解其完整脉络。"
    )
    impact = (
        f"短期内，这一事件可能影响相关参与方的市场判断和舆论关注；"
        f"中长期看，它也可能成为观察 {topic} 走向的一个信号。"
        f"页面摘要仅提供快速浏览，具体判断仍应以原始报道为准。"
    )
    return points, background, impact


def build_news_json(raw_items: list[dict], now: datetime | None = None, limit: int = 10) -> dict:
    now = now or datetime.now(timezone.utc)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    used_slugs: set[str] = set()
    scored: list[tuple[float, RawNews]] = []
    for item in raw_items:
        url = item.get("url") or item.get("originalUrl") or ""
        title = strip_html(item.get("title", ""))
        if not title or not url or url in seen_urls:
            continue
        # 跨源去重：同一事件被多家转载时只保留一家
        # 去掉全/半角括号里的转载标记再取前 18 字做指纹
        title_key = re.sub(r"[（(【\[].*?[）)】\]]", "", re.sub(r"\s+", "", title))[:18]
        if title_key in seen_titles:
            continue
        seen_urls.add(url)
        seen_titles.add(title_key)
        published = item.get("published")
        if isinstance(published, str):
            published = parse_date(published)
        if not isinstance(published, datetime):
            published = now
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        source = item.get("source", "RSS")
        summary = item.get("summary", "")
        score = score_item(title, summary, source)
        scored.append((score, RawNews(title, source, url, summary, published.astimezone(timezone.utc))))

    # 按相关度/质量分排序选头条，而不是按 feed 顺序截断
    scored.sort(key=lambda x: -x[0])
    output_items = []
    for index, (score, item) in enumerate(scored[:limit], start=1):
        date = item.published.astimezone(timezone.utc)
        summary = trim_summary(item.summary, item.title)
        tags = infer_tags(item.title, summary, item.source)
        rank = f"{index:02d}"
        points, background, impact = make_analysis(item, summary, tags, date)
        output_items.append({
            "id": slugify(item.title, used_slugs),
            "rank": rank,
            "title": item.title,
            "source": item.source,
            "badge": tags[0],
            "summary": summary,
            "date": f"{date.year} 年 {date.month} 月 {date.day} 日",
            "time": date.strftime("%H:%M GMT"),
            "tags": tags,
            "originalUrl": item.url,
            "points": points,
            "background": background,
            "impact": impact,
        })

    return {"updatedAt": f"{now.year} 年 {now.month} 月 {now.day} 日", "items": output_items}


def write_news_json(data: dict, path: Path = DEFAULT_OUTPUT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_feed_list(path: Path | None) -> list[str]:
    if not path or not path.exists():
        return DEFAULT_FEEDS
    feeds = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [line for line in feeds if line and not line.startswith("#")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update static news JSON from RSS feeds")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--feeds", type=Path, default=ROOT / "config" / "feeds.txt")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    feeds = load_feed_list(args.feeds)
    raw_items = fetch_news(feeds)
    if not raw_items:
        print("error: no news items fetched", file=sys.stderr)
        return 1
    data = build_news_json(raw_items, limit=args.limit)
    if args.dry_run:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        write_news_json(data, args.output)
        print(f"updated {args.output} with {len(data['items'])} items from {len(feeds)} feeds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
