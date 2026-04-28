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
    "https://news.google.com/rss/search?q=AI%20OR%20%E7%A7%91%E6%8A%80%20OR%20%E8%B4%A2%E7%BB%8F&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://news.google.com/rss/search?q=%E4%B8%AD%E5%9B%BD%20AI%20OR%20%E5%A4%A7%E6%A8%A1%E5%9E%8B%20OR%20%E8%8A%AF%E7%89%87&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
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


def parse_rss_items(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items: list[dict] = []
    for item in root.findall(".//item"):
        raw_title = item.findtext("title") or ""
        title, source = split_title_source(raw_title)
        url = clean_url(item.findtext("link") or item.findtext("guid") or "")
        summary = strip_html(item.findtext("description") or item.findtext("summary") or title)
        published = parse_date(item.findtext("pubDate") or item.findtext("published") or item.findtext("updated"))
        if title and url:
            items.append({"title": title, "source": source, "url": url, "summary": summary, "published": published})
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


def build_news_json(raw_items: list[dict], now: datetime | None = None, limit: int = 10) -> dict:
    now = now or datetime.now(timezone.utc)
    seen_urls: set[str] = set()
    used_slugs: set[str] = set()
    unique: list[RawNews] = []
    for item in raw_items:
        url = item.get("url") or item.get("originalUrl") or ""
        title = strip_html(item.get("title", ""))
        if not title or not url or url in seen_urls:
            continue
        seen_urls.add(url)
        published = item.get("published")
        if isinstance(published, str):
            published = parse_date(published)
        if not isinstance(published, datetime):
            published = now
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        unique.append(RawNews(title, item.get("source", "RSS"), url, item.get("summary", ""), published.astimezone(timezone.utc)))

    # RSS feeds are normally already ordered by editorial freshness. Preserve
    # that feed order so the output stays predictable and tests can inject a
    # deterministic sequence.
    output_items = []
    for index, item in enumerate(unique[:limit], start=1):
        date = item.published.astimezone(timezone.utc)
        summary = trim_summary(item.summary, item.title)
        tags = infer_tags(item.title, summary, item.source)
        rank = f"{index:02d}"
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
            "points": [
                f"这条新闻来自 {item.source}，发布时间为 {date.strftime('%H:%M GMT')}。",
                "页面内容由自动更新脚本根据公开 RSS 标题、摘要和时间整理生成。",
                "详情页保留原始报道链接，进一步信息请以原文为准。",
            ],
            "background": "该条目由每日新闻爬虫从公开 RSS 源抓取，并按时间排序后写入站点数据文件。",
            "impact": "自动更新后，首页目录和详情模板会读取同一份 JSON 数据，避免手写多个重复 HTML 页面。",
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
