"""⚡ Проверка ТТ на насыщение при КЗ. ГОСТ Р 58669-2019. Релиз 2.0.
Добавлена вкладка «Характеристики»: ввод ВАХ и B(H) из файла (CSV/Excel),
вручную или типовая кривая."""
import math
from datetime import datetime

import streamlit as st

try:
    from methods.gost_58669 import (
        ANALYTIC_KEYS, CTParams, GRAPHIC_KEYS, K_R_PRED, KZParams,
        ST_NO_SAT, ST_OK, ST_STEADY, VAH_KEYS, BN_KEYS, build_kpr_curve,
        calculate, build_vah_default, build_bn_default,
        calculate_vah, calculate_bn, validate_bn_inputs, validate_bn_usage,
    )
    from methods.curve_io import (
        read_uploaded_curve, curve_from_dataframe, VAH_TEMPLATE, BN_TEMPLATE,
    )
    from methods.reference_examples import (
        REFERENCE_EXAMPLES, run_graphic_checks, run_method_comparison, run_self_checks,
    )
    from methods.summary import build_summary
    from report.docx_report import build_report
    _ERR = None
except Exception as e:
    _ERR = e

if _ERR is not None:
    st.set_page_config(page_title="Ошибка структуры файлов")
    st.error(f"Не загружены модули: {type(_ERR).__name__}: {_ERR}")
    st.markdown("Проверьте файлы: `methods/gost_58669.py`, `methods/summary.py`, "
                "`methods/curve_io.py`, `methods/reference_examples.py`, "
                "`report/docx_report.py`.")
    st.stop()

import numpy as np   # noqa: E402
import pandas as pd  # noqa: E402

st.set_page_config(page_title="Проверка ТТ — ГОСТ Р 58669-2019", layout="wide", page_icon="⚡")
st.title("⚡ Проверка трансформаторов тока")
st.caption("ГОСТ Р 58669-2019 · каскад: аналитический → графический → ВАХ → B(H) · релиз 2.0")

LBL_STAR = "θ = θ* — расчётный минимум (п. Г.3.7)"
LBL_ZERO = "θ = 0° — максимум апериодической составляющей"

SCHEME_FACTORS = {
    "Полная звезда (3 ТТ)": (1.0, 2.0),
    "Неполная звезда (2 ТТ)": (math.sqrt(3.0), math.sqrt(3.0)),
    "Треугольник": (3.0, 3.0),
    "Один ТТ (2 провода)": (2.0, 2.0),
}
RHO = {"Медь": 0.0175, "Алюминий": 0.0281}

PRESETS = {
    "— ввести вручную —": {},
    "ТОЛ-10 600/5 10P10 15 ВА": dict(i1_nom=600., i2_nom=5., k_nom=10., s_nom=15.,
                                     r2=.12, r_prib=.35),
    "ТФЗМ-110 2000/5 10P20 30 ВА": dict(i1_nom=2000., i2_nom=5., k_nom=20., s_nom=30.,
                                        r2=.45, r_prib=.8),
}

PRIMARY_NAMES = {
    "analytic": "аналитический (п. 5.1)",
    "graphic": "графический по паспортным данным (п. 5.2)",
    "vah": "по ВАХ (п. 5.3)",
    "bn": "по характеристике намагничивания (п. 5.4)",
}


def make_scenario_title(key, k_r):
    prefix = {
        "without_residual": "Аналитический", "with_residual": "Аналитический",
        "graphic_without_residual": "Графический (паспортные данные)",
        "graphic_with_residual": "Графический (паспортные данные)",
        "vah_without_residual": "По ВАХ", "vah_with_residual": "По ВАХ",
        "bn_without_residual": "По B(H)", "bn_with_residual": "По B(H)",
    }.get(key, key)
    suffix = ("без остаточной намагниченности (K_r = 0)" if "without" in key
              else f"с остаточной намагниченностью (K_r = {k_r:g})")
    return f"{prefix} · {suffix}"


