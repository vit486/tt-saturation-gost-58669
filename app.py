"""
⚡ Проверка трансформаторов тока на насыщение при коротких замыканиях.
Методика: ГОСТ Р 58669-2019:
  - раздел 5.1 — аналитический метод;
  - раздел 5.2 — графический метод по паспортным данным (численный эквивалент
    универсальных характеристик приложения Б с динамическими графиками).
Релиз 1.3: графический метод по паспортным данным с динамическими графиками;
вкладка «Теория» обновлена (кириллические обозначения, «+1» в знаменателе
формул (3)/(6)).

Структура проекта:
  - app.py                        — интерфейс (вкладки, формы, результаты, графики);
  - methods/gost_58669.py         — расчётное ядро ГОСТ Р 58669-2019;
  - methods/reference_examples.py — самопроверка по эталонным примерам стандарта;
  - report/docx_report.py         — генерация отчёта Word.
"""

from datetime import datetime

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Импорт расчётных модулей с диагностикой ошибок структуры репозитория
# ---------------------------------------------------------------------------
try:
    from methods.gost_58669 import (
        CTParams, KZParams, calculate, calculate_graphical, K_R_PRED,
    )
    from methods.reference_examples import run_self_checks, run_self_checks_graphical
    from report.docx_report import build_report
    _IMPORT_ERROR = None
except Exception as e:  # ModuleNotFoundError, ImportError, SyntaxError и др.
    _IMPORT_ERROR = e

if _IMPORT_ERROR is not None:
    st.set_page_config(page_title="Ошибка структуры файлов", page_icon="⚠️")
    st.error(f"Не удалось загрузить расчётные модули: {_IMPORT_ERROR}")
    st.markdown(
        """
Проверьте состав репозитория — должны быть файлы:

| Файл | Признак целостности (поиск по Ctrl+F) |
|---|---|
| `methods/__init__.py` | текст «Пакет расчётных методик» |
| `methods/gost_58669.py` | `def calculate_graphical(` |
| `methods/reference_examples.py` | `def run_self_checks_graphical(` |
| `report/__init__.py` | текст «Пакет генерации отчётов» |
| `report/docx_report.py` | `def build_report(` |

Каждый модуль должен заканчиваться строкой-маркером `# === КОНЕЦ ФАЙЛА ... ===`.
Если файл обрезан при копировании — замените его содержимое полностью.
"""
    )
    st.stop()

# ===========================================================================
# ИНТЕРФЕЙС
# ===========================================================================

st.set_page_config(
    page_title="Проверка ТТ — ГОСТ Р 58669-2019",
    layout="wide",
    page_icon="⚡",
)

st.title("⚡ Проверка трансформаторов тока")
st.caption("Насыщение при КЗ · ГОСТ Р 58669-2019 · аналитический и графический методы · релиз 1.3")

# Пресеты ТТ — задел под будущую базу типовых трансформаторов
PRESETS = {
    "— ввести вручную —": {},
    "Пример: ТОЛ-10 600/5 10P10 15 ВА": dict(
        i1_nom=600.0, i2_nom=5.0, k_nom=10.0, s_nom=15.0, cos_phi_nom=0.8,
        r2=0.12, x2=0.0, r_load_fact=0.35, x_load_fact=0.0,
    ),
    "Пример: ТФЗМ-110 2000/5 10P20 30 ВА": dict(
        i1_nom=2000.0, i2_nom=5.0, k_nom=20.0, s_nom=30.0, cos_phi_nom=0.8,
        r2=0.45, x2=0.0, r_load_fact=0.8, x_load_fact=0.0,
    ),
}

