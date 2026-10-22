"""
⚡ Проверка трансформаторов тока на насыщение при коротких замыканиях.
Методика: ГОСТ Р 58669-2019.
Релиз 1.5: фактическая вторичная нагрузка формируется из параметров всей
вторичной цепи — приборы, соединительный кабель (материал, длина, сечение,
схема соединения), переходные контакты (п. 4.2.6, Приложение А).

Структура проекта:
  - app.py                        — интерфейс (вкладки, формы, результаты, графики);
  - methods/gost_58669.py         — расчётное ядро ГОСТ Р 58669-2019 (оба метода);
  - methods/reference_examples.py — самопроверка по эталонным примерам стандарта;
  - report/docx_report.py         — генерация отчёта Word (с графиками).
"""

import math
from datetime import datetime

import streamlit as st

try:
    from methods.gost_58669 import (
        ANALYTIC_KEYS, CTParams, GRAPHIC_KEYS, K_R_PRED, KZParams, ST_GRAPHIC_REQUIRED,
        ST_NO_SAT, ST_OK, ST_STEADY, build_kpr_curve, calculate,
    )
    from methods.reference_examples import (
        run_graphic_checks, run_method_comparison, run_self_checks,
    )
    from report.docx_report import build_report
    _IMPORT_ERROR = None
except Exception as e:
    _IMPORT_ERROR = e

if _IMPORT_ERROR is not None:
    st.set_page_config(page_title="Ошибка структуры файлов", page_icon="⚠️")
    st.error(f"Не удалось загрузить расчётные модули: "
             f"{type(_IMPORT_ERROR).__name__}: {_IMPORT_ERROR}")
    st.markdown(
        """
Проверьте состав репозитория — должны быть файлы (каждый заканчивается строкой-маркером
`# === КОНЕЦ ФАЙЛА ... ===`):

| Файл | Признак целостности (поиск Ctrl+F) |
|---|---|
| `methods/__init__.py` | текст «Пакет расчётных методик» |
| `methods/gost_58669.py` | `def t_nas_graphic(` |
| `methods/reference_examples.py` | `def run_graphic_checks(` |
| `report/__init__.py` | текст «Пакет генерации отчётов» |
| `report/docx_report.py` | `def build_report(` |

Если файл обрезан при копировании — замените его содержимое полностью.
"""
    )
    st.stop()

import numpy as np      # noqa: E402
import pandas as pd     # noqa: E402

# ===========================================================================
# ИНТЕРФЕЙС
# ===========================================================================

st.set_page_config(page_title="Проверка ТТ — ГОСТ Р 58669-2019", layout="wide", page_icon="⚡")

st.title("⚡ Проверка трансформаторов тока")
st.caption("Насыщение при КЗ · ГОСТ Р 58669-2019 · аналитический и графический методы "
           "· релиз 1.5")

METHOD_OPTIONS = {
    "Аналитический (п. 5.1)": "analytic",
    "Графический по паспортным данным (п. 5.2)": "graphic",
    "Оба метода — сравнение": "both",
}
METHOD_KEYS = {"analytic": ANALYTIC_KEYS, "graphic": GRAPHIC_KEYS, "both": GRAPHIC_KEYS}
SCENARIO_TITLE = {
    "without_residual": "Аналитический · без остаточной намагниченности (K_r = 0)",
    "with_residual": f"Аналитический · с остаточной намагниченностью (K_r = {K_R_PRED})",
    "graphic_without_residual": "Графический · без остаточной намагниченности (K_r = 0)",
    "graphic_with_residual": f"Графический · с остаточной намагниченностью (K_r = {K_R_PRED})",
}
LBL_STAR_AUTO = "θ = θ* — расчётный минимум (п. Г.3.7)"
LBL_ZERO = "θ = 0° — максимум апериодической составляющей"

