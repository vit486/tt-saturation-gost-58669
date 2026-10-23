"""Отчёт Word: все методы, каскадный вывод, графики. Релиз 2.1."""
from __future__ import annotations

import io
import math
import os
import tempfile
from datetime import datetime

from docx import Document
from docx.shared import Inches

from methods.gost_58669 import (
    ANALYTIC_KEYS, GRAPHIC_KEYS, VAH_KEYS, BN_KEYS, K_R_PRED,
    ST_NO_SAT, ST_OK, ST_STEADY, build_kpr_curve, ts_fact_71879,
)
from methods.summary import build_summary

try:
    os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="mpl_"))
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["font.family"] = "DejaVu Sans"
    _HAS_MPL = True
except Exception:
    _HAS_MPL = False


def fmt_t(res):
    if res is None:
        return "—"
    if res.status == ST_OK and res.t_nas is not None:
        return f"{res.t_nas * 1000:.2f} мс"
    if res.status == ST_NO_SAT:
        return "насыщение отсутствует"
    if res.status == ST_STEADY:
        return "насыщение в установившемся режиме (A ≤ 1)"
    return "метод неприменим — см. примечания"


def _table(doc, headers, rows):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, h in enumerate(headers):
        t.rows[0].cells[i].text = str(h)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v)


def _scenario(key, k_r):
    return ("без остаточной намагниченности (K_r = 0)" if "without" in key
            else f"с остаточной намагниченностью (K_r = {k_r:g})")


