"""⚡ Проверка ТТ на насыщение при КЗ. ГОСТ Р 58669-2019 и ГОСТ Р 71879-2024.
Релиз 2.3: графический метод 71879 по формулам (12)–(14) в режиме предпросмотра."""
import math
from datetime import datetime

import streamlit as st

try:
    from methods.gost_58669 import (
        ANALYTIC_KEYS, CTParams, GRAPHIC_KEYS, K_R_PRED, K_R_PR_DEFAULT, KZParams,
        OMEGA, ST_NO_SAT, ST_OK, ST_STEADY, VAH_KEYS, BN_KEYS, SECOND_KZ_KEYS,
        GRAPHIC71_KEYS, SECOND_GRAPHIC71_KEYS, build_kpr_curve, build_kpr1_curve_71879,
        calculate, build_vah_default, build_bn_default, calculate_vah, calculate_bn,
        calculate_second_kz_71879, calculate_graphic_71879,
        calculate_second_graphic_71879, validate_bn_inputs, validate_bn_usage,
        effective_ct_kz, ts_fact_71879,
    )
    from methods.curve_io import (
        read_uploaded_curve, curve_from_dataframe, VAH_TEMPLATE, BN_TEMPLATE,
    )
    from methods.reference_examples import (
        REFERENCE_EXAMPLES, run_graphic_checks, run_graphic_checks_71879,
        run_method_comparison, run_self_checks, run_self_checks_71879,
    )
    from methods.summary import build_summary
    from report.docx_report import build_report
    _ERR = None
except Exception as e:
    _ERR = e

if _ERR is not None:
    st.set_page_config(page_title="Ошибка структуры файлов")
    st.error(f"Не загружены модули: {type(_ERR).__name__}: {_ERR}")
    st.markdown("Проверьте файлы: `methods/gost_58669.py` (`GRAPHIC71_KEYS`), "
                "`methods/reference_examples.py` (`def run_graphic_checks_71879(`), "
                "`methods/curve_io.py`, `methods/summary.py`, `report/docx_report.py`.")
    st.stop()

import numpy as np   # noqa: E402
import pandas as pd  # noqa: E402

st.set_page_config(page_title="Проверка ТТ — ГОСТ Р 58669/71879", layout="wide", page_icon="⚡")
st.title("⚡ Проверка трансформаторов тока")
st.caption("ГОСТ Р 58669-2019 · ГОСТ Р 71879-2024 · каскад методов · релиз 2.3")

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
STANDARD_OPTIONS = ["ГОСТ Р 58669-2019 — классы P, PX, TPX",
                    "ГОСТ Р 71879-2024 — классы 5PR, 10PR, TPY, TPZ, TPE"]
PR_CLASSES = ["5PR", "10PR", "TPY", "TPZ", "TPE"]


def make_scenario_title(key, k_r):
    prefix = {
        "without_residual": "Аналитический", "with_residual": "Аналитический",
        "graphic_without_residual": "Графический (паспортные данные)",
        "graphic_with_residual": "Графический (паспортные данные)",
        "vah_without_residual": "По ВАХ", "vah_with_residual": "По ВАХ",
        "bn_without_residual": "По B(H)", "bn_with_residual": "По B(H)",
        "second_without_residual": "Второе КЗ (АПВ), аналитический",
        "second_with_residual": "Второе КЗ (АПВ), аналитический",
        "graphic71_without_residual": "Графический 71879, предпросмотр",
        "graphic71_with_residual": "Графический 71879, предпросмотр",
        "second_graphic71_without_residual": "Второе КЗ 71879, предпросмотр",
        "second_graphic71_with_residual": "Второе КЗ 71879, предпросмотр",
    }.get(key, key)
    suffix = ("без остаточной намагниченности (K_r = 0)" if "without" in key
              else f"с остаточной намагниченностью (K_r = {k_r:g})")
    return f"{prefix} · {suffix}"


