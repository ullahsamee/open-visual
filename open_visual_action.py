"""
title: Open Visual
author: Ullah
version: 1.1.0
required_open_webui_version: 0.6.0
description: Opens Open-Custom Visuals with runtime-parity recovery: clone the live iframe when possible, otherwise rebuild the saved visual with the original theme tokens, helper APIs, and export controls.
"""

import json
import re
from typing import Any

from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


_OCV_BUILD = "3.1.0"
_START_MARK = "@@@OCV-START"
_END_MARK = "@@@OCV-END"
_BLOCK_RE = re.compile(r"@@@OCV-START\n?([\s\S]+?)(?:\n?@@@OCV-END|$)")
_FENCED_HTML_RE = re.compile(r"```(?:html|svg|xml)?\s*([\s\S]+?)```", re.IGNORECASE)
_HTML_START_RE = re.compile(r"(?is)(<!DOCTYPE[^>]*>\s*)?<(?P<tag>svg|div|section|main|article|table|figure|canvas)\b")
_HTML_SIGNAL_RE = re.compile(r"(?is)<(?:svg|div|section|main|article|table|figure|canvas|button|script|style|span|p|h[1-6]|input|select)\b")
_TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_HEADING_RE = re.compile(r"(?is)<h1[^>]*>(.*?)</h1>|<h2[^>]*>(.*?)</h2>")
_RUNTIME_ASSIGN_RE = re.compile(r"window\.OpenCustomVisuals\s*=")


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


