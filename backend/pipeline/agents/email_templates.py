"""HTML email template builder for the publishing agent.

Generates fully inline-styled, responsive HTML emails for each channel.
All styles are inlined (no external CSS / web fonts) for maximum email
client compatibility.  The outer shell is shared; the inner content block
is channel-specific.
"""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.state import AggregatedScore, CampaignBrief, ContentVariant

# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
_BRAND_DARK = "#1a1a2e"
_BRAND_MID = "#16213e"
_BRAND_ACCENT = "#e94560"
_BRAND_GOLD = "#f5a623"
_BG = "#eef2ff"
_CARD_BG = "#ffffff"
_TEXT_PRIMARY = "#1e293b"
_TEXT_SECONDARY = "#64748b"
_TEXT_MUTED = "#94a3b8"
_BORDER = "#e2e8f0"

# Per-channel accent colours
_CHANNEL_COLOURS: dict[str, dict[str, str]] = {
    "email": {
        "accent": "#2563eb",
        "light": "#eff6ff",
        "label": "Email Campaign",
        "icon": "✉️",
        "badge_bg": "#dbeafe",
        "badge_fg": "#1d4ed8",
    },
    "linkedin": {
        "accent": "#0077b5",
        "light": "#e8f4fb",
        "label": "LinkedIn Post",
        "icon": "💼",
        "badge_bg": "#cce5f3",
        "badge_fg": "#005885",
    },
    "sms": {
        "accent": "#16a34a",
        "light": "#f0fdf4",
        "label": "SMS Message",
        "icon": "📱",
        "badge_bg": "#dcfce7",
        "badge_fg": "#15803d",
    },
    "social_post": {
        "accent": "#7c3aed",
        "light": "#f5f3ff",
        "label": "Social Post",
        "icon": "📸",
        "badge_bg": "#ede9fe",
        "badge_fg": "#6d28d9",
    },
    "display_ad": {
        "accent": "#d97706",
        "light": "#fffbeb",
        "label": "Display Ad",
        "icon": "🖼️",
        "badge_bg": "#fef3c7",
        "badge_fg": "#b45309",
    },
    "push_notification": {
        "accent": "#dc2626",
        "light": "#fef2f2",
        "label": "Push Notification",
        "icon": "🔔",
        "badge_bg": "#fee2e2",
        "badge_fg": "#b91c1c",
    },
}

_DEFAULT_CHANNEL_COLOUR: dict[str, str] = {
    "accent": "#475569",
    "light": "#f8fafc",
    "label": "Content",
    "icon": "📄",
    "badge_bg": "#e2e8f0",
    "badge_fg": "#334155",
}

# Routing-decision badge colours  (fg, bg, label)
_ROUTING_BADGE: dict[str, tuple[str, str, str]] = {
    "auto_approve": ("#166534", "#dcfce7", "✅ AUTO APPROVED"),
    "flag": ("#92400e", "#fef3c7", "⚠️ FLAGGED FOR REVIEW"),
    "auto_reject": ("#991b1b", "#fee2e2", "❌ AUTO REJECTED"),
}
_DEFAULT_ROUTING_BADGE: tuple[str, str, str] = ("#334155", "#e2e8f0", "— UNSCORED")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_campaign_email_html(
    variant: "ContentVariant",
    brief: "CampaignBrief | None",
    score: "AggregatedScore | None",
) -> str:
    """Return a fully inline-styled HTML email string.

    Args:
        variant: The ContentVariant being published.
        brief:   The CampaignBrief from pipeline state (may be None).
        score:   The AggregatedScore for this variant (may be None).

    Returns:
        Complete HTML document as a string.
    """
    channel = (variant.get("channel") or "email").lower()
    palette = _CHANNEL_COLOURS.get(channel, _DEFAULT_CHANNEL_COLOUR)

    content_block = _render_channel_block(variant, channel, palette)
    score_block = _render_score_block(score)
    meta_block = _render_meta_block(variant, brief)

    objective = brief.get("objective", "Campaign") if brief else "Campaign"
    locale = variant.get("locale", "en")

    return _render_outer_shell(
        channel=channel,
        palette=palette,
        objective=objective,
        locale=locale,
        meta_block=meta_block,
        content_block=content_block,
        score_block=score_block,
    )


