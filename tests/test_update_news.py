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

    def test_build_news_json_uses_reader_facing_analysis_not_technical_placeholders(self):
        raw = [{
            "title": "中国 AI 创业公司发布新产品",
            "source": "示例媒体",
            "url": "https://example.com/ai",
            "summary": "这是一条关于 AI 产品发布的新闻摘要。",
            "published": datetime(2026, 4, 28, 8, tzinfo=timezone.utc),
        }]

        data = update_news.build_news_json(raw, now=datetime(2026, 4, 28, 12, tzinfo=timezone.utc), limit=1)
        item = data["items"][0]
        visible_text = " ".join(item["points"] + [item["background"], item["impact"]])

        self.assertIn("中国 AI 创业公司发布新产品", visible_text)
        self.assertNotIn("RSS", visible_text)
        self.assertNotIn("JSON", visible_text)
        self.assertNotIn("HTML", visible_text)
        self.assertNotIn("模板", visible_text)

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

    def test_clean_description_strips_google_news_boilerplate(self):
        text = update_news.clean_description(
            "这是摘要正文 https://www.example.com/ 在Google 新闻上查看更多头条新闻和观点 相关新闻标题甲 相关新闻标题乙"
        )
        self.assertEqual(text, "这是摘要正文")
        self.assertNotIn("Google", text)
        self.assertNotIn("https://", text)

    def test_parse_rss_items_supports_atom_feeds(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Anthropic 发布新模型 - Anthropic</title>
            <link rel="alternate" href="https://example.com/atom-entry?x=1"/>
            <content>这是 Atom 摘要</content>
            <updated>2026-10-13T08:00:00Z</updated>
          </entry>
        </feed>
        """.encode("utf-8")

        items = update_news.parse_rss_items(xml)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.com/atom-entry?x=1")
        self.assertIn("Atom 摘要", items[0]["summary"])

    def test_build_news_json_ranks_ai_news_higher_and_dedupes_by_title(self):
        raw = [
            {
                "title": "弘扬伟大长征精神 走好新时代的长征路 新闻上查看更多",
                "source": "示例媒体",
                "url": "https://example.com/politics",
                "summary": "泛时政头条，页面测试用。",
                "published": datetime(2026, 4, 28, 8, tzinfo=timezone.utc),
            },
            {
                "title": "DeepSeek 发布新一代模型（转载甲）",
                "source": "媒体甲",
                "url": "https://example.com/ai-1",
                "summary": "DeepSeek 发布新一代 AI 大模型。",
                "published": datetime(2026, 4, 28, 9, tzinfo=timezone.utc),
            },
            {
                "title": "DeepSeek 发布新一代模型",
                "source": "媒体乙",
                "url": "https://example.com/ai-2",
                "summary": "DeepSeek 发布新一代 AI 大模型。",
                "published": datetime(2026, 4, 28, 9, tzinfo=timezone.utc),
            },
            {
                "title": "AI 芯片出口新规分析",
                "source": "openai.com",
                "url": "https://openai.com/x",
                "summary": "关于 ai 芯片与算力的政策解读。",
                "published": datetime(2026, 4, 28, 7, tzinfo=timezone.utc),
            },
        ]

        data = update_news.build_news_json(raw, now=datetime(2026, 4, 28, 12, tzinfo=timezone.utc), limit=10)

        # 转载去重：只剩一条 DeepSeek
        self.assertEqual(len([i for i in data["items"] if "DeepSeek" in i["title"]]), 1)
        # AI 相关新闻排在头条前面，泛时政的排最后
        self.assertIn("ai", data["items"][0]["title"].lower())
        self.assertIn("长征", data["items"][-1]["title"])


if __name__ == "__main__":
    unittest.main()