def _extract_runtime_contract_from_text(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    decoder = json.JSONDecoder()
    for match in _RUNTIME_ASSIGN_RE.finditer(text):
        brace_index = text.find("{", match.end())
        if brace_index < 0:
            continue
        try:
            payload, _ = decoder.raw_decode(text[brace_index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _extract_runtime_contract_from_body(body: dict[str, Any] | None) -> dict[str, Any] | None:
    text_parts: list[str] = []
    _collect_strings(body or {}, text_parts)
    joined = "\n".join(text_parts)
    for text in [joined, *text_parts]:
        payload = _extract_runtime_contract_from_text(text)
        if payload:
            return payload
    return None


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
    return _trim_html_fragment(text)


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
  function messageNodes() {{
    const nodes = [];
    const seen = new Set();
    function push(node) {{
      if (!node || seen.has(node)) return;
      seen.add(node);
      nodes.push(node);
    }}
    for (const id of candidates) {{
      push(document.getElementById(id));
      push(document.getElementById('message-' + id));
      push(document.querySelector('[data-message-id="' + id + '"]'));
      push(document.querySelector('[id="message-' + id + '"]'));
    }}
    Array.from(document.querySelectorAll('[id^="message-"]')).reverse().forEach(push);
    return nodes;
  }}
  function liveHtmlDoc(iframe) {{
    try {{
      if (iframe && iframe.contentDocument && iframe.contentDocument.documentElement) {{
        const doc = iframe.contentDocument;
        const doctype = doc.doctype && doc.doctype.name ? '<!DOCTYPE ' + doc.doctype.name + '>' : '<!DOCTYPE html>';
        return doctype + '\\n' + doc.documentElement.outerHTML;
      }}
    }} catch (e) {{}}
    return null;
  }}
  function liveContract(iframe) {{
    try {{
      if (iframe && iframe.contentWindow && iframe.contentWindow.OpenCustomVisuals) {{
        return JSON.parse(JSON.stringify(iframe.contentWindow.OpenCustomVisuals));
      }}
    }} catch (e) {{}}
    return null;
  }}
  function liveTitle(message, iframe) {{
    try {{
      if (iframe && iframe.contentDocument && iframe.contentDocument.title) {{
        return iframe.contentDocument.title;
      }}
    }} catch (e) {{}}
    return (iframe && iframe.getAttribute('title')) || message.getAttribute('data-title') || 'Open Visual';
  }}
  for (const message of messageNodes()) {{
    const iframe = message.querySelector('iframe');
    const text = getSearchableText(message);
    blockRe.lastIndex = 0;
    const match = blockRe.exec(text);
    const htmlDoc = liveHtmlDoc(iframe);
    const contract = liveContract(iframe);
    const srcdoc = iframe ? (iframe.getAttribute('srcdoc') || null) : null;
    if (match || htmlDoc || contract || srcdoc) {{
      return {{
        messageId: message.id || null,
        source: match ? match[1] : null,
        title: liveTitle(message, iframe),
        htmlDoc,
        contract,
        srcdoc
      }};
    }}
  }}
  return null;
}})();
"""


async def _extract_live_view(body: dict[str, Any] | None, __event_call__=None) -> dict[str, Any] | None:
    if not __event_call__:
        return None
    candidates: set[str] = set()
    _collect_message_ids(body or {}, candidates)
    try:
        result = await __event_call__(
            {
                "type": "execute",
                "data": {"code": _build_dom_extract_code(sorted(candidates))},
            }
        )
    except Exception:
        return None
    return result if isinstance(result, dict) else None


def _normalize_runtime_contract(title: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    contract = dict(payload or {})
    contract["version"] = str(contract.get("version") or _OCV_BUILD)
    contract["title"] = str(contract.get("title") or title or "Open Visual")
    contract["mode"] = "static"
    contract["dataset"] = contract.get("dataset")
    contract["datasetSummary"] = contract.get("datasetSummary")

    markers = contract.get("markers") if isinstance(contract.get("markers"), dict) else {}
    markers.setdefault("start", _START_MARK)
    markers.setdefault("end", _END_MARK)
    contract["markers"] = markers

    capabilities = contract.get("capabilities") if isinstance(contract.get("capabilities"), dict) else {}
    capabilities.setdefault("securityLevel", "recovered")
    capabilities.setdefault("streaming", False)
    capabilities.setdefault("staticFallback", True)
    capabilities.setdefault("sameOriginRequiredForStreaming", True)
    exports = capabilities.get("exports")
    if not isinstance(exports, list) or not exports:
        capabilities["exports"] = ["copyImage", "downloadHTML", "downloadSVG"]
    contract["capabilities"] = capabilities
    return contract


_THEME_CSS = """
:root {
  --color-text-primary: #1F2937;
  --color-text-secondary: #6B7280;
  --color-text-tertiary: #9CA3AF;
  --color-text-info: #2563EB;
  --color-text-success: #059669;
  --color-text-warning: #D97706;
  --color-text-danger: #DC2626;
  --color-bg-primary: #FFFFFF;
  --color-bg-secondary: #F9FAFB;
  --color-bg-tertiary: #F3F4F6;
  --color-border-tertiary: rgba(0,0,0,0.15);
  --color-border-secondary: rgba(0,0,0,0.3);
  --color-border-primary: rgba(0,0,0,0.4);
  --font-sans: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  --font-mono: 'SF Mono', Menlo, Consolas, monospace;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --ramp-purple-fill:#EEEDFE; --ramp-purple-stroke:#534AB7; --ramp-purple-th:#3C3489; --ramp-purple-ts:#534AB7;
  --ramp-teal-fill:#E1F5EE;   --ramp-teal-stroke:#0F6E56;   --ramp-teal-th:#085041;   --ramp-teal-ts:#0F6E56;
  --ramp-coral-fill:#FAECE7;  --ramp-coral-stroke:#993C1D;  --ramp-coral-th:#712B13;  --ramp-coral-ts:#993C1D;
  --ramp-pink-fill:#FBEAF0;   --ramp-pink-stroke:#993556;   --ramp-pink-th:#72243E;   --ramp-pink-ts:#993556;
  --ramp-gray-fill:#F1EFE8;   --ramp-gray-stroke:#5F5E5A;   --ramp-gray-th:#444441;   --ramp-gray-ts:#5F5E5A;
  --ramp-blue-fill:#E6F1FB;   --ramp-blue-stroke:#185FA5;   --ramp-blue-th:#0C447C;   --ramp-blue-ts:#185FA5;
  --ramp-green-fill:#EAF3DE;  --ramp-green-stroke:#3B6D11;  --ramp-green-th:#27500A;  --ramp-green-ts:#3B6D11;
  --ramp-amber-fill:#FAEEDA;  --ramp-amber-stroke:#854F0B;  --ramp-amber-th:#633806;  --ramp-amber-ts:#854F0B;
  --ramp-red-fill:#FCEBEB;    --ramp-red-stroke:#A32D2D;    --ramp-red-th:#791F1F;    --ramp-red-ts:#A32D2D;
  --fg: var(--color-text-primary);
  --text: var(--color-text-primary);
  --foreground: var(--color-text-primary);
  --text-primary: var(--color-text-primary);
  --text-color: var(--color-text-primary);
  --color-text: var(--color-text-primary);
  --color-foreground: var(--color-text-primary);
  --body-color: var(--color-text-primary);
  --muted: var(--color-text-secondary);
  --muted-foreground: var(--color-text-secondary);
  --text-muted: var(--color-text-secondary);
  --text-secondary: var(--color-text-secondary);
  --secondary: var(--color-text-secondary);
  --subtle: var(--color-text-tertiary);
  --text-tertiary: var(--color-text-tertiary);
  --bg: var(--color-bg-primary);
  --background: var(--color-bg-primary);
  --bg-primary: var(--color-bg-primary);
  --body-bg: var(--color-bg-primary);
  --color-bg: var(--color-bg-primary);
  --surface: var(--color-bg-secondary);
  --surface-1: var(--color-bg-secondary);
  --surface-2: var(--color-bg-tertiary);
  --card: var(--color-bg-secondary);
  --card-bg: var(--color-bg-secondary);
  --card-foreground: var(--color-text-primary);
  --card-background: var(--color-bg-secondary);
  --popover: var(--color-bg-secondary);
  --popover-foreground: var(--color-text-primary);
  --hover: rgba(0,0,0,0.04);
  --border: var(--color-border-tertiary);
  --border-color: var(--color-border-tertiary);
  --divider: var(--color-border-tertiary);
  --separator: var(--color-border-tertiary);
  --input: var(--color-border-tertiary);
  --ring: var(--color-border-secondary);
  --primary: #6c2eb9;
  --primary-foreground: #ffffff;
  --accent: #6c2eb9;
  --accent-foreground: #ffffff;
}
:root[data-theme="dark"] {
  --color-text-primary: #E5E7EB;
  --color-text-secondary: #9CA3AF;
  --color-text-tertiary: #6B7280;
  --color-text-info: #60A5FA;
  --color-text-success: #34D399;
  --color-text-warning: #FBBF24;
  --color-text-danger: #F87171;
  --color-bg-primary: #1A1A1A;
  --color-bg-secondary: #262626;
  --color-bg-tertiary: #111111;
  --color-border-tertiary: rgba(255,255,255,0.15);
  --color-border-secondary: rgba(255,255,255,0.3);
  --color-border-primary: rgba(255,255,255,0.4);
  --ramp-purple-fill:#3C3489; --ramp-purple-stroke:#AFA9EC; --ramp-purple-th:#CECBF6; --ramp-purple-ts:#AFA9EC;
  --ramp-teal-fill:#085041;   --ramp-teal-stroke:#5DCAA5;   --ramp-teal-th:#9FE1CB;   --ramp-teal-ts:#5DCAA5;
  --ramp-coral-fill:#712B13;  --ramp-coral-stroke:#F0997B;  --ramp-coral-th:#F5C4B3;  --ramp-coral-ts:#F0997B;
  --ramp-pink-fill:#72243E;   --ramp-pink-stroke:#ED93B1;   --ramp-pink-th:#F4C0D1;   --ramp-pink-ts:#ED93B1;
  --ramp-gray-fill:#444441;   --ramp-gray-stroke:#B4B2A9;   --ramp-gray-th:#D3D1C7;   --ramp-gray-ts:#B4B2A9;
  --ramp-blue-fill:#0C447C;   --ramp-blue-stroke:#85B7EB;   --ramp-blue-th:#B5D4F4;   --ramp-blue-ts:#85B7EB;
  --ramp-green-fill:#27500A;  --ramp-green-stroke:#97C459;  --ramp-green-th:#C0DD97;  --ramp-green-ts:#97C459;
  --ramp-amber-fill:#633806;  --ramp-amber-stroke:#EF9F27;  --ramp-amber-th:#FAC775;  --ramp-amber-ts:#EF9F27;
  --ramp-red-fill:#791F1F;    --ramp-red-stroke:#F09595;    --ramp-red-th:#F7C1C1;    --ramp-red-ts:#F09595;
  --text: var(--color-text-primary);
  --foreground: var(--color-text-primary);
  --text-primary: var(--color-text-primary);
  --text-color: var(--color-text-primary);
  --color-text: var(--color-text-primary);
  --body-color: var(--color-text-primary);
  --muted: var(--color-text-secondary);
  --muted-foreground: var(--color-text-secondary);
  --text-muted: var(--color-text-secondary);
  --text-secondary: var(--color-text-secondary);
  --secondary: var(--color-text-secondary);
  --subtle: var(--color-text-tertiary);
  --text-tertiary: var(--color-text-tertiary);
  --bg: var(--color-bg-primary);
  --background: var(--color-bg-primary);
  --bg-primary: var(--color-bg-primary);
  --body-bg: var(--color-bg-primary);
  --color-bg: var(--color-bg-primary);
  --surface: var(--color-bg-secondary);
  --surface-1: var(--color-bg-secondary);
  --surface-2: var(--color-bg-tertiary);
  --card: var(--color-bg-secondary);
  --card-bg: var(--color-bg-secondary);
  --card-foreground: var(--color-text-primary);
  --card-background: var(--color-bg-secondary);
  --popover: var(--color-bg-secondary);
  --popover-foreground: var(--color-text-primary);
  --hover: rgba(255,255,255,0.06);
  --border: var(--color-border-tertiary);
  --border-color: var(--color-border-tertiary);
  --divider: var(--color-border-tertiary);
  --separator: var(--color-border-tertiary);
  --input: var(--color-border-tertiary);
  --ring: var(--color-border-secondary);
  --primary: #a78bfa;
  --primary-foreground: #1A1A1A;
  --accent: #a78bfa;
  --accent-foreground: #ffffff;
}
"""


_SVG_CLASSES = """
.t  { font: 400 14px/1.4 var(--font-sans); fill: var(--color-text-primary); }
.ts { font: 400 12px/1.4 var(--font-sans); fill: var(--color-text-secondary); }
.th { font: 500 14px/1.4 var(--font-sans); fill: var(--color-text-primary); }
.box    { fill: var(--color-bg-secondary); stroke: var(--color-border-tertiary); stroke-width: 0.5; }
.node   { cursor: pointer; }
.node:hover { opacity: 0.85; }
.arr    { stroke: var(--color-border-secondary); stroke-width: 1.5; fill: none; }
.leader { stroke: var(--color-text-tertiary); stroke-width: 0.5; stroke-dasharray: 3 2; fill: none; }
.c-purple>rect,.c-purple>circle,.c-purple>ellipse{fill:var(--ramp-purple-fill);stroke:var(--ramp-purple-stroke);stroke-width:.5}
.c-purple>.th{fill:var(--ramp-purple-th)!important} .c-purple>.ts{fill:var(--ramp-purple-ts)!important}
.c-teal>rect,.c-teal>circle,.c-teal>ellipse{fill:var(--ramp-teal-fill);stroke:var(--ramp-teal-stroke);stroke-width:.5}
.c-teal>.th{fill:var(--ramp-teal-th)!important} .c-teal>.ts{fill:var(--ramp-teal-ts)!important}
.c-coral>rect,.c-coral>circle,.c-coral>ellipse{fill:var(--ramp-coral-fill);stroke:var(--ramp-coral-stroke);stroke-width:.5}
.c-coral>.th{fill:var(--ramp-coral-th)!important} .c-coral>.ts{fill:var(--ramp-coral-ts)!important}
.c-pink>rect,.c-pink>circle,.c-pink>ellipse{fill:var(--ramp-pink-fill);stroke:var(--ramp-pink-stroke);stroke-width:.5}
.c-pink>.th{fill:var(--ramp-pink-th)!important} .c-pink>.ts{fill:var(--ramp-pink-ts)!important}
.c-gray>rect,.c-gray>circle,.c-gray>ellipse{fill:var(--ramp-gray-fill);stroke:var(--ramp-gray-stroke);stroke-width:.5}
.c-gray>.th{fill:var(--ramp-gray-th)!important} .c-gray>.ts{fill:var(--ramp-gray-ts)!important}
.c-blue>rect,.c-blue>circle,.c-blue>ellipse{fill:var(--ramp-blue-fill);stroke:var(--ramp-blue-stroke);stroke-width:.5}
.c-blue>.th{fill:var(--ramp-blue-th)!important} .c-blue>.ts{fill:var(--ramp-blue-ts)!important}
.c-green>rect,.c-green>circle,.c-green>ellipse{fill:var(--ramp-green-fill);stroke:var(--ramp-green-stroke);stroke-width:.5}
.c-green>.th{fill:var(--ramp-green-th)!important} .c-green>.ts{fill:var(--ramp-green-ts)!important}
.c-amber>rect,.c-amber>circle,.c-amber>ellipse{fill:var(--ramp-amber-fill);stroke:var(--ramp-amber-stroke);stroke-width:.5}
.c-amber>.th{fill:var(--ramp-amber-th)!important} .c-amber>.ts{fill:var(--ramp-amber-ts)!important}
.c-red>rect,.c-red>circle,.c-red>ellipse{fill:var(--ramp-red-fill);stroke:var(--ramp-red-stroke);stroke-width:.5}
.c-red>.th{fill:var(--ramp-red-th)!important} .c-red>.ts{fill:var(--ramp-red-ts)!important}
"""


_RECOVERY_HTML = """
<!DOCTYPE html>
<html data-theme="light" data-ocv-build="__BUILD__">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <style>
    __THEME_CSS__
    __SVG_CLASSES__
    * { box-sizing: border-box; margin: 0; font-family: var(--font-sans); }
    html, body { min-height: 100%; background: var(--color-bg-primary); }
    body {
      padding: 16px;
      color: var(--color-text-primary);
      background:
        radial-gradient(circle at top left, rgba(37, 99, 235, 0.08), transparent 28%),
        linear-gradient(180deg, rgba(249, 250, 251, 0.88), rgba(255, 255, 255, 1));
    }
    :root[data-theme="dark"] body {
      background:
        radial-gradient(circle at top left, rgba(96, 165, 250, 0.12), transparent 30%),
        linear-gradient(180deg, rgba(17, 17, 17, 0.96), rgba(26, 26, 26, 1));
    }
    svg { overflow: visible; }
    svg text { fill: var(--color-text-primary); }
    h1 { font-size: 22px; font-weight: 600; color: var(--color-text-primary); margin-bottom: 12px; }
    h2 { font-size: 18px; font-weight: 600; color: var(--color-text-primary); margin-bottom: 8px; }
    h3 { font-size: 16px; font-weight: 600; color: var(--color-text-primary); margin-bottom: 6px; }
    p  { font-size: 14px; color: var(--color-text-secondary); margin-bottom: 8px; line-height: 1.6; }
    button {
      background: var(--color-bg-primary);
      border: 0.5px solid var(--color-border-tertiary);
      border-radius: var(--radius-md);
      padding: 8px 12px;
      font-size: 13px;
      color: var(--color-text-primary);
      cursor: pointer;
    }
    button:hover { background: var(--color-bg-secondary); }
    button.active { background: var(--color-bg-secondary); border-color: var(--color-border-primary); }
    select {
      background: var(--color-bg-secondary);
      border: 0.5px solid var(--color-border-tertiary);
      border-radius: var(--radius-md);
      padding: 6px 10px;
      font-size: 13px;
      color: var(--color-text-primary);
    }
    input[type="range"] {
      -webkit-appearance: none;
      width: 100%;
      height: 4px;
      background: var(--color-border-tertiary);
      border-radius: 999px;
      outline: none;
    }
    input[type="range"]::-webkit-slider-thumb {
      -webkit-appearance: none;
      width: 18px;
      height: 18px;
      border-radius: 50%;
      background: var(--color-bg-primary);
      border: 0.5px solid var(--color-border-secondary);
      cursor: pointer;
    }
    code {
      font-family: var(--font-mono);
      font-size: 13px;
      background: var(--color-bg-tertiary);
      padding: 2px 6px;
      border-radius: 4px;
    }
    pre {
      font-family: var(--font-mono);
      white-space: pre-wrap;
      word-break: break-word;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      color: var(--color-text-primary);
    }
    th, td {
      border-bottom: 0.5px solid var(--color-border-tertiary);
      padding: 8px 10px;
      text-align: left;
      font-size: 13px;
    }
    .ov-shell {
      border: 1px solid var(--color-border-tertiary);
      border-radius: 22px;
      overflow: hidden;
      background: var(--color-bg-primary);
      background: color-mix(in srgb, var(--color-bg-primary) 92%, transparent);
      box-shadow: 0 16px 48px rgba(15, 23, 42, 0.08);
      backdrop-filter: blur(10px);
    }
    .ov-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 14px 16px;
      border-bottom: 0.5px solid var(--color-border-tertiary);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.5), rgba(255,255,255,0.18)),
        var(--color-bg-secondary);
    }
    :root[data-theme="dark"] .ov-toolbar {
      background:
        linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01)),
        var(--color-bg-secondary);
    }
    .ov-title {
      font-size: 14px;
      font-weight: 600;
      color: var(--color-text-primary);
      letter-spacing: 0.01em;
    }
    .ov-subtitle {
      margin-top: 3px;
      font-size: 12px;
      color: var(--color-text-secondary);
    }
    .ov-toolbar-right {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .ov-status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 32px;
      padding: 0 10px;
      border-radius: 999px;
      background: var(--color-bg-primary);
      border: 0.5px solid var(--color-border-tertiary);
      font-size: 12px;
      color: var(--color-text-secondary);
    }
    .ov-status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--color-text-tertiary);
    }
    .ov-status[data-tone="ready"] .ov-status-dot { background: var(--color-text-success); }
    .ov-status[data-tone="limited"] .ov-status-dot { background: var(--color-text-warning); }
    .ov-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .ov-primary {
      background: var(--color-bg-secondary);
      border-color: var(--color-border-secondary);
    }
    #iv-render {
      position: relative;
      padding: 18px;
      min-height: 140px;
      background: transparent;
    }
    #iv-render > *:first-child { margin-top: 0; }
    .ov-toast-stack {
      position: fixed;
      top: 18px;
      right: 18px;
      z-index: 9999;
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-width: min(360px, calc(100vw - 36px));
      pointer-events: none;
    }
    .ov-toast {
      padding: 8px 12px;
      border-radius: var(--radius-md);
      background: var(--color-bg-secondary);
      border: 0.5px solid var(--color-border-tertiary);
      color: var(--color-text-primary);
      font-size: 12px;
      line-height: 1.4;
      box-shadow: 0 10px 28px rgba(15, 23, 42, 0.16);
      opacity: 0;
      transform: translateY(-4px);
      transition: opacity 0.18s ease, transform 0.18s ease;
    }
    .ov-toast[data-tone="success"] { color: var(--color-text-success); }
    .ov-toast[data-tone="warn"] { color: var(--color-text-warning); }
    .ov-toast[data-tone="danger"] { color: var(--color-text-danger); }
    @media (max-width: 720px) {
      body { padding: 10px; }
      .ov-toolbar {
        align-items: flex-start;
        flex-direction: column;
      }
      .ov-toolbar-right {
        width: 100%;
        justify-content: flex-start;
      }
      #iv-render { padding: 14px; }
    }
  </style>
  <script>
    (function() {
      function detectTheme(root) {
        return root.classList.contains('dark')
          || root.getAttribute('data-theme') === 'dark'
          || getComputedStyle(root).colorScheme === 'dark';
      }
      function applyTheme(isDark) {
        var theme = isDark ? 'dark' : 'light';
        if (document.documentElement.getAttribute('data-theme') === theme) return;
        document.documentElement.setAttribute('data-theme', theme);
        if (window.Chart && Chart.instances) {
          var s = getComputedStyle(document.documentElement);
          var tickColor = s.getPropertyValue('--color-text-secondary').trim();
          var gridColor = s.getPropertyValue('--color-border-tertiary').trim();
          Chart.defaults.color = tickColor;
          Chart.defaults.borderColor = gridColor;
          Object.values(Chart.instances).forEach(function(chart) {
            Object.values(chart.options.scales || {}).forEach(function(scale) {
              if (scale.ticks) scale.ticks.color = tickColor;
              if (scale.grid) scale.grid.color = gridColor;
            });
            var legend = (chart.options.plugins || {}).legend;
            if (legend && legend.labels) legend.labels.color = tickColor;
            chart.update();
          });
        }
      }
      try {
        var parentRoot = parent.document.documentElement;
        applyTheme(detectTheme(parentRoot));
        new MutationObserver(function() {
          applyTheme(detectTheme(parentRoot));
        }).observe(parentRoot, { attributes: true, attributeFilter: ['class', 'data-theme', 'style'] });
      } catch (e) {
        var mq = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)');
        if (mq) {
          applyTheme(mq.matches);
          if (mq.addEventListener) {
            mq.addEventListener('change', function(event) { applyTheme(event.matches); });
          } else if (mq.addListener) {
            mq.addListener(function(event) { applyTheme(event.matches); });
          }
        }
      }
    })();
  </script>
