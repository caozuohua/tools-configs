---
name: discord-mobile-formatting
description: "Format messages for Discord mobile readability — avoid tables, use lists."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [discord, formatting, mobile, communication]
    related_skills: []
---

# Discord Mobile Formatting

## Overview

Discord's mobile app renders Markdown tables poorly — columns misalign and become unreadable. This skill ensures all responses are formatted for optimal mobile readability.

## Rule

**Never use Markdown tables (pipe-delimited `| ... |` format) in responses.**

This is a hard rule, not a preference. Tables break on Discord mobile regardless of content.

## Formatting Guidelines

### Tables → Lists

Convert any tabular data to bullet lists:

```
❌ Bad (table):
| Tool | Status | Description |
|------|--------|-------------|
| uv   | ✅     | Python env  |
| rg   | ✅     | Code search  |

✅ Good (list):
- ✅ **uv** — Python environment management
- ✅ **rg** — Fast code search
- ❌ **fd** — Not installed
```

### Key formatting rules

- Each item on its own line with a bullet (`-`) or number (`1.`)
- Bold the key/title, then em-dash (`—`) or colon (`:`) before the description
- Use emoji indicators (✅ ❌ ⚠️ 🔧) for status when appropriate
- For key-value pairs: `**key** — value` format
- For comparisons: use separate bullets per item, not side-by-side columns

### Multi-column data

When you would normally use a 3+ column table, use a grouped list:

```
❌ Bad:
| Name | Type | Status | Path |
|------|------|--------|------|
| alpha | blog | done | /a |
| beta | task | pending | /b |

✅ Good:
**Blog items:**
- ✅ **alpha** — done — /a

**Tasks:**
- ⏳ **beta** — pending — /b
```

### When tables are acceptable

Tables are ONLY acceptable when:
- The user explicitly asks for a table format
- The output is going to a file (not a Discord message)
- The content is code that happens to use pipe characters

## Pitfalls

- **Don't use `|` pipe characters** for visual alignment — they render as literal pipes on mobile
- **Don't use code blocks with spaces for alignment** — mobile uses variable-width fonts
- **Don't assume the user is on desktop** — always default to mobile-safe formatting
- **Don't use `---` horizontal rules as visual separators** — they render inconsistently on mobile; use blank lines instead
- **Don't nest deep bullet lists** — more than 3 levels of nesting becomes unreadably indented on narrow screens; use bold headings to break up deep hierarchies

## Media Attachments

- **Images** (`.png`, `.jpg`, `.webp`): sent as photo attachments via `MEDIA:/absolute/path` in the message
- **Audio**: sent as file attachments (same `MEDIA:` syntax)
- **Markdown `![alt](url)` images**: delivered as native Discord attachments, not inline
- For multi-file deliveries, list each `MEDIA:<path>` on its own line

## General Tone

- **Concise, technical, practical.** No filler, no over-explanation unless asked.
- **Match the user's language** — Chinese/English mixed is normal for this user. Mirror their register and language mix in the reply.
- **No Cantonese particles. No traditional Chinese characters.** This is a HARD rule (user explicitly cleared all Cantonese-related memory after I over-mirrored their Cantonese input into stylized "老香港 BBS 网友" voice). Concrete prohibitions:
  - **Banned traditional characters**: 对→對, 时→時, 后→後, 应→應, 长→長, 这→這, 来→來, 发→發, 为→為, 会→會, 简→簡, 体→體, 输→輸, 处→處, 终→終, 级→級, 线→線, 个→個, 国→國, 头→頭, 实→實, 动→動, 问→問, 点→點, 记→記, 学→學, 声→聲, 亲→親, 丽→麗, 龙→龍, 鸟→鳥, 鱼→魚, 鸡→雞, 饭→飯, 读→讀, 钱→錢, 铁→鐵, 门→門, 電→電 (and the simplified form 電 itself is banned, use 电), 页→頁, 边→邊, 颜→顏, 色→色, 麦→麥 etc. If unsure whether a character is simplified or traditional, prefer a different word.
  - **Banned Cantonese particles**: 嗰, 冇, 嘅, 嘅嘢, 睇下, 系, 喺, 边, 嚟, 咩, 乜, 嘢, 啦, 咗. Even "light Cantonese flavor" is too much. Default to standard Mandarin particles (的/了/吗/呢/吧/的).
  - **Reply to Cantonese input in standard simplified Mandarin.** Mirror the user's **topic** and **technical vocabulary**, not their **language style**. Phrases the user uses as terms (e.g. 对端 as a tech word for "the remote end") can be echoed in simplified form, but do not add Cantonese stylistic particles beyond what's strictly needed.
  - **Defense against style-mirroring**: when the user writes in Cantonese, the default `match-user-style` heuristic pushes toward "performative Cantonese" (heavy jyutping characters as if writing HK forum posts). Suppress this. Match the *language register*, not the *language family*. Output should be readable as standard simplified Mandarin by someone who doesn't know Cantonese.
  - **Verification**: before sending, scan the draft for any 嗰/冇/嘅/啦/咗/嚟/咩/邊/喺 or any character that has a different glyph in 繁体 (vs 简体) form. If found, replace.
- **No excessive emoji** — use ✅ ❌ ⚠️ 🔧 sparingly for status flags, never decoratively.
- **Bullet lists over wide tables** for Discord mobile readability (this is the rule above, applied as a default).
- When the user is debugging something, the tone can be more technical/dense; when planning, lean toward structured but readable.
