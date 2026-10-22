"""Генерация отчёта в формате Word (.docx)."""
from __future__ import annotations

import io
import math
from datetime import datetime

from docx import Document

from methods.gost_58669 import (
    ANALYTIC_KEYS, GRAPHIC_KEYS, K_R_PRED, ST_GRAPHIC_REQUIRED, ST_NO_SAT, ST_OK,
    ST_STEADY,
)

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


def build_report(ct, results, verdict_lines, verdict, t_req_ms, method="analytic") -> bytes:
    """results — список кортежей (KZParams, dict результатов calculate())."""
    doc = Document()
    doc.add_heading("Отчёт о проверке трансформатора тока", 0)

    p = doc.add_paragraph()
    p.add_run("Дата формирования: ").bold = True
    p.add_run(datetime.now().strftime("%d.%m.%Y %H:%M"))
    doc.add_paragraph(
        "Определение времени до насыщения при коротких замыканиях по ГОСТ Р 58669-2019, "
        f"{METHOD_TITLES.get(method, method)}. Расчёт выполнен без остаточной "
        f"намагниченности и с предельной остаточной намагниченностью K_r = {K_R_PRED} "
        "(п. 4.3, п. 5.1.3)."
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
        ("Фактическое активное сопротивление нагрузки Rн.факт", f"{ct.r_load_fact:g} Ом"),
        ("Фактическое индуктивное сопротивление нагрузки Xн.факт", f"{ct.x_load_fact:g} Ом"),
        ("Требуемое время до насыщения", f"{t_req_ms:g} мс" if t_req_ms else "не задано"),
    ])

    doc.add_heading("2. Промежуточные величины", level=1)
    _add_table(doc, ["Величина", "Значение"], [
        ("Сопротивление номинальной нагрузки zн.ном = Sном / I2ном²", f"{ct.z_n_nom:.4f} Ом"),
        ("Номинальное полное сопротивление z2Σном (формула 10)", f"{ct.z2_sigma_nom:.4f} Ом"),
        ("Полное сопротивление ветви вторичного тока z2Σ (формула 11)", f"{ct.z2_sigma:.4f} Ом"),
        ("Угол сопротивления ветви вторичного тока α (формула 12)",
         f"{math.degrees(ct.alpha):.2f}° (cos α = {ct.cos_alpha:.4f})"),
    ])

    keys = _keys_for(method)
    for idx, (kz, res) in enumerate(results, start=3):
        doc.add_heading(f"{idx}. Режим: {kz.label}", level=1)
        _add_table(doc, ["Параметр", "Значение"], [
            ("Ток КЗ (действующее значение)", f"{kz.i_kz:g} А"),
            ("Постоянная времени T_p", f"{kz.t_p:g} с ({kz.t_p * 1000:.0f} мс)"),
            ("Фактическая кратность Kфакт = Iкз / I1ном", f"{kz.i_kz / ct.i1_nom:.2f}"),
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
                extra = f", θ* = {math.degrees(r.theta_star):.1f}°"
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
