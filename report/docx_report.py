"""Генерация отчёта в формате Word (.docx), включая графики K_п.р(t)."""
from __future__ import annotations

import io
import math
import os
import tempfile
from datetime import datetime

from docx import Document
from docx.shared import Inches

from methods.gost_58669 import (
    ANALYTIC_KEYS, GRAPHIC_KEYS, K_R_PRED, ST_GRAPHIC_REQUIRED, ST_NO_SAT, ST_OK,
    ST_STEADY, build_kpr_curve,
)

# matplotlib: неинтерактивный бэкенд и шрифт с поддержкой кириллицы.
# Если пакет отсутствует — отчёт собирается без графиков.
try:
    os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="mpl_"))
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["font.family"] = "DejaVu Sans"
    _HAS_MPL = True
except Exception:
    _HAS_MPL = False

METHOD_TITLES = {
    "analytic": "аналитический метод (раздел 5.1)",
    "graphic": "графический метод по паспортным данным (раздел 5.2)",
    "both": "аналитический и графический методы (разделы 5.1 и 5.2)",
}

SCENARIO_TITLES = {
    "without_residual": "без остаточной намагниченности (K_r = 0)",
    "with_residual": f"с предельной остаточной намагниченностью (K_r = {K_R_PRED})",
    "graphic_without_residual": "без остаточной намагниченности (K_r = 0)",
    "graphic_with_residual": f"с предельной остаточной намагниченностью (K_r = {K_R_PRED})",
}


def fmt_t(res) -> str:
    if res is None:
        return "—"
    if res.status == ST_OK and res.t_nas is not None:
        return f"{res.t_nas * 1000:.2f} мс"
    if res.status == ST_NO_SAT:
        return "насыщение отсутствует"
    if res.status == ST_STEADY:
        return "насыщение в установившемся режиме (A ≤ 1)"
    if res.status == ST_GRAPHIC_REQUIRED:
        return "аналитический метод неприменим (усл. 8) — см. графический метод"
    return "—"


def _add_table(doc, headers, rows):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Light Grid Accent 1"
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = str(h)
    for row in rows:
        cells = table.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v)
    return table


def _keys_for(method: str):
    if method == "graphic":
        return GRAPHIC_KEYS
    if method == "both":
        return ANALYTIC_KEYS + GRAPHIC_KEYS
    return ANALYTIC_KEYS


