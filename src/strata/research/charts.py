"""Dependency-free SVG line charts for research reports (equity curves)."""

from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd

PALETTE = ("#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6")
WIDTH, HEIGHT = 860, 380
MARGIN = {"left": 64, "right": 16, "top": 40, "bottom": 56}


def equity_curves(returns: pd.DataFrame) -> pd.DataFrame:
    """Growth of 1 unit per column; NaN returns count as flat days."""
    curves: pd.DataFrame = (1.0 + returns.fillna(0.0)).cumprod()
    return curves


def equity_svg(returns: pd.DataFrame, title: str, *, log_scale: bool = True) -> str:
    curves = equity_curves(returns)
    values = curves.to_numpy(dtype=float)
    if log_scale:
        values = np.log(np.clip(values, 1e-6, None))
    lo, hi = float(np.nanmin(values)), float(np.nanmax(values))
    pad = (hi - lo) * 0.05 or 0.05
    lo, hi = lo - pad, hi + pad
    plot_w = WIDTH - MARGIN["left"] - MARGIN["right"]
    plot_h = HEIGHT - MARGIN["top"] - MARGIN["bottom"]
    n = len(curves)

    def x(i: int) -> float:
        return MARGIN["left"] + plot_w * i / max(n - 1, 1)

    def y(v: float) -> float:
        return MARGIN["top"] + plot_h * (1 - (v - lo) / (hi - lo))

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        'font-family="system-ui, sans-serif" font-size="12">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>',
        f'<text x="{MARGIN["left"]}" y="24" font-size="15" font-weight="600">'
        f"{escape(title)}</text>",
    ]
    # Horizontal grid with growth-multiple labels.
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        label = np.exp(v) if log_scale else v
        parts.append(
            f'<line x1="{MARGIN["left"]}" x2="{WIDTH - MARGIN["right"]}" y1="{y(v):.1f}" '
            f'y2="{y(v):.1f}" stroke="#e5e7eb"/>'
            f'<text x="{MARGIN["left"] - 8}" y="{y(v) + 4:.1f}" text-anchor="end" '
            f'fill="#6b7280">{label:.2f}x</text>'
        )
    dates = pd.DatetimeIndex(curves.index)
    for k in range(6):
        i = round((n - 1) * k / 5)
        parts.append(
            f'<text x="{x(i):.1f}" y="{HEIGHT - MARGIN["bottom"] + 18}" text-anchor="middle" '
            f'fill="#6b7280">{dates[i]:%Y-%m}</text>'
        )
    for j, column in enumerate(curves.columns):
        color = PALETTE[j % len(PALETTE)]
        points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values[:, j]))
        parts.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="1.8" points="{points}"/>'
        )
        lx = MARGIN["left"] + 170 * j
        ly = HEIGHT - 14
        parts.append(
            f'<rect x="{lx}" y="{ly - 9}" width="14" height="3" fill="{color}"/>'
            f'<text x="{lx + 20}" y="{ly - 4}">{escape(str(column))} '
            f"({curves[column].iloc[-1]:.2f}x)</text>"
        )
    parts.append("</svg>")
    return "\n".join(parts)
