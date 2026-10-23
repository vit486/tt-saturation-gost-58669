"""⚡ Проверка ТТ на насыщение при КЗ. ГОСТ Р 58669-2019. Релиз 1.10."""
import math
from datetime import datetime

import streamlit as st

try:
    from methods.gost_58669 import (
        ANALYTIC_KEYS, CTParams, GRAPHIC_KEYS, K_R_PRED, KZParams,
        ST_NO_SAT, ST_OK, ST_STEADY, VAH_KEYS, BN_KEYS, build_kpr_curve,
        calculate, build_vah_default, build_bn_default, calculate_vah, calculate_bn,
        validate_bn_inputs, validate_bn_usage,
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
    st.markdown("Проверьте: `methods/gost_58669.py` (`def calculate_bn(`), "
                "`methods/summary.py` (`def build_summary(`), "
                "`methods/reference_examples.py` (`REFERENCE_EXAMPLES`), "
                "`report/docx_report.py` (`def build_report(`).")
    st.stop()

import numpy as np   # noqa: E402
import pandas as pd  # noqa: E402

st.set_page_config(page_title="Проверка ТТ — ГОСТ Р 58669-2019", layout="wide", page_icon="⚡")
st.title("⚡ Проверка трансформаторов тока")
st.caption("ГОСТ Р 58669-2019 · каскад методов: аналитический → графический → ВАХ → B(H) "
           "· релиз 1.10")

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

with st.sidebar:
    st.header("⚙️ Исходные данные")
    st.caption("Методы применяются каскадно. Итог — по самому точному из доступных.")

    manual_theta = st.checkbox("Задать θ вручную", value=False)
    theta_override = None
    if manual_theta:
        theta_deg = st.number_input("θ, градусы", -90.0, 90.0, 0.0, 1.0)
        theta_override = math.radians(theta_deg)

    st.subheader("Остаточная намагниченность")
    custom_kr = st.checkbox("Задать K_r вручную", value=False,
                            help="По умолчанию 0,86 (класс P, п. 5.1.3). Для 5PR/10PR "
                                 "и по заводским данным — например 0,1.")
    k_r = (st.number_input("K_r", 0.0, 1.0, 0.86, 0.01, format="%.2f")
           if custom_kr else K_R_PRED)

    pn = st.selectbox("Тип ТТ", list(PRESETS.keys()))
    pr = PRESETS[pn]
    st.subheader("Паспорт ТТ")
    i1 = st.number_input("I1ном, А", 1., float(pr.get("i1_nom", 1000.)), 50., key=pn+"i1")
    i2 = st.selectbox("I2ном, А", (1., 2., 5.),
                      index=(1., 2., 5.).index(float(pr.get("i2_nom", 5.))), key=pn+"i2")
    kn = st.number_input("Kном", 1., float(pr.get("k_nom", 10.)), 1., key=pn+"kn")
    sn = st.number_input("Sном, ВА", 1., float(pr.get("s_nom", 15.)), 1., key=pn+"sn")
    cpf = st.slider("cos φном", .1, 1., .8, .05, key=pn+"cpf")
    r2 = st.number_input("R2, Ом", 0., float(pr.get("r2", .15)), .01, "%.3f", key=pn+"r2")
    x2 = st.number_input("X2, Ом", 0., 0., .01, "%.3f", key=pn+"x2")

    st.subheader("Вторичная цепь (п. 4.2.6)")
    rp = st.number_input("Rприб, Ом", 0., float(pr.get("r_prib", .5)), .01, "%.3f", key=pn+"rp")
    xl = st.number_input("Xн, Ом", 0., 0., .01, "%.3f", key=pn+"xl")
    scheme = st.selectbox("Схема соединения", list(SCHEME_FACTORS))
    mat = st.radio("Материал жилы", list(RHO), horizontal=True)
    clen = st.number_input("Длина кабеля, м", 0., 3000., 30., 5.)
    cs = st.number_input("Сечение жилы, мм²", .5, 300., 2.5, .5)
    rper = st.radio("Переходное сопротивление, Ом", (.05, .1), horizontal=True,
                    format_func=lambda v: f"{v:g}")

    st.subheader("КЗ")
    ikz3 = st.number_input("Iкз(3), А", 1., 15000., 100.)
    tp3 = st.number_input("Tр(3), с", .001, .05, .005, "%.3f")
    use1 = st.checkbox("Расчёт для однофазного КЗ")
    ikz1 = tp1 = None
    if use1:
        ikz1 = st.number_input("Iкз(1), А", 1., 12000., 100.)
        tp1 = st.number_input("Tр(1), с", .001, .05, .005, "%.3f")
    treq = st.number_input("Требуемое t_нас, мс (0 — не проверять)", 0., 500., 0., 5.)

    st.subheader("ВАХ (п. 5.3)")
    use_vah = st.checkbox("Есть данные ВАХ", value=False)
    vah_data, eps = None, 10.0
    if use_vah:
        eps = st.selectbox("Полная погрешность ε, % (класс ТТ)", (10.0, 5.0), 0)
        ustar = st.number_input("U*, В", 1., 100., 10.)
        i0star = st.number_input("I₀*, А", .001, 1., .1, format="%.3f")
        vah_data = {'u_star': ustar, 'i0_star': i0star}

    st.subheader("Характеристика намагничивания (п. 5.4)")
    use_bn = st.checkbox("Есть данные B(H)", value=False)
    bn_data = bn_params = None
    if use_bn:
        w2 = st.number_input("w2, витков", 1, 100000, 2000, 50)
        s_cm2 = st.number_input("s, см²", .1, 1000., 26.5, .5)
        l = st.number_input("l, м", .01, 10., 1.437, .001, "%.3f")
        bsat = st.number_input("Bнас, Тл", .5, 2.5, 1.8, .1)
        hk = st.number_input("Hколено, А/м", 1., 10000., 100., 10.)
        bn_data = build_bn_default(bsat, hk)
        bn_params = {'w2': w2, 's': s_cm2 * 1e-4, 'l': l,
                     'b_sat': bsat, 'h_knee': hk}

# ---------------------------------------------------------------------------
rho = RHO[mat]
k3, k1 = SCHEME_FACTORS[scheme]
rn3 = rp + rper + rho * clen * k3 / cs
rn1 = rp + rper + rho * clen * k1 / cs
chain = {"scheme": scheme, "material": f"{mat} (ρ = {rho} Ом·мм²/м, 20 °С)",
         "length": clen, "section": cs, "r_prib": rp, "r_per": rper,
         "x_load": xl, "k_sch_3": k3, "k_sch_1": k1}

ct3 = CTParams(i1, i2, kn, sn, cpf, r2, x2, rn3, xl)
kz3 = KZParams(ikz3, tp3, "трёхфазное КЗ")
bn_inputs_ok = True
bn_input_msg = ""
if use_bn and bn_params:
    bn_inputs_ok, bn_input_msg = validate_bn_inputs(
        w2, bn_params['s'], l, bsat, hk)

try:
    with st.spinner("Каскадный расчёт методов…"):
        res3 = calculate(ct3, kz3, "both", theta_override, k_r)
        if use_vah and vah_data:
            res3.update(calculate_vah(ct3, kz3, vah_data['u_star'], vah_data['i0_star'],
                                      theta_override, k_r, eps))
        if use_bn and bn_params and bn_inputs_ok:
            res3.update(calculate_bn(ct3, kz3, bn_data, w2, bn_params['s'], l,
                                     theta_override, k_r, eps))
        results = [(ct3, kz3, res3)]
        if use1:
            ct1 = CTParams(i1, i2, kn, sn, cpf, r2, x2, rn1, xl)
            kz1 = KZParams(ikz1, tp1, "однофазное КЗ")
            res1 = calculate(ct1, kz1, "both", theta_override, k_r)
            if use_vah and vah_data:
                res1.update(calculate_vah(ct1, kz1, vah_data['u_star'],
                                          vah_data['i0_star'], theta_override, k_r, eps))
            if use_bn and bn_params and bn_inputs_ok:
                res1.update(calculate_bn(ct1, kz1, bn_data, w2, bn_params['s'], l,
                                         theta_override, k_r, eps))
            results.append((ct1, kz1, res1))
except ValueError as e:
    st.error(f"Ошибка исходных данных: {e}")
    st.stop()

summary_rows, verdict, summary_lines, primary = build_summary(
    results, bool(use_vah and vah_data), bool(use_bn and bn_params and bn_inputs_ok), treq)


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


def chart_kpr(ct_m, kz, r, eff):
    tn = r.t_nas * 1000.0 if r.t_nas is not None else None
    tend = min(max(tn * 1.45, 20.) if tn else max(kz.t_p * 3000, 40.), 400.)
    th = r.theta_star if r.theta_star is not None else 0.
    label = (f"θ = {math.degrees(th):.1f}° — вручную" if r.theta_manual else LBL_STAR)
    tm, ks = build_kpr_curve(kz.t_p, ct_m.alpha, th, tend)
    _, k0 = build_kpr_curve(kz.t_p, ct_m.alpha, 0., tend)
    df = pd.DataFrame({"t_ms": np.r_[tm, tm], "K_pr": np.r_[ks, k0],
                       "curve": [label] * len(tm) + [LBL_ZERO] * len(tm)})
    dl = pd.DataFrame({"lvl": [eff]})
    dp = (pd.DataFrame({"t_ms": [tn], "K_pr": [eff]}) if tn is not None
          else pd.DataFrame({"t_ms": [], "K_pr": []}))
    try:
        import altair as alt
        base = alt.Chart(df).mark_line(strokeWidth=2).encode(
            x=alt.X("t_ms:Q", title="Время t, мс"),
            y=alt.Y("K_pr:Q", title="K_п.р(t)"),
            color=alt.Color("curve:N", title="Начальная фаза"),
            tooltip=["t_ms:Q", "K_pr:Q", "curve:N"])
        layers = [base, alt.Chart(dl).mark_rule(strokeDash=[6, 4], color="#2ca02c",
                                               strokeWidth=2).encode(y="lvl:Q")]
        if not dp.empty:
            layers.append(alt.Chart(dp).mark_rule(color="#2ca02c", strokeDash=[3, 3])
                          .encode(x="t_ms:Q"))
            layers.append(alt.Chart(dp).mark_point(size=170, filled=True,
                                                   color="#2ca02c", stroke="black")
                          .encode(x="t_ms:Q", y="K_pr:Q"))
        st.altair_chart(alt.layer(*layers).properties(
            title=f"{kz.label} · {label} · T_p = {kz.t_p * 1000:.0f} мс", height=400))
    except Exception as exc:
        st.warning(f"Интерактивный график недоступен ({type(exc).__name__}: {exc}).")
        st.line_chart(pd.DataFrame({label: ks, LBL_ZERO: k0}, index=np.round(tm, 3))
                      .rename_axis("Время, мс"))
    st.caption(f"Уровень A·(1−K_r) = {eff:.3f}; {label}; t_нас = {fmt_t(r)}.")


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


tab_res, tab_check, tab_theory, tab_about = st.tabs([
    "🧮 Результаты расчёта", "🧪 Самопроверка",
    "📚 Теория и формулы", "ℹ️ О приложении"])

with tab_res:
    {"success": st.success, "warning": st.warning, "danger": st.error}[verdict](
        " ".join(summary_lines))
    st.markdown("#### Сводка по всем методам")
    st.table(summary_rows)
    if not bn_inputs_ok and use_bn:
        st.error("Проверка входов B(H): " + bn_input_msg + ". Метод B(H) пропущен.")

    for ct_m, kz, res in results:
        st.subheader(f"Режим: {kz.label}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Iкз", f"{kz.i_kz:g} А")
        c2.metric("Kфакт", f"{kz.i_kz / ct_m.i1_nom:.2f}")
        c3.metric("Rн.факт", f"{ct_m.r_load_fact:.3f} Ом")
        c4.metric("A", f"{res[ANALYTIC_KEYS[0]].a:.3f}")

        seen = set()
        for keys, name in ((ANALYTIC_KEYS, "Аналитический"),
                           (GRAPHIC_KEYS, "Графический по паспортным данным"),
                           (VAH_KEYS, "По ВАХ"), (BN_KEYS, "По B(H)")):
            present = [k for k in keys if k in res]
            if not present:
                continue
            st.markdown(f"**{name}**")
            rows = []
            for k in present:
                r = res[k]
                extra = (f"  (θ = {math.degrees(r.theta_star):.1f}°)"
                         if r.theta_star is not None else "")
                rows.append({"Сценарий": ("без остаточной (K_r = 0)" if "without" in k
                                          else f"с остаточной (K_r = {k_r:g})"),
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

        if vah_data and VAH_KEYS[0] in res:
            with st.expander("📈 ВАХ"):
                v = build_vah_default(vah_data['u_star'], vah_data['i0_star'], ct_m.r2)
                chart_generic(v['i0'], v['u'], "I₀, А", "U, В",
                              "ВАХ ТТ (типовая)", "#d62728")
                st.caption("Для реального расчёта используйте фактическую ВАХ конкретного ТТ.")

        if bn_data and BN_KEYS[0] in res:
            with st.expander("📈 Характеристика намагничивания"):
                chart_generic(bn_data['h'], bn_data['b'], "H, А/м", "B, Тл",
                              "B(H) ТТ (типовая)", "#9467bd")
                _, _, det, b_me = validate_bn_usage(
                    ct_m, kz, bn_data, bn_params['w2'], bn_params['s'], bn_params['l'], eps)
                st.caption(det + f". Проверяется условие (21): B_me(H_e) ≥ 1,8 Тл.")

    st.divider()
    data = build_report(ct3, chain, results, summary_lines, verdict, treq, "both",
                        vah_data, bn_data, bn_params, k_r, eps)
    st.download_button("📄 Скачать отчёт (.docx)", data,
                       f"Otchet_TT_{datetime.now():%Y%m%d_%H%M}.docx",
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

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
    st.success("✅ Все эталоны воспроизведены") if oka else st.error("❌ Расхождение")
    st.dataframe(ra, hide_index=True)
    st.success("✅ Свойства формулы (Г.15) подтверждены") if okg else st.error("❌ Расхождение")
    st.dataframe(rg, hide_index=True)
    st.dataframe(rc, hide_index=True)

with tab_theory:
    st.markdown("### 1. Каскад методов")
    st.markdown("Аналитический (5.1) → графический по паспортным данным (5.2) → "
                "по ВАХ (5.3) → по характеристике намагничивания (5.4). "
                "Каждый следующий используется при наличии данных; итог выносится "
                "по самому точному из доступных. Неприменимые методы пропускаются.")
    st.markdown("### 2. Условие A > 1 и остальные условия")
    st.markdown("""
| Условие | Если выполняется | Если НЕ выполняется |
|---|---|---|
| A > 1 (усл. 5) | предельный ток ТТ больше тока КЗ — допустимо | эксплуатация недопустима |
| ωT_p+1 > A (усл. 4) | насыщение при конечном t | насыщения нет |
| A(1−K_r) > 1 (усл. 8) | применима формула (6) | графический метод (п. 5.1.5) |
| ωT_p+1 > A(1−K_r) (усл. 7) | насыщение при конечном t | насыщения нет |
| t_нас ≥ 15 мс (п. 5.1.7) | аналитика точна | уточнить графически |
""")
    st.code("t_нас = T_p·ln( ω·T_p / (ω·T_p + 1 − A·(1−K_r)) )        (3), (6)",
            language="text")
    st.warning("«+1» — только в знаменателе.")
    st.markdown("### 3. ВАХ (п. 5.3)")
    st.code("I0ε = (ε/100)·I2ном·Kфакт                                (17)\n"
            "U2sin = Kфакт·I2ном·z2Σ                                  (20)\n"
            "A = Uε / U2sin                                           (19)\n"
            "Условие (16): (I0ε/Uε) / (Iлин/Uлин) > 3", language="text")
    st.markdown("**Откуда брать ВАХ:** паспорт/заводская документация ТТ либо измерение "
                "при проверке. Порядок измерений — ГОСТ Р 70507.2-2024, п. 6.7.5 и "
                "п. 9.17; контрольные точки токов 10 %, 20 %, 80 %, 100 %, 200 % от точки "
                "перегиба. Методика проверки эксплуатируемых ТТ — РД 153-34.0-35.301-2002. "
                "Типовая ВАХ пригодна только для оценочного расчёта.")
    st.markdown("### 4. Характеристика намагничивания (п. 5.4)")
    st.code("H_e = I0ε·w2 / l                                          (22)\n"
            "B_me(H_e) ≥ 1,8 Тл                              условие (21)\n"
            "B_m = U2sin / (222·w2·s)                                 (24)\n"
            "A = B_me / B_m                                           (23)", language="text")
    st.markdown("**Важно:** порог 1,8 Тл относится к **B_me, взятой с кривой намагничивания "
                "при H_e**, а не к рабочей индукции B_m. В примере В.4.2 B_m = 0,44 Тл, "
                "при этом B_me ≈ 1,9 Тл — метод применим. Ввод Bнас вне 0,5…2,5 Тл "
                "и некорректные w2, s, l отклоняются проверкой входов.")
    st.markdown("**Откуда брать данные:** w2, s, l — конструктивные параметры из паспорта "
                "ТТ (пример В.4.1.1); характеристика B(H) — заводские данные или измерения "
                "по РД 153-34.0-35.301-2002, п. 1.4.")
    st.markdown("### 5. Разобранный пример В.1.1")
    st.markdown("I1ном=2000, I2ном=1, Kном=20, Sном=40, cos φ=0,8, R2=7,51, "
                "Rн=6,3, Iкз=23145, T_p=0,128.\n\n"
                "z2Σном=46,23 Ом; z2Σ=13,81 Ом; A=5,785; ωT_p=40,21; "
                "t_нас=0,128·ln(40,21/35,43)=**16,22 мс** — совпадает с ГОСТ.")

with tab_about:
    st.markdown("""
**Релиз 1.10:** каскадный разбор всех методов с итоговым выводом по самому точному;
исправлено поведение ВАХ/графики при A ≤ 1; исправлена формула (23) — A = B_me/B_m;
условие (21) применяется к B_me(H_e), а не к рабочей индукции; добавлен контроль
входов B(H); справка об источниках ВАХ и B(H).

**Ранее:** 1.9 — монотонная B(H), ручной K_r; 1.8 — прозрачная самопроверка,
устранение дублей; 1.7 — метод B(H); 1.6 — метод ВАХ; 1.5 — кабель; 1.4 — графики
в Word и ручной θ; 1.3 — графический метод; 1.2 — модули; 1.1 — корректная формула t_нас.

**Ограничения:** типовые ВАХ и B(H) (ввод фактических таблиц — следующий релиз);
классы P/PX/TPX; одна экспонента T_р.экв.
""")

# === КОНЕЦ ФАЙЛА app.py ===