# ---------------------------------------------------------------------------
# Боковая панель
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Исходные данные")

    st.subheader("Стандарт и класс ТТ")
    standard_name = st.radio("Стандарт", STANDARD_OPTIONS, key="std")
    is_71879 = standard_name.startswith("ГОСТ Р 71879")
    std_code = "71879" if is_71879 else "58669"
    ct_class = None
    l2 = ts_nom = kp_r_nom = 0.0
    use_second_kz = False
    t_kz1 = t_bp = None
    if is_71879:
        ct_class = st.selectbox("Класс точности", PR_CLASSES)
        l2 = st.number_input("L2 — индуктивность рассеяния, Гн", min_value=0.0,
                             max_value=1.0, value=0.00182, step=0.00001, format="%.6f",
                             help="Из паспорта/заводских данных. В примере Б.1: 0,00182 Гн.")
        ts_nom = st.number_input("Ts.ном — постоянная времени контура, с",
                                 min_value=0.01, max_value=10.0, value=0.507,
                                 step=0.001, format="%.3f",
                                 help="В примере Б.1: 0,507 с.")
        kp_r_nom = st.number_input(
            "Kп.р.ном — коэфф. переходного режима", min_value=1.0, max_value=100.0,
            value=1.0 if ct_class in ("5PR", "10PR") else 10.0, step=1.0,
            help="Для 5PR/10PR = 1; для TPY/TPZ/TPE — по паспорту.")
        use_second_kz = st.checkbox("Второе КЗ — неуспешное АПВ (п. 5.1.6)", value=False,
                                    help="Если АПВ нет — не включайте.")
        if use_second_kz:
            t_kz1 = st.number_input("t_кз1 — время отключения 1-го КЗ, с",
                                    min_value=0.0, max_value=5.0, value=0.1, step=0.01,
                                    format="%.3f", help="В примере Б.1: 0,1 с.")
            t_bp = st.number_input("t_б.п — бестоковая пауза АПВ, с",
                                   min_value=0.0, max_value=5.0, value=1.0, step=0.05,
                                   format="%.3f",
                                   help="t2 = t_кз1 + t_б.п. В примере Б.1: 1,0 с.")

    st.subheader("Начальная фаза")
    manual_theta = st.checkbox("Задать угол вручную", value=False)
    theta_override = None
    if manual_theta:
        if is_71879:
            theta_deg = st.number_input("φкз, градусы (для 71879)",
                                        min_value=0.0, max_value=90.0, value=0.0, step=1.0,
                                        help="Фаза периодической составляющей. θ находится "
                                             "из неё по формуле (14).")
        else:
            theta_deg = st.number_input("θ, градусы (для 58669)",
                                        min_value=-90.0, max_value=90.0, value=0.0, step=1.0)
        theta_override = math.radians(theta_deg)

    st.subheader("Остаточная намагниченность")
    k_r_default = K_R_PR_DEFAULT if is_71879 else K_R_PRED
    custom_kr = st.checkbox("Задать K_r вручную", value=False,
                            help=f"По умолчанию: {K_R_PRED} для 58669 (класс P); "
                                 f"{K_R_PR_DEFAULT} для 5PR/10PR/TPY/TPZ без паспорта.")
    if custom_kr:
        k_r = st.number_input("K_r", min_value=0.0, max_value=1.0,
                              value=k_r_default, step=0.01, format="%.3f")
    else:
        k_r = k_r_default

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
    t_p3 = st.number_input("Tр(3) = Tа.экв, с", min_value=0.001, value=0.05,
                           step=0.005, format="%.3f")
    use_kz1 = st.checkbox("Расчёт для однофазного КЗ")
    i_kz1 = t_p1 = None
    if use_kz1:
        i_kz1 = st.number_input("Iкз(1), А", min_value=1.0, value=12000.0, step=100.0)
        t_p1 = st.number_input("Tр(1) = Tа.экв, с", min_value=0.001, value=0.05,
                               step=0.005, format="%.3f")
    t_req = st.number_input("Требуемое t_нас, мс (0 — не проверять)",
                            min_value=0.0, max_value=500.0, value=0.0, step=5.0)

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


