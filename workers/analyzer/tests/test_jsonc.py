from analyzer.resolve.jsonc import parse_jsonc


def test_comments_and_trailing_commas():
    text = """{
      // line comment
      "compilerOptions": { /* block */ "baseUrl": ".", "paths": { "@/*": ["src/*",], }, },
      "url": "http://example.com//not-a-comment",
    }"""
    data = parse_jsonc(text)
    assert data["compilerOptions"]["paths"] == {"@/*": ["src/*"]}
    assert data["url"] == "http://example.com//not-a-comment"


def test_bom_and_invalid():
    assert parse_jsonc('﻿{"a": 1}') == {"a": 1}
    assert parse_jsonc("{not json") is None
