"""
=============================================================================
SMC-Liquidity FVG Bot v1.0 - Chart Visualizer (Matplotlib)
=============================================================================
Plots swing highs/lows, liquidity sweeps, FVG zones, and entry/exit points
on candlestick charts for visual debugging and strategy verification.
=============================================================================
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
import matplotlib
matplotlib.use('Agg')  # Headless backend for thread-safe image rendering
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import pandas as pd

import config


def plot_smc_setup(
    df_window: pd.DataFrame,
    symbol: str,
    direction: str,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    fvg_top: float,
    fvg_bottom: float,
    swing_high: float,
    swing_low: float,
    setup_name: str = "smc_trade",
    save_path: Optional[Path] = None
) -> str:
    """
    Renders an SMC trade setup chart with candlesticks, FVG boxes, and SL/TP markers.
    """
    os.makedirs(config.CHARTS_DIR, exist_ok=True)
    if save_path is None:
        timestamp_str = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        save_path = config.CHARTS_DIR / f"{symbol}_{direction}_{timestamp_str}.png"

    fig, ax = plt.subplots(figsize=(14, 8), dpi=120)
    fig.patch.set_facecolor('#12161f')
    ax.set_facecolor('#181d27')

    # Draw Candlesticks
    candle_width = 0.6
    x_indices = range(len(df_window))

    for i, (_, row) in enumerate(df_window.iterrows()):
        o, h, l, c = row['open'], row['high'], row['low'], row['close']
        color = '#089981' if c >= o else '#f23645'  # TradingView green / red
        
        # Wick
        ax.plot([i, i], [l, h], color=color, linewidth=1.2, zorder=2)
        # Body
        body_bottom = min(o, c)
        body_height = max(abs(c - o), 0.001)
        rect = patches.Rectangle(
            (i - candle_width / 2, body_bottom),
            candle_width,
            body_height,
            linewidth=0.5,
            edgecolor=color,
            facecolor=color,
            zorder=3
        )
        ax.add_patch(rect)

    # 1. Plot Swing Levels
    ax.axhline(swing_high, color='#f59e0b', linestyle='--', linewidth=1.2, label=f'Swing High ({swing_high:.2f})', zorder=4)
    ax.axhline(swing_low, color='#38bdf8', linestyle='--', linewidth=1.2, label=f'Swing Low ({swing_low:.2f})', zorder=4)

    # 2. Plot FVG Zone (Shaded Rectangle)
    fvg_color = '#10b981' if direction == "BUY" else '#ef4444'
    fvg_box = patches.Rectangle(
        (0, fvg_bottom),
        len(df_window) - 1,
        fvg_top - fvg_bottom,
        facecolor=fvg_color,
        alpha=0.25,
        edgecolor=fvg_color,
        linestyle=':',
        linewidth=1.5,
        label=f'FVG Zone [{fvg_bottom:.2f} - {fvg_top:.2f}]',
        zorder=1
    )
    ax.add_patch(fvg_box)

    # 3. Entry, Stop Loss, and Take Profit
    entry_idx = len(df_window) - 1
    marker = '^' if direction == "BUY" else 'v'
    m_color = '#22c55e' if direction == "BUY" else '#ef4444'

    ax.scatter([entry_idx], [entry_price], color=m_color, s=160, marker=marker, label=f'Entry {direction} @ {entry_price:.2f}', zorder=5)
    ax.axhline(sl_price, color='#ef4444', linestyle='-', linewidth=1.5, label=f'Stop Loss @ {sl_price:.2f}', zorder=4)
    ax.axhline(tp_price, color='#22c55e', linestyle='-', linewidth=1.5, label=f'Take Profit @ {tp_price:.2f}', zorder=4)

    # Labels and Grid
    ax.set_title(
        f"Smart Money Concepts (SMC) Setup: {symbol} (5M) | Direction: {direction}",
        color='#f8fafc',
        fontsize=14,
        fontweight='bold',
        pad=15
    )
    ax.set_ylabel("Price", color='#94a3b8', fontsize=11)
    ax.tick_params(colors='#94a3b8')
    ax.grid(True, color='#262d3d', linestyle=':', alpha=0.6)

    # Format x-axis with time labels
    step = max(1, len(df_window) // 8)
    time_labels = [
        df_window.index[i].strftime('%H:%M') if hasattr(df_window.index[i], 'strftime') else str(i)
        for i in range(0, len(df_window), step)
    ]
    ax.set_xticks(range(0, len(df_window), step))
    ax.set_xticklabels(time_labels, rotation=30, ha='right', color='#94a3b8')

    # Legend
    legend = ax.legend(loc='upper left', facecolor='#1e293b', edgecolor='#334155', labelcolor='#e2e8f0', fontsize=9)
    legend.set_zorder(10)

    plt.tight_layout()
    plt.savefig(save_path, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)

    return str(save_path)