# Коэффициенты расчётной длины кабеля: (трёхфазное КЗ, однофазное КЗ)
# Классическая методика расчёта вторичных нагрузок (РД 153-34.0-35.301-2002,
# Приложение А ГОСТ Р 58669-2019):
#  - полная звезда: при трёхфазном КЗ ток в нулевом проводе равен нулю (k = 1),
#    при однофазном — обратный ток идёт по нулевому проводу (k = 2);
#  - неполная звезда: при трёхфазном КЗ общий провод несёт ток неповреждённой
#    фазы, сумма сопротивлений даёт k = √3; для однофазного КЗ — k = 2;
#  - один ТТ: ток идёт по двум проводам (туда и обратно), k = 2.
SCHEME_FACTORS = {
    "Полная звезда (3 ТТ)": (1.0, 2.0),
    "Неполная звезда (2 ТТ)": (math.sqrt(3.0), 2.0),
    "Один ТТ (токовые цепи в 2 проводах)": (2.0, 2.0),
}
# Удельное сопротивление жил при 20 °С (п. 4.2.1 ГОСТ 58669: сопротивления
# приводят к нормальной температуре по ГОСТ 15150), Ом·мм²/м
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

with st.sidebar:
    st.header("⚙️ Исходные данные")

    method_label = st.radio(
        "Метод расчёта (п. 4.1 ГОСТ)", list(METHOD_OPTIONS.keys()), index=2,
        help="Аналитический — формулы (3)/(6): быстрый, но приближённый, применим при "
             "t_нас ≥ 15 мс (п. 5.1.7). Графический по паспортным данным — численное "
             "воспроизведение универсальных характеристик приложения Б по формуле (Г.15); "
             "является определяющим.")
    method = METHOD_OPTIONS[method_label]

    st.subheader("Начальная фаза θ")
    manual_theta = st.checkbox(
        "Задать θ вручную (графический метод)", value=False,
        help="По умолчанию для графического метода автоматически находится наихудшая фаза θ*, "
             "при которой время до насыщения минимально (п. Г.3.7). Включите, чтобы зафиксировать "
             "конкретную фазу. На аналитический метод не влияет.")
    theta_override = None
    if manual_theta:
        theta_deg = st.number_input(
            "θ, градусы", min_value=-90.0, max_value=90.0, value=0.0, step=1.0,
            help="Начальная фаза апериодической составляющей тока КЗ, диапазон −90…+90°.")
        theta_override = math.radians(theta_deg)

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
    r_prib = st.number_input(
        "Rприб (реле, приборы), Ом", min_value=0.0,
        value=float(preset.get("r_prib", 0.5)), step=0.01, format="%.3f",
        key=f"{preset_name}_rp",
        help="Суммарное активное сопротивление реле, измерительных преобразователей "
             "и прочих приборов, включённых в цепь данной обмотки ТТ.")
    x_load = st.number_input(
        "Xн (индуктивная составляющая), Ом", min_value=0.0,
        value=float(preset.get("x_load", 0.0)), step=0.01, format="%.3f",
        key=f"{preset_name}_xl",
        help="Индуктивное сопротивление нагрузки. Для кабельных цепей обычно пренебрежимо мало.")

    scheme = st.selectbox(
        "Схема соединения вторичных обмоток", list(SCHEME_FACTORS.keys()),
        help="Определяет коэффициент расчётной длины кабеля: при разных схемах и видах КЗ "
             "обратный ток протекает по разному числу проводов.")
    cable_mat = st.radio("Материал жилы кабеля", list(RHO_MATERIALS.keys()), horizontal=True,
                         help="Удельное сопротивление при 20 °С: медь 0,0175; алюминий 0,0281 Ом·мм²/м "
                              "(п. 4.2.1 ГОСТ 58669, ГОСТ 15150).")
    cable_len = st.number_input("Длина кабеля (в одну сторону), м", min_value=0.0,
                                max_value=3000.0, value=30.0, step=5.0,
                                help="Длина от ТТ до панели защиты/учёта в одну сторону.")
    cable_s = st.number_input("Сечение жилы, мм²", min_value=0.5, max_value=300.0,
                              value=2.5, step=0.5)
    r_per = st.radio("Переходное сопротивление контактов, Ом", (0.05, 0.1),
                     horizontal=True, format_func=lambda v: f"{v:g}",
                     help="Суммарное переходное сопротивление контактных соединений "
                          "вторичной цепи (зажимы, испытательные блоки, реле).")

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
    t_req = st.number_input("Требуемое t_нас, мс (0 — не проверять)", 0.0, 500.0, 0.0, 5.0,
                            help="Минимально необходимое время до насыщения по требованиям "
                                 "РЗА (например, время отключения КЗ с запасом).")
    st.subheader("Метод по ВАХ (опционально)")
    use_vah = st.checkbox(
        "Использовать метод по ВАХ (п. 5.3)", value=False,
        help="Метод позволяет точнее определить время до насыщения, если известна "
             "вольт-амперная характеристика ТТ. Требует проверки условия (16) ГОСТ.")
    
    vah_data = None
    if use_vah:
        st.markdown("**Параметры типовой ВАХ** (можно скорректировать по фактическим данным):")
        u_star_input = st.number_input(
            "U* — напряжение при полной погрешности ε, В", min_value=1.0,
            value=100.0, step=10.0,
            help="Напряжение на выводах вторичной обмотки при токе намагничивания, "
                 "соответствующем полной погрешности ТТ (обычно при 10% погрешности).")
        i0_star_input = st.number_input(
            "I₀* — ток намагничивания при U*, А", min_value=0.001,
            value=1.0, step=0.1, format="%.3f",
            help="Ток намагничивания в точке U*.")
        
        # Проверка условия (16)
        ct_temp = CTParams(i1_nom, i2_nom, k_nom, s_nom, cos_phi, r2, x2, r_n3, x_load)
        kz_temp = KZParams(i_kz3, tp3, "трёхфазное КЗ")
        valid, msg = validate_vah_usage(u_star_input, i0_star_input, ct_temp, kz_temp)
        if valid:
            st.success(f"✅ {msg}")
        else:
            st.warning(f"⚠️ {msg}")
        
        vah_data = {'u_star': u_star_input, 'i0_star': i0_star_input}
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
        results = [(ct3, kz3, calculate(ct3, kz3, method, theta_override))]
        
        # Если включён метод по ВАХ, добавляем его результаты
        if use_vah and vah_data:
            vah_res = _vah_method(ct3, kz3, vah_data['u_star'], vah_data['i0_star'], theta_override)
            results[0][2].update(vah_res)
        
        if use_kz1:
            ct1 = CTParams(i1_nom, i2_nom, k_nom, s_nom, cos_phi, r2, x2, r_n1, x_load)
            kz1 = KZParams(i_kz1, tp1, "однофазное КЗ")
            res1 = calculate(ct1, kz1, method, theta_override)
            if use_vah and vah_data:
                vah_res1 = _vah_method(ct1, kz1, vah_data['u_star'], vah_data['i0_star'], theta_override)
                res1.update(vah_res1)
            results.append((ct1, kz1, res1))
