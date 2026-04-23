"""
title: Keep Visual
author: Ullah
version: 1.0.1
required_open_webui_version: 0.6.0
description: Multi-action toolbar for copying or downloading Open-Custom Visuals outputs from page context.
"""

import json
import re
from typing import Any

from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


_BLOCK_RE = re.compile(r"@@@OCV-START\n?([\s\S]+?)(?:\n?@@@OCV-END|$)")
_FENCED_HTML_RE = re.compile(r"```(?:html|svg|xml)?\s*([\s\S]+?)```", re.IGNORECASE)
_HTML_START_RE = re.compile(r"(?is)(<!DOCTYPE[^>]*>\s*)?<(?P<tag>svg|div|section|main|article|table|figure|canvas)\b")
_HTML_SIGNAL_RE = re.compile(r"(?is)<(?:svg|div|section|main|article|table|figure|canvas|button|script|style|span|p|h[1-6])\b")
_TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_HEADING_RE = re.compile(r"(?is)<h1[^>]*>(.*?)</h1>|<h2[^>]*>(.*?)</h2>")


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def _sanitize_fragment(html_code: str) -> str:
    return re.sub(r"<!DOCTYPE[^>]*>|</?(?:html|head|body)[^>]*>", "", html_code or "", flags=re.IGNORECASE).strip()


