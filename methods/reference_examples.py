"""
Эталонные примеры и самопроверка.
- ГОСТ Р 58669-2019, Приложение В (В.1.1–В.1.3), с Поправкой ИУС 6–7, 2020;
- ГОСТ Р 71879-2024, Приложение Б (Б.1: первое и второе КЗ);
- структурные проверки формул (Г.15) 58669 и (12)–(14) 71879.
"""
from __future__ import annotations

import math

import numpy as np

_TRAPEZOID = getattr(np, "trapezoid", None) or getattr(np, "trapz")

from methods.gost_58669 import (
    CTParams, KZParams, K_R_PRED, OMEGA, ST_GRAPHIC_REQUIRED, ST_NO_SAT, ST_OK,
    calculate, calculate_second_kz_71879, k_pr, t_nas_graphic, ts_fact_71879,
)

A_TOL = 0.02
T_TOL_MS = 0.2

REFERENCE_EXAMPLES = [
    {
        "id": "В.1.1", "name": "SAS 550/5G 2000/1",
        "ct": dict(i1_nom=2000.0, i2_nom=1.0, k_nom=20.0, s_nom=40.0,
                   cos_phi_nom=0.8, r2=7.51, x2=0.0),
        "modes": [
            {"label": "трёхфазное КЗ", "i_kz": 23145.0, "t_p": 0.128,
             "r_load": 6.3, "x_load": 0.0, "a_expected": 5.785,
             "t_expected_ms": 16.22, "residual_expected": "graphic_required"},
            {"label": "однофазное КЗ", "i_kz": 26900.0, "t_p": 0.180,
             "r_load": 12.6, "x_load": 0.0, "a_expected": 3.418,
             "t_expected_ms": 7.87, "residual_expected": "graphic_required"},
        ],
    },
    {
        "id": "В.1.2", "name": "ТФЗМ-500Б-1У 2000/1",
        "ct": dict(i1_nom=2000.0, i2_nom=1.0, k_nom=18.0, s_nom=50.0,
                   cos_phi_nom=0.8, r2=10.0, x2=0.0),
        "modes": [
            {"label": "трёхфазное КЗ", "i_kz": 23145.0, "t_p": 0.128,
             "r_load": 6.3, "x_load": 0.0, "a_expected": 5.564,
             "t_expected_ms": 15.42, "residual_expected": "graphic_required"},
            {"label": "однофазное КЗ", "i_kz": 26900.0, "t_p": 0.180,
             "r_load": 12.6, "x_load": 0.0, "a_expected": 3.453,
             "t_expected_ms": 7.98, "residual_expected": "graphic_required"},
        ],
    },
    {
        "id": "В.1.3", "name": "JK ELK СВЗ 4000/1",
        "ct": dict(i1_nom=4000.0, i2_nom=1.0, k_nom=20.0, s_nom=30.0,
                   cos_phi_nom=0.8, r2=10.5, x2=0.0),
        "modes": [
            {"label": "трёхфазное КЗ", "i_kz": 23145.0, "t_p": 0.128,
             "r_load": 6.3, "x_load": 0.0, "a_expected": 8.0,
             "t_expected_ms": 24.5, "residual_expected": "ok",
             "t_residual_expected_ms": 0.39},
            {"label": "однофазное КЗ", "i_kz": 26900.0, "t_p": 0.180,
             "r_load": 12.6, "x_load": 0.0, "a_expected": 5.0,
             "t_expected_ms": 13.24, "residual_expected": "graphic_required"},
        ],
    },
]

# ГОСТ Р 71879-2024, Приложение Б, пример Б.1 — ТРГ-УЭТМ-500 10PR 2000/1.
# Ts.ном = 0.507 с восстановлена из результатов примера (формула 5).
# Эталоны времени первого КЗ — по формуле (6) с K_r = 0,085.
# Второе КЗ: t_кз1 = 0,1 с, t_б.п = 1,0 с (t2 = 1,1 с), формула (9).
EXAMPLE_71879_B1 = {
    "id": "Б.1", "name": "ТРГ-УЭТМ-500 10PR 2000/1 (ГОСТ Р 71879-2024)",
    "ct": dict(i1_nom=2000.0, i2_nom=1.0, k_nom=40.0, s_nom=20.0,
               cos_phi_nom=0.8, r2=6.96, x2=0.0,
               l2=0.00182, ts_nom=0.507, kp_r_nom=1.0),
    "k_r": 0.085,
    "t_kz1": 0.1,
    "t_bp": 1.0,
    "modes": [
        {"label": "трёхфазное КЗ", "i_kz": 23145.0, "t_p": 0.128,
         "r_load": 6.3, "x_load": 0.0, "a_expected": 6.82,
         "ts_expected_s": 0.878, "t_expected_ms": 17.87,
         "t_second_expected_ms": 10.12},
        {"label": "однофазное КЗ", "i_kz": 26900.0, "t_p": 0.180,
         "r_load": 12.6, "x_load": 0.0, "a_expected": 3.97,
         "ts_expected_s": 0.595, "t_expected_ms": 8.61,
         "t_second_expected_ms": 6.15},
    ],
}