# ---------------------------------------------------------------------------
# Channel-specific content blocks
# ---------------------------------------------------------------------------


def _render_channel_block(
    variant: "ContentVariant",
    channel: str,
    palette: dict[str, str],
) -> str:
    raw = (
        variant.get("final_content")
        or variant.get("personalized_content")
        or variant.get("generated_content")
        or "(No content generated)"
    )
    content = html.escape(str(raw))

    if channel == "linkedin":
        return _block_linkedin(content, palette)
    if channel == "sms":
        return _block_sms(content, palette)
    if channel == "social_post":
        return _block_social(content, palette)
    if channel == "display_ad":
        return _block_display_ad(content, palette)
    if channel == "push_notification":
        return _block_push(content, palette)
    return _block_email(content, palette)


def _first_line(content: str) -> str:
    """Return the first non-empty line (already HTML-escaped)."""
    for line in content.split("<br>"):
        stripped = line.strip()
        if stripped:
            return stripped
    return content[:80]


def _rest_of_content(lines: str) -> str:
    """Return everything after the first line (already HTML-escaped with <br>)."""
    parts = lines.split("<br>", 1)
    return parts[1].strip() if len(parts) > 1 else ""


def _style_hashtags(content: str, accent: str) -> str:
    """Wrap #hashtag and @mention tokens in a coloured span."""
    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        token = m.group(0)
        return f'<span style="color:{accent};font-weight:600;">{token}</span>'

    return re.sub(r"[#@]\w+", _replace, content)


# ── individual channel renderers ──────────────────────────────────────────


def _block_email(content: str, palette: dict[str, str]) -> str:
    accent = palette["accent"]
    light = palette["light"]
    lines = content.replace("\n", "<br>")
    headline = _first_line(lines)
    body = _rest_of_content(lines) or lines
    return (
        f'<div style="background:{light};border-radius:12px;padding:28px 32px;'
        f'border-left:4px solid {accent};margin-bottom:8px;">'
        f'<div style="font-size:11px;font-weight:700;letter-spacing:1.5px;'
        f'color:{accent};text-transform:uppercase;margin-bottom:14px;">'
        f'✉️ Email Campaign Content</div>'
        f'<div style="font-size:16px;font-weight:700;color:#0f172a;'
        f'margin-bottom:14px;line-height:1.4;">{headline}</div>'
        f'<div style="font-size:14px;color:{_TEXT_PRIMARY};line-height:1.7;'
        f'margin-bottom:20px;">{body}</div>'
        f'<a href="#" style="display:inline-block;background:{accent};color:#fff;'
        f'padding:12px 28px;border-radius:8px;font-size:14px;font-weight:600;'
        f'text-decoration:none;letter-spacing:0.3px;">Read More →</a>'
        f"</div>"
    )


def _block_linkedin(content: str, palette: dict[str, str]) -> str:
    accent = palette["accent"]
    light = palette["light"]
    char_count = len(content)
    lines = content.replace("\n", "<br>")
    return (
        f'<div style="background:{light};border-radius:12px;padding:28px 32px;'
        f'border:1px solid #b3d4e8;margin-bottom:8px;">'
        # Author row
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        f' style="margin-bottom:16px;"><tr>'
        f'<td style="width:48px;vertical-align:top;">'
        f'<div style="width:48px;height:48px;border-radius:50%;background:{accent};'
        f'text-align:center;line-height:48px;font-size:20px;color:#fff;font-weight:700;">O</div>'
        f"</td>"
        f'<td style="padding-left:12px;vertical-align:top;">'
        f'<div style="font-size:14px;font-weight:700;color:#0f172a;">OmniBrand Studio</div>'
        f'<div style="font-size:12px;color:{_TEXT_SECONDARY};">AI-Generated Campaign Content</div>'
        f'<div style="font-size:11px;color:{_TEXT_MUTED};">Just now · 🌐</div>'
        f"</td>"
        f'<td align="right" style="vertical-align:top;">'
        f'<span style="background:{accent};color:#fff;font-size:11px;font-weight:700;'
        f'padding:4px 10px;border-radius:20px;">IN</span>'
        f"</td></tr></table>"
        # Content
        f'<div style="font-size:14px;color:{_TEXT_PRIMARY};line-height:1.7;'
        f'margin-bottom:16px;border-top:1px solid #d4e8f5;padding-top:14px;">{lines}</div>'
        # Footer
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        f' style="border-top:1px solid {_BORDER};padding-top:12px;"><tr>'
        f'<td style="font-size:12px;color:{_TEXT_SECONDARY};">'
        f"👍 Like &nbsp;💬 Comment &nbsp;🔁 Repost</td>"
        f'<td align="right" style="font-size:11px;color:{_TEXT_MUTED};">{char_count} chars</td>'
        f"</tr></table>"
        f"</div>"
    )