def _collect_strings(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            _collect_strings(child, out)
    elif isinstance(value, list):
        for child in value:
            _collect_strings(child, out)


def _collect_message_ids(value: Any, out: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"id", "message_id", "messageId"} and isinstance(child, str) and child:
                out.add(child)
            _collect_message_ids(child, out)
    elif isinstance(value, list):
        for child in value:
            _collect_message_ids(child, out)


def _looks_like_visual_html(text: str) -> bool:
    if not text:
        return False
    normalized = text.strip()
    if len(normalized) < 32:
        return False
    tag_hits = len(_HTML_SIGNAL_RE.findall(normalized))
    return (
        tag_hits >= 3
        and ("</" in normalized or "/>" in normalized or "<script" in normalized)
        and any(token in normalized.lower() for token in ("<svg", "<div", "<section", "<main", "<article", "<table", "<figure", "<canvas"))
    )


def _trim_html_fragment(text: str) -> str | None:
    if not text:
        return None
    match = _HTML_START_RE.search(text)
    if not match:
        return None
    fragment = text[match.start() :].strip()
    lower = fragment.lower()
    end_candidates = [
        lower.rfind("</svg>"),
        lower.rfind("</div>"),
        lower.rfind("</section>"),
        lower.rfind("</main>"),
        lower.rfind("</article>"),
        lower.rfind("</table>"),
        lower.rfind("</figure>"),
        lower.rfind("</canvas>"),
        lower.rfind("</script>"),
    ]
    end = max(end_candidates)
    if end >= 0:
        if end == lower.rfind("</script>"):
            fragment = fragment[: end + len("</script>")]
        elif end == lower.rfind("</svg>"):
            fragment = fragment[: end + len("</svg>")]
        elif end == lower.rfind("</div>"):
            fragment = fragment[: end + len("</div>")]
        elif end == lower.rfind("</section>"):
            fragment = fragment[: end + len("</section>")]
        elif end == lower.rfind("</main>"):
            fragment = fragment[: end + len("</main>")]
        elif end == lower.rfind("</article>"):
            fragment = fragment[: end + len("</article>")]
        elif end == lower.rfind("</table>"):
            fragment = fragment[: end + len("</table>")]
        elif end == lower.rfind("</figure>"):
            fragment = fragment[: end + len("</figure>")]
    fragment = fragment.strip()
    return fragment if _looks_like_visual_html(fragment) else None


def _extract_from_text(text: str) -> str | None:
    if not text:
        return None
    for match in _FENCED_HTML_RE.finditer(text):
        candidate = _trim_html_fragment(match.group(1))
        if candidate:
            return candidate
    direct = _trim_html_fragment(text)
    return direct


def _extract_from_body(body: dict[str, Any] | None) -> str | None:
    text_parts: list[str] = []
    _collect_strings(body or {}, text_parts)
    joined = "\n".join(text_parts)
    match = _BLOCK_RE.search(joined)
    if match:
        return match.group(1)

    candidates: list[str] = []
    for text in [*text_parts, joined]:
        candidate = _extract_from_text(text)
        if candidate:
            candidates.append(candidate)
    if not candidates:
        return None
    return max(candidates, key=lambda value: (len(value), value.count("<")))


def _extract_title_from_source(source: str | None, fallback: str) -> str:
    if not source:
        return fallback
    title_match = _TITLE_RE.search(source)
    if title_match:
        title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()
        if title:
            return title
    heading_match = _HEADING_RE.search(source)
    if heading_match:
        title = re.sub(r"<[^>]+>", "", heading_match.group(1) or heading_match.group(2) or "").strip()
        if title:
            return title
    return fallback


def _build_dom_extract_code(candidates: list[str]) -> str:
    return f"""
return (() => {{
  const candidates = {json.dumps(candidates)};
  const blockRe = /@@@OCV-START\\n?([\\s\\S]+?)(?:\\n?@@@OCV-END|$)/g;
  function getSearchableText(root) {{
    try {{
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {{
        acceptNode(node) {{
          let parent = node.parentNode;
          while (parent && parent !== root) {{
            if (parent.nodeType === 1 && parent.tagName === 'DETAILS') {{
              const type = parent.getAttribute && parent.getAttribute('type');
              if (type === 'tool_calls' || type === 'reasoning' || type === 'code_execution' || type === 'code_interpreter') {{
                return NodeFilter.FILTER_REJECT;
              }}
            }}
            parent = parent.parentNode;
          }}
          return NodeFilter.FILTER_ACCEPT;
        }}
      }});
      let text = '';
      let next;
      while ((next = walker.nextNode())) text += next.nodeValue || '';
      return text;
    }} catch (e) {{
      return root.textContent || '';
    }}
  }}
  function nodes() {{
    const found = [];
    const seen = new Set();
    function push(node) {{
      if (!node || seen.has(node)) return;
      seen.add(node);
      found.push(node);
    }}
    for (const id of candidates) {{
      push(document.getElementById(id));
      push(document.getElementById('message-' + id));
      push(document.querySelector('[data-message-id="' + id + '"]'));
      push(document.querySelector('[id="message-' + id + '"]'));
    }}
    Array.from(document.querySelectorAll('[id^="message-"]')).reverse().forEach(push);
    return found;
  }}
  for (const message of nodes()) {{
    const text = getSearchableText(message);
    blockRe.lastIndex = 0;
    const match = blockRe.exec(text);
    if (match) {{
      return {{
        source: match[1],
        title: (message.querySelector('iframe') && message.querySelector('iframe').getAttribute('title')) || 'visual'
      }};
    }}
  }}
  return null;
}})();
"""


_EXPORT_DOC = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <style>
    :root {
      --color-text-primary: #172033;
      --color-text-secondary: #5f6b85;
      --color-text-tertiary: #8c97ad;
      --color-bg-primary: #ffffff;
      --color-bg-secondary: #f5f7fb;
      --color-bg-tertiary: #eef2f8;
      --color-border-tertiary: rgba(23, 32, 51, 0.14);
      --color-border-secondary: rgba(23, 32, 51, 0.28);
      --font-sans: "IBM Plex Sans", "Segoe UI", sans-serif;
      --font-mono: "IBM Plex Mono", monospace;
      --radius-md: 10px;
      --radius-lg: 16px;
      --radius-xl: 22px;
      --ramp-purple-fill:#EEEDFE; --ramp-purple-stroke:#534AB7; --ramp-purple-th:#3C3489; --ramp-purple-ts:#534AB7;
      --ramp-teal-fill:#E1F5EE; --ramp-teal-stroke:#0F6E56; --ramp-teal-th:#085041; --ramp-teal-ts:#0F6E56;
      --ramp-coral-fill:#FAECE7; --ramp-coral-stroke:#993C1D; --ramp-coral-th:#712B13; --ramp-coral-ts:#993C1D;
      --ramp-pink-fill:#FBEAF0; --ramp-pink-stroke:#993556; --ramp-pink-th:#72243E; --ramp-pink-ts:#993556;
      --ramp-gray-fill:#F1EFE8; --ramp-gray-stroke:#5F5E5A; --ramp-gray-th:#444441; --ramp-gray-ts:#5F5E5A;
      --ramp-blue-fill:#E6F1FB; --ramp-blue-stroke:#185FA5; --ramp-blue-th:#0C447C; --ramp-blue-ts:#185FA5;
      --ramp-green-fill:#EAF3DE; --ramp-green-stroke:#3B6D11; --ramp-green-th:#27500A; --ramp-green-ts:#3B6D11;
      --ramp-amber-fill:#FAEEDA; --ramp-amber-stroke:#854F0B; --ramp-amber-th:#633806; --ramp-amber-ts:#854F0B;
      --ramp-red-fill:#FCEBEB; --ramp-red-stroke:#A32D2D; --ramp-red-th:#791F1F; --ramp-red-ts:#A32D2D;
    }
    * { box-sizing: border-box; margin: 0; font-family: var(--font-sans); }
    body { padding: 12px; background: transparent; color: var(--color-text-primary); }
    svg { overflow: visible; }
    svg text { fill: var(--color-text-primary); }
    h1 { font-size: 22px; font-weight: 500; margin-bottom: 12px; }
    h2 { font-size: 18px; font-weight: 500; margin-bottom: 8px; }
    h3 { font-size: 16px; font-weight: 500; margin-bottom: 6px; }
    p  { font-size: 14px; color: var(--color-text-secondary); margin-bottom: 8px; }
    button {
      background: transparent; border: 0.5px solid var(--color-border-secondary);
      border-radius: var(--radius-md); padding: 6px 14px; font-size: 13px; color: var(--color-text-primary);
    }
    code { font-family: var(--font-mono); font-size: 13px; background: var(--color-bg-tertiary); padding: 2px 6px; border-radius: 4px; }
    .t { font: 400 14px/1.4 var(--font-sans); fill: var(--color-text-primary); }
    .ts { font: 400 12px/1.4 var(--font-sans); fill: var(--color-text-secondary); }
    .th { font: 500 14px/1.4 var(--font-sans); fill: var(--color-text-primary); }
    .box { fill: var(--color-bg-secondary); stroke: var(--color-border-tertiary); stroke-width: 0.5; }
    .node { cursor: pointer; }
    .node:hover { opacity: 0.85; }
    .arr { stroke: var(--color-border-secondary); stroke-width: 1.5; fill: none; }
    .leader { stroke: var(--color-text-tertiary); stroke-width: 0.5; stroke-dasharray: 3 2; fill: none; }
    .c-purple>rect,.c-purple>circle,.c-purple>ellipse{fill:var(--ramp-purple-fill);stroke:var(--ramp-purple-stroke);stroke-width:.5}
    .c-purple>.th{fill:var(--ramp-purple-th)!important}.c-purple>.ts{fill:var(--ramp-purple-ts)!important}
    .c-teal>rect,.c-teal>circle,.c-teal>ellipse{fill:var(--ramp-teal-fill);stroke:var(--ramp-teal-stroke);stroke-width:.5}
    .c-teal>.th{fill:var(--ramp-teal-th)!important}.c-teal>.ts{fill:var(--ramp-teal-ts)!important}
    .c-coral>rect,.c-coral>circle,.c-coral>ellipse{fill:var(--ramp-coral-fill);stroke:var(--ramp-coral-stroke);stroke-width:.5}
    .c-coral>.th{fill:var(--ramp-coral-th)!important}.c-coral>.ts{fill:var(--ramp-coral-ts)!important}
    .c-pink>rect,.c-pink>circle,.c-pink>ellipse{fill:var(--ramp-pink-fill);stroke:var(--ramp-pink-stroke);stroke-width:.5}
    .c-pink>.th{fill:var(--ramp-pink-th)!important}.c-pink>.ts{fill:var(--ramp-pink-ts)!important}
    .c-gray>rect,.c-gray>circle,.c-gray>ellipse{fill:var(--ramp-gray-fill);stroke:var(--ramp-gray-stroke);stroke-width:.5}
    .c-gray>.th{fill:var(--ramp-gray-th)!important}.c-gray>.ts{fill:var(--ramp-gray-ts)!important}
    .c-blue>rect,.c-blue>circle,.c-blue>ellipse{fill:var(--ramp-blue-fill);stroke:var(--ramp-blue-stroke);stroke-width:.5}
    .c-blue>.th{fill:var(--ramp-blue-th)!important}.c-blue>.ts{fill:var(--ramp-blue-ts)!important}
    .c-green>rect,.c-green>circle,.c-green>ellipse{fill:var(--ramp-green-fill);stroke:var(--ramp-green-stroke);stroke-width:.5}
    .c-green>.th{fill:var(--ramp-green-th)!important}.c-green>.ts{fill:var(--ramp-green-ts)!important}
    .c-amber>rect,.c-amber>circle,.c-amber>ellipse{fill:var(--ramp-amber-fill);stroke:var(--ramp-amber-stroke);stroke-width:.5}
    .c-amber>.th{fill:var(--ramp-amber-th)!important}.c-amber>.ts{fill:var(--ramp-amber-ts)!important}
    .c-red>rect,.c-red>circle,.c-red>ellipse{fill:var(--ramp-red-fill);stroke:var(--ramp-red-stroke);stroke-width:.5}
    .c-red>.th{fill:var(--ramp-red-th)!important}.c-red>.ts{fill:var(--ramp-red-ts)!important}
  </style>
</head>
<body>
  __SOURCE__
  <script>
    function sendPrompt(text) {
      try { parent.postMessage({ type: 'input:prompt:submit', text }, '*'); } catch (e) {}
    }
    function openLink(url) {
      try { window.open(url, '_blank'); } catch (e) {}
    }
    function saveState() {}
    function loadState(key, fallback) { return fallback; }
    function copyText(text) {
      try { if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(String(text == null ? '' : text)); } catch (e) {}
    }
  </script>
</body>
</html>
"""


def _build_export_doc(title: str, source: str) -> str:
    safe_title = title or "visual"
    return (
        _EXPORT_DOC
        .replace("__TITLE__", safe_title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        .replace("__SOURCE__", _sanitize_fragment(source))
    )


def _standalone_svg_xml(source: str) -> str | None:
    trimmed = _sanitize_fragment(source)
    if not trimmed:
        return None
    match = re.fullmatch(r"\s*(<svg\b[\s\S]*</svg>)\s*", trimmed, flags=re.IGNORECASE)
    return match.group(1) if match else None


_ACTION_PAGE = """
<!DOCTYPE html>
<html data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <style>
    :root {
      --fg: #172033;
      --muted: #5f6b85;
      --bg: #ffffff;
      --panel: #f5f7fb;
      --line: rgba(23, 32, 51, 0.12);
      --accent: #1455d9;
      --success: #0b8a63;
      --warning: #a55d00;
      --danger: #b42318;
      --font: "IBM Plex Sans", "Segoe UI", sans-serif;
      --radius: 18px;
    }
    :root[data-theme="dark"] {
      --fg: #e7edf8;
      --muted: #9aa7bf;
      --bg: #0f1420;
      --panel: #171f30;
      --line: rgba(255, 255, 255, 0.12);
      --accent: #81a8ff;
      --success: #49d2a4;
      --warning: #f7b267;
      --danger: #ff8f8f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 14px;
      color: var(--fg);
      background:
        radial-gradient(circle at top left, rgba(20, 85, 217, 0.10), transparent 30%),
        var(--bg);
      font-family: var(--font);
    }
    .shell {
      border: 1px solid var(--line);
      border-radius: 22px;
      overflow: hidden;
      background: var(--bg);
    }
    .toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(20, 85, 217, 0.07), transparent), var(--panel);
    }
    .title { font-size: 13px; font-weight: 600; }
    .subtitle { margin-top: 2px; font-size: 12px; color: var(--muted); }
    .meta {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .status {
      padding: 7px 11px;
      border-radius: 999px;
      border: 1px solid var(--line);
      font-size: 12px;
      color: var(--muted);
      background: var(--bg);
    }
    .status.success { color: var(--success); }
    .status.warning { color: var(--warning); }
    .status.error { color: var(--danger); }
    .actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    button {
      border: 1px solid var(--line);
      background: var(--bg);
      color: var(--fg);
      border-radius: 999px;
      padding: 8px 12px;
      font: 500 12px/1 var(--font);
      cursor: pointer;
    }
    button.primary {
      background: var(--accent);
      border-color: transparent;
      color: #fff;
    }
    .preview-wrap {
      padding: 14px;
      background: var(--panel);
    }
    iframe {
      width: 100%;
      min-height: 720px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: #fff;
    }
    .notes {
      padding: 0 14px 14px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
  </style>
</head>
<body>
  <div class="shell">
    <div class="toolbar">
      <div>
        <div class="title">__TITLE__</div>
        <div class="subtitle">__ACTION_LABEL__</div>
      </div>
      <div class="meta">
        <div id="status" class="status">Preparing…</div>
        <div class="actions">
          <button id="run" class="primary" type="button">Run again</button>
          <button type="button" onclick="openPreview()">Open preview</button>
        </div>
      </div>
    </div>
    <div class="preview-wrap">
      <iframe id="preview" title="Open-Custom Visuals export preview"></iframe>
    </div>
    <div class="notes" id="notes"></div>
  </div>
  <script>
    const actionId = __ACTION_ID__;
    const title = __TITLE_JSON__;
    const htmlDoc = __HTML_DOC__;
    const svgXml = __SVG_XML__;

    function applyTheme(dark) {
      document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    }
    try {
      const parentRoot = parent.document.documentElement;
      const detect = () => parentRoot.classList.contains('dark')
        || parentRoot.getAttribute('data-theme') === 'dark'
        || getComputedStyle(parentRoot).colorScheme === 'dark';
      applyTheme(detect());
      new MutationObserver(() => applyTheme(detect())).observe(parentRoot, {
        attributes: true,
        attributeFilter: ['class', 'data-theme', 'style']
      });
    } catch (e) {}

    const preview = document.getElementById('preview');
    preview.srcdoc = htmlDoc;

    function safeFilename(ext) {
      let base = String(title || 'visual').replace(/[<>:"/\\\\|?*]+/g, '-').replace(/\\s+/g, ' ').trim();
      if (!base) base = 'visual';
      return base + ext;
    }

    function setStatus(kind, text) {
      const status = document.getElementById('status');
      status.className = 'status' + (kind ? ' ' + kind : '');
      status.textContent = text;
      const notes = document.getElementById('notes');
      if (kind === 'error') {
        notes.textContent = 'The browser blocked this action or the visual source was incomplete. Use Run again after the page finishes loading.';
      } else if (kind === 'warning') {
        notes.textContent = text;
      } else if (kind === 'success') {
        notes.textContent = 'If nothing happened, use Run again. Some browsers only allow clipboard or download actions after the preview page fully loads.';
      } else {
        notes.textContent = '';
      }
    }

    function triggerDownload(filename, blob, mimeType) {
      const finalBlob = blob instanceof Blob ? blob : new Blob([blob], { type: mimeType });
      const url = URL.createObjectURL(finalBlob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      link.style.display = 'none';
      document.body.appendChild(link);
      link.click();
      setTimeout(() => {
        link.remove();
        URL.revokeObjectURL(url);
      }, 60000);
    }

    const scriptCache = Object.create(null);
    function loadScript(src) {
      if (scriptCache[src]) return scriptCache[src];
      scriptCache[src] = new Promise((resolve, reject) => {
        const existing = document.querySelector('script[data-ocv-lib="' + src + '"]');
        if (existing) {
          if (existing.getAttribute('data-ocv-ready') === '1') {
            resolve();
            return;
          }
          existing.addEventListener('load', resolve, { once: true });
          existing.addEventListener('error', reject, { once: true });
          return;
        }
        const script = document.createElement('script');
        script.src = src;
        script.async = true;
        script.setAttribute('data-ocv-lib', src);
        script.onload = () => {
          script.setAttribute('data-ocv-ready', '1');
          resolve();
        };
        script.onerror = reject;
        document.head.appendChild(script);
      });
      return scriptCache[src];
    }

    async function copySvgImage(svgText) {
      const url = URL.createObjectURL(new Blob([svgText], { type: 'image/svg+xml;charset=utf-8' }));
      try {
        const img = new Image();
        await new Promise((resolve, reject) => {
          img.onload = resolve;
          img.onerror = reject;
          img.src = url;
        });
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, img.width || 1400);
        canvas.height = Math.max(1, img.height || 900);
        const context = canvas.getContext('2d');
        if (!context) throw new Error('Canvas rendering is unavailable.');
        context.drawImage(img, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
        if (!blob || !navigator.clipboard || !window.ClipboardItem) {
          throw new Error('Clipboard image API unavailable.');
        }
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
      } finally {
        URL.revokeObjectURL(url);
      }
    }

    async function copyHtmlImage(docHtml) {
      await loadScript('https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js');
      const iframe = document.createElement('iframe');
      iframe.style.cssText = 'position:fixed;left:-10000px;top:0;width:1600px;height:1200px;border:0;opacity:0;';
      document.body.appendChild(iframe);
      iframe.srcdoc = docHtml;
      try {
        await new Promise((resolve) => {
          iframe.onload = resolve;
        });
        await new Promise((resolve) => setTimeout(resolve, 900));
        const canvas = await window.html2canvas(iframe.contentDocument.body, {
          backgroundColor: null,
          scale: Math.min(window.devicePixelRatio || 1, 2),
          useCORS: true
        });
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
        if (!blob || !navigator.clipboard || !window.ClipboardItem) {
          throw new Error('Clipboard image API unavailable.');
        }
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
      } finally {
        iframe.remove();
      }
    }

    function openPreview() {
      const blob = new Blob([htmlDoc], { type: 'text/html;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    }

    async function runAction() {
      setStatus('', 'Working…');
      try {
        if (actionId === 'download_html') {
          triggerDownload(safeFilename('.html'), htmlDoc, 'text/html;charset=utf-8');
          setStatus('success', 'Downloaded HTML export.');
          return;
        }
        if (actionId === 'download_svg') {
          if (!svgXml) {
            setStatus('warning', 'SVG download is only available when the visual is a single standalone SVG root.');
            return;
          }
          triggerDownload(safeFilename('.svg'), svgXml, 'image/svg+xml;charset=utf-8');
          setStatus('success', 'Downloaded SVG export.');
          return;
        }
        if (actionId === 'copy_image') {
          if (svgXml) {
            await copySvgImage(svgXml);
          } else {
            await copyHtmlImage(htmlDoc);
          }
          setStatus('success', 'Copied visual image.');
          return;
        }
        setStatus('error', 'Unknown export action.');
      } catch (error) {
        setStatus('error', error && error.message ? error.message : String(error));
      }
    }

    document.getElementById('run').addEventListener('click', runAction);
    window.addEventListener('load', () => setTimeout(runAction, 80));
  </script>
</body>
</html>
"""


def _build_action_page(action_id: str, title: str, html_doc: str, svg_xml: str | None) -> str:
    action_label = {
        "copy_image": "Copy Image",
        "download_html": "Download HTML",
        "download_svg": "Download SVG",
    }.get(action_id, "Keep Visual")
    safe_title = title or "visual"
    return (
        _ACTION_PAGE
        .replace("__TITLE__", safe_title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        .replace("__ACTION_LABEL__", action_label)
        .replace("__ACTION_ID__", _safe_json(action_id))
        .replace("__TITLE_JSON__", _safe_json(safe_title))
        .replace("__HTML_DOC__", _safe_json(html_doc))
        .replace("__SVG_XML__", _safe_json(svg_xml))
    )


class Action:
    actions = [
        {"id": "copy_image", "name": "Copy Image"},
        {"id": "download_html", "name": "Download HTML"},
        {"id": "download_svg", "name": "Download SVG"},
    ]

    class Valves(BaseModel):
        priority: int = Field(default=11, description="Lower values appear earlier in the message toolbar.")

    def __init__(self):
        self.valves = self.Valves()

    async def action(
        self,
        body: dict,
        __id__=None,
        __event_call__=None,
        __event_emitter__=None,
    ):
        action_id = __id__ or "download_html"
        source = _extract_from_body(body)
        title = _extract_title_from_source(source, "visual")

        if not source:
            return {"content": "No Open-Custom Visuals block was found on this message."}

        html_doc = _build_export_doc(title, source)
        svg_xml = _standalone_svg_xml(source)
        return HTMLResponse(content=_build_action_page(action_id, title, html_doc, svg_xml))