def _iter_examples():
    for ex in REFERENCE_EXAMPLES:
        for mode in ex["modes"]:
            ct = CTParams(**ex["ct"], r_load_fact=mode["r_load"], x_load_fact=mode["x_load"])
            kz = KZParams(mode["i_kz"], mode["t_p"], mode["label"])
            yield ex, mode, ct, kz


def run_self_checks():
    rows, all_ok = [], True
    for ex, mode, ct, kz in _iter_examples():
        res = calculate(ct, kz, "both")
        r0 = res["without_residual"]
        a_ok = abs(r0.a - mode["a_expected"]) <= A_TOL
        t_ok = (r0.status == ST_OK
                and abs(r0.t_nas * 1000.0 - mode["t_expected_ms"]) <= T_TOL_MS)
        r_res = res["with_residual"]
        if mode["residual_expected"] == "graphic_required":
            res_ok = r_res.status == ST_GRAPHIC_REQUIRED
            res_text = "аналитика: неприменим (усл. 8)"
        else:
            res_ok = (r_res.status == ST_OK and
                      abs(r_res.t_nas * 1000.0 - mode["t_residual_expected_ms"]) <= T_TOL_MS)
            res_text = (f"{r_res.t_nas * 1000.0:.2f} мс (эталон {mode['t_residual_expected_ms']} мс)"
                        if r_res.status == ST_OK else r_res.status)
        g_res = res["graphic_with_residual"]
        if g_res.status == ST_OK and g_res.t_nas is not None:
            res_text += f"; графич.: {g_res.t_nas * 1000.0:.2f} мс"
        g0 = res["graphic_without_residual"]
        g_txt = f"{g0.t_nas * 1000.0:.2f}" if (g0.status == ST_OK and g0.t_nas) else "—"
        ok = bool(a_ok and t_ok and res_ok)
        all_ok = all_ok and ok
        rows.append({
            "Пример": f"{ex['id']} {ex['name']}", "Режим": mode["label"],
            "A эталон": mode["a_expected"], "A расчёт": round(float(r0.a), 3),
            "t эталон, мс": mode["t_expected_ms"],
            "t аналит., мс": round(float(r0.t_nas * 1000.0), 2) if r0.status == ST_OK else "—",
            "t графич., мс": g_txt, "Сценарий K_r = 0,86": res_text,
            "Статус": "✅" if ok else "❌",
        })
    return rows, all_ok


def run_self_checks_71879():
    """Самопроверка по примеру Б.1 ГОСТ Р 71879-2024 (первое и второе КЗ)."""
    ex = EXAMPLE_71879_B1
    rows, all_ok = [], True
    for mode in ex["modes"]:
        ct = CTParams(**ex["ct"], r_load_fact=mode["r_load"], x_load_fact=mode["x_load"])
        kz = KZParams(mode["i_kz"], mode["t_p"], mode["label"])
        ts = ts_fact_71879(ct)
        res = calculate(ct, kz, "analytic", None, ex["k_r"], standard="71879")
        r0 = res["with_residual"]
        a_ok = abs(r0.a - mode["a_expected"]) <= A_TOL
        ts_ok = abs(ts - mode["ts_expected_s"]) <= 0.005
        t_ok = (r0.status == ST_OK
                and abs(r0.t_nas * 1000.0 - mode["t_expected_ms"]) <= T_TOL_MS)
        res2 = calculate_second_kz_71879(ct, kz, ex["k_r"], ex["t_bp"])
        r2 = res2["second_with_residual"]
        t2_ok = (r2.status == ST_OK
                 and abs(r2.t_nas * 1000.0 - mode["t_second_expected_ms"]) <= T_TOL_MS)
        ok = bool(a_ok and ts_ok and t_ok and t2_ok)
        all_ok = all_ok and ok
        rows.append({
            "Режим": mode["label"],
            "A эталон": mode["a_expected"], "A расчёт": round(float(r0.a), 3),
            "Ts эталон, с": mode["ts_expected_s"], "Ts расчёт, с": round(float(ts), 3),
            "t′ эталон, мс": mode["t_expected_ms"],
            "t′ расчёт, мс": round(float(r0.t_nas * 1000.0), 2) if r0.status == ST_OK else "—",
            "t″ эталон, мс": mode["t_second_expected_ms"],
            "t″ расчёт, мс": round(float(r2.t_nas * 1000.0), 2) if r2.status == ST_OK else "—",
            "Статус": "✅" if ok else "❌",
        })
    return rows, all_ok