# ---------------------------------------------------------------------------
# Боковая панель (без ВАХ и B(H) — они переехали во вкладку «Характеристики»)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Исходные данные")

    st.subheader("Начальная фаза θ")
    manual_theta = st.checkbox("Задать θ вручную", value=False)
    theta_override = None
    if manual_theta:
        theta_deg = st.number_input("θ, градусы", min_value=-90.0, max_value=90.0,
                                    value=0.0, step=1.0)
        theta_override = math.radians(theta_deg)

    st.subheader("Остаточная намагниченность")
    custom_kr = st.checkbox("Задать K_r вручную", value=False,
                            help="По умолчанию 0,86 (класс P, п. 5.1.3). Для 5PR/10PR "
                                 "и по заводским данным — например 0,1.")
    if custom_kr:
        k_r = st.number_input("K_r", min_value=0.0, max_value=1.0, value=0.86,
                              step=0.01, format="%.2f")
    else:
        k_r = K_R_PRED

    pn = st.selectbox("Тип ТТ", list(PRESETS.keys()))
    pr = PRESETS[pn]

    st.subheader("Паспорт ТТ")
    i1_nom = st.number_input("I1ном, А", min_value=1.0,
                             value=float(pr.get("i1_nom", 1000.0)), step=50.0, key=pn + "i1")
    i2_nom = st.selectbox("I2ном, А", (1., 2., 5.),
                          index=(1., 2., 5.).index(float(pr.get("i2_nom", 5.))), key=pn + "i2")
    k_nom = st.number_input("Kном", min_value=1.0, value=float(pr.get("k_nom", 10.)),
                            step=1.0, key=pn + "kn")
    s_nom = st.number_input("Sном, ВА", min_value=1.0, value=float(pr.get("s_nom", 15.)),
                            step=1.0, key=pn + "sn")
    cos_phi = st.slider("cos φном", 0.1, 1.0, 0.8, 0.05, key=pn + "cpf")
    r2 = st.number_input("R2, Ом", min_value=0.0, value=float(pr.get("r2", .15)),
                         step=0.01, format="%.3f", key=pn + "r2")
    x2 = st.number_input("X2, Ом", min_value=0.0, value=0.0,
                         step=0.01, format="%.3f", key=pn + "x2")

    st.subheader("Вторичная цепь (п. 4.2.6)")
    r_prib = st.number_input("Rприб, Ом", min_value=0.0,
                             value=float(pr.get("r_prib", .5)), step=0.01, format="%.3f",
                             key=pn + "rp")
    x_load = st.number_input("Xн, Ом", min_value=0.0, value=0.0,
                             step=0.01, format="%.3f", key=pn + "xl")
    scheme = st.selectbox("Схема соединения", list(SCHEME_FACTORS.keys()))
    mat = st.radio("Материал жилы", list(RHO.keys()), horizontal=True)
    cable_len = st.number_input("Длина кабеля, м", min_value=0.0, max_value=3000.0,
                                value=30.0, step=5.0)
    cable_s = st.number_input("Сечение жилы, мм²", min_value=0.5, max_value=300.0,
                              value=2.5, step=0.5)
    r_per = st.radio("Переходное сопротивление, Ом", (0.05, 0.1), horizontal=True,
                     format_func=lambda v: f"{v:g}")

    st.subheader("Короткое замыкание")
    i_kz3 = st.number_input("Iкз(3), А", min_value=1.0, value=15000.0, step=100.0)
    t_p3 = st.number_input("Tр(3), с", min_value=0.001, value=0.05, step=0.005,
                           format="%.3f")
    use_kz1 = st.checkbox("Расчёт для однофазного КЗ")
    i_kz1 = t_p1 = None
    if use_kz1:
        i_kz1 = st.number_input("Iкз(1), А", min_value=1.0, value=12000.0, step=100.0)
        t_p1 = st.number_input("Tр(1), с", min_value=0.001, value=0.05, step=0.005,
                               format="%.3f")
    t_req = st.number_input("Требуемое t_нас, мс (0 — не проверять)",
                            min_value=0.0, max_value=500.0, value=0.0, step=5.0)

    st.caption("ВАХ и характеристика намагничивания задаются во вкладке «📋 Характеристики».")


