"""Renders beautiful dark-themed climate history charts as PNG images for Telegram & Web."""
import io
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


def generate_climate_chart(points: List[Dict[str, Any]], stats: Dict[str, Any],
                           floor_title: str = "Підвал", hours: float = 24.0) -> Optional[bytes]:
    """Render a dual-axis line chart (Temperature & Humidity) using matplotlib."""
    if not points:
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime

        # Extract timestamps and values
        dts = []
        temps = []
        hums = []

        for p in points:
            ts = p.get("timestamp")
            t_val = p.get("temperature")
            h_val = p.get("humidity")
            if ts is not None and (t_val is not None or h_val is not None):
                dts.append(datetime.fromtimestamp(ts))
                temps.append(t_val)
                hums.append(h_val)

        if not dts:
            return None

        # Dark theme styling matching dashboard UI
        bg_color = "#0b1329"
        plot_bg = "#0f172a"
        grid_color = "#1e293b"
        text_color = "#94a3b8"
        title_color = "#f1f5f9"
        temp_color = "#38bdf8"
        hum_color = "#22c55e"

        plt.rcParams["figure.facecolor"] = bg_color
        plt.rcParams["axes.facecolor"] = plot_bg

        fig, ax_temp = plt.subplots(figsize=(8.5, 4.8), dpi=140)

        # Plot Temperature
        valid_temps = [(dt, t) for dt, t in zip(dts, temps) if t is not None]
        if valid_temps:
            x_t, y_t = zip(*valid_temps)
            ax_temp.plot(x_t, y_t, color=temp_color, linewidth=2.4, label="Температура (°C)",
                         marker="o" if len(x_t) <= 25 else None, markersize=4, zorder=4)
            ax_temp.fill_between(x_t, y_t, min(y_t) - 1.0, color=temp_color, alpha=0.12, zorder=2)

        ax_temp.set_ylabel("Температура (°C)", color=temp_color, fontsize=11, fontweight="bold", labelpad=8)
        ax_temp.tick_params(axis="y", labelcolor=temp_color, labelsize=10)
        ax_temp.tick_params(axis="x", labelcolor=text_color, labelsize=9)
        ax_temp.grid(True, color=grid_color, linestyle="--", linewidth=0.8, alpha=0.7)

        # Plot Humidity on secondary Y-axis
        ax_hum = ax_temp.twinx()
        valid_hums = [(dt, h) for dt, h in zip(dts, hums) if h is not None]
        if valid_hums:
            x_h, y_h = zip(*valid_hums)
            ax_hum.plot(x_h, y_h, color=hum_color, linewidth=2.0, linestyle="--", label="Вологість (%)",
                        marker="s" if len(x_h) <= 25 else None, markersize=4, zorder=3)

        ax_hum.set_ylabel("Вологість (%)", color=hum_color, fontsize=11, fontweight="bold", labelpad=8)
        ax_hum.tick_params(axis="y", labelcolor=hum_color, labelsize=10)
        ax_hum.set_ylim(bottom=max(0, min(hums) - 10) if hums and min(hums) is not None else 0,
                        top=min(100, max(hums) + 10) if hums and max(hums) is not None else 100)

        # Format X Axis Dates
        if hours > 24:
            ax_temp.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m %H:%M"))
        else:
            ax_temp.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        fig.autofmt_xdate(rotation=25, ha="right")

        # Titles and stats banner
        cur_t = stats.get("current_temp", "--")
        min_t = stats.get("min_temp", "--")
        max_t = stats.get("max_temp", "--")
        cur_h = stats.get("current_hum", "--")

        fig.suptitle(f"Smart Garage • Динаміка клімату: {floor_title}", color=title_color, fontsize=13, fontweight="bold", y=0.98)
        ax_temp.set_title(f"Період: {int(hours)}г | Зараз: {cur_t}°C, {cur_h}% | Мін: {min_t}°C | Макс: {max_t}°C",
                          color=text_color, fontsize=9.5, pad=10)

        # Spines styling
        for ax in (ax_temp, ax_hum):
            for spine in ax.spines.values():
                spine.set_color(grid_color)

        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", facecolor=bg_color)
        plt.close(fig)
        buf.seek(0)
        return buf.getvalue()

    except Exception as e:
        logger.error(f"Error generating climate chart image: {e}")
        return None
