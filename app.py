"""
⚡ Проверка трансформаторов тока на насыщение при коротких замыканиях.
Методика: ГОСТ Р 58669-2019.  Релиз 1.9.
"""

import math
from datetime import datetime

import streamlit as st

try:
    from methods.gost_58669 import (
        ANALYTIC_KEYS, CTParams, GRAPHIC_KEYS, K_R_PRED, KZParams, ST_GRAPHIC_REQUIRED,
        ST_NO_SAT, ST_OK, ST_STEADY, VAH_KEYS, BN_KEYS, build_kpr_curve, calculate,
        build_vah_default, build_bn_default, calculate_vah, calculate_bn, calc_b_t,
    )
    from methods.reference_examples import (
        REFERENCE_EXAMPLES, run_graphic_checks, run_method_comparison, run_self_checks,
    )
    from report.docx_report import build_report
    _IMPORT_ERROR = None
except Exception as e:
    _IMPORT_ERROR = e

if _IMPORT_ERROR is not None:
    st.set_page_config(page_title="Ошибка структуры файлов", page_icon="⚠️")
    st.error(f"Не удалось загрузить расчётные модули: "
             f"{type(_IMPORT_ERROR).__name__}: {_IMPORT_ERROR}")
    st.markdown("Проверьте файлы `methods/gost_58669.py` (признак: `def calculate_bn(`), "
                "`methods/reference_examples.py` (признак: `REFERENCE_EXAMPLES`), "
                "`report/docx_report.py` (признак: `def build_report(`).")
    st.stop()

import numpy as np      # noqa: E402
import pandas as pd     # noqa: E402

st.set_page_config(page_title="Проверка ТТ — ГОСТ Р 58669-2019", layout="wide", page_icon="⚡")

st.title("⚡ Проверка трансформаторов тока")
st.caption("Насыщение при КЗ · ГОСТ Р 58669-2019 · аналитический и графический методы "
           "· релиз 1.9")

METHOD_OPTIONS = {
    "Аналитический (п. 5.1)": "analytic",
    "Графический по паспортным данным (п. 5.2)": "graphic",
    "Оба метода — сравнение": "both",
}
METHOD_KEYS = {"analytic": ANALYTIC_KEYS, "graphic": GRAPHIC_KEYS, "both": GRAPHIC_KEYS}
LBL_STAR_AUTO = "θ = θ* — расчётный минимум (п. Г.3.7)"
LBL_ZERO = "θ = 0° — максимум апериодической составляющей"

SCHEME_FACTORS = {
    "Полная звезда (3 ТТ)": (1.0, 2.0),
    "Неполная звезда (2 ТТ)": (math.sqrt(3.0), math.sqrt(3.0)),
    "Треугольник": (3.0, 3.0),
    "Один ТТ (токовые цепи в 2 проводах)": (2.0, 2.0),
}
RHO_MATERIALS = {"Медь": 0.0175, "Алюминий": 0.0281}

PRESETS = {
    "— ввести вручную —": {},
    "Пример: ТОЛ-10 600/5 10P10 15 ВА": dict(
        i1_nom=600.0, i2_nom=5.0, k_nom=10.0, s_nom=15.0, cos_phi_nom=0.8,
        r2=0.12, x2=0.0, r_prib=0.35, x_load=0.0),
    "Пример: ТФЗМ-110 2000/5 10P20 30 ВА": dict(
        i1_nom=2000.0, i2_nom=5.0, k_nom=20.0, s_nom=30.0, cos_phi_nom=0.8,
        r2=0.45, x2=0.0, r_prib=0.8, x_load=0.0),
}


def make_scenario_title(key, k_r):
    """Название сценария с актуальным значением K_r."""
    prefix = {
        "without_residual": "Аналитический",
        "with_residual": "Аналитический",
        "graphic_without_residual": "Графический",
        "graphic_with_residual": "Графический",
        "vah_without_residual": "По ВАХ",
        "vah_with_residual": "По ВАХ",
        "bn_without_residual": "По B(H)",
        "bn_with_residual": "По B(H)",
    }.get(key, key)
    suffix = ("без остаточной намагниченности (K_r = 0)" if "without" in key
              else f"с остаточной намагниченностью (K_r = {k_r:g})")
    return f"{prefix} · {suffix}"