def _make_chart_png(kz, ct_m, gres, eff) -> io.BytesIO:
    """Рендер графика K_п.р(t) в PNG для вставки в Word."""
    if not _HAS_MPL:
        raise RuntimeError("matplotlib не установлен")
    import matplotlib.pyplot as plt

    if gres.status == ST_OK and gres.t_nas is not None:
        t_nas_ms = gres.t_nas * 1000.0
        t_end = min(max(t_nas_ms * 1.45, 20.0), 400.0)
    else:
        t_nas_ms = None
        t_end = min(max(kz.t_p * 3000.0, 40.0), 400.0)

    theta = gres.theta_star if gres.theta_star is not None else 0.0
    t_ms, k_star = build_kpr_curve(kz.t_p, ct_m.alpha, theta, t_end)
    _, k_zero = build_kpr_curve(kz.t_p, ct_m.alpha, 0.0, t_end)

    lbl_star = (f"θ = {math.degrees(theta):.1f}° (задано вручную)" if gres.theta_manual
                else "θ = θ* (расчётный минимум, п. Г.3.7)")

    fig, ax = plt.subplots(figsize=(8.0, 4.0))
    ax.plot(t_ms, k_star, color="#d62728", linewidth=2.0, label=lbl_star)
    ax.plot(t_ms, k_zero, color="#1f77b4", linewidth=1.3, label="θ = 0°")
    ax.axhline(eff, color="#2ca02c", linestyle="--", linewidth=1.5,
               label=f"Уровень A·(1−K_r) = {eff:.3f}")
    if t_nas_ms is not None:
        ax.axvline(t_nas_ms, color="#2ca02c", linestyle=":", linewidth=1.0)
        ax.plot([t_nas_ms], [eff], "o", color="#2ca02c", markersize=9,
                label=f"t_нас = {t_nas_ms:.2f} мс")
    ax.set_xlabel("Время t, мс")
    ax.set_ylabel("Коэффициент переходного режима K_п.р(t)")
    ax.set_title(f"{kz.label} · T_p = {kz.t_p * 1000:.0f} мс · cos α = {ct_m.cos_alpha:.3f}",
                 fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def build_report(ct, chain, results, verdict_lines, verdict, t_req_ms, method="analytic") -> bytes:
    """ct — паспортные данные ТТ; chain — параметры вторичной цепи;
    results — список кортежей (CTParams режима, KZParams, dict результатов)."""
    doc = Document()
    doc.add_heading("Отчёт о проверке трансформатора тока", 0)

    p = doc.add_paragraph()
    p.add_run("Дата формирования: ").bold = True
    p.add_run(datetime.now().strftime("%d.%m.%Y %H:%M"))
    doc.add_paragraph(
        "Определение времени до насыщения при коротких замыканиях по ГОСТ Р 58669-2019, "
        f"{METHOD_TITLES.get(method, method)}. Расчёт выполнен без остаточной "
        f"намагниченности и с предельной остаточной намагниченностью K_r = {K_R_PRED} "
        "(п. 4.3, п. 5.1.3). Фактическая вторичная нагрузка определена по параметрам "
        "вторичной цепи в соответствии с п. 4.2.6 и Приложением А."
    )
    if method in ("graphic", "both"):
        doc.add_paragraph(
            "Графический метод по паспортным данным (раздел 5.2) реализован в численной "
            "форме: универсальные характеристики приложения Б построены по формуле (Г.15) "
            "для начальных фаз θ, при которых время до насыщения наименьшее (п. Г.3.7), — "
            "что и воспроизводится расчётом вместо снятия значений с чертежей."
        )

    doc.add_heading("1. Исходные данные", level=1)
    _add_table(doc, ["Параметр", "Значение"], [
        ("Номинальный первичный ток I1ном", f"{ct.i1_nom:g} А"),
        ("Номинальный вторичный ток I2ном", f"{ct.i2_nom:g} А"),
        ("Номинальная предельная кратность Kном", f"{ct.k_nom:g}"),
        ("Номинальная мощность вторичной нагрузки Sном", f"{ct.s_nom:g} ВА"),
        ("Коэффициент мощности нагрузки cos φном", f"{ct.cos_phi_nom:g}"),
        ("Активное сопротивление вторичной обмотки R2", f"{ct.r2:g} Ом"),
        ("Индуктивное сопротивление вторичной обмотки X2", f"{ct.x2:g} Ом"),
        ("Сопротивление приборов Rприб", f"{chain['r_prib']:g} Ом"),
        ("Индуктивная составляющая нагрузки Xн", f"{chain['x_load']:g} Ом"),
        ("Схема соединения вторичных обмоток", chain["scheme"]),
        ("Материал жилы кабеля", chain["material"]),
        ("Длина кабеля (в одну сторону)", f"{chain['length']:g} м"),
        ("Сечение жилы", f"{chain['section']:g} мм²"),
        ("Переходное сопротивление контактов", f"{chain['r_per']:g} Ом"),
        ("Требуемое время до насыщения", f"{t_req_ms:g} мс" if t_req_ms else "не задано"),
    ])

    doc.add_heading("2. Промежуточные величины (общие)", level=1)
    _add_table(doc, ["Величина", "Значение"], [
        ("Сопротивление номинальной нагрузки zн.ном = Sном / I2ном²", f"{ct.z_n_nom:.4f} Ом"),
        ("Номинальное полное сопротивление z2Σном (формула 10)", f"{ct.z2_sigma_nom:.4f} Ом"),
        ("Коэффициент расчётной длины кабеля — трёхфазное КЗ", f"{chain['k_sch_3']:g}"),
        ("Коэффициент расчётной длины кабеля — однофазное КЗ", f"{chain['k_sch_1']:g}"),
    ])

    keys = _keys_for(method)
    for idx, (ct_m, kz, res) in enumerate(results, start=3):
        r_cable = ct_m.r_load_fact - chain["r_prib"] - chain["r_per"]
        doc.add_heading(f"{idx}. Режим: {kz.label}", level=1)
        _add_table(doc, ["Параметр", "Значение"], [
            ("Ток КЗ (действующее значение)", f"{kz.i_kz:g} А"),
            ("Постоянная времени T_p", f"{kz.t_p:g} с ({kz.t_p * 1000:.0f} мс)"),
            ("Фактическая кратность Kфакт = Iкз / I1ном", f"{kz.i_kz / ct_m.i1_nom:.2f}"),
            ("R кабеля для этого режима (ρ·k·L/S)", f"{r_cable:.4f} Ом"),
            ("Rн.факт = Rприб + Rпер + Rкаб", f"{ct_m.r_load_fact:.4f} Ом"),
            ("z2Σ (формула 11)", f"{ct_m.z2_sigma:.4f} Ом"),
            ("Угол α (формула 12)", f"{math.degrees(ct_m.alpha):.2f}° (cos α = {ct_m.cos_alpha:.4f})"),
            ("Параметр режима A (формула 9)", f"{res[keys[0]].a:.4f}"),
        ])

        rows = []
        for key in keys:
            r = res.get(key)
            if r is None:
                continue
            m_name = "графический" if key in GRAPHIC_KEYS else "аналитический"
            extra = ""
            if key in GRAPHIC_KEYS and r.status == ST_OK and r.theta_star is not None:
                tag = "вручную" if r.theta_manual else "θ*"
                extra = f", {tag} = {math.degrees(r.theta_star):.1f}°"
            rows.append((f"{m_name} — {SCENARIO_TITLES[key]}", f"{r.a:.4f}",
                         f"{fmt_t(r)}{extra}"))
        _add_table(doc, ["Метод и сценарий", "Параметр A", "Время до насыщения"], rows)

        seen = set()
        for key in keys:
            r = res.get(key)
            if r is None:
                continue
            for note in r.notes:
                if note not in seen:
                    seen.add(note)
                    doc.add_paragraph(note, style="List Bullet")

        # Графики K_п.р(t) для графического метода
        if method in ("graphic", "both"):
            for key in GRAPHIC_KEYS:
                r = res.get(key)
                if r is None or r.status != ST_OK or r.t_nas is None:
                    continue
                eff = r.a * (1.0 - r.k_r)
                cap = doc.add_paragraph()
                cap.add_run(f"График K_п.р(t) — {SCENARIO_TITLES[key]}:").bold = True
                try:
                    png = _make_chart_png(kz, ct_m, r, eff)
                    doc.add_picture(png, width=Inches(6.0))
                except Exception as exc:
                    doc.add_paragraph(f"(График не построен: {type(exc).__name__}. "
                                      "Установите библиотеку matplotlib для отображения графиков.)")

    doc.add_heading("Вывод", level=1)
    label = {"success": "ТТ проходит проверку.",
             "warning": "ТТ проходит проверку с замечаниями.",
             "danger": "ТТ проверку не проходит."}.get(verdict, "")
    if label:
        p = doc.add_paragraph()
        p.add_run(label).bold = True
    for line in verdict_lines:
        doc.add_paragraph(line, style="List Bullet")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# === КОНЕЦ ФАЙЛА report/docx_report.py ===