def _block_sms(content: str, palette: dict[str, str]) -> str:
    accent = palette["accent"]
    light = palette["light"]
    display = content[:160] + ("…" if len(content) > 160 else "")
    char_count = min(len(content), 160)
    return (
        f'<div style="background:#f8fafc;border-radius:12px;padding:28px 32px;'
        f'margin-bottom:8px;">'
        f'<div style="font-size:11px;font-weight:700;letter-spacing:1.5px;'
        f'color:{accent};text-transform:uppercase;margin-bottom:16px;">📱 SMS Message Preview</div>'
        f'<div style="max-width:320px;margin:0 auto;">'
        # Bubble
        f'<div style="background:#e5e5ea;border-radius:18px 18px 4px 18px;'
        f'padding:14px 18px;font-size:14px;color:#1c1c1e;line-height:1.5;'
        f'font-family:monospace;">{display}</div>'
        f'<div style="text-align:right;margin-top:6px;font-size:11px;color:{_TEXT_MUTED};">'
        f"Delivered · {char_count}/160 chars</div>"
        # Warning banner
        f'<div style="margin-top:12px;padding:10px 14px;background:{light};'
        f'border-radius:8px;border:1px dashed {accent};">'
        f'<span style="font-size:11px;color:{accent};font-weight:600;">'
        f"⚠️ SMS Demo: Full content shown above. Real delivery truncates to 160 chars."
        f"</span></div>"
        f"</div>"
        f"</div>"
    )


def _block_social(content: str, palette: dict[str, str]) -> str:
    accent = palette["accent"]
    light = palette["light"]
    lines = content.replace("\n", "<br>")
    styled = _style_hashtags(lines, accent)
    return (
        f'<div style="border-radius:12px;overflow:hidden;margin-bottom:8px;'
        f'border:1px solid {_BORDER};">'
        # Gradient top bar
        f'<div style="height:6px;background:linear-gradient('
        f'90deg,#f09433,#e6683c,#dc2743,#cc2366,#bc1888);"></div>'
        f'<div style="background:{light};padding:24px 28px;">'
        # Author row
        f'<table cellpadding="0" cellspacing="0" border="0"'
        f' style="width:100%;margin-bottom:14px;"><tr>'
        f'<td style="width:40px;vertical-align:top;">'
        f'<div style="width:40px;height:40px;border-radius:50%;'
        f'background:linear-gradient(135deg,#f09433,#bc1888);'
        f'text-align:center;line-height:40px;font-size:16px;color:#fff;font-weight:700;">O</div>'
        f"</td>"
        f'<td style="padding-left:10px;vertical-align:top;">'
        f'<div style="font-size:13px;font-weight:700;color:#0f172a;">omnibrand_studio</div>'
        f'<div style="font-size:11px;color:{_TEXT_SECONDARY};">Sponsored</div>'
        f"</td>"
        f'<td align="right" style="font-size:18px;color:{_TEXT_SECONDARY};">···</td>'
        f"</tr></table>"
        # Image placeholder
        f'<div style="background:linear-gradient(135deg,{accent}33,{accent}55);'
        f'border-radius:8px;height:140px;text-align:center;line-height:140px;'
        f'margin-bottom:14px;border:1px solid {accent}44;">'
        f'<span style="font-size:36px;">🖼️</span></div>'
        # Content
        f'<div style="font-size:14px;color:{_TEXT_PRIMARY};line-height:1.7;'
        f'margin-bottom:12px;">{styled}</div>'
        # Engagement
        f'<div style="font-size:13px;color:{_TEXT_SECONDARY};'
        f'padding-top:10px;border-top:1px solid {_BORDER};">'
        f"❤️ 248 &nbsp; 💬 31 &nbsp; 📤 Share</div>"
        f"</div>"
        f"</div>"
    )