def _kpr_layers(df, d_lvl, d_pt, title):
    import altair as alt
    base = alt.Chart(df).mark_line(strokeWidth=2).encode(
        x=alt.X("t_ms:Q", title="Время t, мс"),
        y=alt.Y("K_pr:Q", title="K_п.р(t)"),
        color=alt.Color("curve:N", title="Кривая"),
        tooltip=["t_ms:Q", "K_pr:Q", "curve:N"])
    layers = [base, alt.Chart(d_lvl).mark_rule(strokeDash=[6, 4], color="#2ca02c",
                                               strokeWidth=2).encode(y="lvl:Q")]
    if not d_pt.empty:
        layers.append(alt.Chart(d_pt).mark_rule(color="#2ca02c", strokeDash=[3, 3])
                      .encode(x="t_ms:Q"))
        layers.append(alt.Chart(d_pt).mark_point(size=170, filled=True,
                                                 color="#2ca02c", stroke="black")
                      .encode(x="t_ms:Q", y="K_pr:Q"))
    return alt.layer(*layers).properties(title=title, height=400)


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
        st.altair_chart(_kpr_layers(df, d_lvl, d_pt,
                                    f"{kz.label} · {label} · T_p = {kz.t_p * 1000:.0f} мс"))
    except Exception as exc:
        st.warning(f"Интерактивный график недоступен ({type(exc).__name__}).")
        st.line_chart(pd.DataFrame({label: k_star, LBL_ZERO: k_zero},
                                   index=np.round(t_ms, 3)).rename_axis("Время, мс"))
    st.caption(f"Уровень A·(1−K_r) = {eff:.3f}; t_нас = {fmt_t(r)}.")


def chart_kpr_71879(ct_m, kz, r, eff):
    """График K'_п.р(t) по формуле (12) ГОСТ Р 71879-2024."""
    tn = r.t_nas * 1000.0 if r.t_nas is not None else None
    t_end = min(max(tn * 1.45, 20.0) if tn else max(kz.t_p * 3000.0, 40.0), 400.0)
    th = r.theta_star if r.theta_star is not None else 0.0
    ts = ts_fact_71879(ct_m)
    t_ms, k_star = build_kpr1_curve_71879(kz.t_p, ts, th, t_end)
    label = f"K'_п.р(t), формула (12), θ = {math.degrees(th):.1f}°"
    df = pd.DataFrame({"t_ms": t_ms, "K_pr": k_star, "curve": [label] * len(t_ms)})
    d_lvl = pd.DataFrame({"lvl": [eff]})
    d_pt = (pd.DataFrame({"t_ms": [tn], "K_pr": [eff]}) if tn is not None
            else pd.DataFrame({"t_ms": [], "K_pr": []}))
    try:
        st.altair_chart(_kpr_layers(df, d_lvl, d_pt,
                                    f"{kz.label} · формула (12) · Tа = {kz.t_p * 1000:.0f} мс,"
                                    f" Ts = {ts * 1000:.0f} мс"))
    except Exception as exc:
        st.warning(f"Интерактивный график недоступен ({type(exc).__name__}).")
        st.line_chart(pd.DataFrame({label: k_star},
                                   index=np.round(t_ms, 3)).rename_axis("Время, мс"))
    st.caption(f"Уровень A·(1−K_r) = {eff:.3f}; t′нас = {fmt_t(r)} (предпросмотр, "
               "сверка с Б.2 не выполнена).")


# ---------------------------------------------------------------------------
# Вкладки; «Характеристики» выполняется первой — её данные нужны расчёту
# ---------------------------------------------------------------------------
tab_res, tab_chars, tab_check, tab_theory, tab_about = st.tabs([
    "🧮 Результаты", "📋 Характеристики", "🧪 Самопроверка",
    "📚 Теория", "ℹ️ О приложении"])

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
    st.caption("ВАХ (п. 5.3) и характеристика намагничивания (п. 5.4). Источники: "
               "типовая кривая, файл CSV/Excel или ручной ввод.")
    eps_idx = 1 if (is_71879 and ct_class == "5PR") else 0
    eps = st.selectbox("Полная погрешность ε, % (класс защиты)", (10.0, 5.0), eps_idx,
                       help="10 % для 10P/10PR; 5 % для 5P/5PR. Формула (17).")

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
            else:
                init = pd.DataFrame({"I0, А": [0.01, 0.05, 0.10, 0.30, 0.60, 1.20],
                                     "U, В": [5.0, 24.0, 47.0, 98.0, 120.0, 132.0]})
                src_df = st.data_editor(init, num_rows="dynamic", key="vah_manual")
                st.caption("Первая колонка — I₀ (А), вторая — U (В).")
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
            else:
                init = pd.DataFrame({"H, А/м": [10., 30., 60., 100., 200., 500.],
                                     "B, Тл": [0.18, 0.54, 1.05, 1.62, 1.76, 1.79]})
                src_df = st.data_editor(init, num_rows="dynamic", key="bn_manual")
                st.caption("Первая колонка — H (А/м), вторая — B (Тл).")
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
         "x_load": x_load, "k_sch_3": k_sch_3, "k_sch_1": k_sch_1,
         "standard": standard_name}