# ---------------------------------------------------------------------------
# Вспомогательные функции отображения
# ---------------------------------------------------------------------------
def fmt_t(r):
    if r is None:
        return "—"
    if r.status == ST_OK and r.t_nas is not None:
        return f"{r.t_nas * 1000:.2f} мс"
    if r.status == ST_NO_SAT:
        return "∞ — насыщения нет"
    if r.status == ST_STEADY:
        return "0 — насыщение в установившемся режиме"
    return "неприменим (см. примечания)"


def chart_generic(xs, ys, xlab, ylab, title, color):
    df = pd.DataFrame({"x": xs, "y": ys})
    try:
        import altair as alt
        st.altair_chart(alt.Chart(df).mark_line(strokeWidth=2, color=color).encode(
            x=alt.X("x:Q", title=xlab), y=alt.Y("y:Q", title=ylab),
            tooltip=["x:Q", "y:Q"]).properties(title=title, height=300))
    except Exception as exc:
        st.warning(f"График недоступен ({type(exc).__name__}).")
        st.line_chart(df.set_index("x"))


def chart_kpr(ct_m, kz, r, eff):
    tn = r.t_nas * 1000.0 if r.t_nas is not None else None
    t_end = min(max(tn * 1.45, 20.0) if tn else max(kz.t_p * 3000.0, 40.0), 400.0)
    th = r.theta_star if r.theta_star is not None else 0.0
    label = (f"θ = {math.degrees(th):.1f}° — вручную" if r.theta_manual else LBL_STAR)
    t_ms, k_star = build_kpr_curve(kz.t_p, ct_m.alpha, th, t_end)
    _, k_zero = build_kpr_curve(kz.t_p, ct_m.alpha, 0.0, t_end)
    df = pd.DataFrame({"t_ms": np.r_[t_ms, t_ms], "K_pr": np.r_[k_star, k_zero],
                       "curve": [label] * len(t_ms) + [LBL_ZERO] * len(t_ms)})
    d_lvl = pd.DataFrame({"lvl": [eff]})
    d_pt = (pd.DataFrame({"t_ms": [tn], "K_pr": [eff]}) if tn is not None
            else pd.DataFrame({"t_ms": [], "K_pr": []}))
    try:
        import altair as alt
        base = alt.Chart(df).mark_line(strokeWidth=2).encode(
            x=alt.X("t_ms:Q", title="Время t, мс"),
            y=alt.Y("K_pr:Q", title="K_п.р(t)"),
            color=alt.Color("curve:N", title="Начальная фаза"),
            tooltip=["t_ms:Q", "K_pr:Q", "curve:N"])
        layers = [base, alt.Chart(d_lvl).mark_rule(strokeDash=[6, 4], color="#2ca02c",
                                                   strokeWidth=2).encode(y="lvl:Q")]
        if not d_pt.empty:
            layers.append(alt.Chart(d_pt).mark_rule(color="#2ca02c", strokeDash=[3, 3])
                          .encode(x="t_ms:Q"))
            layers.append(alt.Chart(d_pt).mark_point(size=170, filled=True,
                                                     color="#2ca02c", stroke="black")
                          .encode(x="t_ms:Q", y="K_pr:Q"))
        st.altair_chart(alt.layer(*layers).properties(
            title=f"{kz.label} · {label} · T_p = {kz.t_p * 1000:.0f} мс", height=400))
    except Exception as exc:
        st.warning(f"Интерактивный график недоступен ({type(exc).__name__}).")
        st.line_chart(pd.DataFrame({label: k_star, LBL_ZERO: k_zero},
                                   index=np.round(t_ms, 3)).rename_axis("Время, мс"))
    st.caption(f"Уровень A·(1−K_r) = {eff:.3f}; {label}; t_нас = {fmt_t(r)}.")


