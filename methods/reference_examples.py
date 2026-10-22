"""
Эталонные примеры для самопроверки расчётного ядра.

Источник: ГОСТ Р 58669-2019:
  - Приложение В (примеры В.1.1–В.1.3) — аналитический метод;
  - Приложение Б (пример В.2.1) — графический метод по паспортным данным;
с учётом Поправки (ИУС 6–7, 2020).

Примечание 1: в примере В.1.2 в тексте стандарта опечатка — в п. В.1.2.1 указан
Kном=20, однако расчёт (п. В.1.2.3 и п. В.2.2.1) выполнен при Kном=18;
в эталоне принято Kном=18.

Примечание 2: для графического метода значения в стандарте снимались с
универсальных характеристик, поэтому допуск увеличен до ±1 мс.
"""
from __future__ import annotations

from methods.gost_58669 import CTParams, KZParams, calculate, calculate_graphical

A_TOL = 0.02            # допуск на параметр A (в стандарте округлён до 3 знаков)
T_TOL_MS = 0.2          # допуск на время для аналитического метода, мс
T_TOL_GRAPH_MS = 1.0    # допуск на время для графического метода, мс

REFERENCE_EXAMPLES = [
    {
        "id": "В.1.1",
        "name": "SAS 550/5G 2000/1",
        "ct": dict(i1_nom=2000.0, i2_nom=1.0, k_nom=20.0, s_nom=40.0,
                   cos_phi_nom=0.8, r2=7.51, x2=0.0),
        "modes": [
            {"label": "трёхфазное КЗ", "i_kz": 23145.0, "t_p": 0.128,
             "r_load": 6.3, "x_load": 0.0,
             "a_expected": 5.785, "t_expected_ms": 16.22,
             "residual_expected": "graphic_required"},
            {"label": "однофазное КЗ", "i_kz": 26900.0, "t_p": 0.180,
             "r_load": 12.6, "x_load": 0.0,
             "a_expected": 3.418, "t_expected_ms": 7.87,
             "residual_expected": "graphic_required"},
        ],
    },
    {
        "id": "В.1.2",
        "name": "ТФЗМ-500Б-1У 2000/1",
        "ct": dict(i1_nom=2000.0, i2_nom=1.0, k_nom=18.0, s_nom=50.0,
                   cos_phi_nom=0.8, r2=10.0, x2=0.0),
        "modes": [
            {"label": "трёхфазное КЗ", "i_kz": 23145.0, "t_p": 0.128,
             "r_load": 6.3, "x_load": 0.0,
             "a_expected": 5.564, "t_expected_ms": 15.42,
             "residual_expected": "graphic_required"},
            {"label": "однофазное КЗ", "i_kz": 26900.0, "t_p": 0.180,
             "r_load": 12.6, "x_load": 0.0,
             "a_expected": 3.453, "t_expected_ms": 7.98,
             "residual_expected": "graphic_required"},
        ],
    },
    {
        "id": "В.1.3",
        "name": "JK ELK СВЗ 4000/1",
        "ct": dict(i1_nom=4000.0, i2_nom=1.0, k_nom=20.0, s_nom=30.0,
                   cos_phi_nom=0.8, r2=10.5, x2=0.0),
        "modes": [
            {"label": "трёхфазное КЗ", "i_kz": 23145.0, "t_p": 0.128,
             "r_load": 6.3, "x_load": 0.0,
             "a_expected": 8.0, "t_expected_ms": 24.5,
             "residual_expected": "ok", "t_residual_expected_ms": 0.39},
            {"label": "однофазное КЗ", "i_kz": 26900.0, "t_p": 0.180,
             "r_load": 12.6, "x_load": 0.0,
             "a_expected": 5.0, "t_expected_ms": 13.24,
             "residual_expected": "graphic_required"},
        ],
    },
]