if is_71879:
    chain.update({"ct_class": ct_class, "l2": l2, "ts_nom": ts_nom,
                  "kp_r_nom": kp_r_nom, "use_second_kz": use_second_kz,
                  "t_kz1": t_kz1, "t_bp": t_bp})

ct3 = CTParams(i1_nom, i2_nom, k_nom, s_nom, cos_phi, r2, x2, r_n3, x_load,
               l2=l2, ts_nom=ts_nom, kp_r_nom=kp_r_nom)
kz3 = KZParams(i_kz3, t_p3, "трёхфазное КЗ")
modes = [(ct3, kz3)]
if use_kz1:
    ct1 = CTParams(i1_nom, i2_nom, k_nom, s_nom, cos_phi, r2, x2, r_n1, x_load,
                   l2=l2, ts_nom=ts_nom, kp_r_nom=kp_r_nom)
    kz1 = KZParams(i_kz1, t_p1, "однофазное КЗ")
    modes.append((ct1, kz1))

vah_active = bool(use_vah and vah_table is not None)
bn_active = bool(use_bn and bn_data is not None and bn_inputs_ok)
second_active = bool(use_second_kz and is_71879 and t_bp is not None)
t2 = (t_kz1 + t_bp) if (second_active and t_kz1 is not None) else None

try:
    with st.spinner("Каскадный расчёт методов…"):
        results = []
        for ct_m, kz in modes:
            res = calculate(ct_m, kz, "both", theta_override, k_r, standard=std_code)
            ct_eff, kz_eff, _, _ = effective_ct_kz(ct_m, kz, std_code)
            if vah_active:
                res.update(calculate_vah(ct_eff, kz_eff, vah_u_star or 1.0,
                                         vah_i0_star or 1.0, theta_override, k_r, eps,
                                         vah_table=vah_table))
            if bn_active:
                res.update(calculate_bn(ct_eff, kz_eff, bn_data, bn_params["w2"],
                                        bn_params["s"], bn_params["l"],
                                        theta_override, k_r, eps))
            if second_active:
                res.update(calculate_second_kz_71879(ct_m, kz, k_r, t_bp))
            if is_71879 and method in ("graphic", "both"):
                res.update(calculate_graphic_71879(ct_m, kz, k_r, theta_override))
                if second_active:
                    res.update(calculate_second_graphic_71879(ct_m, kz, k_r,
                                                              t_kz1, t_bp, theta_override))
            results.append((ct_m, kz, res))
except ValueError as e:
    st.error(f"Ошибка исходных данных: {e}")
    st.stop()

summary_rows, verdict, summary_lines, primary = build_summary(
    results, vah_active, bn_active, t_req)

# Учёт второго КЗ в итоговой оценке
second_kz_min_ms = None
if second_active:
    t2_vals = []
    for ct_m, kz, res in results:
        for key in SECOND_KZ_KEYS:
            r = res.get(key)
            if r is not None and r.status == ST_OK and r.t_nas is not None:
                t2_vals.append(r.t_nas * 1000.0)
    if t2_vals:
        second_kz_min_ms = min(t2_vals)
        t2_note = (f" (t2 = {t2:.2f} с)" if t2 is not None else "")
        if t_req > 0 and second_kz_min_ms < t_req:
            verdict = "danger"
            summary_lines.append(f"Второе КЗ (АПВ){t2_note}: наименьшее t″нас = "
                                 f"{second_kz_min_ms:.2f} мс < требуемого {t_req:g} мс — "
                                 "условие НЕ выполняется.")
        else:
            summary_lines.append(f"Второе КЗ (АПВ){t2_note}: наименьшее t″нас = "
                                 f"{second_kz_min_ms:.2f} мс.")