with st.sidebar:
    st.header("⚙️ Исходные данные")

    method_label = st.radio("Метод расчёта (п. 4.1 ГОСТ)", list(METHOD_OPTIONS.keys()), index=2,
                            help="Аналитический — формулы (3)/(6). Графический по паспортным "
                                 "данным — численное воспроизведение приложения Б (формула Г.15); "
                                 "является определяющим.")
    method = METHOD_OPTIONS[method_label]

    st.subheader("Начальная фаза θ")
    manual_theta = st.checkbox("Задать θ вручную (графический метод)", value=False)
    theta_override = None
    if manual_theta:
        theta_deg = st.number_input("θ, градусы", min_value=-90.0, max_value=90.0,
                                    value=0.0, step=1.0)
        theta_override = math.radians(theta_deg)

    st.subheader("Остаточная намагниченность")
    custom_kr = st.checkbox(
        "Задать K_r вручную", value=False,
        help="По умолчанию K_r = 0,86 (класс P, п. 5.1.3 ГОСТ Р 58669-2019). Для классов "
             "5PR/10PR или по заводским данным K_r может быть ниже, например 0,1 "
             "(ГОСТ Р 70507.2-2024, таблица 5; ГОСТ Р 71879-2024).")
    if custom_kr:
        k_r_value = st.number_input(
            "K_r — коэффициент остаточной намагниченности", min_value=0.0, max_value=1.0,
            value=0.86, step=0.01, format="%.2f")
    else:
        k_r_value = K_R_PRED

    preset_name = st.selectbox("Тип ТТ", list(PRESETS.keys()))
    preset = PRESETS[preset_name]

    st.subheader("Паспортные данные ТТ")
    i1_nom = st.number_input("I1ном, А", min_value=1.0, value=float(preset.get("i1_nom", 1000.0)),
                             step=50.0, key=f"{preset_name}_i1")
    i2_nom = st.selectbox("I2ном, А", (1.0, 2.0, 5.0),
                          index=(1.0, 2.0, 5.0).index(float(preset.get("i2_nom", 5.0))),
                          key=f"{preset_name}_i2")
    k_nom = st.number_input("Kном (предельная кратность)", min_value=1.0,
                            value=float(preset.get("k_nom", 10.0)), step=1.0,
                            key=f"{preset_name}_k")
    s_nom = st.number_input("Sном вторичной нагрузки, ВА", min_value=1.0,
                            value=float(preset.get("s_nom", 15.0)), step=1.0,
                            key=f"{preset_name}_s")
    cos_phi = st.slider("cos φ ном. нагрузки", 0.1, 1.0,
                        float(preset.get("cos_phi_nom", 0.8)), 0.05, key=f"{preset_name}_cos")
    r2 = st.number_input("R2 вторичной обмотки, Ом", min_value=0.0,
                         value=float(preset.get("r2", 0.15)), step=0.01, format="%.3f",
                         key=f"{preset_name}_r2")
    x2 = st.number_input("X2 вторичной обмотки, Ом", min_value=0.0,
                         value=float(preset.get("x2", 0.0)), step=0.01, format="%.3f",
                         key=f"{preset_name}_x2")

    st.subheader("Нагрузка вторичной цепи (п. 4.2.6)")
    r_prib = st.number_input("Rприб (реле, приборы), Ом", min_value=0.0,
                             value=float(preset.get("r_prib", 0.5)), step=0.01, format="%.3f",
                             key=f"{preset_name}_rp")
    x_load = st.number_input("Xн (индуктивная составляющая), Ом", min_value=0.0,
                             value=float(preset.get("x_load", 0.0)), step=0.01, format="%.3f",
                             key=f"{preset_name}_xl")
    scheme = st.selectbox("Схема соединения вторичных обмоток", list(SCHEME_FACTORS.keys()))
    cable_mat = st.radio("Материал жилы кабеля", list(RHO_MATERIALS.keys()), horizontal=True)
    cable_len = st.number_input("Длина кабеля (в одну сторону), м", min_value=0.0,
                                max_value=3000.0, value=30.0, step=5.0)
    cable_s = st.number_input("Сечение жилы, мм²", min_value=0.5, max_value=300.0,
                              value=2.5, step=0.5)
    r_per = st.radio("Переходное сопротивление контактов, Ом", (0.05, 0.1),
                     horizontal=True, format_func=lambda v: f"{v:g}")

    st.subheader("Короткое замыкание")
    i_kz3 = st.number_input("Iкз(3), А", min_value=1.0, value=15000.0, step=100.0)
    tp3 = st.number_input("Tр.экв для трёхфазного КЗ, с", min_value=0.001, value=0.05,
                          step=0.005, format="%.3f")
    st.caption("Например: 0.05 с = 50 мс")

    use_kz1 = st.checkbox("Добавить расчёт для однофазного КЗ (п. 4.2.4 ГОСТ)")
    i_kz1 = tp1 = None
    if use_kz1:
        i_kz1 = st.number_input("Iкз(1), А", min_value=1.0, value=12000.0, step=100.0)
        tp1 = st.number_input("Tр.экв для однофазного КЗ, с", min_value=0.001, value=0.05,
                              step=0.005, format="%.3f")

    st.subheader("Критерий проверки")
    t_req = st.number_input("Требуемое t_нас, мс (0 — не проверять)", 0.0, 500.0, 0.0, 5.0)

    st.subheader("Метод по ВАХ (опционально)")
    use_vah = st.checkbox("Использовать метод по ВАХ (п. 5.3)", value=False)
    vah_data = None
    if use_vah:
        u_star_input = st.number_input("U* — напряжение при полной погрешности ε, В",
                                       min_value=1.0, value=100.0, step=10.0)
        i0_star_input = st.number_input("I₀* — ток намагничивания при U*, А",
                                        min_value=0.001, value=1.0, step=0.1, format="%.3f")
        vah_data = {'u_star': u_star_input, 'i0_star': i0_star_input}

    st.subheader("Метод по характеристике намагничивания (опционально)")
    use_bn = st.checkbox("Использовать метод по B(H) (п. 5.4)", value=False)
    bn_data = None
    bn_params = None
    if use_bn:
        st.markdown("**Параметры магнитопровода ТТ:**")
        w2_input = st.number_input("w2 — число витков вторичной обмотки", min_value=10,
                                   value=200, step=50)
        s_input = st.number_input("s — сечение сердечника, см²", min_value=0.5,
                                  value=6.0, step=0.5)
        l_input = st.number_input("l — средняя длина силовой линии, м", min_value=0.05,
                                  value=0.6, step=0.05)
        st.markdown("**Типовая характеристика намагничивания B(H):**")
        b_sat_input = st.number_input("Bнас — индукция насыщения, Тл", min_value=1.0,
                                      max_value=2.5, value=1.8, step=0.1)
        h_knee_input = st.number_input("Hколено — напряжённость начала насыщения, А/м",
                                       min_value=10, value=100, step=10)
        bn_data = build_bn_default(b_sat_input, h_knee_input)
        bn_params = {'w2': w2_input, 's': s_input * 1e-4, 'l': l_input}

