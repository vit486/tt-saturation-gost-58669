import streamlit as st

from methods.gost_58669 import CTParams, KZParams, calculate, K_R_PRED
from report.docx_report import build_report

st.set_page_config(
    page_title="Проверка ТТ — ГОСТ Р 58669-2019",
    layout="wide",
    page_icon="⚡",
)

st.title("⚡ Проверка трансформаторов тока")
st.caption("Насыщение при КЗ · ГОСТ Р 58669-2019 · аналитический метод")

# ---------------------------------------------------------------------------
# Пресеты ТТ — задел под будущую базу типовых трансформаторов
# ---------------------------------------------------------------------------
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

    preset_name = st.selectbox("Тип ТТ", list(PRESETS.keys()))
    preset = PRESETS[preset_name]

    st.subheader("Паспортные данные ТТ")
    i1_nom = st.number_input("I1ном, А", min_value=1.0, value=float(preset.get("i1_nom", 1000.0)),
                             step=50.0, key=f"{preset_name}_i1")
    i2_nom = st.selectbox("I2ном, А", (1.0, 2.0, 5.0),
                          index=(1.0, 2.0, 5.0).index(float(preset.get("i2_nom", 5.0))),
                          key=f"{preset_name}_i2")
    k_nom = st.number_input("Kном (предельная кратность)", min_value=1.0,
                            value=float(preset.get("k_nom", 10.0)), step=1.0, key=f"{preset_name}_k")
    s_nom = st.number_input("Sном вторичной нагрузки, ВА", min_value=1.0,
                            value=float(preset.get("s_nom", 15.0)), step=1.0, key=f"{preset_name}_s")
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
    results = [(kz, calculate(ct, kz)) for kz in kz_list]
except ValueError as e:
    st.error(f"Ошибка исходных данных: {e}")
    st.stop()


def build_verdict(res_list, t_req_ms):
    """Итоговый вывод: минимальное время по всем режимам и сценариям (п. 4.2.4)."""
    lines = []
    steady = any(r["without_residual"].status == "steady_saturation" for _, r in res_list)
    t_values = [r.t_nas for _, res in res_list for r in res.values() if r.status == "ok"]

    if steady:
        verdict = "danger"
        lines.append("A ≤ 1: ток КЗ превышает ток предельной кратности ТТ — насыщение "
                     "наступает в установившемся режиме. Эксплуатация недопустима.")
        lines.append("Рекомендация: выбрать ТТ с большей Kном или большим коэффициентом "
                     "трансформации, либо уменьшить вторичную нагрузку.")
    elif not t_values:
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
    return verdict, lines


verdict, verdict_lines = build_verdict(results, t_req)

# ---------------------------------------------------------------------------
# Вкладки
# ---------------------------------------------------------------------------
tab_calc, tab_theory, tab_about = st.tabs([
    "🧮 Результаты расчёта",
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
        st.dataframe(rows, hide_index=True, use_container_width=True)

        for key in ("without_residual", "with_residual"):
            for note in res[key].notes:
                st.caption(f"• {note}")

    with st.expander("🔍 Промежуточные величины"):
        st.write(
            f"- zн.ном = Sном / I2ном² = **{ct.z_n_nom:.4f} Ом**\n"
            f"- z2Σном (формула 10) = **{ct.z2_sigma_nom:.4f} Ом**\n"
            f"- z2Σ (формула 11) = **{ct.z2_sigma:.4f} Ом**\n"
            f"- ω = 2π·50 = **314.16 рад/с**"
        )

    st.divider()
    report_bytes = build_report(ct, kz_list, results, verdict_lines, verdict, t_req)
    st.download_button(
        "📄 Скачать отчёт (.docx)",
        data=report_bytes,
        file_name=f"Otchet_TT_GOST_58669_{__import__('datetime').datetime.now():%Y%m%d_%H%M}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

with tab_theory:
    st.markdown("""
### Аналитический метод (раздел 5.1 ГОСТ Р 58669-2019)

**1. Сопротивления вторичной цепи**

Номинальная нагрузка: `zн.ном = Sном / I2ном²`

Номинальное полное сопротивление вторичной нагрузки ТТ (формула 10):
""")
    st.latex(r"z_{2\Sigma\,ном} = \sqrt{(R_2 + z_{н.ном}\cos\varphi_{ном})^2 + "
             r"(X_2 + z_{н.ном}\sin\varphi_{ном})^2}")
    st.markdown("Полное сопротивление ветви вторичного тока (формула 11):")
    st.latex(r"z_{2\Sigma} = \sqrt{(R_2 + R_{н.факт})^2 + (X_2 + X_{н.факт})^2}")

    st.markdown("**2. Параметр режима A (формула 9)** — отношение потокосцепления насыщения "
                "к амплитуде потокосцепления от периодической составляющей тока КЗ:")
    st.latex(r"A = \frac{I_{1ном} \cdot K_{ном} \cdot z_{2\Sigma\,ном}}{I_{КЗ} \cdot z_{2\Sigma}}")

    st.markdown("**3. Время до насыщения**")
    st.markdown(f"Без остаточной намагниченности (формула 3) и с предельной остаточной "
                f"намагниченностью K_r = {K_R_PRED} (формула 6):")
    st.latex(r"t_{нас} = T_p \cdot \ln\frac{\omega T_p + 1}{\omega T_p + 1 - A(1 - K_r)}")

    st.markdown("""
**4. Проверяемые условия**

| Условие | Смысл | Действие при нарушении |
|---|---|---|
| A > 1 (5) | ток предельной кратности больше тока КЗ | эксплуатация ТТ недопустима |
| A·(1−K_r) > 1 (8) | применимость формулы (6) | графический метод (п. 5.1.5) |
| ω·T_p + 1 > A·(1−K_r) (7) | наличие насыщения | насыщения нет, t_нас = ∞ |
| t_нас ≥ 15 мс (п. 5.1.7) | точность аналитического метода | уточнить графическим методом |

Расчёт выполняется для трёхфазного и (в сетях с глухозаземлённой нейтралью) однофазного КЗ;
итогом является **наименьшее** из полученных значений (п. 4.2.4).
""")

with tab_about:
    st.markdown("""
Приложение выполняет проверку трансформаторов тока на насыщение при коротких замыканиях
в соответствии с **ГОСТ Р 58669-2019** (аналитический метод, раздел 5.1).

**Ограничения текущего релиза:**
- только аналитический метод (графические методы по универсальным характеристикам, ВАХ
  и характеристике намагничивания — в планах);
- только ТТ классов точности P / PX / TPX с замкнутым магнитопроводом.

**Планы развития:**
- проверка ТТ по 10%-й погрешности (ГОСТ 7746);
- выбор ТТ из базы типовых моделей;
- графический метод по универсальным характеристикам (приложение Б);
- поддержка ГОСТ Р 71879-2024.

Архитектура модульная: новые методики добавляются отдельными файлами в пакет `methods/`
без изменения интерфейса.
""")