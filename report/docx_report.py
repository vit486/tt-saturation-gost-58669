"""Генерация отчёта в формате Word (.docx)."""
from __future__ import annotations

import io
from datetime import datetime

from docx import Document

from methods.gost_58669 import K_R_PRED


def fmt_t(res) -> str:
    if res.status == "ok":
        return f"{res.t_nas * 1000:.1f} мс"
    if res.status == "no_saturation":
        return "насыщение отсутствует"
    if res.status == "steady_saturation":
        return "насыщение в установившемся режиме"
    return "требуется графический метод"


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


def build_report(ct, results, verdict_lines, verdict, t_req_ms) -> bytes:
    """Формирует байты .docx-файла."""
    doc = Document()
    doc.add_heading("Отчёт о проверке трансформатора тока", 0)

    p = doc.add_paragraph()
    p.add_run("Дата формирования: ").bold = True
    p.add_run(datetime.now().strftime("%d.%m.%Y %H:%M"))
    doc.add_paragraph(
        "Определение времени до насыщения аналитическим методом по ГОСТ Р 58669-2019 "
        "(раздел 5.1). Расчёт выполнен без остаточной намагниченности и с предельной "
        f"остаточной намагниченностью K_r = {K_R_PRED} (п. 4.3, п. 5.1.3)."
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
    ])

    for idx, (kz, res) in enumerate(results, start=3):
        doc.add_heading(f"{idx}. Режим: {kz.label}", level=1)
        _add_table(doc, ["Параметр", "Значение"], [
            ("Ток КЗ (действующее значение)", f"{kz.i_kz:g} А"),
            ("Постоянная времени T_p", f"{kz.t_p:g} с ({kz.t_p * 1000:.0f} мс)"),
            ("Фактическая кратность Kфакт = Iкз / I1ном", f"{kz.i_kz / ct.i1_nom:.2f}"),
        ])
        _add_table(doc, ["Сценарий", "Параметр A", "Время до насыщения"], [
            ("Без остаточной намагниченности (K_r = 0)",
             f"{res['without_residual'].a:.3f}", fmt_t(res["without_residual"])),
            (f"С предельной остаточной намагниченностью (K_r = {K_R_PRED})",
             f"{res['with_residual'].a:.3f}", fmt_t(res["with_residual"])),
        ])
        for key in ("without_residual", "with_residual"):
            for note in res[key].notes:
                doc.add_paragraph(note, style="List Bullet")

    doc.add_heading("Вывод", level=1)
    label = {
        "success": "ТТ проходит проверку.",
        "warning": "ТТ проходит проверку с замечаниями.",
        "danger": "ТТ проверку не проходит.",
    }.get(verdict, "")
    if label:
        p = doc.add_paragraph()
        p.add_run(label).bold = True
    for line in verdict_lines:
        doc.add_paragraph(line, style="List Bullet")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# === КОНЕЦ ФАЙЛА report/docx_report.py ===