REFERENCE_EXAMPLES_GRAPHICAL = [
    {
        "id": "В.2.1",
        "name": "SAS 550/5G 2000/1",
        "ct": dict(i1_nom=2000.0, i2_nom=1.0, k_nom=20.0, s_nom=40.0,
                   cos_phi_nom=0.8, r2=7.51, x2=0.0),
        "modes": [
            {"label": "трёхфазное КЗ", "i_kz": 23145.0, "t_p": 0.128,
             "r_load": 6.3, "x_load": 0.0,
             "t_expected_ms": 16.8, "t_residual_expected_ms": 4.2},
            {"label": "однофазное КЗ", "i_kz": 26900.0, "t_p": 0.180,
             "r_load": 12.6, "x_load": 0.0,
             "t_expected_ms": 9.6, "t_residual_expected_ms": 3.2},
        ],
    },
]


def run_self_checks():
    """Прогон аналитического метода по эталонным примерам Приложения В."""
    rows = []
    all_ok = True
    for ex in REFERENCE_EXAMPLES:
        for mode in ex["modes"]:
            ct = CTParams(
                **ex["ct"],
                r_load_fact=mode["r_load"],
                x_load_fact=mode["x_load"],
            )
            kz = KZParams(mode["i_kz"], mode["t_p"], mode["label"])
            res = calculate(ct, kz)

            r0 = res["without_residual"]
            a_ok = abs(r0.a - mode["a_expected"]) <= A_TOL
            t_ok = (r0.status == "ok"
                    and abs(r0.t_nas * 1000.0 - mode["t_expected_ms"]) <= T_TOL_MS)

            r_res = res["with_residual"]
            if mode["residual_expected"] == "graphic_required":
                res_ok = r_res.status == "graphic_required"
                res_text = "графический метод (условие (8) не выполняется)"
            else:
                res_ok = (r_res.status == "ok" and
                          abs(r_res.t_nas * 1000.0 - mode["t_residual_expected_ms"]) <= T_TOL_MS)
                res_text = (f"{r_res.t_nas * 1000.0:.2f} мс "
                            f"(эталон {mode['t_residual_expected_ms']} мс)"
                            if r_res.status == "ok" else r_res.status)

            ok = a_ok and t_ok and res_ok
            all_ok = all_ok and ok
            rows.append({
                "Пример": f"{ex['id']} {ex['name']}",
                "Режим": mode["label"],
                "A эталон": mode["a_expected"],
                "A расчёт": round(r0.a, 3),
                "t эталон, мс": mode["t_expected_ms"],
                "t расчёт, мс": round(r0.t_nas * 1000.0, 2) if r0.status == "ok" else "—",
                "Сценарий K_r=0,86": res_text,
                "Статус": "✅" if ok else "❌",
            })
    return rows, all_ok


def run_self_checks_graphical():
    """Прогон графического метода по эталонному примеру В.2.1 (Приложение Б)."""
    rows = []
    all_ok = True
    for ex in REFERENCE_EXAMPLES_GRAPHICAL:
        for mode in ex["modes"]:
            ct = CTParams(
                **ex["ct"],
                r_load_fact=mode["r_load"],
                x_load_fact=mode["x_load"],
            )
            kz = KZParams(mode["i_kz"], mode["t_p"], mode["label"])
            res, _ = calculate_graphical(ct, kz)

            r0 = res["without_residual"]
            t_ok = (r0.status == "ok"
                    and abs(r0.t_nas * 1000.0 - mode["t_expected_ms"]) <= T_TOL_GRAPH_MS)
            r_res = res["with_residual"]
            tr_ok = (r_res.status == "ok"
                     and abs(r_res.t_nas * 1000.0 - mode["t_residual_expected_ms"]) <= T_TOL_GRAPH_MS)

            ok = t_ok and tr_ok
            all_ok = all_ok and ok
            rows.append({
                "Пример": f"{ex['id']} {ex['name']}",
                "Режим": mode["label"],
                "t эталон, мс (K_r=0)": mode["t_expected_ms"],
                "t расчёт, мс (K_r=0)": round(r0.t_nas * 1000.0, 2) if r0.status == "ok" else "—",
                "t эталон, мс (K_r=0,86)": mode["t_residual_expected_ms"],
                "t расчёт, мс (K_r=0,86)": (round(r_res.t_nas * 1000.0, 2)
                                             if r_res.status == "ok" else "—"),
                "Статус": "✅" if ok else "❌",
            })
    return rows, all_ok


# === КОНЕЦ ФАЙЛА methods/reference_examples.py ===