# ---------------------------------------------------------------------------
# Вкладки. «Характеристики» выполняется ПЕРВЫМ, чтобы данные попали в расчёт.
# ---------------------------------------------------------------------------
tab_res, tab_chars, tab_check, tab_theory, tab_about = st.tabs([
    "🧮 Результаты", "📋 Характеристики", "🧪 Самопроверка",
    "📚 Теория", "ℹ️ О приложении"])

# Значения по умолчанию (переопределяются во вкладке «Характеристики»)
eps = 10.0
use_vah = False
vah_table = None
vah_curve_final = None
vah_u_star = None
vah_i0_star = None
use_bn = False
bn_data = None
bn_params = None
bn_inputs_ok = True
bn_input_msg = ""

with tab_chars:
    st.markdown("### Уточняющие характеристики ТТ")
    st.caption("Используются методами по ВАХ (п. 5.3) и по характеристике намагничивания "
               "(п. 5.4). Источники: типовая кривая, файл CSV/Excel или ручной ввод. "
               "Минимум 5 точек, от нуля до насыщения.")
    eps = st.selectbox("Полная погрешность ε, % (класс защиты)", (10.0, 5.0), 0,
                       help="Для формулы (17): I0ε = (ε/100)·I2ном·Kфакт.")

    # ---------------- ВАХ ----------------
    st.markdown("#### Вольт-амперная характеристика — ВАХ (п. 5.3)")
    use_vah = st.checkbox("Использовать метод по ВАХ", value=False, key="use_vah")
    if use_vah:
        vah_source = st.radio("Источник ВАХ",
                              ["Типовая кривая", "Файл (CSV/Excel)", "Ввод вручную"],
                              horizontal=True, key="vah_src")
        src_df = None
        if vah_source == "Типовая кривая":
            c1, c2 = st.columns(2)
            u_star = c1.number_input("U*, В", min_value=1.0, value=100.0, step=10.0,
                                     key="vah_ustar")
            i0_star = c2.number_input("I₀*, А", min_value=0.001, value=1.0, step=0.1,
                                      format="%.3f", key="vah_i0star")
            vah_curve_final = build_vah_default(u_star, i0_star, r2)
            vah_u_star, vah_i0_star = u_star, i0_star
            vah_table = vah_curve_final
        else:
            if vah_source == "Файл (CSV/Excel)":
                st.download_button("Скачать шаблон CSV", VAH_TEMPLATE.encode("utf-8"),
                                   "VAH_template.csv", "text/csv", key="vah_tpl")
                up = st.file_uploader("Файл ВАХ", type=["csv", "txt", "xlsx"], key="vah_file")
                if up is not None:
                    try:
                        src_df = read_uploaded_curve(up)
                    except Exception as e:
                        st.error(f"Не удалось прочитать файл: {e}")
            else:  # Ввод вручную
                init = pd.DataFrame({"I0, А": [0.01, 0.05, 0.10, 0.30, 0.60, 1.20],
                                     "U, В": [5.0, 24.0, 47.0, 98.0, 120.0, 132.0]})
                src_df = st.data_editor(init, num_rows="dynamic", key="vah_manual")
                st.caption("Редактируйте таблицу: строки можно добавлять/удалять. "
                           "Первая колонка — I₀ (А), вторая — U (В).")
            if src_df is not None and len(src_df):
                try:
                    ok, warns, xs, ys = curve_from_dataframe(src_df)
                    for w in warns:
                        st.warning(w)
                    if ok:
                        vah_table = {"i0": xs, "u": ys}
                        vah_curve_final = vah_table
                        vah_u_star, vah_i0_star = max(ys), max(xs)
                        st.success(f"Принято точек: {len(xs)}")
                    else:
                        st.error("Недостаточно корректных точек для ВАХ.")
                except Exception as e:
                    st.error(f"Ошибка разбора данных ВАХ: {e}")
        if vah_curve_final:
            chart_generic(vah_curve_final["i0"], vah_curve_final["u"],
                          "I₀, А", "U, В", "ВАХ ТТ", "#d62728")

    # ---------------- B(H) ----------------
    st.markdown("#### Характеристика намагничивания B(H) (п. 5.4)")
    use_bn = st.checkbox("Использовать метод по B(H)", value=False, key="use_bn")
    if use_bn:
        c1, c2, c3 = st.columns(3)
        w2 = c1.number_input("w2, витков", min_value=1, max_value=100000,
                             value=2000, step=50, key="bn_w2")
        s_cm2 = c2.number_input("s, см²", min_value=0.1, max_value=1000.0,
                                value=26.5, step=0.5, key="bn_s")
        l_mag = c3.number_input("l, м", min_value=0.01, max_value=10.0,
                                value=1.437, step=0.001, format="%.3f", key="bn_l")
        bn_source = st.radio("Источник кривой B(H)",
                             ["Типовая кривая", "Файл (CSV/Excel)", "Ввод вручную"],
                             horizontal=True, key="bn_src")
        src_df = None
        if bn_source == "Типовая кривая":
            cc1, cc2 = st.columns(2)
            b_sat = cc1.number_input("Bнас, Тл", min_value=0.5, max_value=2.5,
                                     value=1.8, step=0.1, key="bn_bsat")
            h_knee = cc2.number_input("Hколено, А/м", min_value=1.0, max_value=10000.0,
                                      value=100.0, step=10.0, key="bn_hknee")
            bn_data = build_bn_default(b_sat, h_knee)
        else:
            if bn_source == "Файл (CSV/Excel)":
                st.download_button("Скачать шаблон CSV", BN_TEMPLATE.encode("utf-8"),
                                   "BH_template.csv", "text/csv", key="bn_tpl")
                up = st.file_uploader("Файл B(H)", type=["csv", "txt", "xlsx"], key="bn_file")
                if up is not None:
                    try:
                        src_df = read_uploaded_curve(up)
                    except Exception as e:
                        st.error(f"Не удалось прочитать файл: {e}")
            else:  # Ввод вручную
                init = pd.DataFrame({"H, А/м": [10., 30., 60., 100., 200., 500.],
                                     "B, Тл": [0.18, 0.54, 1.05, 1.62, 1.76, 1.79]})
                src_df = st.data_editor(init, num_rows="dynamic", key="bn_manual")
                st.caption("Редактируйте таблицу: первая колонка — H (А/м), вторая — B (Тл).")
            if src_df is not None and len(src_df):
                try:
                    ok, warns, xs, ys = curve_from_dataframe(src_df)
                    for w in warns:
                        st.warning(w)
                    if ok:
                        bn_data = {"h": xs, "b": ys,
                                   "b_sat": max(ys), "h_knee": xs[len(xs) // 2]}
                        st.success(f"Принято точек: {len(xs)}")
                    else:
                        st.error("Недостаточно корректных точек для B(H).")
                except Exception as e:
                    st.error(f"Ошибка разбора данных B(H): {e}")
        if bn_data is not None:
            bn_params = {"w2": w2, "s": s_cm2 * 1e-4, "l": l_mag,
                         "b_sat": bn_data.get("b_sat", 1.8),
                         "h_knee": bn_data.get("h_knee", 100.0)}
            bn_inputs_ok, bn_input_msg = validate_bn_inputs(
                w2, bn_params["s"], l_mag, bn_params["b_sat"], bn_params["h_knee"])
            if not bn_inputs_ok:
                st.error("Проверка параметров: " + bn_input_msg)
            chart_generic(bn_data["h"], bn_data["b"], "H, А/м", "B, Тл",
                          "Характеристика намагничивания", "#9467bd")

# ---------------------------------------------------------------------------
# Нагрузка вторичной цепи и расчёт
# ---------------------------------------------------------------------------
rho = RHO[mat]
k_sch_3, k_sch_1 = SCHEME_FACTORS[scheme]
r_n3 = r_prib + r_per + rho * cable_len * k_sch_3 / cable_s
r_n1 = r_prib + r_per + rho * cable_len * k_sch_1 / cable_s

chain = {"scheme": scheme, "material": f"{mat} (ρ = {rho} Ом·мм²/м, 20 °С)",
         "length": cable_len, "section": cable_s, "r_prib": r_prib, "r_per": r_per,
         "x_load": x_load, "k_sch_3": k_sch_3, "k_sch_1": k_sch_1}

ct3 = CTParams(i1_nom, i2_nom, k_nom, s_nom, cos_phi, r2, x2, r_n3, x_load)
kz3 = KZParams(i_kz3, t_p3, "трёхфазное КЗ")
modes = [(ct3, kz3)]
if use_kz1:
    ct1 = CTParams(i1_nom, i2_nom, k_nom, s_nom, cos_phi, r2, x2, r_n1, x_load)
    kz1 = KZParams(i_kz1, t_p1, "однофазное КЗ")
    modes.append((ct1, kz1))

vah_active = bool(use_vah and vah_table is not None)
bn_active = bool(use_bn and bn_data is not None and bn_inputs_ok)

try:
    with st.spinner("Каскадный расчёт методов…"):
        results = []
        for ct_m, kz in modes:
            res = calculate(ct_m, kz, "both", theta_override, k_r)
            if vah_active:
                res.update(calculate_vah(ct_m, kz, vah_u_star or 1.0, vah_i0_star or 1.0,
                                         theta_override, k_r, eps, vah_table=vah_table))
            if bn_active:
                res.update(calculate_bn(ct_m, kz, bn_data, bn_params["w2"], bn_params["s"],
                                        bn_params["l"], theta_override, k_r, eps))
            results.append((ct_m, kz, res))
except ValueError as e:
    st.error(f"Ошибка исходных данных: {e}")
    st.stop()

summary_rows, verdict, summary_lines, primary = build_summary(
    results, vah_active, bn_active, t_req)

# ---------------------------------------------------------------------------
# Вкладка «Результаты»
# ---------------------------------------------------------------------------
with tab_res:
    {"success": st.success, "warning": st.warning, "danger": st.error}[verdict](
        " ".join(summary_lines))
    st.markdown("#### Сводка по всем методам (каскад: от грубого к точному)")
    st.table(summary_rows)
    st.caption("Итог вынесен по определяющему методу: **"
               + PRIMARY_NAMES.get(primary, "нет применимого метода") + "**.")

    for ct_m, kz, res in results:
        st.subheader(f"Режим: {kz.label}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Iкз", f"{kz.i_kz:g} А")
        c2.metric("Kфакт", f"{kz.i_kz / ct_m.i1_nom:.2f}")
        c3.metric("Rн.факт", f"{ct_m.r_load_fact:.3f} Ом")
        c4.metric("A (формула 9)", f"{res[ANALYTIC_KEYS[0]].a:.3f}")

        seen = set()
        for keys, _ in ((ANALYTIC_KEYS, "Аналитический"), (GRAPHIC_KEYS, "Графический"),
                        (VAH_KEYS, "По ВАХ"), (BN_KEYS, "По B(H)")):
            present = [k for k in keys if k in res]
            if not present:
                continue
            rows = []
            for k in present:
                r = res[k]
                extra = (f"   (θ = {math.degrees(r.theta_star):.1f}°)"
                         if r.theta_star is not None else "")
                rows.append({"Сценарий": make_scenario_title(k, k_r),
                             "A": round(r.a, 4), "t_нас": fmt_t(r) + extra})
            st.table(rows)
            for k in present:
                for note in res[k].notes:
                    if note not in seen:
                        seen.add(note)
                        st.caption("• " + note)

        for k in GRAPHIC_KEYS:
            r = res.get(k)
            if r is None or r.status != ST_OK:
                continue
            with st.expander("📈 K_п.р(t) — " + ("без" if "without" in k else "с")
                             + " остаточной намагниченности", expanded=True):
                chart_kpr(ct_m, kz, r, r.a * (1 - r.k_r))

        if VAH_KEYS[0] in res and vah_curve_final:
            with st.expander("📈 ВАХ (использованная в расчёте)"):
                chart_generic(vah_curve_final["i0"], vah_curve_final["u"],
                              "I₀, А", "U, В", "ВАХ ТТ", "#d62728")

        if BN_KEYS[0] in res and bn_data:
            with st.expander("📈 Характеристика намагничивания (использованная в расчёте)"):
                chart_generic(bn_data["h"], bn_data["b"], "H, А/м", "B, Тл",
                              "B(H) ТТ", "#9467bd")
                _, _, det, _ = validate_bn_usage(ct_m, kz, bn_data, bn_params["w2"],
                                                 bn_params["s"], bn_params["l"], eps)
                st.caption(det + ". Условие (21): B_me(H_e) ≥ 1,8 Тл.")

    st.divider()
    report_bytes = build_report(ct3, chain, results, summary_lines, verdict, t_req, "both",
                                vah_curve=(vah_curve_final if vah_active else None),
                                bn_data=(bn_data if bn_active else None),
                                bn_params=bn_params, k_r=k_r, eps=eps)
    st.download_button("📄 Скачать отчёт (.docx)", report_bytes,
                       f"Otchet_TT_{datetime.now():%Y%m%d_%H%M}.docx",
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

# ---------------------------------------------------------------------------
# Вкладка «Самопроверка»
# ---------------------------------------------------------------------------
with tab_check:
    @st.cache_data(show_spinner="Самопроверка…")
    def checks():
        return run_self_checks(), run_graphic_checks(), run_method_comparison()
    (ra, oka), (rg, okg), rc = checks()
    st.markdown("#### Исходные данные эталонов (Приложение В)")
    for ex in REFERENCE_EXAMPLES:
        cc = ex['ct']
        with st.expander(f"{ex['id']} — {ex['name']}"):
            st.caption(f"I1ном={cc['i1_nom']:g} А, I2ном={cc['i2_nom']:g} А, "
                       f"Kном={cc['k_nom']:g}, Sном={cc['s_nom']:g} ВА, "
                       f"cos φ={cc['cos_phi_nom']:g}, R2={cc['r2']:g} Ом.")
            for m in ex['modes']:
                st.caption(f"{m['label']}: Iкз={m['i_kz']:g} А, T_p={m['t_p']*1000:g} мс, "
                           f"Rн={m['r_load']:g} Ом; эталон A={m['a_expected']}, "
                           f"t={m['t_expected_ms']} мс.")
    if oka:
        st.success("✅ Все эталоны Приложения В воспроизведены")
    else:
        st.error("❌ Расхождение с эталонами")
    st.dataframe(ra, hide_index=True)
    if okg:
        st.success("✅ Свойства формулы (Г.15) подтверждены")
    else:
        st.error("❌ Расхождение в графическом методе")
    st.dataframe(rg, hide_index=True)
    st.markdown("#### Сопоставление методов (справочно)")
    st.dataframe(rc, hide_index=True)

# ---------------------------------------------------------------------------
# Вкладка «Теория»
# ---------------------------------------------------------------------------
with tab_theory:
    st.markdown("### 1. Каскад методов и определяющий метод")
    st.markdown("Порядок: **аналитический (5.1) → графический по паспортным данным (5.2) → "
                "по ВАХ (5.3) → по характеристике намагничивания (5.4)**. Каждый следующий "
                "уточняет результат при наличии данных. Итог — по самому точному из доступных.")
    st.markdown("### 2. Характеристики: откуда брать данные")
    st.markdown("**ВАХ** — из паспорта/заводской документации ТТ либо измерением при проверке "
                "(ГОСТ Р 70507.2-2024, п. 6.7.5 и 9.17; РД 153-34.0-35.301-2002). "
                "Контрольные точки — 10, 20, 80, 100, 200 % тока точки перегиба.\n\n"
                "**B(H)** — w2, s, l из конструктивных данных паспорта (пример В.4.1.1: "
                "«w2 = 1997 витков, s = 13,125 см², l = 1,437 м»); сама кривая — заводские "
                "данные или измерения (РД 153-34.0-35.301-2002, п. 1.4).\n\n"
                "Формат файла: две числовые колонки. Для ВАХ — I₀ (А) и U (В); "
                "для B(H) — H (А/м) и B (Тл). Разделитель `;` или `,`, десятичная точка "
                "или запятая — распознаются автоматически. Шаблоны CSV — во вкладке "
                "«Характеристики». Минимум 5 точек.")
    st.markdown("### 3. Условия применимости")
    st.markdown("""
| Условие | Если выполняется | Если НЕ выполняется |
|---|---|---|
| A > 1 (усл. 5) | предельный ток ТТ больше тока КЗ | эксплуатация недопустима |
| ωT_p+1 > A (усл. 4) | насыщение при конечном t | насыщения нет |
| A(1−K_r) > 1 (усл. 8) | применима формула (6) | графический метод (п. 5.1.5) |
| ωT_p+1 > A(1−K_r) (усл. 7) | насыщение при конечном t | насыщения нет |
| t_нас ≥ 15 мс (п. 5.1.7) | аналитика точна | уточнить графически |
| (I0ε/Uε)/(Iлин/Uлин) > 3 (усл. 16) | ВАХ-метод применим | ВАХ-метод неприменим |
| B_me(H_e) ≥ 1,8 Тл (усл. 21) | B(H)-метод применим | B(H)-метод неприменим |
""")
    st.markdown("### 4. Формулы")
    st.code("t_нас = T_p·ln( ω·T_p / (ω·T_p + 1 − A·(1−K_r)) )        (3), (6)\n\n"
            "ВАХ:   Kфакт = Iкз/I1ном                              (18)\n"
            "       I0ε = (ε/100)·I2ном·Kфакт                        (17)\n"
            "       U2sin = Kфакт·I2ном·z2Σ                          (20)\n"
            "       A = Uε / U2sin                                   (19)\n\n"
            "B(H):  H_e = I0ε·w2 / l                                 (22)\n"
            "       B_m = U2sin / (222·w2·s)                         (24)\n"
            "       A = B_me / B_m                                   (23)", language="text")
    st.warning("В формуле времени «+1» — только в знаменателе. В формуле (23) порог 1,8 Тл "
               "относится к B_me с кривой намагничивания, а не к рабочей B_m.")
    st.markdown("### 5. Разобранный пример В.1.1")
    st.markdown("I1ном=2000, I2ном=1, Kном=20, Sном=40, cos φ=0,8, R2=7,51, Rн=6,3, "
                "Iкз=23145, T_p=0,128. z2Σном=46,23 Ом; z2Σ=13,81 Ом; A=5,785; ωT_p=40,21; "
                "t_нас=0,128·ln(40,21/35,43)=**16,22 мс** — совпадает с ГОСТ.")

# ---------------------------------------------------------------------------
# Вкладка «О приложении»
# ---------------------------------------------------------------------------
with tab_about:
    st.markdown("""
**Релиз 2.0:** вкладка «Характеристики» — ввод ВАХ и B(H) из файла (CSV/Excel),
вручную (редактируемая таблица) или типовая кривая; шаблоны CSV; контроль количества
и корректности точек; превью загруженной кривой; реальные таблицы передаются в расчёт
и в Word-отчёт. Сайдбар разгружен.

**Ранее:** 1.10 — каскад методов с итоговым выводом (summary.py), исправлены формулы (16)–(24);
1.9 — монотонная B(H), ручной K_r; 1.8 — прозрачная самопроверка; 1.7 — метод B(H);
1.6 — метод ВАХ; 1.5 — кабель; 1.4 — графики в Word, ручной θ; 1.3 — графический метод;
1.2 — модули; 1.1 — корректная формула t_нас.

**Ограничения:** классы P/PX/TPX; одна экспонента T_р.экв; для точного расчёта нужны
фактические характеристики конкретного ТТ.
""")

# === КОНЕЦ ФАЙЛА app.py ===
