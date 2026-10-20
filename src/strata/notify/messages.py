"""Human-friendly Telegram messages (Russian, plain language, HTML)."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from html import escape

from strata.paper.trader import CycleReport, Reconciliation

LINE = "━━━━━━━━━━━━━━━━━━"
DISCLAIMER = "<i>Виртуальный портфель: реальные деньги не используются.</i>"


def _usd(value: Decimal | float) -> str:
    v = float(value)
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.2f} $".replace(",", " ")


def _pct(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.2f}%"


def _coin(symbol: str) -> str:
    return escape(symbol.removesuffix("USDT"))


def _weights(items: Iterable[tuple[str, float]]) -> str:
    return "\n".join(f"  • <code>{_coin(s):<8}</code> {abs(w) * 100:5.1f}%" for s, w in items)


def rebalance_message(report: CycleReport, strategy: str) -> str:
    longs = sorted(((s, w) for s, w in report.target.items() if w > 0), key=lambda x: -x[1])
    shorts = sorted(((s, w) for s, w in report.target.items() if w < 0), key=lambda x: x[1])
    turnover = sum(abs(f.quantity * f.price) for f in report.fills)
    parts = [
        f"🔄 <b>Новый портфель</b> · {escape(strategy)}",
        LINE,
        f"📅 Сигнал по закрытию {report.signal_date:%d.%m.%Y}",
        "",
        f"🟢 <b>Лонг</b> (ставка на рост), {len(longs)}:",
        _weights(longs) or "  —",
        "",
        f"🔴 <b>Шорт</b> (ставка на падение), {len(shorts)}:",
        _weights(shorts) or "  —",
        LINE,
        f"💱 Оборот: <b>{_usd(turnover).lstrip('+')}</b>, сделок: {len(report.fills)}",
        f"💸 Комиссии и проскальзывание: <b>{_usd(-report.costs)}</b>",
        f"💼 Капитал: <b>{_usd(report.equity).lstrip('+')}</b>",
    ]
    if report.dropped:
        parts.append(
            "ℹ️ Пропущены (меньше минимального ордера биржи): "
            + ", ".join(_coin(s) for s in report.dropped)
        )
    parts += [*(f"⚠️ {escape(w)}" for w in report.warnings), "", DISCLAIMER]
    return "\n".join(parts)


def daily_message(report: CycleReport, initial: Decimal) -> str:
    day_pnl = report.equity - report.previous_equity
    day_ret = float(day_pnl / report.previous_equity) if report.previous_equity else 0.0
    total_ret = float(report.equity / initial - 1) if initial else 0.0
    emoji = "📈" if day_pnl >= 0 else "📉"
    parts = [
        f"📊 <b>Итоги дня</b> · {report.processed[-1]:%d.%m.%Y}" if report.processed else "📊",
        LINE,
        f"{emoji} За день: <b>{_usd(day_pnl)}</b> ({_pct(day_ret)})",
        f"💰 Фандинг (платежи между лонгами и шортами): {_usd(report.funding)}",
        f"💼 Капитал: <b>{_usd(report.equity).lstrip('+')}</b> · с начала {_pct(total_ret)}",
    ]
    parts += [*(f"⚠️ {escape(w)}" for w in report.warnings), "", DISCLAIMER]
    return "\n".join(parts)


def reconciliation_message(rec: Reconciliation, tolerance: float) -> str:
    ok = rec.within(tolerance)
    return "\n".join(
        [
            f"{'✅' if ok else '⚠️'} <b>Сверка с бэктестом</b> за {rec.days} дн.",
            LINE,
            f"Виртуальный портфель: {_pct(rec.paper_return)}",
            f"Бэктест тех же дней: {_pct(rec.backtest_return)}",
            f"Расхождение: <b>{rec.deviation * 100:.1f}%</b> (допуск {tolerance * 100:.0f}%)",
            "Это проверка, что живая симуляция повторяет расчёты на истории.",
        ]
    )


def warning_message(title: str, details: str) -> str:
    return f"⚠️ <b>{escape(title)}</b>\n{LINE}\n{escape(details)}"