with st.sidebar:
    st.header("⚙️ Исходные данные")

    method = st.radio(
        "Метод определения t_нас",
        ("Аналитический (п. 5.1)", "Графический по паспортным данным (п. 5.2)"),
        help="Аналитический — по формулам (3)/(6). Графический — численный эквивалент "
             "универсальных характеристик приложения Б: кривые K_п.р(t) по формуле (Г.15) "
             "с подбором наихудшей начальной фазы θ.",
    )
    is_graphical = method.startswith("Графический")

    preset_name = st.selectbox("Тип ТТ", list(PRESETS.keys()))
    preset = PRESETS[preset_name]

    st.subheader("Паспортные данные ТТ")
    i1_nom = st.number_input(
        "I1ном, А", min_value=1.0, value=float(preset.get("i1_nom", 1000.0)),
        step=50.0, key=f"{preset_name}_i1")
    i2_nom = st.selectbox(
        "I2ном, А", (1.0, 2.0, 5.0),
        index=(1.0, 2.0, 5.0).index(float(preset.get("i2_nom", 5.0))),
        key=f"{preset_name}_i2")
    k_nom = st.number_input(
        "Kном (предельная кратность)", min_value=1.0,
        value=float(preset.get("k_nom", 10.0)), step=1.0, key=f"{preset_name}_k")
    s_nom = st.number_input(
        "Sном вторичной нагрузки, ВА", min_value=1.0,
        value=float(preset.get("s_nom", 15.0)), step=1.0, key=f"{preset_name}_s")
    cos_phi = st.slider(
        "cos φ ном. нагрузки", 0.1, 1.0,
        float(preset.get("cos_phi_nom", 0.8)), 0.05, key=f"{preset_name}_cos")
    r2 = st.number_input(
        "R2 вторичной обмотки, Ом", min_value=0.0,
        value=float(preset.get("r2", 0.15)), step=0.01, format="%.3f",
        key=f"{preset_name}_r2")
    x2 = st.number_input(
        "X2 вторичной обмотки, Ом", min_value=0.0,
        value=float(preset.get("x2", 0.0)), step=0.01, format="%.3f",
        key=f"{preset_name}_x2")

    st.subheader("Фактическая нагрузка")
    r_load = st.number_input(
        "Rн.факт, Ом", min_value=0.0,
        value=float(preset.get("r_load_fact", 0.5)), step=0.01, format="%.3f",
        key=f"{preset_name}_rl")
    x_load = st.number_input(
        "Xн.факт, Ом", min_value=0.0,
        value=float(preset.get("x_load_fact", 0.0)), step=0.01, format="%.3f",
        key=f"{preset_name}_xl")

    st.subheader("Короткое замыкание")
    i_kz3 = st.number_input("Iкз(3), А", min_value=1.0, value=15000.0, step=100.0)
    tp3 = st.number_input(
        "Tр.экв для трёхфазного КЗ, с", min_value=0.001, value=0.05,
        step=0.005, format="%.3f")
    st.caption("Например: 0.05 с = 50 мс")

    use_kz1 = st.checkbox("Добавить расчёт для однофазного КЗ (п. 4.2.4 ГОСТ)")
    i_kz1 = tp1 = None
    if use_kz1:
        i_kz1 = st.number_input("Iкз(1), А", min_value=1.0, value=12000.0, step=100.0)
        tp1 = st.number_input(
            "Tр.экв для однофазного КЗ, с", min_value=0.001, value=0.05,
            step=0.005, format="%.3f")

    st.subheader("Критерий проверки")
    t_req = st.number_input(
        "Требуемое t_нас, мс (0 — не проверять)", 0.0, 500.0, 0.0, 5.0,
        help="Минимально необходимое время до насыщения по требованиям РЗА "
             "(например, время отключения КЗ с запасом).")

# ---------------------------------------------------------------------------
# Расчёт
# ---------------------------------------------------------------------------
ct = CTParams(i1_nom, i2_nom, k_nom, s_nom, cos_phi, r2, x2, r_load, x_load)

kz_list = [KZParams(i_kz3, tp3, "трёхфазное КЗ")]
if use_kz1:
    kz_list.append(KZParams(i_kz1, tp1, "однофазное КЗ"))

try:
    charts = {}
    if is_graphical:
        results = []
        for kz in kz_list:
            res, ch = calculate_graphical(ct, kz)
            results.append((kz, res))
            charts[kz.label] = ch
    else:
        results = [(kz, calculate(ct, kz)) for kz in kz_list]
except ValueError as e:
    st.error(f"Ошибка исходных данных: {e}")
    st.stop()


