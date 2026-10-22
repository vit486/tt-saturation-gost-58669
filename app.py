"""
⚡ Проверка трансформаторов тока на насыщение при коротких замыканиях.
Методика: ГОСТ Р 58669-2019.
Релиз 1.4: графики K_п.р(t) в Word-отчёте; ручное задание начальной фазы θ
для графического метода (автоматический θ* остаётся по умолчанию).

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

import numpy as np      # noqa: E402  (зависимость Streamlit, гарантированно установлена)
import pandas as pd     # noqa: E402

# ===========================================================================
# ИНТЕРФЕЙС
# ===========================================================================

st.set_page_config(page_title="Проверка ТТ — ГОСТ Р 58669-2019", layout="wide", page_icon="⚡")

st.title("⚡ Проверка трансформаторов тока")
st.caption("Насыщение при КЗ · ГОСТ Р 58669-2019 · аналитический и графический методы "
           "· релиз 1.4")

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

PRESETS = {
    "— ввести вручную —": {},
    "Пример: ТОЛ-10 600/5 10P10 15 ВА": dict(
        i1_nom=600.0, i2_nom=5.0, k_nom=10.0, s_nom=15.0, cos_phi_nom=0.8,
        r2=0.12, x2=0.0, r_load_fact=0.35, x_load_fact=0.0),
    "Пример: ТФЗМ-110 2000/5 10P20 30 ВА": dict(
        i1_nom=2000.0, i2_nom=5.0, k_nom=20.0, s_nom=30.0, cos_phi_nom=0.8,
        r2=0.45, x2=0.0, r_load_fact=0.8, x_load_fact=0.0),
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

    st.subheader("Фактическая нагрузка")
    r_load = st.number_input("Rн.факт, Ом", min_value=0.0,
                             value=float(preset.get("r_load_fact", 0.5)), step=0.01,
                             format="%.3f", key=f"{preset_name}_rl")
    x_load = st.number_input("Xн.факт, Ом", min_value=0.0,
                             value=float(preset.get("x_load_fact", 0.0)), step=0.01,
                             format="%.3f", key=f"{preset_name}_xl")

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

# ---------------------------------------------------------------------------
# Расчёт
# ---------------------------------------------------------------------------
ct = CTParams(i1_nom, i2_nom, k_nom, s_nom, cos_phi, r2, x2, r_load, x_load)

kz_list = [KZParams(i_kz3, tp3, "трёхфазное КЗ")]
if use_kz1:
    kz_list.append(KZParams(i_kz1, tp1, "однофазное КЗ"))

try:
    with st.spinner("Расчёт времени до насыщения…"):
        results = [(kz, calculate(ct, kz, method, theta_override)) for kz in kz_list]
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
        return "неприменим (усл. 8) — см. графический метод"
    return "—"


def build_verdict(res_list, t_req_ms, active_keys, use_method):
    """Итоговый вывод: минимум по всем режимам и сценариям (п. 4.2.4 ГОСТ)."""
    lines, t_values = [], []
    steady = any(res[k].status == ST_STEADY for _, res in res_list for k in ANALYTIC_KEYS
                 if res[k].k_r == 0.0)
    graphic_needed = any(res[k].status == ST_GRAPHIC_REQUIRED for _, res in res_list
                         for k in ANALYTIC_KEYS)
    for _, res in res_list:
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


def render_kpr_chart(kz, gres, eff):
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

    df, df_lvl, df_pt, wide = curve_frames(kz.t_p, ct.alpha, gres.theta_star, eff,
                                           t_nas_ms, t_end, star_label)
    theta_txt = ("θ = 0°" if gres.theta_star is None
                 else (f"θ = {math.degrees(gres.theta_star):.1f}°"
                       + (" (вручную)" if gres.theta_manual else " (θ*)")))
    title = (f"K_п.р(t) по формуле (Г.15) · {kz.label} · {theta_txt} · "
             f"T_p = {kz.t_p * 1000:.0f} мс · cos α = {ct.cos_alpha:.3f}")
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

    for kz, res in results:
        st.subheader(f"Режим: {kz.label}")
        a_val = res[ANALYTIC_KEYS[0]].a
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Iкз", f"{kz.i_kz:g} А")
        c2.metric("Kфакт = Iкз / I1ном", f"{kz.i_kz / ct.i1_nom:.2f}")
        c3.metric("Tр.экв", f"{kz.t_p * 1000:.0f} мс")
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

        if method in ("graphic", "both"):
            g0 = res.get("graphic_without_residual")
            gr = res.get("graphic_with_residual")
            if g0 is not None:
                with st.expander("📈 График K_п.р(t) — без остаточной намагниченности",
                                 expanded=(method == "graphic")):
                    render_kpr_chart(kz, g0, a_val)
            if gr is not None:
                with st.expander(f"📈 График K_п.р(t) — с остаточной намагниченностью "
                                 f"K_r = {K_R_PRED}"):
                    render_kpr_chart(kz, gr, a_val * (1.0 - K_R_PRED))

    if method == "both":
        st.markdown("#### Сравнение методов")
        cmp_rows = []
        for kz, res in results:
            for k_a, k_g in zip(ANALYTIC_KEYS, GRAPHIC_KEYS):
                ra, rg = res[k_a], res[k_g]
                ta = ra.t_nas * 1000.0 if (ra.status == ST_OK and ra.t_nas) else None
                tg = rg.t_nas * 1000.0 if (rg.status == ST_OK and rg.t_nas) else None
                dev = f"{(ta - tg) / tg * 100.0:+.1f}%" if (ta and tg) else "—"
                sc = ("без остаточной намагниченности" if k_a == "without_residual"
                      else f"K_r = {K_R_PRED}")
                cmp_rows.append({
                    "Режим": kz.label, "Сценарий": sc,
                    "Аналитический": round(ta, 2) if ta else fmt_t(ra),
                    "Графический": round(tg, 2) if tg else fmt_t(rg),
                    "Отклонение аналитики": dev,
                })
        st.table(cmp_rows)
        st.caption("Аналитический метод — приближённый: п. 5.1.7 ограничивает его применимость "
                   "снизу значением 15 мс, а п. 5.1.5 направляет к графическому методу при "
                   "A·(1−K_r) ≤ 1. Определяющим является графический метод.")

    with st.expander("🔍 Промежуточные величины"):
        st.markdown(
            f"- zн.ном = Sном / I2ном² = **{ct.z_n_nom:.4f} Ом**\n"
            f"- z2Σном (формула 10) = **{ct.z2_sigma_nom:.4f} Ом**\n"
            f"- z2Σ (формула 11) = **{ct.z2_sigma:.4f} Ом**\n"
            f"- cos α (формула 12) = (R2 + Rн.факт) / z2Σ = **{ct.cos_alpha:.4f}** "
            f"(α = {math.degrees(ct.alpha):.2f}°)\n"
            f"- ω = 2π·50 = **314.16 рад/с**"
        )

    st.divider()
    report_bytes = build_report(ct, results, verdict_lines, verdict, t_req, method)
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
               "Самопроверка использует автоматический выбор θ; ручной ввод θ на эталоны не влияет.")

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

    st.markdown("### 1. Исходные величины (одинаковы для обоих методов)")
    st.code("zн.ном = Sном / I2ном²", language="text")
    st.code("z2Σном = √( (R2 + zн.ном·cos φном)² + (X2 + zн.ном·sin φном)² )     (10)",
            language="text")
    st.code("z2Σ    = √( (R2 + Rн.факт)² + (X2 + Xн.факт)² )                     (11)",
            language="text")
    st.code("A      = ( I1ном · Kном · z2Σном ) / ( Iкз · z2Σ )                  (9)",
            language="text")
    st.code("cos α  = ( R2 + Rн.факт ) / z2Σ                                     (12)",
            language="text")

    st.markdown("### 2. Аналитический метод (раздел 5.1)")
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

    st.markdown("### 3. Графический метод по паспортным данным (раздел 5.2)")
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
        "чек-бокс «Задать θ вручную» в панели слева; тогда расчёт и график строятся для этой θ. "
        "Это полезно, например, для анализа конкретной осциллограммы с известной фазой КЗ."
    )
    st.markdown(
        "**Преимущества графического метода:**\n"
        "- работает там, где аналитический отказывает: при A·(1−K_r) ≤ 1 (п. 5.1.5) "
        "и при t_нас < 15 мс (п. 5.1.7);\n"
        "- учитывает наихудшую начальную фазу θ, которая обычно не равна нулю "
        "(в эталонных примерах θ* = 5…36°);\n"
        "- не ограничен диапазоном T_p = 30–300 мс."
    )

    st.markdown("### 4. Порядок расчёта по стандарту")
    st.markdown(
        "1. Расчёт выполняется для трёхфазного КЗ, а в сетях с глухозаземлённой нейтралью — "
        "и для однофазного; итогом является **наименьшее** из полученных значений (п. 4.2.4).\n"
        "2. Каждый расчёт проводится дважды: без остаточной намагниченности и с предельной "
        f"(K_r = {K_R_PRED}) — п. 4.3.\n"
        "3. Эквивалентная постоянная времени T_р.экв определяется по формуле (1) или "
        "по осциллограмме (п. 4.2.7)."
    )

with tab_about:
    st.markdown("""