# ---------------------------------------------------------------------------
# Формирование нагрузки вторичной цепи и расчёт
# ---------------------------------------------------------------------------
rho = RHO_MATERIALS[cable_mat]
k_sch_3, k_sch_1 = SCHEME_FACTORS[scheme]
r_cable3 = rho * cable_len * k_sch_3 / cable_s
r_cable1 = rho * cable_len * k_sch_1 / cable_s
r_n3 = r_prib + r_per + r_cable3
r_n1 = r_prib + r_per + r_cable1

chain = {
    "scheme": scheme,
    "material": f"{cable_mat} (ρ = {rho} Ом·мм²/м при 20 °С)",
    "length": cable_len,
    "section": cable_s,
    "r_prib": r_prib,
    "r_per": r_per,
    "x_load": x_load,
    "k_sch_3": k_sch_3,
    "k_sch_1": k_sch_1,
}

ct3 = CTParams(i1_nom, i2_nom, k_nom, s_nom, cos_phi, r2, x2, r_n3, x_load)
kz3 = KZParams(i_kz3, tp3, "трёхфазное КЗ")

try:
    with st.spinner("Расчёт времени до насыщения…"):
        results = [(ct3, kz3, calculate(ct3, kz3, method, theta_override, k_r_value))]
        if use_vah and vah_data:
            results[0][2].update(calculate_vah(ct3, kz3, vah_data['u_star'],
                                               vah_data['i0_star'], theta_override, k_r_value))
        if use_bn and bn_data and bn_params:
            results[0][2].update(calculate_bn(ct3, kz3, bn_data, bn_params['w2'],
                                              bn_params['s'], bn_params['l'],
                                              theta_override, k_r_value))
        if use_kz1:
            ct1 = CTParams(i1_nom, i2_nom, k_nom, s_nom, cos_phi, r2, x2, r_n1, x_load)
            kz1 = KZParams(i_kz1, tp1, "однофазное КЗ")
            res1 = calculate(ct1, kz1, method, theta_override, k_r_value)
            if use_vah and vah_data:
                res1.update(calculate_vah(ct1, kz1, vah_data['u_star'],
                                          vah_data['i0_star'], theta_override, k_r_value))
            if use_bn and bn_data and bn_params:
                res1.update(calculate_bn(ct1, kz1, bn_data, bn_params['w2'],
                                         bn_params['s'], bn_params['l'],
                                         theta_override, k_r_value))
            results.append((ct1, kz1, res1))
except ValueError as e:
    st.error(f"Ошибка исходных данных: {e}")
    st.stop()

keys = METHOD_KEYS[method]


def fmt_t(res) -> str:
    if res is None:
        return "—"
    if res.status == ST_OK and res.t_nas is not None:
        return f"{res.t_nas * 1000:.2f} мс"
    if res.status == ST_NO_SAT:
        return "∞ — насыщения нет"
    if res.status == ST_STEADY:
        return "0 мс — насыщение в установившемся режиме"
    if res.status == ST_GRAPHIC_REQUIRED:
        return "неприменим (см. примечания)"
    return "—"


