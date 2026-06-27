---
name: markdown-to-html-email
title: Markdown to HTML Email Converter
description: Robust Markdown-to-HTML conversion for email clients, with proper list/heading/paragraph handling
---

# Markdown to HTML Email Converter

## Trigger
- Converting LLM-generated Markdown content to HTML emails
- Building newsletter/digest HTML from structured Markdown
- Fixing broken list rendering in email HTML

## Key Lessons Learned

### 1. Never Delete Newlines
The #1 bug: `ai_html = ai_html.replace('\n', '')` collapses everything. Email HTML needs proper block-level structure.

### 2. Parse Line-by-Line, Not by Paragraph
Splitting on `\n\n` (blank lines) fails because LLM output often has:
```
**板块总结：**
*   **Item 1:** ...
*   **Item 2:** ...
```
No blank line between the label and the list items. Use **line-by-line parsing with a while loop** instead.

### 3. Recognize All List Types
LLMs output multiple list formats:
- `* item` (asterisk)
- `- item` (dash)
- `1. item` (numbered)

Regex: `^(\d+\.\s+|[-*]\s+)`

### 4. Paragraph Collection Logic
For non-list, non-heading lines, collect consecutive non-empty lines into one paragraph. Stop when hitting:
- Empty line
- Heading (`#` prefix)
- List item (`-`, `*`, or `digit.` prefix)

```python
while i < len(lines) and lines[i].strip() and not re.match(r'^(#+\s|[-*]\s+|\d+\.\s+)', lines[i].strip()):
    para_lines.append(lines[i].strip())
    i += 1
```

### 5. Google AI Studio vs VertexAI Proxy
- **Google AI Studio direct** (`https://generativelanguage.googleapis.com/v1beta`): Does NOT support `extra_body={"google": {"thinking_config": ...}}` — returns 400
- **VertexAI proxy**: Supports `extra_body` with thinking config
- Fix: Only send `extra_body` when NOT connecting to `generativelanguage.googleapis.com`

### 6. Gemini Thinking Models Return Empty
Gemini 2.0 Flash / 3.5 Flash with thinking enabled consume output tokens for thinking, often resulting in empty `content` with `finish_reason:length`. Must disable thinking:
```python
extra_body={"google": {"thinking_config": {"include_thoughts": False, "thinking_budget": 0}}}
```

### 7. GitHub API Workflow File Update Pitfalls
- `gh api` URL-encodes `/` to `%2F` in paths like `.github/workflows/file.yml` → 404
- `PUT` to workflow files requires `workflow` scope (not just `repo`)
- Token with `read:org, repo` scope gets 404 on workflow file updates
- Fix: Add `workflow` scope to the OAuth token

### 8. GitHub Actions Secrets
- Secrets are masked in logs as `***`
- `GOOGLE_API_KEY` must be set as a repository secret
- Free tier quota is per-model — `gemini-2.0-flash` and `gemini-3.1-flash-lite` have separate quotas

## Code Template

```python
def markdown_to_email_html(text: str) -> str:
    """Convert LLM Markdown output to well-formatted HTML for email."""
    import re

    lines = text.strip().split('\n')
    html_parts = []
    i = 0

    def _inline(t):
        t = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)
        t = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" style="color:#1a73e8;text-decoration:none">\1</a>', t)
        return t

    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1; continue

        # Heading
        if re.match(r'^#+\s+(.+)$', stripped):
            html_parts.append(f'<h3>{_inline(re.match(r'^#+\s+(.+)$', stripped).group(1))}</h3>')
            i += 1; continue

        # List (*, -, or numbered)
        if re.match(r'^(\d+\.\s+|[-*]\s+)', stripped):
            li = ''
            while i < len(lines) and re.match(r'^(\d+\.\s+|[-*]\s+)', lines[i].strip()):
                item = re.sub(r'^(\d+\.\s+|[-*]\s+)', '', lines[i].strip())
                li += f'<li style="margin:5px 0 5px 20px;line-height:1.7">{_inline(item)}</li>'
                i += 1
            html_parts.append(f'<ul style="margin:6px 0;padding:0">{li}</ul>')
            continue

        # Paragraph (collect consecutive non-empty, non-list, non-heading lines)
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r'^(#+\s|[-*]\s+|\d+\.\s+)', lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        if para:
            html_parts.append(f'<p style="margin:8px 0;line-height:1.8">{_inline(" ".join(para))}</p>')

    return '\n'.join(html_parts)
```

## Pitfalls Section

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| `replace('\n', '')` | All content on one line | Use line-by-line parser |
| Paragraph split on `\n\n` | Lists not recognized when no blank line before | Line-by-line with while loop |
| Missing `workflow` scope on token | 404 on workflow file update | Add `workflow` scope |
| `extra_body` on Google AI Studio | 400 "Unknown name: google" | Only for VertexAI proxy |
| Thinking mode enabled | Empty content, `finish_reason=length` | `thinking_budget: 0` |
| Only matching `-` and `*` lists | `1. item` merged into paragraph | Include `\d+\.\s+` in regex |