except ValueError as e:
    st.error(f"Ошибка исходных данных: {e}")
    st.stop()


# ---------------------------------------------------------------------------
# Графики K_п.р(t) по формуле (Г.15)
# ---------------------------------------------------------------------------
def curve_frames(t_p, alpha, theta_star, eff, t_nas_ms, t_end_ms, star_label, n=1200):
    """Кадры для Altair (имена полей ASCII) и запасной широкий кадр для st.line_chart."""
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
    """Динамический график коэффициента переходного режима."""
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
                   "показан упрощённый график. Если ошибка повторяется — пришлите этот текст.")
        st.line_chart(wide)
    st.caption(f"Зелёная пунктирная линия — уровень насыщения A·(1−K_r) = {eff:.3f}; "
               "точка пересечения с кривой и есть время до насыщения t_нас.")


# ---------------------------------------------------------------------------
# Вкладки
# ---------------------------------------------------------------------------
tab_calc, tab_check, tab_theory, tab_about = st.tabs([
    "🧮 Результаты расчёта",
    "🧪 Самопроверка (эталонные примеры)",
    "📚 Теория и формулы (ГОСТ Р 58669-2019)",
    "ℹ️ О приложении и планы",
])

with tab_calc:
    banner = {"success": st.success, "warning": st.warning, "danger": st.error}[verdict]
    banner(" ".join(verdict_lines))
    mode_note = (f"Метод: **{method_label}**." if not manual_theta
                 else f"Метод: **{method_label}**, θ задана вручную = {theta_deg:.1f}°.")
    st.caption(mode_note + f" Итог определяется по сценариям выбранного метода "
               f"(без остаточной намагниченности и с K_r = {K_R_PRED}).")

    for ct_m, kz, res in results:
        st.subheader(f"Режим: {kz.label}")
        a_val = res[ANALYTIC_KEYS[0]].a
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Iкз", f"{kz.i_kz:g} А")
        c2.metric("Kфакт = Iкз / I1ном", f"{kz.i_kz / ct_m.i1_nom:.2f}")
        c3.metric("Rн.факт (с кабелем)", f"{ct_m.r_load_fact:.3f} Ом")
        c4.metric("Параметр A", f"{a_val:.3f}")

        rows = []
        for k in ANALYTIC_KEYS + GRAPHIC_KEYS:
            r = res.get(k)
            if r is None:
                continue
            extra = ""
            if k in GRAPHIC_KEYS and r.status == ST_OK and r.theta_star is not None:
                tag = "θ (вручную)" if r.theta_manual else "θ*"
                extra = f"   ({tag} = {math.degrees(r.theta_star):.1f}°)"
            rows.append({"Метод и сценарий": SCENARIO_TITLE[k],
                         "Время до насыщения": fmt_t(r) + extra})
        st.table(rows)

        seen = set()
        for k in ANALYTIC_KEYS + GRAPHIC_KEYS:
            r = res.get(k)
            if r is None:
                continue
            for note in r.notes:
                if note not in seen:
                    seen.add(note)
                    st.caption(f"• {note}")
        # Метод по ВАХ
        if use_vah and vah_data:
            st.markdown("#### Метод по ВАХ (п. 5.3)")
            vah_rows = []
            for k in VAH_KEYS:
                r = res.get(k)
                if r is None:
                    continue
                extra = ""
                if r.status == ST_OK and r.theta_star is not None:
                    tag = "θ (вручную)" if r.theta_manual else "θ*"
                    extra = f"   ({tag} = {math.degrees(r.theta_star):.1f}°)"
                vah_rows.append({
                    "Сценарий": "Без остаточной намагниченности" if "without" in k else f"С K_r = {K_R_PRED}",
                    "Время до насыщения": fmt_t(r) + extra,
                })
            st.table(vah_rows)
            
            # Примечания
            for k in VAH_KEYS:
                r = res.get(k)
                if r is None:
                    continue
                for note in r.notes:
                    if note not in seen:
                        seen.add(note)
                        st.caption(f"• {note}")
            
            # График ВАХ
            with st.expander("📈 График ВАХ", expanded=False):
                vah_plot = build_vah_default(vah_data['u_star'], vah_data['i0_star'], ct_m.r2)
                df_vah = pd.DataFrame({
                    "I₀, А": vah_plot['i0'],
                    "U, В": vah_plot['u'],
                })
                try:
                    import altair as alt
                    chart_vah = alt.Chart(df_vah).mark_line(strokeWidth=2, color="#d62728").encode(
                        x=alt.X("I₀, А:Q", title="Ток намагничивания I₀, А"),
                        y=alt.Y("U, В:Q", title="Напряжение U, В"),
                        tooltip=["I₀, А:Q", "U, В:Q"],
                    ).properties(title="Вольт-амперная характеристика ТТ (типовая)", height=300)
                    st.altair_chart(chart_vah)
                except Exception as exc:
                    st.warning(f"График ВАХ недоступен ({type(exc).__name__}).")
                st.caption(f"Типовая ВАХ построена по точкам U* = {vah_data['u_star']:.1f} В, "
                          f"I₀* = {vah_data['i0_star']:.3f} А.")
              
        if method in ("graphic", "both"):
            g0 = res.get("graphic_without_residual")
            gr = res.get("graphic_with_residual")
            if g0 is not None:
                with st.expander("📈 График K_п.р(t) — без остаточной намагниченности",
                                 expanded=(method == "graphic")):
                    render_kpr_chart(ct_m, kz, g0, a_val)
            if gr is not None:
                with st.expander(f"📈 График K_п.р(t) — с остаточной намагниченностью "
                                 f"K_r = {K_R_PRED}"):
                    render_kpr_chart(ct_m, kz, gr, a_val * (1.0 - K_R_PRED))

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
                      else f"K_r = {K_R_PRED}")
                cmp_rows.append({
                    "Режим": kz.label, "Сценарий": sc,
                    "Аналитический": f"{ta:.2f} мс" if ta is not None else fmt_t(ra),
                    "Графический": f"{tg:.2f} мс" if tg is not None else fmt_t(rg),
                    "Отклонение аналитики": dev,
                })
        st.table(cmp_rows)
        st.caption("Аналитический метод — приближённый: п. 5.1.7 ограничивает его применимость "
                   "снизу значением 15 мс, а п. 5.1.5 направляет к графическому методу при "
                   "A·(1−K_r) ≤ 1. Определяющим является графический метод.")

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
    report_bytes = build_report(ct3, chain, results, verdict_lines, verdict, t_req, method)
    st.download_button(
        "📄 Скачать отчёт (.docx)",
        data=report_bytes,
        file_name=f"Otchet_TT_GOST_58669_{datetime.now():%Y%m%d_%H%M}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

with tab_check:
    st.markdown(
        "Расчётное ядро автоматически сверяется с эталонами и математическими свойствами "
        "стандарта. Если хотя бы одна строка ❌ — результатам расчёта доверять нельзя."
    )

    @st.cache_data(show_spinner="Выполняется самопроверка…")
    def _cached_checks():
        return run_self_checks(), run_graphic_checks(), run_method_comparison()

    (rows_a, ok_a), (rows_g, ok_g), rows_c = _cached_checks()

    st.markdown("#### 1. Аналитический метод — эталонные примеры ГОСТ "
                "(Приложение В, В.1.1–В.1.3)")
    if ok_a:
        st.success("✅ Все эталонные примеры воспроизведены (допуски: A ±0,02; t ±0,2 мс).")
    else:
        st.error("❌ Обнаружено расхождение с эталонными примерами.")
    st.dataframe(rows_a, hide_index=True)
    st.caption("Примечание: в примере В.1.2 в тексте стандарта опечатка (в исходных данных "
               "Kном = 20, расчёт выполнен при Kном = 18) — в эталоне принято Kном = 18. "
               "В эталонных примерах нагрузка уже задана полным сопротивлением, поэтому "
               "кабельный блок на самопроверку не влияет.")

    st.markdown("#### 2. Графический метод — проверка реализации формулы (Г.15)")
    if ok_g:
        st.success("✅ Все проверки свойств формулы (Г.15) и численного решения пройдены.")
    else:
        st.error("❌ Обнаружено расхождение в реализации графического метода.")
    st.dataframe(rows_g, hide_index=True)

    st.markdown("#### 3. Сопоставление методов на эталонных примерах (справочно)")
    st.caption("Не является критерием: аналитический метод приближённый, графический — "
               "определяющий. Расхождение тем больше, чем меньше t_нас (п. 5.1.7).")
    st.dataframe(rows_c, hide_index=True)

with tab_theory:
    st.markdown("### Общие положения")
    st.markdown(
        "Оба метода решают одно и то же уравнение переходного процесса (п. Г.6.2):\n\n"
        "`A·(1 − K_r) = K_п.р(t_нас)`,\n\n"
        "где **A** — параметр режима, **K_п.р(t)** — коэффициент переходного режима, "
        f"**K_r** — коэффициент остаточной намагниченности (для класса P — {K_R_PRED}, п. 5.1.3)."
    )

    st.markdown("### 1. Нагрузка вторичной цепи (п. 4.2.6, Приложение А)")
    st.markdown("Фактическая нагрузка вторичной обмотки ТТ складывается из сопротивлений "
                "приборов, соединительных кабелей и контактов:")
    st.code("Rн.факт = Rприб + Rпер + Rкаб\n"
            "Rкаб    = ρ · kсх · L / S", language="text")
    st.markdown(
        "где **ρ** — удельное сопротивление жилы при 20 °С (п. 4.2.1: сопротивления приводят "
        "к нормальной температуре по ГОСТ 15150): медь 0,0175 Ом·мм²/м, алюминий "
        "0,0281 Ом·мм²/м; **L** — длина кабеля в одну сторону, м; **S** — сечение жилы, мм²; "
        "**kсх** — коэффициент расчётной длины, зависящий от схемы соединения и вида КЗ."
    )
    st.markdown("""
| Схема соединения | Трёхфазное КЗ | Однофазное КЗ | Пояснение |
|---|---|---|---|
| Полная звезда (3 ТТ) | 1 | 2 | при симметрии ток нулевого провода равен нулю; при однофазном КЗ обратный ток идёт по нулевому проводу |
| Неполная звезда (2 ТТ) | √3 ≈ 1,73 | 2 | общий провод несёт ток неповреждённой фазы |
| Один ТТ (2 провода) | 2 | 2 | ток идёт по двум проводам (туда и обратно) |
""")
    st.caption("Индуктивное сопротивление кабеля (~0,06–0,08 Ом/км) на длинах в десятки метров "
               "пренебрежимо мало, поэтому учитывается только активная составляющая; индуктивную "
               "часть нагрузки можно задать отдельным полем Xн.")
    st.markdown("В схемах с полной звездой сопротивление кабеля для трёхфазного и однофазного КЗ "
                "различается, поэтому приложение рассчитывает Rн.факт отдельно для каждого вида КЗ.")

    st.markdown("### 2. Исходные величины (одинаковы для обоих методов)")
    st.code("zн.ном = Sном / I2ном²", language="text")
    st.code("z2Σном = √( (R2 + zн.ном·cos φном)² + (X2 + zн.ном·sin φном)² )     (10)",
            language="text")
    st.code("z2Σ    = √( (R2 + Rн.факт)² + (X2 + Xн.факт)² )                     (11)",
            language="text")
    st.code("A      = ( I1ном · Kном · z2Σном ) / ( Iкз · z2Σ )                  (9)",
            language="text")
    st.code("cos α  = ( R2 + Rн.факт ) / z2Σ                                     (12)",
            language="text")

    st.markdown("### 3. Аналитический метод (раздел 5.1)")
    st.code("t_нас = T_p · ln( ω·T_p / ( ω·T_p + 1 − A·(1 − K_r) ) )       (3), (6)",
            language="text")
    st.warning("«+1» присутствует **только в знаменателе**; в числителе — только ω·T_p.")
    st.markdown("Контрольный пример стандарта (Приложение В, п. В.1.1.8):")
    st.code("t(3) = 0,128 · ln( 314·0,128 / ( 314·0,128 − 5,785 + 1 ) ) = 16,22 мс",
            language="text")
    st.markdown("""
**Проверяемые условия**

| Условие | Смысл | Действие при нарушении |
|---|---|---|
| A > 1 (условие 5) | ток предельной кратности больше тока КЗ | эксплуатация ТТ недопустима |
| A·(1−K_r) > 1 (условие 8) | применимость формулы времени | графический метод (п. 5.1.5) |
| ω·T_p + 1 > A·(1−K_r) (условие 7) | наличие насыщения | насыщения нет, t_нас = ∞ |
| t_нас ≥ 15 мс (п. 5.1.7) | точность аналитического метода | уточнить графическим методом |
""")

    st.markdown("### 4. Графический метод по паспортным данным (раздел 5.2)")
    st.markdown(
        "Универсальные характеристики приложения Б построены по формуле (Г.15) для начальных "
        "фаз θ, при которых время до насыщения наименьшее (п. Г.3.7). Приложение решает то же "
        "уравнение численно — это исключает погрешность чтения графиков и снимает ограничение "
        "на диапазон T_p (30–300 мс):"
    )
    st.code(
        "K_п.р(t) = sin α · cos θ · e^(−t/T_p)\n"
        "         + cos α · cos θ · ω·T_p · ( 1 − e^(−t/T_p) )\n"
        "         − sin( ω·t + α + θ ) + cos α · sin θ                        (Г.15)\n"
        "\n"
        "t_нас:   K_п.р(t_нас) = A·(1 − K_r),  минимум по θ ∈ (−90°, +90°)",
        language="text")
    st.markdown(
        "**Начальная фаза θ.** По умолчанию приложение автоматически находит наихудшую θ* "
        "(минимум t_нас, п. Г.3.7). При необходимости конкретную фазу можно задать вручную — "
        "чек-бокс «Задать θ вручную» в панели слева."
    )
    st.markdown(
        "**Преимущества графического метода:**\n"
        "- работает там, где аналитический отказывает: при A·(1−K_r) ≤ 1 (п. 5.1.5) "
        "и при t_нас < 15 мс (п. 5.1.7);\n"
        "- учитывает наихудшую начальную фазу θ, которая обычно не равна нулю "
        "(в эталонных примерах θ* = 5…36°);\n"
        "- не ограничен диапазоном T_p = 30–300 мс."
    )

    st.markdown("### 5. Порядок расчёта по стандарту")
    st.markdown(
        "1. Расчёт выполняется для трёхфазного КЗ, а в сетях с глухозаземлённой нейтралью — "
        "и для однофазного; итогом является **наименьшее** из полученных значений (п. 4.2.4).\n"
        "2. Каждый расчёт проводится дважды: без остаточной намагниченности и с предельной "
        f"(K_r = {K_R_PRED}) — п. 4.3.\n"
        "3. Эквивалентная постоянная времени T_р.экв определяется по формуле (1) или "
        "по осциллограмме (п. 4.2.7).\n"
        "4. Нагрузки во вторичных цепях рассчитываются по формулам Приложения А (п. 4.2.6)."
    )

with tab_about:
    st.markdown("""
Приложение выполняет проверку трансформаторов тока на насыщение при коротких замыканиях
в соответствии с **ГОСТ Р 58669-2019**.

**Реализованные методы:**
- аналитический (раздел 5.1) — формулы (3), (6), (9)–(12), условия (4), (5), (7), (8), п. 5.1.7;
- графический по паспортным данным (раздел 5.2) — численное воспроизведение универсальных
  характеристик приложения Б по формуле (Г.15) с динамическими графиками и возможностью
  ручного задания начальной фазы θ;
- нагрузка вторичной цепи формируется из параметров всей цепи (п. 4.2.6, Приложение А):
  приборы, соединительный кабель (материал, длина, сечение, схема соединения),
  переходные контакты (0,05 / 0,1 Ом).

**История релизов:**
- **Релиз 1.5 (23.10.2026):** фактическая вторичная нагрузка рассчитывается из параметров
  всей вторичной цепи — сопротивление приборов, соединительного кабеля (материал жилы,
  длина, сечение; коэффициент расчётной длины зависит от схемы соединения и вида КЗ)
  и переходного сопротивления контактов; для трёхфазного и однофазного КЗ нагрузка
  рассчитывается отдельно; параметры цепи вынесены в таблицу каждого режима в отчёте Word.
- **Релиз 1.4:** графики K_п.р(t) в Word-отчёте (matplotlib); ручное задание начальной фазы θ.
- **Релиз 1.3:** графический метод по паспортным данным, динамические графики,
  переключатель метода, расширенная самопроверка.
- **Релиз 1.2:** модульная структура (`methods/`, `report/`), диагностика структуры файлов.
- **Релиз 1.1:** исправлена формула времени до насыщения (числитель ω·T_p), самопроверка.
- **Релиз 1.0:** аналитический метод ГОСТ Р 58669-2019, отчёт в Word.

**Планы развития:**
- релиз 1.6 — графические методы по ВАХ (п. 5.3) и по характеристике намагничивания (п. 5.4);
- релиз 1.7 — ГОСТ Р 71879-2024: классы 5PR/10PR/TPY/TPZ, циклы АПВ (второе КЗ);
- релиз 1.8 — выбор ТТ по ГОСТ Р 71403-2024;
- релиз 1.9 — справочные данные ГОСТ Р 70507.2-2024;
- релиз 2.0 — проверка эксплуатируемых ТТ по РД 153-34.0-35.301-2002 и ГОСТ 7746-2015;
- релиз 2.1 — чек-лист требований ПУЭ.

**Ограничения текущего релиза:**
- ТТ классов точности P / PX / TPX с замкнутым магнитопроводом;
- одноэкспоненциальная апериодическая составляющая (T_р.экв); расчёт по сумме воздействий
  отдельных ветвей (п. 5.2.3, формула 15) будет добавлен позднее;
- для кабеля учитывается только активное сопротивление (индуктивное ~0,07 Ом/км на типовых
  длинах пренебрежимо мало); сопротивления приведены к 20 °С (п. 4.2.1).
""")

# === КОНЕЦ ФАЙЛА app.py ===
