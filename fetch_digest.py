#!/usr/bin/env python3
"""
Daily AI model release fetcher (v3 - less noisy Hugging Face feed).
Pulls new releases/announcements from major AI labs, Hugging Face trending
models, and arXiv cs.AI, then writes a digest JSON and appends to history.
Adds short human-readable summaries and simplified categories.
"""
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

DATA_DIR = "data"
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
LATEST_FILE = os.path.join(DATA_DIR, "latest.json")

RSS_SOURCES = {
    "OpenAI": ("https://openai.com/news/rss.xml", "release"),
    "Anthropic": ("https://www.anthropic.com/rss.xml", "release"),
    "Google AI": ("https://blog.google/technology/ai/rss/", "release"),
    "Meta AI": ("https://ai.meta.com/blog/rss/", "release"),
    "Hugging Face": ("https://huggingface.co/blog/feed.xml", "release"),
    "Mistral AI": ("https://mistral.ai/news/rss.xml", "release"),
    "Stability AI": ("https://stability.ai/news?format=rss", "release"),
    "DeepMind": ("https://deepmind.google/blog/rss.xml", "release"),
}

# Sort by trendingScore instead of lastModified - lastModified surfaces any
# recently-touched repo (including junk/test uploads); trendingScore reflects
# genuine community attention (likes + downloads velocity).
HF_TRENDING_API = "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=15"
HF_MIN_LIKES = 3  # filter out obscure/test repos with almost no engagement
ARXIV_API = (
    "http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.CL"
    "&sortBy=submittedDate&sortOrder=descending&max_results=15"
)

LOOKBACK_HOURS = 30
UA = {"User-Agent": "ai-model-release-radar/3.0 (+github actions daily digest)"}

CATEGORY_META = {
    "release":     {"label_en": "New Release",       "label_pt": "Lançamento",        "emoji": "🚀"},
    "model_upload":{"label_en": "New Model on HF",    "label_pt": "Novo Modelo (HF)",  "emoji": "🤗"},
    "paper":       {"label_en": "Research Paper",     "label_pt": "Artigo de Pesquisa","emoji": "📄"},
}


def http_get(url, timeout=15):
    req = Request(url, headers=UA)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def clean_text(raw, max_len=220):
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "…"
    return text


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
        desc = clean_text(item.findtext("description") or "")
        items.append({"title": title, "link": link, "published": pub, "summary": desc})
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall(".//a:entry", ns):
            title = (entry.findtext("a:title", namespaces=ns) or "").strip()
            link_el = entry.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else ""
            pub = (entry.findtext("a:updated", namespaces=ns)
                   or entry.findtext("a:published", namespaces=ns) or "").strip()
            desc = clean_text(entry.findtext("a:summary", namespaces=ns) or "")
            items.append({"title": title, "link": link, "published": pub, "summary": desc})
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
    for source, (url, category) in RSS_SOURCES.items():
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
                "summary": item.get("summary", ""),
                "published": dt.isoformat() if dt else item.get("published", ""),
                "category": category,
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
    for m in models:
        likes = m.get("likes", 0) or 0
        if likes < HF_MIN_LIKES:
            continue
        last_modified = m.get("lastModified")
        dt = None
        if last_modified:
            try:
                dt = datetime.strptime(last_modified, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        model_id = m.get("id", "")
        pipeline = m.get("pipeline_tag", "")
        summary = f"{likes} curtidas no Hugging Face" + (f" · {pipeline}" if pipeline else "")
        results.append({
            "source": "Hugging Face Hub",
            "title": model_id,
            "link": f"https://huggingface.co/{model_id}",
            "summary": summary,
            "published": dt.isoformat() if dt else "",
            "category": "model_upload",
        })
    return results[:10]


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
        summary = clean_text(entry.findtext("a:summary", namespaces=ns) or "", max_len=200)
        dt = None
        try:
            dt = datetime.strptime(published, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            pass
        if dt and dt < cutoff:
            continue
        results.append({
            "source": "arXiv",
            "title": title,
            "link": link,
            "summary": summary,
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

    releases = [it for it in all_items if it["category"] in ("release", "model_upload")]
    papers = [it for it in all_items if it["category"] == "paper"]

    lines = [f"# 🛰️ Resumo Diário de IA — {today}", ""]
    if not all_items:
        lines.append("Nenhuma novidade detectada nas últimas 24-30h.")
    else:
        if releases:
            lines.append(f"## 🚀 Lançamentos e novidades ({len(releases)})")
            for it in releases:
                meta = CATEGORY_META.get(it["category"], {})
                emoji = meta.get("emoji", "•")
                lines.append(f"**{emoji} [{it['title']}]({it['link']})** — {it['source']}")
                if it.get("summary"):
                    lines.append(f"> {it['summary']}")
                lines.append("")
        if papers:
            lines.append(f"## 📄 Pesquisas recentes ({len(papers)})")
            for it in papers[:8]:
                lines.append(f"- [{it['title']}]({it['link']})")
            if len(papers) > 8:
                lines.append(f"- …e mais {len(papers) - 8} artigos no dashboard")
            lines.append("")
    lines.append("---")
    lines.append("[📊 Ver dashboard completo](https://ricardobonbarbosa-creator.github.io/ai-model-release-radar/)")
    with open(os.path.join(DATA_DIR, "digest_body.md"), "w") as f:
        f.write("\n".join(lines))

    print(f"Digest generated: {len(all_items)} items ({len(releases)} releases, {len(papers)} papers)")


if __name__ == "__main__":
    main()