def _block_display_ad(content: str, palette: dict[str, str]) -> str:
    accent = palette["accent"]
    light = palette["light"]
    headline = _first_line(content)[:40]
    parts = content.split("<br>", 1)
    body = parts[1].strip() if len(parts) > 1 else content[:120]
    return (
        f'<div style="border-radius:12px;overflow:hidden;margin-bottom:8px;'
        f'border:2px solid {accent};">'
        # Gradient header with headline
        f'<div style="background:linear-gradient(135deg,{_BRAND_DARK},{accent});'
        f'padding:24px 28px;position:relative;">'
        f'<div style="position:absolute;top:10px;right:12px;background:{_BRAND_DARK};'
        f'color:#fff;font-size:10px;font-weight:700;padding:3px 8px;'
        f'border-radius:4px;letter-spacing:1px;">AD</div>'
        f'<div style="font-size:22px;font-weight:900;color:#fff;'
        f'text-shadow:0 2px 4px rgba(0,0,0,0.3);line-height:1.3;">{headline}</div>'
        f"</div>"
        # Body
        f'<div style="background:{light};padding:20px 24px;">'
        f'<div style="font-size:13px;color:{_TEXT_SECONDARY};line-height:1.6;'
        f'margin-bottom:16px;">{body}</div>'
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
        f'<td><a href="#" style="display:inline-block;background:{accent};color:#fff;'
        f'padding:10px 24px;border-radius:6px;font-size:13px;font-weight:700;'
        f'text-decoration:none;letter-spacing:0.5px;">Learn More</a></td>'
        f'<td align="right" style="font-size:11px;color:{_TEXT_MUTED};">omnibrandstudio.ai</td>'
        f"</tr></table>"
        f"</div>"
        f"</div>"
    )


def _block_push(content: str, palette: dict[str, str]) -> str:
    accent = palette["accent"]
    light = palette["light"]
    title = _first_line(content)[:60]
    parts = content.split("<br>", 1)
    body_text = parts[1].strip()[:100] if len(parts) > 1 else content[:100]
    return (
        f'<div style="background:{light};border-radius:12px;padding:24px 28px;'
        f'margin-bottom:8px;border:1px solid {_BORDER};">'
        f'<div style="font-size:11px;font-weight:700;letter-spacing:1.5px;'
        f'color:{accent};text-transform:uppercase;margin-bottom:16px;">'
        f"🔔 Push Notification Preview</div>"
        # Phone notification card
        f'<div style="background:#fff;border-radius:14px;padding:16px 18px;'
        f'box-shadow:0 4px 16px rgba(0,0,0,0.10);border:1px solid {_BORDER};'
        f'max-width:360px;margin:0 auto;">'
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
        # App icon
        f'<td style="width:44px;vertical-align:top;">'
        f'<div style="width:40px;height:40px;border-radius:10px;background:{accent};'
        f'text-align:center;line-height:40px;font-size:18px;">🏷️</div>'
        f"</td>"
        # Text
        f'<td style="padding-left:12px;vertical-align:top;">'
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
        f'<td style="font-size:12px;font-weight:700;color:#0f172a;">OmniBrand</td>'
        f'<td align="right" style="font-size:11px;color:{_TEXT_MUTED};">now</td>'
        f"</tr></table>"
        f'<div style="font-size:13px;font-weight:600;color:#0f172a;'
        f'margin-top:2px;line-height:1.3;">{title}</div>'
        f'<div style="font-size:12px;color:{_TEXT_SECONDARY};margin-top:4px;'
        f'line-height:1.4;">{body_text}</div>'
        f"</td></tr></table>"
        f"</div>"
        f'<div style="text-align:center;margin-top:12px;font-size:11px;'
        f'color:{_TEXT_MUTED};">iOS / Android push simulation</div>'
        f"</div>"
    )