def build_verdict(res_list, t_req_ms, active_keys, use_method):
    """Итоговый вывод: минимум по всем режимам и сценариям (п. 4.2.4 ГОСТ)."""
    lines, t_values = [], []
    steady = any(res[k].status == ST_STEADY for _, _, res in res_list for k in ANALYTIC_KEYS
                 if res[k].k_r == 0.0)
    graphic_needed = any(res[k].status == ST_GRAPHIC_REQUIRED for _, _, res in res_list
                         for k in ANALYTIC_KEYS)
    for _, _, res in res_list:
        for k in active_keys:
            r = res.get(k)
            if r is not None and r.status == ST_OK and r.t_nas is not None:
                t_values.append(r.t_nas)

    if steady:
        return "danger", [
            "A ≤ 1: ток КЗ превышает ток предельной кратности ТТ — погрешность превышает "
            "допустимую уже в установившемся режиме. Эксплуатация недопустима.",
            "Рекомендация: выбрать ТТ с большей Kном или большим коэффициентом "
            "трансформации, либо уменьшить вторичную нагрузку."]

    if not t_values:
        return "success", ["Во всех расчётных режимах насыщение магнитопровода отсутствует."]

    t_min_ms = min(t_values) * 1000.0
    lines.append(f"Наименьшее время до насыщения по всем режимам и сценариям: {t_min_ms:.2f} мс.")
    verdict = "success"
    if t_req_ms > 0:
        if t_min_ms >= t_req_ms:
            lines.append(f"Требование выполняется: {t_min_ms:.2f} мс ≥ {t_req_ms:g} мс.")
        else:
            verdict = "danger"
            lines.append(f"Требование НЕ выполняется: {t_min_ms:.2f} мс < {t_req_ms:g} мс.")
            lines.append("Рекомендация: выбрать ТТ с большей Kном или Sном, либо уменьшить "
                         "сопротивление вторичной цепи.")

    if use_method == "analytic":
        need_warning = False
        if graphic_needed:
            need_warning = True
            lines.append("Для сценария с остаточной намагниченностью аналитический метод "
                         "неприменим (п. 5.1.5) — переключитесь на графический метод.")
        if t_min_ms < 15.0:
            need_warning = True
            lines.append("t_нас < 15 мс — согласно п. 5.1.7 аналитический метод неприменим, "
                         "переключитесь на графический метод.")
        if need_warning and verdict != "danger":
            verdict = "warning"
    return verdict, lines


verdict, verdict_lines = build_verdict(results, t_req, keys, method)


def curve_frames(t_p, alpha, theta_star, eff, t_nas_ms, t_end_ms, star_label, n=1200):
    t_ms, k_star = build_kpr_curve(t_p, alpha, theta_star if theta_star is not None else 0.0,
                                   t_end_ms, n)
    _, k_zero = build_kpr_curve(t_p, alpha, 0.0, t_end_ms, n)
    df = pd.DataFrame({
        "t_ms": np.concatenate([t_ms, t_ms]),
        "K_pr": np.concatenate([k_star, k_zero]),
        "curve": [star_label] * n + [LBL_ZERO] * n,
    })
    df_lvl = pd.DataFrame({"lvl": [float(eff)]})
    df_pt = (pd.DataFrame({"t_ms": [float(t_nas_ms)], "K_pr": [float(eff)]})
             if t_nas_ms is not None else pd.DataFrame({"t_ms": [], "K_pr": []}))
    wide = pd.DataFrame({
        star_label: k_star,
        LBL_ZERO: k_zero,
        f"Уровень A·(1−K_r) = {eff:.3f}": np.full(n, float(eff)),
    }, index=np.round(t_ms, 3))
    wide.index.name = "Время, мс"
    return df, df_lvl, df_pt, wide


def render_kpr_chart(ct_m, kz, gres, eff):
    if gres.status == ST_OK and gres.t_nas is not None:
        t_nas_ms = gres.t_nas * 1000.0
        t_end = min(max(t_nas_ms * 1.45, 20.0), 400.0)
    else:
        t_nas_ms = None
        t_end = min(max(kz.t_p * 3000.0, 40.0), 400.0)

    if gres.theta_manual and gres.theta_star is not None:
        star_label = f"θ = {math.degrees(gres.theta_star):.1f}° — задано вручную"
    else:
        star_label = LBL_STAR_AUTO

    df, df_lvl, df_pt, wide = curve_frames(kz.t_p, ct_m.alpha, gres.theta_star, eff,
                                           t_nas_ms, t_end, star_label)
    theta_txt = ("θ = 0°" if gres.theta_star is None
                 else (f"θ = {math.degrees(gres.theta_star):.1f}°"
                       + (" (вручную)" if gres.theta_manual else " (θ*)")))
    title = (f"K_п.р(t) по формуле (Г.15) · {kz.label} · {theta_txt} · "
             f"T_p = {kz.t_p * 1000:.0f} мс · cos α = {ct_m.cos_alpha:.3f}")
    try:
        import altair as alt
        base = alt.Chart(df).mark_line(strokeWidth=2).encode(
            x=alt.X("t_ms:Q", title="Время t, мс"),
            y=alt.Y("K_pr:Q", title="Коэффициент переходного режима K_п.р(t)"),
            color=alt.Color("curve:N", title="Начальная фаза"),
            tooltip=["t_ms:Q", "K_pr:Q", "curve:N"],
        )
        layers = [base,
                  alt.Chart(df_lvl).mark_rule(strokeDash=[6, 4], color="#2ca02c",
                                              strokeWidth=2).encode(y="lvl:Q")]
        if not df_pt.empty:
            layers.append(alt.Chart(df_pt).mark_rule(color="#2ca02c", strokeDash=[3, 3])
                          .encode(x="t_ms:Q"))
            layers.append(alt.Chart(df_pt).mark_point(size=170, filled=True,
                                                      color="#2ca02c", stroke="black")
                          .encode(x="t_ms:Q", y="K_pr:Q"))
        st.altair_chart(alt.layer(*layers).properties(title=title, height=400))
    except Exception as exc:
        st.warning(f"Интерактивный график недоступен ({type(exc).__name__}: {exc}) — "
                   "показан упрощённый график.")
        st.line_chart(wide)
    st.caption(f"Уровень насыщения A·(1−K_r) = {eff:.3f}; точка пересечения — время до "
               f"насыщения. {theta_txt}.")


