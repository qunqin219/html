import json
import unittest
from datetime import datetime, timezone

from scripts import update_news


class UpdateNewsTests(unittest.TestCase):
    def test_parse_rss_items_extracts_title_source_and_url(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel>
          <item>
            <title>中国 AI 创业公司发布新产品 - 示例媒体</title>
            <link>https://example.com/a?utm_source=x</link>
            <description><![CDATA[这是一段摘要。<b>包含标签</b>]]></description>
            <pubDate>Tue, 28 Apr 2026 08:30:00 GMT</pubDate>
          </item>
        </channel></rss>
        """.encode("utf-8")

        items = update_news.parse_rss_items(xml)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "中国 AI 创业公司发布新产品")
        self.assertEqual(items[0]["source"], "示例媒体")
        self.assertEqual(items[0]["url"], "https://example.com/a")
        self.assertIn("包含标签", items[0]["summary"])

    def test_build_news_json_limits_to_ten_and_adds_detail_fields(self):
        raw = [
            {
                "title": f"新闻标题 {i}",
                "source": "示例媒体",
                "url": f"https://example.com/{i}",
                "summary": "这是新闻摘要，用于生成页面。",
                "published": datetime(2026, 4, 28, i % 24, tzinfo=timezone.utc),
            }
            for i in range(12)
        ]

        data = update_news.build_news_json(raw, now=datetime(2026, 4, 28, 12, tzinfo=timezone.utc), limit=10)

        self.assertEqual(data["updatedAt"], "2026 年 4 月 28 日")
        self.assertEqual(len(data["items"]), 10)
        self.assertEqual(data["items"][0]["rank"], "01")
        self.assertEqual(data["items"][9]["rank"], "10")
        first = data["items"][0]
        self.assertEqual(first["id"], "xin-wen-biao-ti-0")
        self.assertTrue(first["badge"])
        self.assertTrue(first["tags"])
        self.assertEqual(len(first["points"]), 3)
        self.assertTrue(first["background"])
        self.assertTrue(first["impact"])

    def test_write_news_json_outputs_pretty_utf8(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        with TemporaryDirectory() as td:
            path = Path(td) / "news.json"
            data = {"updatedAt": "2026 年 4 月 28 日", "items": [{"title": "中文标题"}]}

            update_news.write_news_json(data, path)

            text = path.read_text(encoding="utf-8")
            self.assertIn("中文标题", text)
            self.assertEqual(json.loads(text), data)


if __name__ == "__main__":
    unittest.main()