# ---------------------------------------------------------------------------
# Score block
# ---------------------------------------------------------------------------


def _render_score_block(score: "AggregatedScore | None") -> str:
    if score is None:
        return (
            f'<div style="background:#f8fafc;border-radius:12px;padding:20px 28px;'
            f'border:1px dashed #cbd5e1;margin-bottom:8px;text-align:center;">'
            f'<span style="font-size:13px;color:#94a3b8;">'
            f"Brand scores not available for this variant</span></div>"
        )

    composite = float(score.get("weighted_mean") or score.get("composite_score") or 0.0)
    composite_pct = int(composite * 10)  # 0–10 → 0–100%
    routing = str(score.get("routing_decision") or "").lower()
    badge_fg, badge_bg, badge_label = _ROUTING_BADGE.get(routing, _DEFAULT_ROUTING_BADGE)

    # Per-judge bars
    criterion_rows = ""
    judge_scores = score.get("judge_scores") or []
    if judge_scores:
        for i, js in enumerate(judge_scores[:6], 1):
            pct = int(float(js) * 10)
            criterion_rows += _score_bar_row(f"Judge {i}", float(js), pct)
    else:
        criterion_rows = _score_bar_row("Composite Score", composite, composite_pct)

    # Violations
    violations = score.get("critical_violations") or []
    violation_html = ""
    if violations:
        items = "".join(
            f'<li style="margin-bottom:4px;">{html.escape(str(v))}</li>'
            for v in violations[:5]
        )
        violation_html = (
            f'<div style="margin-top:12px;background:#fef2f2;border-radius:8px;'
            f'padding:12px 16px;border-left:3px solid #ef4444;">'
            f'<div style="font-size:11px;font-weight:700;color:#b91c1c;margin-bottom:6px;'
            f'text-transform:uppercase;letter-spacing:1px;">Critical Violations</div>'
            f'<ul style="margin:0;padding-left:16px;font-size:12px;color:#7f1d1d;">'
            f"{items}</ul></div>"
        )

    consensus = str(score.get("consensus_level") or "").replace("_", " ").title() or "—"
    degraded = "Yes" if bool(score.get("degraded_mode")) else "No"

    return (
        f'<div style="background:#f8fafc;border-radius:12px;padding:24px 28px;'
        f'border:1px solid {_BORDER};margin-bottom:8px;">'
        # Title row
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        f' style="margin-bottom:16px;"><tr>'
        f'<td style="font-size:12px;font-weight:700;color:{_TEXT_PRIMARY};'
        f'text-transform:uppercase;letter-spacing:1px;">🏆 Brand Score</td>'
        f'<td align="right">'
        f'<span style="background:{badge_bg};color:{badge_fg};font-size:11px;'
        f'font-weight:700;padding:5px 12px;border-radius:20px;letter-spacing:0.5px;">'
        f"{badge_label}</span></td></tr></table>"
        # Composite gauge
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        f' style="margin-bottom:18px;"><tr>'
        f'<td style="font-size:13px;color:{_TEXT_SECONDARY};font-weight:600;">'
        f"Weighted Mean</td>"
        f'<td align="right" style="font-size:22px;font-weight:900;color:{_BRAND_DARK};">'
        f'{composite:.1f}<span style="font-size:14px;color:{_TEXT_MUTED};">/10</span></td>'
        f"</tr></table>"
        f'<div style="background:#e2e8f0;border-radius:999px;height:10px;'
        f'overflow:hidden;margin-bottom:18px;">'
        f'<div style="background:linear-gradient(90deg,{_BRAND_ACCENT},{_BRAND_GOLD});'
        f'width:{composite_pct}%;height:100%;border-radius:999px;"></div></div>'
        # Per-judge bars
        f"{criterion_rows}"
        f"{violation_html}"
        # Meta chips
        f'<div style="margin-top:14px;padding-top:12px;border-top:1px solid {_BORDER};">'
        f"{_meta_chip('Consensus', consensus)}"
        f"&nbsp;"
        f"{_meta_chip('Degraded Mode', degraded)}"
        f"</div>"
        f"</div>"
    )