def render_vah_chart(vah_data, r2):
    vah_plot = build_vah_default(vah_data['u_star'], vah_data['i0_star'], r2)
    df_vah = pd.DataFrame({"I0_A": vah_plot['i0'], "U_V": vah_plot['u']})
    try:
        import altair as alt
        chart = alt.Chart(df_vah).mark_line(strokeWidth=2, color="#d62728").encode(
            x=alt.X("I0_A:Q", title="Ток намагничивания I₀, А"),
            y=alt.Y("U_V:Q", title="Напряжение U, В"),
            tooltip=["I0_A:Q", "U_V:Q"],
        ).properties(title="Вольт-амперная характеристика ТТ (типовая)", height=300)
        st.altair_chart(chart)
    except Exception as exc:
        st.warning(f"График ВАХ недоступен ({type(exc).__name__}).")
        st.line_chart(df_vah.set_index("I0_A"))
    st.caption(f"Типовая ВАХ: U* = {vah_data['u_star']:.1f} В, I₀* = {vah_data['i0_star']:.3f} А.")


def render_bn_chart(bn_data):
    df_bn = pd.DataFrame({"H_A_m": bn_data['h'], "B_T": bn_data['b']})
    try:
        import altair as alt
        chart = alt.Chart(df_bn).mark_line(strokeWidth=2, color="#9467bd").encode(
            x=alt.X("H_A_m:Q", title="Напряжённость магнитного поля H, А/м"),
            y=alt.Y("B_T:Q", title="Магнитная индукция B, Тл"),
            tooltip=["H_A_m:Q", "B_T:Q"],
        ).properties(title="Характеристика намагничивания B(H) (типовая)", height=300)
        st.altair_chart(chart)
    except Exception as exc:
        st.warning(f"График B(H) недоступен ({type(exc).__name__}).")
        st.line_chart(df_bn.set_index("H_A_m"))
    st.caption(f"Типовая B(H): Bнас = {bn_data['b_sat']:.2f} Тл, "
               f"Hколено = {bn_data['h_knee']:.0f} А/м.")


def render_method_table(res, method_keys, k_r):
    rows = []
    for k in method_keys:
        r = res.get(k)
        if r is None:
            continue
        extra = ""
        if r.status == ST_OK and r.theta_star is not None:
            tag = "θ (вручную)" if r.theta_manual else "θ*"
            extra = f"   ({tag} = {math.degrees(r.theta_star):.1f}°)"
        rows.append({"Сценарий": make_scenario_title(k, k_r),
                     "Время до насыщения": fmt_t(r) + extra})
    return rows


def show_notes(res, method_keys, seen):
    for k in method_keys:
        r = res.get(k)
        if r is None:
            continue
        for note in r.notes:
            if note not in seen:
                seen.add(note)
                st.caption(f"• {note}")


tab_calc, tab_check, tab_theory, tab_about = st.tabs([
    "🧮 Результаты расчёта",
    "🧪 Самопроверка (эталонные примеры)",
    "📚 Теория и формулы (ГОСТ Р 58669-2019)",
    "ℹ️ О приложении и планы",
])