def _k_quad(t, t_p, alpha, theta, z2=1.0, n=4000):
    """Независимая проверка (Г.15): интегрирование потокосцепления по (Г.13)."""
    rs = z2 * math.cos(alpha)
    ls = z2 * math.sin(alpha) / OMEGA
    x = np.linspace(0.0, t, n)
    i2 = np.exp(-x / t_p) * math.cos(theta) - np.cos(OMEGA * x + theta)
    di2 = -np.exp(-x / t_p) * math.cos(theta) / t_p + OMEGA * np.sin(OMEGA * x + theta)
    return float(_TRAPEZOID(rs * i2 + ls * di2, x) * OMEGA / z2)


def run_graphic_checks():
    rows = []

    def add(name, ok, detail):
        rows.append({"Проверка": name, "Результат": detail, "Статус": "✅" if ok else "❌"})
        return bool(ok)

    all_ok = True
    tp = 0.128
    m = max(abs(float(k_pr(0.0, tp, a, th)))
            for a in (0.0, 0.4, 1.1) for th in (-1.2, 0.0, 0.7))
    all_ok &= add("Начальное условие K_п.р(0) = 0", m < 1e-12, f"max |K(0)| = {m:.1e}")
    m = 0.0
    for t in (0.001, 0.005, 0.02, 0.06, 0.15):
        g18 = OMEGA * tp * (1 - math.exp(-t / tp)) - math.sin(OMEGA * t)
        m = max(m, abs(float(k_pr(t, tp, 0.0, 0.0)) - g18))
    all_ok &= add("Вырождение (Г.15) → (Г.18) при α = 0, θ = 0", m < 1e-9, f"max |Δ| = {m:.1e}")
    m = 0.0
    for t in (0.001, 0.005, 0.02, 0.06, 0.15):
        al = 0.5
        e = math.exp(-t / tp)
        g17 = math.sin(al) * e + math.cos(al) * OMEGA * tp * (1 - e) - math.sin(OMEGA * t + al)
        m = max(m, abs(float(k_pr(t, tp, al, 0.0)) - g17))
    all_ok &= add("Вырождение (Г.15) → (Г.17) при θ = 0", m < 1e-9, f"max |Δ| = {m:.1e}")
    m = 0.0
    for al in (0.0, 0.6):
        for th in (-0.9, 0.3):
            m = max(m, abs(float(k_pr(0.02, tp, al, th))
                           + float(k_pr(0.02, tp, al, th + math.pi))))
    all_ok &= add("Симметрия K(θ+π) = −K(θ)", m < 1e-12, f"max |Δ| = {m:.1e}")
    m = 0.0
    for (t_, tp_, al_, th_) in [(0.016, 0.128, 0.0, 0.09), (0.009, 0.180, 0.0, 0.62),
                                (0.030, 0.128, 0.5, 0.30), (0.005, 0.050, 1.0, -0.40)]:
        a_ = float(k_pr(t_, tp_, al_, th_))
        b_ = _k_quad(t_, tp_, al_, th_)
        m = max(m, abs(a_ - b_) / max(abs(a_), 1e-9))
    all_ok &= add("Сверка с интегрированием Ψ по (Г.13)", m < 1e-4,
                  f"макс. относительное расхождение = {m:.1e}")
    t1, _, _ = t_nas_graphic(5.785, 0.128, 0.0, 0.0, n_theta=181, n_t=2000)
    t2, _, _ = t_nas_graphic(5.785, 0.128, 0.0, 0.0, n_theta=721, n_t=12000)
    d = abs(t1 - t2) * 1000.0
    all_ok &= add("Сходимость по сеткам", d < 0.05, f"|Δt| = {d:.4f} мс")
    t3, _, why = t_nas_graphic(60.0, 0.05, 0.0, 0.0)
    all_ok &= add("Условие (7): при A ≫ ωT_p + 1 насыщения нет",
                  why == ST_NO_SAT and t3 is None, f"статус = {why}")
    ct = CTParams(2000.0, 1.0, 20.0, 40.0, 0.8, 7.51, 0.0, 6.3, 0.0)
    kz = KZParams(23145.0, 0.128, "трёхфазное КЗ")
    r = calculate(ct, kz, "both")
    an, gr = r["with_residual"], r["graphic_with_residual"]
    all_ok &= add("П. 5.1.5: где аналитика отказывает, графический считает",
                  an.status == ST_GRAPHIC_REQUIRED and gr.status == ST_OK,
                  f"аналитика: {an.status}; графический: {gr.t_nas * 1000:.2f} мс")
    return rows, all_ok


