#!/usr/bin/env python3
"""
Daily AI model release fetcher.
Pulls new releases/announcements from major AI labs, Hugging Face trending
models, and arXiv cs.AI, then writes a digest JSON and appends to history.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

DATA_DIR = "data"
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
LATEST_FILE = os.path.join(DATA_DIR, "latest.json")

RSS_SOURCES = {
    "OpenAI": "https://openai.com/news/rss.xml",
    "Anthropic": "https://www.anthropic.com/rss.xml",
    "Google AI": "https://blog.google/technology/ai/rss/",
    "Meta AI": "https://ai.meta.com/blog/rss/",
    "Hugging Face": "https://huggingface.co/blog/feed.xml",
    "Mistral AI": "https://mistral.ai/news/rss.xml",
    "Stability AI": "https://stability.ai/news?format=rss",
    "DeepMind": "https://deepmind.google/blog/rss.xml",
}

HF_TRENDING_API = "https://huggingface.co/api/models?sort=lastModified&direction=-1&limit=25"
ARXIV_API = (
    "http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.CL"
    "&sortBy=submittedDate&sortOrder=descending&max_results=15"
)

LOOKBACK_HOURS = 30
UA = {"User-Agent": "ai-model-release-radar/1.0 (+github actions daily digest)"}


def http_get(url, timeout=15):
    req = Request(url, headers=UA)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_rss(xml_bytes):
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        items.append({"title": title, "link": link, "published": pub})
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//a:entry", ns):
            title = (entry.findtext("a:title", namespaces=ns) or "").strip()
            link_el = entry.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else ""
            pub = (entry.findtext("a:updated", namespaces=ns)
                   or entry.findtext("a:published", namespaces=ns) or "").strip()
            items.append({"title": title, "link": link, "published": pub})
    return items


def try_parse_date(s):
    fmts = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    s = s.strip()
    for f in fmts:
        try:
            dt = datetime.strptime(s, f)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def fetch_rss_sources():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    results = []
    for source, url in RSS_SOURCES.items():
        try:
            raw = http_get(url)
        except Exception as e:
            print(f"[skip] {source}: {e}")
            continue
        for item in parse_rss(raw):
            dt = try_parse_date(item.get("published", ""))
            if dt and dt < cutoff:
                continue
            results.append({
                "source": source,
                "title": item["title"],
                "link": item["link"],
                "published": dt.isoformat() if dt else item.get("published", ""),
                "category": "announcement",
            })
    return results


def fetch_hf_trending():
    results = []
    try:
        raw = http_get(HF_TRENDING_API)
        models = json.loads(raw)
    except Exception as e:
        print(f"[skip] HuggingFace API: {e}")
        return results
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    for m in models:
        last_modified = m.get("lastModified")
        dt = None
        if last_modified:
            try:
                dt = datetime.strptime(last_modified, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        if dt and dt < cutoff:
            continue
        model_id = m.get("id", "")
        results.append({
            "source": "Hugging Face Hub",
            "title": model_id,
            "link": f"https://huggingface.co/{model_id}",
            "published": dt.isoformat() if dt else "",
            "category": "model_upload",
        })
    return results


def fetch_arxiv():
    results = []
    try:
        raw = http_get(ARXIV_API)
        root = ET.fromstring(raw)
    except Exception as e:
        print(f"[skip] arXiv: {e}")
        return results
    ns = {"a": "http://www.w3.org/2005/Atom"}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    for entry in root.findall("a:entry", ns):
        title = re.sub(r"\s+", " ", (entry.findtext("a:title", namespaces=ns) or "")).strip()
        link = entry.findtext("a:id", namespaces=ns) or ""
        published = entry.findtext("a:published", namespaces=ns) or ""
        dt = None
        try:
            dt = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            pass
        if dt and dt < cutoff:
            continue
        results.append({
            "source": "arXiv cs.AI/cs.CL",
            "title": title,
            "link": link,
            "published": dt.isoformat() if dt else published,
            "category": "paper",
        })
    return results


def dedupe(items):
    seen = set()
    out = []
    for it in items:
        key = (it["source"], it["title"].lower().strip())
        if key in seen or not it["title"]:
            continue
        seen.add(key)
        out.append(it)
    return out


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    all_items = []
    all_items += fetch_rss_sources()
    all_items += fetch_hf_trending()
    all_items += fetch_arxiv()
    all_items = dedupe(all_items)
    all_items.sort(key=lambda x: x.get("published") or "", reverse=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    digest = {
        "date": today,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_items),
        "items": all_items,
    }

    with open(LATEST_FILE, "w") as f:
        json.dump(digest, f, indent=2, ensure_ascii=False)

    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                history = json.load(f)
        except json.JSONDecodeError:
            history = []
    history = [d for d in history if d.get("date") != today]
    history.append(digest)
    history = history[-90:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

    lines = [f"# AI Model Release Digest — {today}", ""]
    if not all_items:
        lines.append("No new releases detected in the last 24-30h window.")
    else:
        by_source = {}
        for it in all_items:
            by_source.setdefault(it["source"], []).append(it)
        for source, items in by_source.items():
            lines.append(f"## {source} ({len(items)})")
            for it in items:
                lines.append(f"- [{it['title']}]({it['link']})")
            lines.append("")
    lines.append("---\n[View live dashboard](https://ricardobonbarbosa-creator.github.io/ai-model-release-radar/)")
    with open(os.path.join(DATA_DIR, "digest_body.md"), "w") as f:
        f.write("\n".join(lines))

    print(f"Digest generated: {len(all_items)} items")


if __name__ == "__main__":
    main()