def _png_curve(xs, ys, xlab, ylab, title, color, hline=None, hlabel=None):
    if not _HAS_MPL:
        raise RuntimeError("matplotlib не установлен")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(xs, ys, color=color, lw=2)
    if hline is not None:
        ax.axhline(hline, color="#2ca02c", ls="--", label=hlabel)
    ax.set_xlabel(xlab)
    ax.set_ylabel(ylab)
    ax.set_title(title, fontsize=10)
    ax.grid(alpha=.3)
    if hline is not None:
        ax.legend(fontsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def _png_kpr(kz, ct_m, r, eff):
    if not _HAS_MPL:
        raise RuntimeError("matplotlib не установлен")
    import matplotlib.pyplot as plt
    tn = r.t_nas * 1000.0 if r.t_nas is not None else None
    t_end = min(max(tn * 1.45, 20.0) if tn else max(kz.t_p * 3000, 40.0), 400.0)
    th = r.theta_star if r.theta_star is not None else 0.0
    tm, ks = build_kpr_curve(kz.t_p, ct_m.alpha, th, t_end)
    _, k0 = build_kpr_curve(kz.t_p, ct_m.alpha, 0.0, t_end)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(tm, ks, color="#d62728", lw=2, label=f"θ* = {math.degrees(th):.1f}°")
    ax.plot(tm, k0, color="#1f77b4", lw=1.2, label="θ = 0°")
    ax.axhline(eff, color="#2ca02c", ls="--", label=f"Уровень A·(1−K_r) = {eff:.3f}")
    if tn is not None:
        ax.axvline(tn, color="#2ca02c", ls=":")
        ax.plot([tn], [eff], "o", color="#2ca02c", label=f"t_нас = {tn:.2f} мс")
    ax.set_xlabel("Время t, мс")
    ax.set_ylabel("K_п.р(t)")
    ax.set_title(f"{kz.label} · T_p = {kz.t_p * 1000:.0f} мс", fontsize=10)
    ax.grid(alpha=.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def _method_rows(res, keys, k_r, name_prefix):
    rows = []
    for key in keys:
        r = res.get(key)
        if r is None:
            continue
        extra = ""
        if r.status == ST_OK and r.theta_star is not None:
            tag = "вручную" if r.theta_manual else "θ*"
            extra = f", {tag} = {math.degrees(r.theta_star):.1f}°"
        rows.append((f"{name_prefix} — {_scenario(key, k_r)}",
                     f"{r.a:.4f}", f"{fmt_t(r)}{extra}", r.detail))
    return rows


def build_report(ct, chain, results, verdict_lines, verdict, t_req_ms, method="both",
                 vah_curve=None, bn_data=None, bn_params=None, k_r=K_R_PRED, eps=10.0):
    is_71879 = "ct_class" in chain
    doc = Document()
    doc.add_heading("Отчёт о проверке трансформатора тока", 0)
    p = doc.add_paragraph()
    p.add_run("Дата формирования: ").bold = True
    p.add_run(datetime.now().strftime("%d.%m.%Y %H:%M"))
    doc.add_paragraph(
        f"Стандарт: {chain.get('standard', 'ГОСТ Р 58669-2019')}. Каскад методов: "
        "аналитический → графический по паспортным данным → ВАХ → характеристика "
        "намагничивания; итог — по самому точному из доступных. Расчёт без остаточной "
        f"намагниченности и с K_r = {k_r:g}. Нагрузка вторичной цепи — по п. 4.2.6 "
        "и Приложению А.")

    doc.add_heading("1. Исходные данные", level=1)
    rows = [
        ("I1ном / I2ном", f"{ct.i1_nom:g} / {ct.i2_nom:g} А"),
        ("Kном", f"{ct.k_nom:g}"),
        ("Sном / cos φном", f"{ct.s_nom:g} ВА / {ct.cos_phi_nom:g}"),
        ("R2 / X2", f"{ct.r2:g} / {ct.x2:g} Ом"),
        ("Rприб / Xн", f"{chain['r_prib']:g} / {chain['x_load']:g} Ом"),
        ("Схема вторичных обмоток", chain["scheme"]),
        ("Кабель", chain["material"]),
        ("Длина / сечение кабеля", f"{chain['length']:g} м / {chain['section']:g} мм²"),
        ("Переходное сопротивление", f"{chain['r_per']:g} Ом"),
        ("Коэффициент остаточной намагниченности K_r", f"{k_r:g}"),
        ("Полная погрешность ε (для ВАХ и B(H))", f"{eps:g} %"),
        ("Требуемое t_нас", f"{t_req_ms:g} мс" if t_req_ms else "не задано"),
    ]
    if is_71879:
        rows += [
            ("Класс точности", chain["ct_class"]),
            ("L2 — индуктивность рассеяния", f"{chain['l2']:g} Гн"),
            ("Ts.ном", f"{chain['ts_nom']:g} с"),
            ("Kп.р.ном", f"{chain['kp_r_nom']:g}"),
        ]
    if vah_curve:
        rows.append(("ВАХ (п. 5.3)", f"{len(vah_curve['i0'])} точек"))
    if bn_data and bn_params:
        rows.append(("B(H) (п. 5.4)",
                     f"{len(bn_data['h'])} точек; w2 = {bn_params['w2']:g}, "
                     f"s = {bn_params['s'] * 1e4:.1f} см², l = {bn_params['l']:g} м"))
    _table(doc, ["Параметр", "Значение"], rows)

    doc.add_heading("2. Промежуточные величины", level=1)
    _table(doc, ["Величина", "Значение"], [
        ("zн.ном = Sном / I2ном²", f"{ct.z_n_nom:.4f} Ом"),
        ("Номинальное полное сопротивление (формула 10)", f"{ct.z2_sigma_nom:.4f} Ом"),
        ("kсх трёхфазное / однофазное КЗ",
         f"{chain['k_sch_3']:g} / {chain['k_sch_1']:g}"),
    ])

    for idx, (ct_m, kz, res) in enumerate(results, start=3):
        doc.add_heading(f"{idx}. Режим: {kz.label}", level=1)
        r_cable = ct_m.r_load_fact - chain["r_prib"] - chain["r_per"]
        mode_rows = [
            ("Ток КЗ", f"{kz.i_kz:g} А"),
            ("Постоянная времени T_а.экв", f"{kz.t_p * 1000:.0f} мс"),
            ("Фактическая кратность Kфакт", f"{kz.i_kz / ct_m.i1_nom:.2f}"),
            ("R кабеля / Rн.факт",
             f"{r_cable:.4f} / {ct_m.r_load_fact:.4f} Ом"),
            ("Полное сопротивление ветви вторичного тока", f"{ct_m.z2_sigma:.4f} Ом"),
            ("Параметр режима A", f"{res[ANALYTIC_KEYS[0]].a:.4f}"),
        ]
        if is_71879:
            ts = ts_fact_71879(ct_m)
            mode_rows.insert(2, ("T_s / T = min(T_а.экв, T_s)",
                                 f"{ts * 1000:.0f} / {min(kz.t_p, ts) * 1000:.0f} мс"))
        _table(doc, ["Параметр", "Значение"], mode_rows)

        all_rows = _method_rows(res, ANALYTIC_KEYS, k_r, "аналитический") + \
                   _method_rows(res, GRAPHIC_KEYS, k_r, "графический") + \
                   _method_rows(res, VAH_KEYS, k_r, "по ВАХ") + \
                   _method_rows(res, BN_KEYS, k_r, "по B(H)")
        if all_rows:
            _table(doc, ["Метод и сценарий", "A", "Время до насыщения", "Уточнение"],
                   all_rows)

        seen = set()
        for key in ANALYTIC_KEYS + GRAPHIC_KEYS + VAH_KEYS + BN_KEYS:
            r = res.get(key)
            if r is None:
                continue
            for note in r.notes:
                if note not in seen:
                    seen.add(note)
                    doc.add_paragraph(note, style="List Bullet")

        for key in GRAPHIC_KEYS:
            r = res.get(key)
            if r is None or r.status != ST_OK:
                continue
            doc.add_paragraph(f"График K_п.р(t) — {_scenario(key, k_r)}:").bold = True
            try:
                doc.add_picture(_png_kpr(kz, ct_m, r, r.a * (1 - r.k_r)), width=Inches(6))
            except Exception as e:
                doc.add_paragraph(f"(График не построен: {type(e).__name__}.)")

    if vah_curve:
        doc.add_paragraph("Вольт-амперная характеристика:").bold = True
        try:
            doc.add_picture(_png_curve(vah_curve["i0"], vah_curve["u"], "I₀, А", "U, В",
                                       "ВАХ ТТ", "#d62728"), width=Inches(6))
        except Exception as e:
            doc.add_paragraph(f"(График ВАХ не построен: {type(e).__name__}.)")

    if bn_data:
        doc.add_paragraph("Характеристика намагничивания:").bold = True
        try:
            doc.add_picture(_png_curve(bn_data["h"], bn_data["b"], "H, А/м", "B, Тл",
                                       "B(H) ТТ", "#9467bd"), width=Inches(6))
        except Exception as e:
            doc.add_paragraph(f"(График B(H) не построен: {type(e).__name__}.)")

    doc.add_heading("Сводка по всем методам и итоговая оценка", level=1)
    rows, _, lines, primary = build_summary(results, bool(vah_curve), bool(bn_data), t_req_ms)
    _table(doc, ["Метод", "Статус", "t_нас, мс", "Пояснение"],
           [(r["Метод"], r["Статус"], r["t_нас, мс"], r["Пояснение"]) for r in rows])
    label = {"success": "ТТ проходит проверку.",
             "warning": "Требуется уточнение.",
             "danger": "ТТ проверку не проходит."}.get(verdict, "")
    if label:
        p = doc.add_paragraph()
        p.add_run(label).bold = True
    for line in lines + verdict_lines:
        doc.add_paragraph(line, style="List Bullet")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# === КОНЕЦ ФАЙЛА report/docx_report.py ===