with tab_calc:
    banner = {"success": st.success, "warning": st.warning, "danger": st.error}[verdict]
    banner(" ".join(verdict_lines))
    kr_note = f"K_r = {k_r_value:g}" + (" (задано вручную)" if custom_kr else " (по умолчанию)")
    mode_note = (f"Метод: **{method_label}**, {kr_note}." if not manual_theta
                 else f"Метод: **{method_label}**, {kr_note}, θ задана вручную = {theta_deg:.1f}°.")
    st.caption(mode_note + " Итог — по сценариям выбранного метода "
               "(без остаточной намагниченности и с остаточной).")

    for ct_m, kz, res in results:
        st.subheader(f"Режим: {kz.label}")
        a_val = res[ANALYTIC_KEYS[0]].a
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Iкз", f"{kz.i_kz:g} А")
        c2.metric("Kфакт = Iкз / I1ном", f"{kz.i_kz / ct_m.i1_nom:.2f}")
        c3.metric("Rн.факт (с кабелем)", f"{ct_m.r_load_fact:.3f} Ом")
        c4.metric("Параметр A", f"{a_val:.3f}")

        st.table(render_method_table(res, ANALYTIC_KEYS + GRAPHIC_KEYS, k_r_value))

        seen = set()
        show_notes(res, ANALYTIC_KEYS + GRAPHIC_KEYS, seen)

        if method in ("graphic", "both"):
            g0 = res.get("graphic_without_residual")
            gr = res.get("graphic_with_residual")
            if g0 is not None:
                with st.expander("📈 График K_п.р(t) — без остаточной намагниченности",
                                 expanded=(method == "graphic")):
                    render_kpr_chart(ct_m, kz, g0, a_val)
            if gr is not None:
                with st.expander(f"📈 График K_п.р(t) — с остаточной намагниченностью "
                                 f"K_r = {k_r_value:g}"):
                    render_kpr_chart(ct_m, kz, gr, a_val * (1.0 - k_r_value))

        if use_vah and vah_data and VAH_KEYS[0] in res:
            st.markdown("#### Метод по ВАХ (п. 5.3)")
            st.table(render_method_table(res, VAH_KEYS, k_r_value))
            show_notes(res, VAH_KEYS, seen)
            with st.expander("📈 График ВАХ", expanded=False):
                render_vah_chart(vah_data, ct_m.r2)

        if use_bn and bn_data and bn_params and BN_KEYS[0] in res:
            st.markdown("#### Метод по характеристике намагничивания (п. 5.4)")
            b_t = calc_b_t(ct_m, kz, bn_params['w2'], bn_params['s'])
            st.caption(f"Расчётная амплитуда магнитной индукции **Bт = {b_t:.3f} Тл** "
                       f"(порог 1,8 Тл). Изменяя w2, s, l, Bнас, Hколено, вы влияете на "
                       "результат метода.")
            st.table(render_method_table(res, BN_KEYS, k_r_value))
            show_notes(res, BN_KEYS, seen)
            with st.expander("📈 Характеристика намагничивания B(H)", expanded=False):
                render_bn_chart(bn_data)

    if method == "both":
        st.markdown("#### Сравнение методов")
        cmp_rows = []
        for ct_m, kz, res in results:
            for k_a, k_g in zip(ANALYTIC_KEYS, GRAPHIC_KEYS):
                ra, rg = res[k_a], res[k_g]
                ta = ra.t_nas * 1000.0 if (ra.status == ST_OK and ra.t_nas) else None
                tg = rg.t_nas * 1000.0 if (rg.status == ST_OK and rg.t_nas) else None
                dev = f"{(ta - tg) / tg * 100.0:+.1f}%" if (ta and tg) else "—"
                sc = ("без остаточной намагниченности" if k_a == "without_residual"
                      else f"K_r = {k_r_value:g}")
                cmp_rows.append({
                    "Режим": kz.label, "Сценарий": sc,
                    "Аналитический": f"{ta:.2f} мс" if ta is not None else fmt_t(ra),
                    "Графический": f"{tg:.2f} мс" if tg is not None else fmt_t(rg),
                    "Отклонение аналитики": dev,
                })
        st.table(cmp_rows)

    with st.expander("🔍 Промежуточные величины"):
        st.markdown(
            f"- zн.ном = Sном / I2ном² = **{ct3.z_n_nom:.4f} Ом**\n"
            f"- z2Σном (формула 10) = **{ct3.z2_sigma_nom:.4f} Ом**\n"
            f"- ρ кабеля ({cable_mat}, 20 °С) = **{rho} Ом·мм²/м**; схема: **{scheme}**\n"
            f"- ω = 2π·50 = **314.16 рад/с**"
        )
        mid_rows = []
        for ct_m, kz, res in results:
            r_cable = ct_m.r_load_fact - r_prib - r_per
            mid_rows.append({
                "Режим": kz.label,
                "k схемы": f"{SCHEME_FACTORS[scheme][0]:g}" if "трёхфазное" in kz.label
                           else f"{SCHEME_FACTORS[scheme][1]:g}",
                "R кабеля, Ом": round(r_cable, 4),
                "Rн.факт, Ом": round(ct_m.r_load_fact, 4),
                "z2Σ (формула 11), Ом": round(ct_m.z2_sigma, 4),
                "cos α (формула 12)": round(ct_m.cos_alpha, 4),
            })
        st.table(mid_rows)

    st.divider()
    report_bytes = build_report(ct3, chain, results, verdict_lines, verdict, t_req, method,
                                vah_data=vah_data, bn_data=bn_data, bn_params=bn_params,
                                k_r=k_r_value)
    st.download_button("📄 Скачать отчёт (.docx)", data=report_bytes,
                       file_name=f"Otchet_TT_GOST_58669_{datetime.now():%Y%m%d_%H%M}.docx",
                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

with tab_check:
    st.markdown("Расчётное ядро автоматически сверяется с эталонами Приложения В и "
                "математическими свойствами стандарта.")

    @st.cache_data(show_spinner="Выполняется самопроверка…")
    def _cached_checks():
        return run_self_checks(), run_graphic_checks(), run_method_comparison()

    (rows_a, ok_a), (rows_g, ok_g), rows_c = _cached_checks()

    st.markdown("#### 1. Аналитический метод — эталонные примеры (Приложение В)")
    st.markdown("Ниже — исходные данные каждого эталона, чтобы проверку можно было "
                "повторить вручную.")
    for ex in REFERENCE_EXAMPLES:
        ctc = ex['ct']
        with st.expander(f"Исходные данные: {ex['id']} — {ex['name']}"):
            st.caption(f"ТТ: I1ном = {ctc['i1_nom']:g} А, I2ном = {ctc['i2_nom']:g} А, "
                       f"Kном = {ctc['k_nom']:g}, Sном = {ctc['s_nom']:g} ВА, "
                       f"cos φ = {ctc['cos_phi_nom']:g}, R2 = {ctc['r2']:g} Ом, "
                       f"X2 = {ctc['x2']:g} Ом.")
            for mode in ex['modes']:
                st.caption(f"{mode['label']}: Iкз = {mode['i_kz']:g} А, "
                           f"T_p = {mode['t_p'] * 1000:g} мс, "
                           f"Rн.факт = {mode['r_load']:g} Ом, "
                           f"эталон A = {mode['a_expected']}, "
                           f"t = {mode['t_expected_ms']} мс.")
    if ok_a:
        st.success("✅ Все эталонные примеры воспроизведены (допуски: A ±0,02; t ±0,2 мс).")
    else:
        st.error("❌ Обнаружено расхождение с эталонными примерами.")
    st.dataframe(rows_a, hide_index=True)
    st.caption("Примечание: в примере В.1.2 в стандарте опечатка (в исходных данных Kном = 20, "
               "расчёт при Kном = 18) — принято Kном = 18.")

    st.markdown("#### 2. Графический метод — проверка реализации формулы (Г.15)")
    if ok_g:
        st.success("✅ Все проверки свойств формулы (Г.15) и численного решения пройдены.")
    else:
        st.error("❌ Обнаружено расхождение в реализации графического метода.")
    st.dataframe(rows_g, hide_index=True)

    st.markdown("#### 3. Сопоставление методов на эталонных примерах (справочно)")
    st.dataframe(rows_c, hide_index=True)

with tab_theory:
    st.markdown("### Общие положения")
    st.markdown("Все методы решают уравнение переходного процесса (п. Г.6.2):\n\n"
                "`A·(1 − K_r) = K_п.р(t_нас)`,\n\n"
                "где **A** — параметр режима, **K_п.р(t)** — коэффициент переходного режима, "
                "**K_r** — коэффициент остаточной намагниченности. По умолчанию "
                f"K_r = {K_R_PRED} (класс P, п. 5.1.3); для классов 5PR/10PR или по заводским "
                "данным его можно задать вручную в панели слева (например 0,1).")

    st.markdown("### 1. Нагрузка вторичной цепи (п. 4.2.6, Приложение А)")
    st.code("Rн.факт = Rприб + Rпер + Rкаб;   Rкаб = ρ · kсх · L / S", language="text")
    st.markdown("""
| Схема соединения | Трёхфазное КЗ | Однофазное КЗ | Пояснение |
|---|---|---|---|
| Полная звезда (3 ТТ) | 1 | 2 | при симметрии ток нулевого провода = 0 |
| Неполная звезда (2 ТТ) | √3 ≈ 1,73 | √3 ≈ 1,73 | общий провод несёт ток неповреждённой фазы |
| Треугольник | 3 | 3 | токи циркулируют по трём проводам |
| Один ТТ (2 провода) | 2 | 2 | ток идёт по двум проводам |
""")

    st.markdown("### 2. Исходные величины")
    st.code("zн.ном = Sном / I2ном²\n"
            "z2Σном = √( (R2 + zн.ном·cos φном)² + (X2 + zн.ном·sin φном)² )   (10)\n"
            "z2Σ    = √( (R2 + Rн.факт)² + (X2 + Xн.факт)² )                   (11)\n"
            "A      = ( I1ном · Kном · z2Σном ) / ( Iкз · z2Σ )                  (9)\n"
            "cos α  = ( R2 + Rн.факт ) / z2Σ                                     (12)",
            language="text")

    st.markdown("### 3. Аналитический метод (раздел 5.1)")
    st.code("t_нас = T_p · ln( ω·T_p / ( ω·T_p + 1 − A·(1 − K_r) ) )          (3), (6)",
            language="text")
    st.warning("«+1» присутствует **только в знаменателе**; в числителе — только ω·T_p.")
    st.markdown("**Проверяемые условия** (справа — что происходит при нарушении):")
    st.markdown("""
| Условие | Если выполняется | Если НЕ выполняется |
|---|---|---|
| **A > 1** (усл. 5) | допустимо: предельный ток ТТ больше тока КЗ | эксплуатация недопустима: ток КЗ выше предельного |
| **ω·T_p + 1 > A** (усл. 4) | насыщение наступит при конечном t | насыщения нет, t_нас = ∞ |
| **A·(1−K_r) > 1** (усл. 8) | применима формула (6) | t было бы отрицательным → графический метод (п. 5.1.5) |
| **ω·T_p + 1 > A·(1−K_r)** (усл. 7) | насыщение наступит при конечном t | насыщения нет, t_нас = ∞ |
| **t_нас ≥ 15 мс** (п. 5.1.7) | аналитический метод точен | уточнить графическим методом |
""")

    st.markdown("### 4. Графический метод по паспортным данным (раздел 5.2)")
    st.code("K_п.р(t) = sin α·cos θ·e^(−t/T_p) + cos α·cos θ·ω·T_p·(1 − e^(−t/T_p))\n"
            "         − sin(ω·t + α + θ) + cos α·sin θ                          (Г.15)\n"
            "t_нас: K_п.р(t_нас) = A·(1 − K_r), минимум по θ ∈ (−90°, +90°)",
            language="text")

    st.markdown("### 5. Метод по ВАХ (п. 5.3)")
    st.code("A = U* / U2sin;   U2sin = I2ном · Kфакт · z2Σ                      (19)",
            language="text")
    st.markdown("Условие применимости (16): `I₀(ε)/U(ε) / (Iлин/Uлин) > 3`.")

    st.markdown("### 6. Метод по характеристике намагничивания (п. 5.4)")
    st.code("A = Bт / Bт(Hг);   Bт = U2sin / (222·w2·s);   Hг = I₀ε·w2 / l     (22)–(24)",
            language="text")
    st.markdown("Условие применимости (21): `Bт > 1,8 Тл`; иначе магнитопровод не насыщается.\n"
                "Типовая кривая B(H) — монотонная: линейный рост до точки излома, затем плавное "
                "насыщение. Для точного расчёта используйте фактическую характеристику конкретного ТТ.")

    st.markdown("### 7. Разобранный пример (В.1.1, ТТ SAS 550/5G 2000/1)")
    st.markdown("""
**Исходные данные:** I1ном = 2000 А, I2ном = 1 А, Kном = 20, Sном = 40 ВА, cos φ = 0.8,
R2 = 7.51 Ом, X2 = 0, Rн.факт = 6.3 Ом, Iкз = 23145 А, T_p = 128 мс.

**Расчёт (аналитический метод, без остаточной намагниченности):**
- zн.ном = 40 / 1² = 40 Ом
- z2Σном = √((7.51 + 40·0.8)² + (0 + 40·0.6)²) = √(39.51² + 24²) = 46.23 Ом
- z2Σ = √((7.51 + 6.3)² + 0²) = 13.81 Ом
- A = 2000·20·46.23 / (23145·13.81) = 5.785
- ω·T_p = 314.16·0.128 = 40.21
- t_нас = 0.128·ln(40.21 / (40.21 − 5.785 + 1)) = **16.22 мс**

Эталон (Приложение В, В.1.1.8): A = 5.785, t_нас = 16.22 мс. Совпадение.
""")

    st.markdown("### 8. Порядок расчёта по стандарту")
    st.markdown(
        "1. Расчёт для трёхфазного КЗ, а в сетях с глухозаземлённой нейтралью — и для "
        "однофазного; итог — **наименьшее** значение (п. 4.2.4).\n"
        f"2. Каждый расчёт — дважды: без остаточной намагниченности и с K_r = {k_r_value:g} (п. 4.3).\n"
        "3. T_р.экв — по формуле (1) или по осциллограмме (п. 4.2.7).\n"
        "4. Нагрузки вторичных цепей — по Приложению А (п. 4.2.6).")

with tab_about:
    st.markdown("""
Приложение выполняет проверку трансформаторов тока на насыщение при КЗ по
**ГОСТ Р 58669-2019**.

**История релизов:**
- **Релиз 1.9:** исправлена физика типовой характеристики намагничивания B(H) — теперь
  кривая монотонна (линейный рост до колена, затем плавное насыщение, без разрыва);
  коэффициент остаточной намагниченности K_r задаётся пользователем: по умолчанию 0,86
  (класс P, п. 5.1.3), чек-бокс позволяет ввести своё значение (например 0,1 для классов
  5PR/10PR по ГОСТ Р 70507.2-2024 и заводским данным).
- **Релиз 1.8:** устранено дублирование примечаний; убрано противоречивое «справочное»
  время при A ≤ 1; метод по B(H) всегда показывает результат с выводом Bт; θ* отображается
  на графике; самопроверка показывает исходные данные эталонов; в Теории — разобранный
  пример В.1.1 и исправленная таблица условий.
- **Релиз 1.7:** метод по характеристике намагничивания (п. 5.4), графики ВАХ и B(H) в Word,
  схема «треугольник», исправленные коэффициенты расчётной длины.
- **Релиз 1.6:** метод по ВАХ (п. 5.3).
- **Релиз 1.5:** нагрузка вторичной цепи из параметров всей цепи.
- **Релиз 1.4:** графики K_п.р в Word, ручное задание θ.
- **Релиз 1.3:** графический метод по паспортным данным, динамические графики.
- **Релиз 1.2:** модульная структура, диагностика файлов.
- **Релиз 1.1:** исправлена формула времени до насыщения, самопроверка.
- **Релиз 1.0:** аналитический метод, отчёт в Word.

**Ограничения текущего релиза:**
- ТТ классов точности P / PX / TPX с замкнутым магнитопроводом;
- одноэкспоненциальная апериодическая составляющая (T_р.экв);
- типовые ВАХ и B(H); для точного расчёта нужны фактические характеристики конкретного ТТ.
""")

# === КОНЕЦ ФАЙЛА app.py ===