def run_graphic_checks_71879():
    """Структурные проверки формул (12)–(14) ГОСТ Р 71879-2024.
    Числовая сверка с примером Б.2 будет добавлена после получения скана."""
    from methods.gost_58669 import (
        OMEGA, ST_OK, calc_a_param, effective_ct_kz, k_pr1_71879, k_pr2_71879,
        theta_from_phi_71879, t_nas_graphic_first_71879, t_nas_graphic_second_71879,
    )
    rows = []

    def add(name, ok, detail):
        rows.append({"Проверка": name, "Результат": detail,
                     "Статус": "✅" if ok else "❌"})
        return bool(ok)

    all_ok = True

    m = max(abs(float(k_pr1_71879(0.0, Ta, Ts, th)))
            for Ta, Ts in ((0.128, 0.878), (0.18, 0.595), (0.05, 0.30))
            for th in (-1.2, 0.0, 0.7))
    all_ok &= add("Формула (12): K'_п.р(0) = 0 при любой θ", m < 1e-12,
                  f"max |K'(0)| = {m:.1e}")

    m = 0.0
    for t in (0.005, 0.02, 0.07):
        for th in (-0.9, 0.4):
            m = max(m, abs(float(k_pr1_71879(t, 0.128, 0.878, th))
                           + float(k_pr1_71879(t, 0.128, 0.878, th + math.pi))))
    all_ok &= add("Симметрия (12): K'(θ+π) = −K'(θ)", m < 1e-12, f"max |Δ| = {m:.1e}")

    t2 = 1.1
    k1v = float(k_pr1_71879(t2, 0.128, 0.878, 0.35))
    m = abs(float(k_pr2_71879(t2, t2, 0.128, 0.878, 0.8, k1v)) - k1v)
    all_ok &= add("Непрерывность (13): K''(t2) = K'(t2)", m < 1e-12, f"|Δ| = {m:.1e}")

    m = abs(theta_from_phi_71879(math.atan(OMEGA * 0.128), 0.128))
    all_ok &= add("Соотношение (14): θ = φкз − arctg(ω·Ta)", m < 1e-12,
                  f"|Δ| = {m:.1e}")

    ex = EXAMPLE_71879_B1
    for mode in ex["modes"]:
        ct = CTParams(**ex["ct"], r_load_fact=mode["r_load"], x_load_fact=mode["x_load"])
        kz = KZParams(mode["i_kz"], mode["t_p"], mode["label"])
        cte, kze, ts, _ = effective_ct_kz(ct, kz, "71879")
        a = calc_a_param(cte, kze)
        t1c, phi1, why1 = t_nas_graphic_first_71879(a, kz.t_p, ts, ex["k_r"])
        ok1 = why1 == ST_OK and t1c is not None and 0.0 < t1c < 0.5
        all_ok &= add(f"Первое КЗ ({mode['label']}): решение по (12) существует",
                      ok1, (f"t′ = {t1c * 1000:.2f} мс при φкз = {math.degrees(phi1):.1f}°"
                            if ok1 else f"статус: {why1}"))
        t2c, phi2, why2 = t_nas_graphic_second_71879(a, kz.t_p, ts,
                                                     ex["t_kz1"], ex["t_bp"], ex["k_r"])
        ok2 = why2 == ST_OK and t2c is not None and t2c >= 0.0
        all_ok &= add(f"Второе КЗ ({mode['label']}): решение по (13) существует",
                      ok2, (f"t″ = {t2c * 1000:.2f} мс от t2 при φкз = "
                            f"{math.degrees(phi2):.1f}°" if ok2 else f"статус: {why2}"))
    return rows, all_ok


def run_method_comparison():
    rows = []
    for ex, mode, ct, kz in _iter_examples():
        res = calculate(ct, kz, "both")
        an, gr = res["without_residual"], res["graphic_without_residual"]
        ta = an.t_nas * 1000.0 if (an.status == ST_OK and an.t_nas) else None
        tg = gr.t_nas * 1000.0 if (gr.status == ST_OK and gr.t_nas) else None
        if ta and tg:
            dev = f"{(ta - tg) / tg * 100.0:+.1f}%"
            domain = ("в области применимости (t ≥ 15 мс)" if ta >= 15.0
                      else "вне области применимости (п. 5.1.7)")
        else:
            dev, domain = "—", "—"
        rows.append({
            "Пример": f"{ex['id']} {mode['label']}",
            "t аналит., мс": round(ta, 2) if ta else "—",
            "t графич., мс": round(tg, 2) if tg else "—",
            "Отклонение аналитики": dev,
            "θ*, град": round(math.degrees(gr.theta_star), 1) if gr.theta_star is not None else "—",
            "Область применимости аналитики": domain,
        })
    return rows


# === КОНЕЦ ФАЙЛА methods/reference_examples.py ===