def build_verdict(res_list, t_req_ms):
    """Итоговый вывод: минимум по всем режимам и сценариям (п. 4.2.4 ГОСТ)."""
    lines = []
    steady = any(r.status == "steady_saturation" for _, res in res_list for r in res.values())
    t_values = [r.t_nas for _, res in res_list for r in res.values() if r.status == "ok"]
    graphic_needed = any(r.status == "graphic_required"
                         for _, res in res_list for r in res.values())

    if steady:
        verdict = "danger"
        lines.append("A ≤ 1: ток КЗ превышает ток предельной кратности ТТ — насыщение "
                     "наступает в установившемся режиме. Эксплуатация недопустима.")
        lines.append("Рекомендация: выбрать ТТ с большей Kном или большим коэффициентом "
                     "трансформации, либо уменьшить вторичную нагрузку.")
    elif not t_values:
        if graphic_needed:
            verdict = "warning"
            lines.append("Аналитический метод неприменим ни в одном сценарии — "
                         "требуется графический метод (п. 5.1.5 ГОСТ).")
        else:
            verdict = "success"
            lines.append("Во всех расчётных режимах насыщение магнитопровода отсутствует.")
    else:
        t_min_ms = min(t_values) * 1000.0
        lines.append(f"Наименьшее время до насыщения по всем режимам и сценариям: "
                     f"{t_min_ms:.1f} мс.")
        if t_req_ms > 0:
            if t_min_ms >= t_req_ms:
                verdict = "success"
                lines.append(f"Требование выполняется: {t_min_ms:.1f} мс ≥ {t_req_ms:g} мс.")
            else:
                verdict = "danger"
                lines.append(f"Требование НЕ выполняется: {t_min_ms:.1f} мс < {t_req_ms:g} мс.")
                lines.append("Рекомендация: выбрать ТТ с большей Kном или Sном, либо "
                             "уменьшить сопротивление вторичной цепи.")
        else:
            verdict = "success"
        if verdict == "success" and graphic_needed:
            verdict = "warning"
            lines.append("Для сценария с остаточной намагниченностью аналитический метод "
                         "неприменим (п. 5.1.5) — переключитесь на графический метод, "
                         "чтобы получить численное значение.")
    return verdict, lines


verdict, verdict_lines = build_verdict(results, t_req)
verdict_lines.insert(
    0,
    "Метод расчёта: графический по паспортным данным (п. 5.2), численный эквивалент "
    "универсальных характеристик приложения Б."
    if is_graphical else
    "Метод расчёта: аналитический (п. 5.1 ГОСТ Р 58669-2019)."
)