</head>
<body>
  <div class="ov-shell">
    <div class="ov-toolbar">
      <div>
        <div class="ov-title">__TITLE__</div>
        <div class="ov-subtitle">Recovered from the saved Open-Custom Visuals block with runtime-parity helpers.</div>
      </div>
      <div class="ov-toolbar-right">
        <div id="ocv-status" class="ov-status" data-tone="ready">
          <span class="ov-status-dot"></span>
          <span id="ocv-status-text">Recovered visual</span>
        </div>
        <div class="ov-actions">
          <button type="button" class="ov-primary" onclick="copyImage()">Copy image</button>
          <button type="button" onclick="downloadHTML()">Download HTML</button>
          <button type="button" onclick="downloadSVG()">Download SVG</button>
          <button type="button" onclick="enterFullscreen()">Fullscreen</button>
        </div>
      </div>
    </div>
    <div id="ocv-toast-stack" class="ov-toast-stack" aria-live="polite"></div>
    <script>
      const OCV_CONTRACT = __CONTRACT_JSON__;

      function reportHeight() {
        var root = document.documentElement;
        var body = document.body;
        var height = Math.max(
          root ? root.scrollHeight : 0,
          body ? body.scrollHeight : 0,
          root ? root.offsetHeight : 0,
          body ? body.offsetHeight : 0
        );
        try { parent.postMessage({ type: 'iframe:height', height: height }, '*'); } catch (e) {}
      }

      function toast(message, tone) {
        var stack = document.getElementById('ocv-toast-stack');
        if (!stack) return;
        var item = document.createElement('div');
        item.className = 'ov-toast';
        item.setAttribute('data-tone', tone || 'info');
        item.textContent = String(message == null ? '' : message);
        stack.appendChild(item);
        requestAnimationFrame(function() {
          item.style.opacity = '1';
          item.style.transform = 'none';
        });
        setTimeout(function() {
          item.style.opacity = '0';
          item.style.transform = 'translateY(-4px)';
          setTimeout(function() {
            if (item.parentNode) item.parentNode.removeChild(item);
          }, 200);
        }, 2200);
      }

      function sendPrompt(text) {
        try {
          parent.postMessage({ type: 'input:prompt:submit', text: String(text == null ? '' : text) }, '*');
        } catch (e) {}
      }

      function openLink(url) {
        try {
          parent.window.open(url, '_blank', 'noopener,noreferrer');
          return;
        } catch (e) {}
        try {
          window.open(url, '_blank', 'noopener,noreferrer');
        } catch (e) {}
      }

      function _statePrefix() {
        var base = 'ocv-open:';
        try {
          if (window.frameElement && window.frameElement.id) {
            return base + window.frameElement.id + ':';
          }
        } catch (e) {}
        return base + (OCV_CONTRACT.title || 'visual') + ':';
      }

      function saveState(key, value) {
        var raw = JSON.stringify(value === undefined ? null : value);
        try {
          parent.localStorage.setItem(_statePrefix() + String(key), raw);
          return;
        } catch (e) {}
        try {
          localStorage.setItem(_statePrefix() + String(key), raw);
        } catch (e) {}
      }

      function loadState(key, fallback) {
        try {
          var fromParent = parent.localStorage.getItem(_statePrefix() + String(key));
          if (fromParent != null) return JSON.parse(fromParent);
        } catch (e) {}
        try {
          var local = localStorage.getItem(_statePrefix() + String(key));
          if (local != null) return JSON.parse(local);
        } catch (e) {}
        return fallback === undefined ? null : fallback;
      }

      function copyText(text, silent) {
        var value = String(text == null ? '' : text);
        function done() {
          if (!silent) toast('Copied', 'success');
        }
        function legacy() {
          try {
            var ta = document.createElement('textarea');
            ta.value = value;
            ta.setAttribute('readonly', '');
            ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0;';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            try { ta.setSelectionRange(0, value.length); } catch (e) {}
            try { document.execCommand('copy'); } catch (e) {}
            ta.remove();
          } catch (e) {}
          done();
        }
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(value).then(done, legacy);
            return;
          }
        } catch (e) {}
        legacy();
      }

      function setToolbarStatus(text, tone) {
        var root = document.getElementById('ocv-status');
        var label = document.getElementById('ocv-status-text');
        if (!root || !label) return;
        if (text) label.textContent = String(text);
        root.setAttribute('data-tone', tone || 'idle');
      }

      function enterFullscreen() {
        var target = null;
        try { target = window.frameElement || document.documentElement; } catch (e) {}
        target = target || document.documentElement;
        try {
          if (target.requestFullscreen) return target.requestFullscreen();
          if (target.webkitRequestFullscreen) return target.webkitRequestFullscreen();
        } catch (e) {}
      }

      function findSvg() {
        var render = document.getElementById('iv-render');
        if (!render) return null;
        var children = Array.from(render.children || []).filter(function(node) {
          return node.tagName !== 'SCRIPT' && node.tagName !== 'STYLE';
        });
        if (children.length === 1 && children[0].tagName && children[0].tagName.toLowerCase() === 'svg') {
          return children[0];
        }
        return render.querySelector('svg');
      }

      function safeFilename(ext) {
        var base = String((OCV_CONTRACT && OCV_CONTRACT.title) || 'visual')
          .replace(/[<>:"/\\\\|?*]+/g, '-')
          .replace(/\\s+/g, ' ')
          .trim();
        if (!base) base = 'visual';
        return base + ext;
      }

      function downloadHTML() {
        try {
          var html = '<!DOCTYPE html>\\n' + document.documentElement.outerHTML;
          var blob = new Blob([html], { type: 'text/html;charset=utf-8' });
          var url = URL.createObjectURL(blob);
          var link = document.createElement('a');
          link.href = url;
          link.download = safeFilename('.html');
          link.target = '_blank';
          link.click();
          setTimeout(function() { URL.revokeObjectURL(url); }, 60000);
        } catch (e) {
          toast('HTML export failed.', 'danger');
        }
      }

      function downloadSVG() {
        var svg = findSvg();
        if (!svg) {
          toast('SVG export is only available when the visual renders a standalone SVG root.', 'warn');
          return;
        }
        try {
          var xml = new XMLSerializer().serializeToString(svg);
          var blob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' });
          var url = URL.createObjectURL(blob);
          var link = document.createElement('a');
          link.href = url;
          link.download = safeFilename('.svg');
          link.target = '_blank';
          link.click();
          setTimeout(function() { URL.revokeObjectURL(url); }, 60000);
        } catch (e) {
          toast('SVG export failed.', 'danger');
        }
      }

      var scriptCache = Object.create(null);
      function loadScript(src) {
        if (scriptCache[src]) return scriptCache[src];
        scriptCache[src] = new Promise(function(resolve, reject) {
          var el = document.createElement('script');
          el.src = src;
          el.async = true;
          el.onload = resolve;
          el.onerror = reject;
          document.head.appendChild(el);
        });
        return scriptCache[src];
      }

      async function copyImage() {
        var svg = findSvg();
        if (svg) {
          var xml = new XMLSerializer().serializeToString(svg);
          var url = URL.createObjectURL(new Blob([xml], { type: 'image/svg+xml;charset=utf-8' }));
          try {
            var img = new Image();
            await new Promise(function(resolve, reject) {
              img.onload = resolve;
              img.onerror = reject;
              img.src = url;
            });
            var rect = svg.getBoundingClientRect();
            var canvas = document.createElement('canvas');
            canvas.width = Math.max(1, Math.ceil(rect.width || 1200));
            canvas.height = Math.max(1, Math.ceil(rect.height || 800));
            canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
            var blob = await new Promise(function(resolve) { canvas.toBlob(resolve, 'image/png'); });
            if (blob && navigator.clipboard && window.ClipboardItem) {
              await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
              toast('Image copied', 'success');
              return;
            }
          } catch (e) {
          } finally {
            URL.revokeObjectURL(url);
          }
        }
        try {
          await loadScript('https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js');
          var canvas = await window.html2canvas(document.getElementById('iv-render'), {
            backgroundColor: null,
            scale: Math.min(window.devicePixelRatio || 1, 2),
            useCORS: true
          });
          var fallbackBlob = await new Promise(function(resolve) { canvas.toBlob(resolve, 'image/png'); });
          if (fallbackBlob && navigator.clipboard && window.ClipboardItem) {
            await navigator.clipboard.write([new ClipboardItem({ 'image/png': fallbackBlob })]);
            toast('Image copied', 'success');
            return;
          }
          toast('Clipboard image copy is unavailable in this browser.', 'warn');
        } catch (e) {
          toast('Image copy failed.', 'danger');
        }
      }

      (function installRuntimeContract() {
        var contract = Object.assign({}, OCV_CONTRACT || {});
        contract.version = contract.version || '__BUILD__';
        contract.title = contract.title || 'Open Visual';
        contract.mode = 'static';
        contract.markers = contract.markers || { start: '__START_MARK__', end: '__END_MARK__' };
        contract.capabilities = contract.capabilities || {};
        contract.capabilities.securityLevel = contract.capabilities.securityLevel || 'recovered';
        contract.capabilities.streaming = false;
        contract.capabilities.staticFallback = true;
        contract.capabilities.sameOriginRequiredForStreaming = true;
        contract.capabilities.exports = Array.isArray(contract.capabilities.exports) && contract.capabilities.exports.length
          ? contract.capabilities.exports
          : ['copyImage', 'downloadHTML', 'downloadSVG'];
        window.OpenCustomVisuals = contract;
        window.OpenCustomVisuals.helpers = {
          sendPrompt: sendPrompt,
          openLink: openLink,
          copyText: copyText,
          copyImage: copyImage,
          downloadHTML: downloadHTML,
          downloadSVG: downloadSVG,
          enterFullscreen: enterFullscreen,
          saveState: saveState,
          loadState: loadState
        };
      })();
    </script>
    <div id="iv-render">__SOURCE__</div>
  </div>
  <script>
    window.addEventListener('load', reportHeight);
    window.addEventListener('resize', reportHeight);
    try { new ResizeObserver(reportHeight).observe(document.body); } catch (e) {}
    setToolbarStatus('Recovered visual', 'ready');
    setTimeout(reportHeight, 40);
  </script>
</body>
</html>
"""


def _build_recovery_html(title: str, source: str, payload: dict[str, Any] | None) -> str:
    safe_title = title or "Open Visual"
    contract = _normalize_runtime_contract(safe_title, payload)
    return (
        _RECOVERY_HTML
        .replace("__BUILD__", _OCV_BUILD)
        .replace("__TITLE__", safe_title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        .replace("__SOURCE__", _sanitize_fragment(source))
        .replace("__CONTRACT_JSON__", _safe_json(contract))
        .replace("__THEME_CSS__", _THEME_CSS)
        .replace("__SVG_CLASSES__", _SVG_CLASSES)
        .replace("__START_MARK__", _START_MARK)
        .replace("__END_MARK__", _END_MARK)
    )


class Action:
    class Valves(BaseModel):
        priority: int = Field(default=10, description="Lower values appear earlier in the message toolbar.")

    def __init__(self):
        self.valves = self.Valves()

    async def action(self, body: dict, __event_call__=None, __event_emitter__=None) -> HTMLResponse | dict:
        live_view = await _extract_live_view(body, __event_call__)
        source = (live_view or {}).get("source") or _extract_from_body(body)

        runtime_contract = (
            (live_view or {}).get("contract")
            or _extract_runtime_contract_from_text((live_view or {}).get("srcdoc") or "")
            or _extract_runtime_contract_from_body(body)
        )

        title_fallback = (
            (runtime_contract or {}).get("title")
            or (live_view or {}).get("title")
            or "Open Visual"
        )
        title = _extract_title_from_source(source, str(title_fallback))

        live_html = (live_view or {}).get("htmlDoc")
        if isinstance(live_html, str) and "<html" in live_html.lower():
            return HTMLResponse(
                content=live_html,
                headers={"Content-Disposition": "inline"},
            )

        if not source:
            return {"content": "No Open-Custom Visuals block or live visual iframe was found on this message."}

        return HTMLResponse(
            content=_build_recovery_html(title, source, runtime_contract),
            headers={"Content-Disposition": "inline"},
        )