def _score_bar_row(label: str, value: float, pct: int) -> str:
    colour = "#22c55e" if value >= 7 else ("#f59e0b" if value >= 4 else "#ef4444")
    return (
        f'<div style="margin-bottom:8px;">'
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        f' style="margin-bottom:3px;"><tr>'
        f'<td style="font-size:12px;color:{_TEXT_SECONDARY};">{html.escape(label)}</td>'
        f'<td align="right" style="font-size:12px;font-weight:600;'
        f'color:{_TEXT_PRIMARY};">{value:.1f}</td></tr></table>'
        f'<div style="background:#e2e8f0;border-radius:999px;height:6px;overflow:hidden;">'
        f'<div style="background:{colour};width:{pct}%;height:100%;'
        f'border-radius:999px;"></div></div>'
        f"</div>"
    )


def _meta_chip(label: str, value: str) -> str:
    return (
        f'<span style="font-size:11px;background:#e2e8f0;color:{_TEXT_SECONDARY};'
        f'padding:4px 10px;border-radius:20px;display:inline-block;margin-bottom:4px;">'
        f"<strong>{html.escape(label)}:</strong> {html.escape(value)}</span>"
    )


# ---------------------------------------------------------------------------
# Meta block (campaign metadata table)
# ---------------------------------------------------------------------------


def _render_meta_block(variant: "ContentVariant", brief: "CampaignBrief | None") -> str:
    channel = str(variant.get("channel") or "—")
    locale = str(variant.get("locale") or "—")
    segment = str(variant.get("segment") or "—")
    task_id = str(variant.get("task_id") or "—")
    objective = str(brief.get("objective") or "—") if brief else "—"
    audience = str(brief.get("target_audience") or "—") if brief else "—"
    model = str(variant.get("generation_model") or "—")
    guide_ver = str(variant.get("brand_guide_version") or "—")

    def _cell(icon: str, label: str, value: str) -> str:
        return (
            f'<td style="padding:10px 14px;border-right:1px solid {_BORDER};'
            f'vertical-align:top;">'
            f'<div style="font-size:10px;color:{_TEXT_MUTED};text-transform:uppercase;'
            f'letter-spacing:0.8px;margin-bottom:3px;">'
            f"{html.escape(icon)} {html.escape(label)}</div>"
            f'<div style="font-size:13px;font-weight:600;color:{_TEXT_PRIMARY};'
            f'white-space:nowrap;overflow:hidden;">'
            f"{html.escape(str(value)[:30])}</div></td>"
        )

    return (
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        f' style="border-collapse:collapse;border:1px solid {_BORDER};'
        f'border-radius:10px;overflow:hidden;margin-bottom:16px;background:{_CARD_BG};">'
        f"<tr>"
        f"{_cell('📋', 'Task ID', task_id)}"
        f"{_cell('📡', 'Channel', channel.upper())}"
        f"{_cell('🌐', 'Locale', locale)}"
        f"{_cell('👥', 'Segment', segment)}"
        f"</tr>"
        f'<tr style="background:#f8fafc;border-top:1px solid {_BORDER};">'
        f"{_cell('🎯', 'Objective', objective[:50])}"
        f"{_cell('🧑', 'Audience', audience[:40])}"
        f"{_cell('🤖', 'Model', model[:20])}"
        f"{_cell('📌', 'Brand Guide', guide_ver)}"
        f"</tr>"
        f"</table>"
    )


# ---------------------------------------------------------------------------
# Outer shell
# ---------------------------------------------------------------------------