def render_knp_chart(t_ms, block, title):
    """График K_п.р(t): наихудшая θ и θ=0, уровень A·(1−K_r), маркер t_нас."""
    n = len(t_ms)
    df = pd.DataFrame({
        "t_ms": list(t_ms) + list(t_ms),
        "k": list(block["k_worst"]) + list(block["k_theta0"]),
        "curve": ["наихудшая θ"] * n + ["θ = 0"] * n,
    })
    lines = alt.Chart(df).mark_line().encode(
        x=alt.X("t_ms:Q", title="t, мс"),
        y=alt.Y("k:Q", title="K_п.р",
                scale=alt.Scale(domain=(0.0, block["a_eff"] * 1.6 + 0.5))),
        color=alt.Color("curve:N", title="Начальная фаза"),
    )
    rule = alt.Chart(pd.DataFrame({"level": [block["a_eff"]]})).mark_rule(
        color="#d62728", strokeDash=[5, 3], strokeWidth=1.5
    ).encode(y="level:Q")
    layers = lines + rule
    if block.get("t_nas_ms") is not None:
        pt = pd.DataFrame({"t_ms": [block["t_nas_ms"]], "k": [block["a_eff"]]})
        layers += alt.Chart(pt).mark_point(color="#d62728", size=120, filled=True).encode(
            x="t_ms:Q", y="k:Q")
    st.altair_chart(layers.properties(width="container", height=260, title=title))


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

    for kz, res in results:
        st.subheader(f"Режим: {kz.label}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Iкз", f"{kz.i_kz:g} А")
        c2.metric("Kфакт = Iкз / I1ном", f"{kz.i_kz / ct.i1_nom:.2f}")
        c3.metric("Tр.экв", f"{kz.t_p * 1000:.0f} мс")

        rows = []
        for name, key in (("Без остаточной намагниченности (K_r = 0)", "without_residual"),
                          (f"С предельной остаточной намагниченностью (K_r = {K_R_PRED})",
                           "with_residual")):
            r = res[key]
            if r.status == "ok":
                t_str = f"{r.t_nas * 1000:.1f} мс"
            elif r.status == "no_saturation":
                t_str = "∞ — насыщения нет"
            elif r.status == "steady_saturation":
                t_str = "0 мс — насыщение в установившемся режиме"
            else:
                t_str = "требуется графический метод"
            rows.append({"Сценарий": name, "Параметр A": round(r.a, 3),
                         "Время до насыщения": t_str})
        st.table(rows)

        for key in ("without_residual", "with_residual"):
            for note in res[key].notes:
                st.caption(f"• {note}")

        if is_graphical:
            ch = charts[kz.label]
            st.caption(
                f"Угол ветви вторичного тока: cos α = {ch['cos_alpha']:.3f} "
                f"(α = {ch['alpha_deg']:.1f}°) — формула (12)."
            )
            col_a, col_b = st.columns(2)
            with col_a:
                sc = ch["scenarios"]["without_residual"]
                if sc is not None:
                    render_knp_chart(ch["t_ms"], sc, "Сценарий K_r = 0")
                else:
                    st.info("График для этого сценария не строится (см. примечания выше).")
            with col_b:
                sc = ch["scenarios"]["with_residual"]
                if sc is not None:
                    render_knp_chart(ch["t_ms"], sc, f"Сценарий K_r = {K_R_PRED}")
                else:
                    st.info("График для этого сценария не строится (см. примечания выше).")

    with st.expander("🔍 Промежуточные величины"):
        st.markdown(
            f"- zн.ном = Sном / I2ном² = **{ct.z_n_nom:.4f} Ом**\n"
            f"- z2Σном (формула 10) = **{ct.z2_sigma_nom:.4f} Ом**\n"
            f"- z2Σ (формула 11) = **{ct.z2_sigma:.4f} Ом**\n"
            f"- ω = 2π·50 = **314.16 рад/с**"
        )

    st.divider()
    report_bytes = build_report(ct, results, verdict_lines, verdict, t_req)
    st.download_button(
        "📄 Скачать отчёт (.docx)",
        data=report_bytes,
        file_name=f"Otchet_TT_GOST_58669_{datetime.now():%Y%m%d_%H%M}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

with tab_check:
    st.markdown(
        "Автоматическая сверка расчёта с **эталонными примерами ГОСТ Р 58669-2019** "
        "с учётом Поправки (ИУС 6–7, 2020). Если хотя бы одна строка ❌ — "
        "результатам расчёта доверять нельзя."
    )

    st.subheader("Аналитический метод — примеры В.1.1–В.1.3 (Приложение В)")
    st.caption("Допуски: параметр A ±0,02; время ±0,2 мс (в стандарте значения округлены).")
    check_rows, ok_an = run_self_checks()
    st.dataframe(check_rows, hide_index=True)
    st.caption(
        "Примечание: в примере В.1.2 в тексте стандарта опечатка (в исходных данных "
        "Kном=20, расчёт выполнен при Kном=18) — в эталоне принято Kном=18."
    )

    st.subheader("Графический метод — пример В.2.1 (Приложение Б)")
    st.caption(
        "Допуск ±1 мс: в стандарте значения снимались с универсальных характеристик; "
        "расчёт выполнен численно по формуле (Г.15) с подбором наихудшей θ."
    )
    g_rows, ok_gr = run_self_checks_graphical()
    st.dataframe(g_rows, hide_index=True)

    if ok_an and ok_gr:
        st.success("✅ Все эталонные примеры воспроизведены — расчётные формулы "
                   "соответствуют ГОСТ Р 58669-2019.")
    else:
        st.error("❌ Обнаружено расхождение с эталонными примерами. Пользоваться "
                 "результатами расчёта до устранения не следует.")

with tab_theory:
    st.markdown("### Методы ГОСТ Р 58669-2019, реализованные в приложении")
    st.markdown(
        "Обозначения приведены в точности как в тексте стандарта и в расчётном ядре "
        "(`methods/gost_58669.py`)."
    )

    st.markdown("#### 1. Аналитический метод (раздел 5.1)")
    st.markdown("Номинальная нагрузка:")
    st.code("zн.ном = Sном / I2ном²", language="text")
    st.markdown("Номинальное полное сопротивление вторичной нагрузки ТТ (формула 10):")
    st.code("z2Σном = √( (R2 + zн.ном·cos φном)² + (X2 + zн.ном·sin φном)² )",
            language="text")
    st.markdown("Полное сопротивление ветви вторичного тока (формула 11):")
    st.code("z2Σ = √( (R2 + Rн.факт)² + (X2 + Xн.факт)² )", language="text")
    st.markdown("Параметр режима A (формула 9):")
    st.code("A = ( I1ном · Kном · z2Σном ) / ( Iкз · z2Σ )", language="text")
    st.markdown(
        f"Время до насыщения — без остаточной намагниченности (формула 3) и с предельной "
        f"остаточной намагниченностью K_r = {K_R_PRED} (формула 6):"
    )
    st.code("t_нас = T_p · ln( ω·T_p / ( ω·T_p + 1 - A·(1 - K_r) ) )", language="text")
    st.warning("В формулах (3)/(6) «+1» присутствует **только в знаменателе**; "
               "в числителе — только ω·T_p.")
    st.markdown("Контрольный пример стандарта (Приложение В, п. В.1.1.8):")
    st.code("t(3) = 0,128 · ln( 314·0,128 / ( 314·0,128 - 5,785 + 1 ) ) = 16,22 мс",
            language="text")

    st.markdown("#### 2. Графический метод по паспортным данным (раздел 5.2)")
    st.markdown("Угол ветви вторичного тока (формула 12):")
    st.code("cos α = (R2 + Rн.факт) / z2Σ", language="text")
    st.markdown(
        "Коэффициент переходного режима K_п.р(t) — формула (Г.15) для начальной фазы θ "
        "апериодической составляющей тока КЗ:"
    )
    st.code(
        "K_п.р(t) = sin α·cos θ·e^(−t/T_p) + cos α·cos θ·ω·T_p·(1 − e^(−t/T_p))\n"
        "           − sin(ω·t + α + θ) + cos α·sin θ",
        language="text",
    )
    st.markdown("Время до насыщения определяется из решения уравнений (13)/(14):")
    st.code("K_п.р(t_нас) = A·(1 - K_r)", language="text")
    st.markdown(
        "при **наихудшей начальной фазе θ**, при которой t_нас минимально (п. Г.3.7). "
        "Реализация — численный эквивалент универсальных характеристик приложения Б: "
        "кривые строятся непосредственно по формуле (Г.15) и динамически "
        "перестраиваются при изменении исходных данных. Проверено примером В.2.1 "
        "(16,8/9,6 мс при K_r = 0 и 4,2/3,2 мс при K_r = 0,86). Графический метод "
        "применим и когда условие (8) не выполняется (A·(1−K_r) ≤ 1) и аналитический "
        "метод отказывает в расчёте."
    )

    st.markdown("""
#### 3. Проверяемые условия

| Условие | Смысл | Действие при нарушении |
|---|---|---|
| A > 1 (условие 5) | ток предельной кратности больше тока КЗ | эксплуатация ТТ недопустима |
| A·(1-K_r) > 1 (условие 8) | применимость формулы времени аналитического метода | графический метод (п. 5.1.5) |
| ω·T_p + 1 > A·(1-K_r) (условие 7) | наличие насыщения | насыщения нет, t_нас = ∞ |
| t_нас ≥ 15 мс (п. 5.1.7) | точность аналитического метода | уточнить графическим методом |

Расчёт выполняется для трёхфазного и (в сетях с глухозаземлённой нейтралью) однофазного КЗ;
итогом является **наименьшее** из полученных значений (п. 4.2.4).
""")

with tab_about:
    st.markdown("""
Приложение выполняет проверку трансформаторов тока на насыщение при коротких замыканиях
по **ГОСТ Р 58669-2019**: аналитический метод (раздел 5.1) и графический метод по
паспортным данным (раздел 5.2 — численный эквивалент универсальных характеристик
с динамическими графиками).

**История релизов:**
- **Релиз 1.3 (22.10.2026):** графический метод по паспортным данным — кривые K_п.р(t)
  по формуле (Г.15) с подбором наихудшей начальной фазы θ, динамические графики с уровнем
  A·(1−K_r) и маркером t_нас; самопроверка дополнена примером В.2.1; вкладка «Теория»
  обновлена (кириллические обозначения, «+1» в знаменателе формул (3)/(6)).
- **Релиз 1.2:** модульная структура (`methods/`, `report/`), диагностика структуры
  файлов репозитория.
- **Релиз 1.1:** исправлена формула времени до насыщения (числитель ω·T_p), добавлена
  вкладка «Самопроверка» по эталонным примерам Приложения В.
- **Релиз 1.0:** аналитический метод ГОСТ Р 58669-2019, отчёт в Word.

**Планы развития:**
- релиз 1.4 — ГОСТ Р 71879-2024: классы 5PR/10PR/TPY/TPZ, циклы АПВ (второе КЗ);
- релиз 1.5 — выбор ТТ по ГОСТ Р 71403-2024;
- релиз 1.6 — справочные данные ГОСТ Р 70507.2-2024 (классы, диапазоны параметров);
- релиз 1.7 — проверка эксплуатируемых ТТ по РД 153-34.0-35.301-2002 (включая 6–10 кВ)
  и ГОСТ 7746-2015;
- релиз 1.8 — чек-лист требований ПУЭ;
- далее — графические методы по ВАХ (п. 5.3) и по характеристике намагничивания (п. 5.4).

**Ограничения текущего релиза:**
- только ТТ классов точности P / PX / TPX с замкнутым магнитопроводом;
- используется эквивалентная постоянная времени T_р.экв (расчёт по сумме воздействий
  апериодических составляющих отдельных ветвей по п. 5.2.3 — в планах).
""")

# === КОНЕЦ ФАЙЛА app.py ===