# ---------------------------------------------------------------------------
# Вкладка «Результаты»
# ---------------------------------------------------------------------------
with tab_res:
    {"success": st.success, "warning": st.warning, "danger": st.error}[verdict](
        " ".join(summary_lines))
    st.markdown("#### Сводка по всем методам (каскад: от грубого к точному)")
    st.table(summary_rows)
    st.caption("Стандарт: **" + standard_name + "** · K_r = " + f"{k_r:g}"
               + (" (вручную)" if custom_kr else " (по умолчанию)")
               + " · Итог по методу: **" + PRIMARY_NAMES.get(primary, "—") + "**.")
    if is_71879 and method in ("graphic", "both"):
        st.warning("Строки «предпросмотр» — формулы (12)–(14) ГОСТ Р 71879-2024: "
                   "численная сверка с примером Б.2 ещё не выполнена, в определяющий "
                   "вердикт они не входят.")

    for ct_m, kz, res in results:
        st.subheader(f"Режим: {kz.label}")
        ct_eff, kz_eff, ts_val, t_eff = effective_ct_kz(ct_m, kz, std_code)
        a_val = res[ANALYTIC_KEYS[0]].a
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Iкз", f"{kz.i_kz:g} А")
        c2.metric("Kфакт", f"{kz.i_kz / ct_m.i1_nom:.2f}")
        c3.metric("Rн.факт", f"{ct_m.r_load_fact:.3f} Ом")
        c4.metric("A", f"{a_val:.3f}")
        if is_71879 and ts_val is not None:
            st.caption(f"T_s = {ts_val * 1000:.0f} мс · T = min(T_а.экв, T_s) = "
                       f"{t_eff * 1000:.0f} мс · ω·L2 = {OMEGA * l2:.3f} Ом")

        seen = set()
        for keys, _ in ((ANALYTIC_KEYS, "Аналитический"), (GRAPHIC_KEYS, "Графический"),
                        (VAH_KEYS, "По ВАХ"), (BN_KEYS, "По B(H)"),
                        (SECOND_KZ_KEYS, "Второе КЗ (АПВ)"),
                        (GRAPHIC71_KEYS, "Графический 71879 (предпросмотр)"),
                        (SECOND_GRAPHIC71_KEYS, "Второе КЗ 71879 (предпросмотр)")):
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
                chart_kpr(ct_eff, kz_eff, r, r.a * (1 - r.k_r))

        for k in GRAPHIC71_KEYS:
            r = res.get(k)
            if r is None or r.status != ST_OK:
                continue
            with st.expander("📈 K'_п.р(t) по формуле (12) — предпросмотр, "
                             + ("без" if "without" in k else "с") + " остаточной"):
                chart_kpr_71879(ct_m, kz, r, r.a * (1 - r.k_r))

        if VAH_KEYS[0] in res and vah_curve_final:
            with st.expander("📈 ВАХ (использованная в расчёте)"):
                chart_generic(vah_curve_final["i0"], vah_curve_final["u"],
                              "I₀, А", "U, В", "ВАХ ТТ", "#d62728")

        if BN_KEYS[0] in res and bn_data:
            with st.expander("📈 Характеристика намагничивания (использованная в расчёте)"):
                chart_generic(bn_data["h"], bn_data["b"], "H, А/м", "B, Тл",
                              "B(H) ТТ", "#9467bd")
                _, _, det, _ = validate_bn_usage(ct_eff, kz_eff, bn_data, bn_params["w2"],
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
        return (run_self_checks(), run_self_checks_71879(), run_graphic_checks(),
                run_graphic_checks_71879(), run_method_comparison())
    (ra, oka), (r71, ok71), (rg, okg), (rg71, okg71), rc = checks()

    st.markdown("#### ГОСТ Р 58669-2019 — Приложение В (В.1.1–В.1.3)")
    for ex in REFERENCE_EXAMPLES:
        cc = ex['ct']
        with st.expander(f"{ex['id']} — {ex['name']}: исходные данные"):
            st.caption(f"I1ном={cc['i1_nom']:g} А, I2ном={cc['i2_nom']:g} А, "
                       f"Kном={cc['k_nom']:g}, Sном={cc['s_nom']:g} ВА, "
                       f"cos φ={cc['cos_phi_nom']:g}, R2={cc['r2']:g} Ом.")
            for m in ex['modes']:
                st.caption(f"{m['label']}: Iкз={m['i_kz']:g} А, T_p={m['t_p']*1000:g} мс, "
                           f"Rн={m['r_load']:g} Ом; эталон A={m['a_expected']}, "
                           f"t={m['t_expected_ms']} мс.")
    if oka:
        st.success("✅ Эталонные примеры 58669 воспроизведены")
    else:
        st.error("❌ Расхождение с эталонами 58669")
    st.dataframe(ra, hide_index=True)

    st.markdown("#### ГОСТ Р 71879-2024 — Приложение Б (пример Б.1: первое и второе КЗ)")
    st.caption("Эталоны времени первого КЗ — по формуле (6) с K_r = 0,085; второго — по (9).")
    if ok71:
        st.success("✅ Пример Б.1 воспроизведён (A, Ts, t′ и t″ — по обоим видам КЗ)")
    else:
        st.error("❌ Расхождение с примером Б.1")
    st.dataframe(r71, hide_index=True)

    st.markdown("#### Свойства формулы (Г.15) — графический метод 58669")
    if okg:
        st.success("✅ Все проверки пройдены")
    else:
        st.error("❌ Расхождение в графическом методе 58669")
    st.dataframe(rg, hide_index=True)

    st.markdown("#### Структурные проверки формул (12)–(14) — графический метод 71879")
    st.caption("Числовая сверка с примером Б.2 будет добавлена после получения скана "
               "Б.2.1–Б.2.4; до тех пор метод работает в режиме предпросмотра.")
    if okg71:
        st.success("✅ Структурные свойства формул (12)–(14) подтверждены")
    else:
        st.error("❌ Расхождение в структурных проверках (12)–(14)")
    st.dataframe(rg71, hide_index=True)

    st.markdown("#### Сопоставление методов (справочно)")
    st.dataframe(rc, hide_index=True)

# ---------------------------------------------------------------------------
# Вкладка «Теория»
# ---------------------------------------------------------------------------
with tab_theory:
    st.markdown("### 1. Каскад методов")
    st.markdown("Аналитический (5.1) → графический по паспортным данным (5.2) → ВАХ (5.3) → "
                "характеристика намагничивания (5.4). Итог — по самому точному из доступных.")
    st.markdown("### 2. Формулы ГОСТ Р 58669-2019")
    st.code("A     = I1ном·Kном·z2Σном / (Iкз·z2Σ)                      (9)\n"
            "t_нас = T_p·ln( ω·T_p / (ω·T_p + 1 − A·(1−K_r)) )         (3), (6)",
            language="text")
    st.markdown("### 3. Первое КЗ — ГОСТ Р 71879-2024")
    st.code("A     = I1ном·Kном·Kп.р.ном·z2Σном / (Iкз·z2Σ)              (4)\n"
            "T_s   = Ts.ном·(R2 + zн.ном·cos φном)/(R2 + Rн.факт)       (5)\n"
            "T     = min(T_а.экв, T_s);  t′нас по формуле (6)",
            language="text")
    st.markdown("### 4. Второе КЗ (неуспешное АПВ) — п. 5.1.6")
    st.code("t2 = t_кз1 + t_б.п\n"
            "t″нас = T·ln( ω·T / (ω·T + 1 − A·(1−K_r) + A·e^(−t_б.п/T_s)) )   (9)\n"
            "усл. (10): ω·T + 1 > A·(1−K_r) − A·e^(−t_б.п/T_s)\n"
            "усл. (11): A·(1−K_r) − A·e^(−t_б.п/T_s) > 1", language="text")
    st.markdown("Время второго КЗ отсчитывается **от момента его возникновения (t2)**. "
                "Если АПВ отсутствует, второе КЗ не рассчитывается.")
    st.markdown("### 5. Графический метод 71879 — формулы (12)–(14), предпросмотр")
    st.code("K'_п.р(t) = ω·Ta.экв·e^(−t/Ts)·cos θ − ω·Ta.экв·cos(ωt+θ)·e^(−t/Ta.экв)\n"
            "          + sin(ωt+θ) − sin θ·e^(−t/Ta.экв)                     (12)\n"
            "θ = φкз − arctg(ω·Ta.экв)                                        (14)\n"
            "K''_п.р(t) = K'_п.р(t2) + ω·Ta.экв·e^(−(t−t2)/Ts)·cos φкз\n"
            "           − ω·Ta.экв·cos(ω(t−t2)+φкз)·e^(−(t−t2)/Ta.экв)\n"
            "           + sin(ω(t−t2)+φкз) − sin φкз·e^(−(t−t2)/Ta.экв)       (13)",
            language="text")
    st.markdown("Условия: K′_п.р.(t′_нас) = A(1−K_r); K″_п.р.(t″_нас) = A(1−K_r); "
                "если K′_п.р.(t2) ≥ A(1−K_r), то t″_нас = 0. "
                "**Статус:** реализация дословная, но численная сверка с примером Б.2 не "
                "выполнена — результаты в режиме предпросмотра и в вердикт не входят.")
    st.markdown("### 6. Условия применимости")
    st.markdown("""
| Условие | Если выполняется | Если НЕ выполняется |
|---|---|---|
| A > 1 (усл. 5) | предельный ток больше тока КЗ | эксплуатация недопустима |
| A(1−K_r) > 1 (усл. 8) | формула времени применима | графический метод (п. 5.1.5) |
| ωT + 1 > A(1−K_r) (усл. 7) | насыщение при конечном t | насыщения нет |
| t_нас ≥ 15 мс (п. 5.1.7) | аналитика точна | уточнить графически |
| (I0ε/Uε)/(Iлин/Uлин) > 3 (16) | ВАХ-метод применим | ВАХ-метод неприменим |
| B_me(H_e) ≥ 1,8 Тл (21) | B(H)-метод применим | B(H)-метод неприменим |
""")
    st.markdown("### 7. ВАХ и B(H): формулы и источники")
    st.code("ВАХ:  I0ε=(ε/100)·I2ном·Kфакт (17); U2sin=Kфакт·I2ном·z2Σ (20); A=Uε/U2sin (19)\n"
            "B(H): H_e=I0ε·w2/l (22); B_m=U2sin/(222·w2·s) (24); A=B_me/B_m (23)",
            language="text")
    st.markdown("**ВАХ** — паспорт/измерения (ГОСТ Р 70507.2-2024, п. 6.7.5, 9.17; "
                "РД 153-34.0-35.301-2002). **B(H)** — w2, s, l из паспорта (пример В.4.1.1); "
                "кривая — заводские данные или измерения.")

# ---------------------------------------------------------------------------
# Вкладка «О приложении»
# ---------------------------------------------------------------------------
with tab_about:
    st.markdown("""
**Релиз 2.3:** графический метод ГОСТ Р 71879-2024 по формулам (12)–(14) — реализация
дословная, в режиме **предпросмотра** (структурные самопроверки выполняются; численная
сверка с примером Б.2 ожидает скана; в определяющий вердикт метод не входит).

**Релиз 2.2.1:** раздельный ввод t_кз1 и t_б.п.
**Релиз 2.2:** второе КЗ (АПВ), формула (9); исправлена самопроверка 71879.
**Ранее:** 2.1 — поддержка 71879 (первое КЗ); 2.0 — ввод ВАХ и B(H) из файла/вручную;
1.10 — каскад методов; 1.9 — монотонная B(H), ручной K_r; 1.8 — прозрачная самопроверка;
1.7 — метод B(H); 1.6 — метод ВАХ; 1.5 — кабель; 1.4 — графики в Word; 1.3 — графический
метод; 1.2 — модули; 1.1 — корректная формула t_нас.

**Что нужно для включения (12)–(14) в вердикт:** скан примера Б.2 (Б.2.1–Б.2.4) —
сравним числа и решим вопрос об ограничении K'_п.р(t2) при насыщении во время первого КЗ.
""")

# === КОНЕЦ ФАЙЛА app.py ===