def _render_outer_shell(
    *,
    channel: str,
    palette: dict[str, str],
    objective: str,
    locale: str,
    meta_block: str,
    content_block: str,
    score_block: str,
) -> str:
    accent = palette["accent"]
    badge_bg = palette["badge_bg"]
    badge_fg = palette["badge_fg"]
    icon = palette["icon"]
    channel_label = palette["label"]
    obj_escaped = html.escape(str(objective)[:70])
    locale_escaped = html.escape(str(locale))

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width,initial-scale=1.0">\n'
        f"  <title>OmniBrand — {html.escape(channel_label)}</title>\n"
        "</head>\n"
        f'<body style="margin:0;padding:0;background:{_BG};'
        f"font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
        f"'Helvetica Neue',Arial,sans-serif;\">\n"
        # Outer table
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"'
        f' style="background:{_BG};padding:32px 16px;">'
        f"<tr><td align=\"center\">"
        # Inner card
        f'<table cellpadding="0" cellspacing="0" border="0"'
        f' style="max-width:600px;width:100%;border-radius:16px;overflow:hidden;'
        f'box-shadow:0 8px 32px rgba(0,0,0,0.12);">'
        # ── HEADER ──
        f"<tr>"
        f'<td style="background:{_BRAND_DARK};padding:22px 32px;">'
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
        f"<td>"
        f'<div style="font-size:22px;font-weight:900;color:#fff;letter-spacing:-0.5px;">'
        f'Omni<span style="color:{_BRAND_ACCENT};">Brand</span>'
        f'<span style="color:#94a3b8;font-weight:400;font-size:16px;"> Studio</span>'
        f"</div>"
        f'<div style="font-size:12px;color:#64748b;margin-top:3px;">'
        f"Agentic Content Platform</div>"
        f"</td>"
        f'<td align="right">'
        f'<span style="background:{_BRAND_GOLD};color:{_BRAND_DARK};font-size:11px;'
        f'font-weight:800;padding:5px 12px;border-radius:20px;letter-spacing:1px;">'
        f"DEMO MODE</span>"
        f"</td></tr></table>"
        f"</td></tr>"
        # ── CHANNEL BADGE STRIP ──
        f"<tr>"
        f'<td style="background:{_BRAND_MID};padding:12px 32px;">'
        f'<table cellpadding="0" cellspacing="0" border="0" width="100%"><tr>'
        f"<td>"
        f'<span style="background:{badge_bg};color:{badge_fg};font-size:12px;'
        f'font-weight:700;padding:5px 14px;border-radius:20px;letter-spacing:0.5px;">'
        f"{icon} {html.escape(channel_label)}</span>"
        f"</td>"
        f'<td align="right" style="font-size:12px;color:#64748b;">'
        f"🌐 {locale_escaped}</td>"
        f"</tr></table>"
        f"</td></tr>"
        # ── OBJECTIVE BANNER ──
        f"<tr>"
        f'<td style="background:#f1f5f9;padding:14px 32px;'
        f'border-bottom:1px solid {_BORDER};">'
        f'<div style="font-size:11px;color:{_TEXT_MUTED};text-transform:uppercase;'
        f'letter-spacing:1px;margin-bottom:3px;">Campaign Objective</div>'
        f'<div style="font-size:15px;font-weight:700;color:{_TEXT_PRIMARY};">'
        f"{obj_escaped}</div>"
        f"</td></tr>"
        # ── BODY ──
        f"<tr>"
        f'<td style="background:{_CARD_BG};padding:28px 32px;">'
        # Metadata table
        f"{meta_block}"
        # Channel content block
        f"{content_block}"
        # Score block
        f"{score_block}"
        f"</td></tr>"
        # ── FOOTER ──
        f"<tr>"
        f'<td style="background:{_BRAND_DARK};padding:18px 32px;text-align:center;">'
        f'<div style="font-size:12px;color:#475569;">'
        f'Generated by <span style="color:{_BRAND_ACCENT};font-weight:700;">'
        f"OmniBrand Studio</span> · AI-assisted content</div>"
        f'<div style="font-size:11px;color:#334155;margin-top:4px;">'
        f"This is a demo email. Content is not for production distribution.</div>"
        f"</td></tr>"
        f"</table>"
        f"</td></tr></table>"
        f"</body></html>"
    )