Приложение выполняет проверку трансформаторов тока на насыщение при коротких замыканиях
в соответствии с **ГОСТ Р 58669-2019**.

**Реализованные методы:**
- аналитический (раздел 5.1) — формулы (3), (6), (9)–(12), условия (4), (5), (7), (8), п. 5.1.7;
- графический по паспортным данным (раздел 5.2) — численное воспроизведение универсальных
  характеристик приложения Б по формуле (Г.15) с динамическими графиками и возможностью
  ручного задания начальной фазы θ.

**История релизов:**
- **Релиз 1.4 (22.10.2026):** графики K_п.р(t) добавлены в экспортируемый Word-отчёт
  (рендер через matplotlib); начальная фаза θ графического метода задаётся вручную
  (чек-бокс + поле ввода в панели слева) при сохранении автоматического выбора θ*
  по умолчанию; усилены сообщения об ошибках графиков.
- **Релиз 1.3:** графический метод по паспортным данным, динамические графики,
  переключатель метода, расширенная самопроверка.
- **Релиз 1.2:** модульная структура (`methods/`, `report/`), диагностика структуры файлов.
- **Релиз 1.1:** исправлена формула времени до насыщения (числитель ω·T_p), самопроверка.
- **Релиз 1.0:** аналитический метод ГОСТ Р 58669-2019, отчёт в Word.

**Планы развития:**
- релиз 1.5 — графические методы по ВАХ (п. 5.3) и по характеристике намагничивания (п. 5.4);
- релиз 1.6 — ГОСТ Р 71879-2024: классы 5PR/10PR/TPY/TPZ, циклы АПВ (второе КЗ);
- релиз 1.7 — выбор ТТ по ГОСТ Р 71403-2024;
- релиз 1.8 — справочные данные ГОСТ Р 70507.2-2024;
- релиз 1.9 — проверка эксплуатируемых ТТ по РД 153-34.0-35.301-2002 и ГОСТ 7746-2015;
- релиз 2.0 — чек-лист требований ПУЭ.

**Ограничения текущего релиза:**
- ТТ классов точности P / PX / TPX с замкнутым магнитопроводом;
- одноэкспоненциальная апериодическая составляющая (T_р.экв); расчёт по сумме воздействий
  отдельных ветвей (п. 5.2.3, формула 15) будет добавлен позднее.
""")

# === КОНЕЦ ФАЙЛА app.py ===
