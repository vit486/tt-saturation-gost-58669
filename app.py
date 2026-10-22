"""
⚡ Проверка трансформаторов тока на насыщение при коротких замыканиях.
Методика: ГОСТ Р 58669-2019.
Релиз 1.7: метод по характеристике намагничивания (п. 5.4), графики ВАХ и B(H)
в Word-отчёте, схема «треугольник», исправленные коэффициенты расчётной длины.
"""

import math
from datetime import datetime

import streamlit as st

try:
    from methods.gost_58669 import (
        ANALYTIC_KEYS, CTParams, GRAPHIC_KEYS, K_R_PRED, KZParams, ST_GRAPHIC_REQUIRED,
        ST_NO_SAT, ST_OK, ST_STEADY, VAH_KEYS, BN_KEYS, build_kpr_curve, calculate,
        build_vah_default, build_bn_default, calc_a_from_vah, calc_u2sin, calc_a_from_bn,
        validate_vah_usage, validate_bn_usage, _graphic,
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
Проверьте состав репозитория — должны быть файлы:

| Файл | Признак целостности (поиск Ctrl+F) |
|---|---|
| `methods/gost_58669.py` | `def build_bn_default(` |
| `methods/reference_examples.py` | `def run_graphic_checks(` |
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
           "· релиз 1.7")

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
    "vah_without_residual": "По ВАХ · без остаточной намагниченности (K_r = 0)",
    "vah_with_residual": f"По ВАХ · с остаточной намагниченностью (K_r = {K_R_PRED})",
    "bn_without_residual": "По B(H) · без остаточной намагниченности (K_r = 0)",
    "bn_with_residual": f"По B(H) · с остаточной намагниченностью (K_r = {K_R_PRED})",
}
LBL_STAR_AUTO = "θ = θ* — расчётный минимум (п. Г.3.7)"
LBL_ZERO = "θ = 0° — максимум апериодической составляющей"

# Коэффициенты расчётной длины кабеля: (трёхфазное КЗ, однофазное КЗ).
# Исправлено по Приложению А ГОСТ Р 58669-2019:
#  - полная звезда: трёхфазное 1 (ток нейтрали = 0), однофазное 2;
#  - неполная звезда: √3 для обоих (общий провод несёт ток неповреждённой фазы);
#  - треугольник: 3 для обоих;
#  - один ТТ: 2 для обоих.
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
             "обратный ток протекает по разному числу проводов. Коэффициенты — по Приложению А "
             "ГОСТ Р 58669-2019.")
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
        st.markdown("**Параметры типовой ВАХ**:")
        u_star_input = st.number_input(
            "U* — напряжение при полной погрешности ε, В", min_value=1.0,
            value=100.0, step=10.0,
            help="Напряжение на выводах вторичной обмотки при токе намагничивания, "
                 "соответствующем полной погрешности ТТ (обычно при 10% погрешности).")
        i0_star_input = st.number_input(
            "I₀* — ток намагничивания при U*, А", min_value=0.001,
            value=1.0, step=0.1, format="%.3f",
            help="Ток намагничивания в точке U*.")
        vah_data = {'u_star': u_star_input, 'i0_star': i0_star_input}

    st.subheader("Метод по характеристике намагничивания (опционально)")
    use_bn = st.checkbox(
        "Использовать метод по B(H) (п. 5.4)", value=False,
        help="Метод использует характеристику намагничивания B(H) для более точного расчёта. "
             "Требует дополнительных данных ТТ: число витков, сечение и длину магнитопровода.")
    bn_data = None
    bn_params = None
    if use_bn:
        st.markdown("**Параметры магнитопровода ТТ:**")
        w2_input = st.number_input(
            "w2 — число витков вторичной обмотки", min_value=10,
            value=2000, step=100,
            help="Число витков вторичной обмотки ТТ.")
        s_input = st.number_input(
            "s — сечение сердечника, см²", min_value=1.0,
            value=20.0, step=1.0,
            help="Поперечное сечение сердечника магнитопровода.")
        l_input = st.number_input(
            "l — средняя длина силовой линии, м", min_value=0.1,
            value=1.0, step=0.1,
            help="Средняя длина магнитной силовой линии.")
        st.markdown("**Типовая характеристика намагничивания B(H):**")
        b_sat_input = st.number_input(
            "Bнас — индукция насыщения, Тл", min_value=1.0, max_value=2.5,
            value=1.8, step=0.1,
            help="Магнитная индукция насыщения (для электротехнической стали ~1.8 Тл).")
        h_knee_input = st.number_input(
            "Hколено — напряжённость начала насыщения, А/м", min_value=10,
            value=100, step=10,
            help="Напряжённость магнитного поля в точке перегиба характеристики.")
        bn_data = build_bn_default(b_sat_input, h_knee_input)
        bn_params = {'w2': w2_input, 's': s_input * 1e-4, 'l': l_input}  # s в м²

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

        # Метод по ВАХ для трёхфазного КЗ
        if use_vah and vah_data:
            valid_vah, msg_vah = validate_vah_usage(vah_data['u_star'], vah_data['i0_star'], ct3, kz3)
            if valid_vah:
                u2sin3 = calc_u2sin(ct3, kz3)
                a_vah3 = calc_a_from_vah(vah_data['u_star'], u2sin3)
                vah_res3 = {
                    "vah_without_residual": _graphic(ct3, kz3, 0.0, a_vah3, theta_override),
                    "vah_with_residual": _graphic(ct3, kz3, K_R_PRED, a_vah3, theta_override),
                }
                for key in VAH_KEYS:
                    vah_res3[key].method = "vah"
                    vah_res3[key].notes.insert(0, f"Метод по ВАХ: A = {a_vah3:.3f} (формула 19)")
                results[0][2].update(vah_res3)

        # Метод по характеристике намагничивания для трёхфазного КЗ
        if use_bn and bn_data and bn_params:
            valid_bn, msg_bn = validate_bn_usage(ct3, kz3, bn_data,
                                                 bn_params['w2'], bn_params['s'], bn_params['l'])
            if valid_bn:
                a_bn3 = calc_a_from_bn(ct3, kz3, bn_data,
                                       bn_params['w2'], bn_params['s'], bn_params['l'])
                bn_res3 = {
                    "bn_without_residual": _graphic(ct3, kz3, 0.0, a_bn3, theta_override),
                    "bn_with_residual": _graphic(ct3, kz3, K_R_PRED, a_bn3, theta_override),
                }
                for key in BN_KEYS:
                    bn_res3[key].method = "bn"
                    bn_res3[key].notes.insert(0, f"Метод по B(H): A = {a_bn3:.3f} (формула 23)")
                results[0][2].update(bn_res3)

        # Однофазное КЗ
        if use_kz1:
            ct1 = CTParams(i1_nom, i2_nom, k_nom, s_nom, cos_phi, r2, x2, r_n1, x_load)
            kz1 = KZParams(i_kz1, tp1, "однофазное КЗ")
            res1 = calculate(ct1, kz1, method, theta_override)

            if use_vah and vah_data:
                valid_vah1, _ = validate_vah_usage(vah_data['u_star'], vah_data['i0_star'], ct1, kz1)
                if valid_vah1:
                    u2sin1 = calc_u2sin(ct1, kz1)
                    a_vah1 = calc_a_from_vah(vah_data['u_star'], u2sin1)
                    vah_res1 = {
                        "vah_without_residual": _graphic(ct1, kz1, 0.0, a_vah1, theta_override),
                        "vah_with_residual": _graphic(ct1, kz1, K_R_PRED, a_vah1, theta_override),
                    }
                    for key in VAH_KEYS:
                        vah_res1[key].method = "vah"
                        vah_res1[key].notes.insert(0, f"Метод по ВАХ: A = {a_vah1:.3f} (формула 19)")
                    res1.update(vah_res1)

            if use_bn and bn_data and bn_params:
                valid_bn1, _ = validate_bn_usage(ct1, kz1, bn_data,
                                                 bn_params['w2'], bn_params['s'], bn_params['l'])
                if valid_bn1:
                    a_bn1 = calc_a_from_bn(ct1, kz1, bn_data,
                                           bn_params['w2'], bn_params['s'], bn_params['l'])
                    bn_res1 = {
                        "bn_without_residual": _graphic(ct1, kz1, 0.0, a_bn1, theta_override),
                        "bn_with_residual": _graphic(ct1, kz1, K_R_PRED, a_bn1, theta_override),
                    }
                    for key in BN_KEYS:
                        bn_res1[key].method = "bn"
                        bn_res1[key].notes.insert(0, f"Метод по B(H): A = {a_bn1:.3f} (формула 23)")
                    res1.update(bn_res1)

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
        return "неприменим (усл. 8) — см. графический метод"
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


# ---------------------------------------------------------------------------
# Графики
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
                   "показан упрощённый график.")
        st.line_chart(wide)
    st.caption(f"Зелёная пунктирная линия — уровень насыщения A·(1−K_r) = {eff:.3f}; "
               "точка пересечения с кривой и есть время до насыщения t_нас.")


def render_vah_chart(vah_data, r2):
    """Динамический график ВАХ."""
    vah_plot = build_vah_default(vah_data['u_star'], vah_data['i0_star'], r2)
    df_vah = pd.DataFrame({
        "I0_A": vah_plot['i0'],
        "U_V": vah_plot['u'],
    })
    try:
        import altair as alt
        chart_vah = alt.Chart(df_vah).mark_line(strokeWidth=2, color="#d62728").encode(
            x=alt.X("I0_A:Q", title="Ток намагничивания I₀, А"),
            y=alt.Y("U_V:Q", title="Напряжение U, В"),
            tooltip=["I0_A:Q", "U_V:Q"],
        ).properties(title="Вольт-амперная характеристика ТТ (типовая)", height=300)
        st.altair_chart(chart_vah)
    except Exception as exc:
        st.warning(f"График ВАХ недоступен ({type(exc).__name__}).")
        st.line_chart(df_vah.set_index("I0_A"))
    st.caption(f"Типовая ВАХ построена по точкам U* = {vah_data['u_star']:.1f} В, "
               f"I₀* = {vah_data['i0_star']:.3f} А.")


def render_bn_chart(bn_data):
    """Динамический график характеристики намагничивания B(H)."""
    df_bn = pd.DataFrame({
        "H_A_m": bn_data['h'],
        "B_T": bn_data['b'],
    })
    try:
        import altair as alt
        chart_bn = alt.Chart(df_bn).mark_line(strokeWidth=2, color="#9467bd").encode(
            x=alt.X("H_A_m:Q", title="Напряжённость магнитного поля H, А/м"),
            y=alt.Y("B_T:Q", title="Магнитная индукция B, Тл"),
            tooltip=["H_A_m:Q", "B_T:Q"],
        ).properties(title="Характеристика намагничивания B(H) (типовая)", height=300)
        st.altair_chart(chart_bn)
    except Exception as exc:
        st.warning(f"График B(H) недоступен ({type(exc).__name__}).")
        st.line_chart(df_bn.set_index("H_A_m"))
    st.caption(f"Типовая B(H): Bнас = {bn_data['b_sat']:.2f} Тл, "
               f"Hколено = {bn_data['h_knee']:.0f} А/м.")


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
        if use_vah and vah_data and VAH_KEYS[0] in res:
            st.markdown("#### Метод по ВАХ (п. 5.3)")
            valid_vah, msg_vah = validate_vah_usage(vah_data['u_star'], vah_data['i0_star'], ct_m, kz)
            if valid_vah:
                st.success(f"✅ {msg_vah}")
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
                for k in VAH_KEYS:
                    r = res.get(k)
                    if r is None:
                        continue
                    for note in r.notes:
                        if note not in seen:
                            seen.add(note)
                            st.caption(f"• {note}")
                with st.expander("📈 График ВАХ", expanded=False):
                    render_vah_chart(vah_data, ct_m.r2)
            else:
                st.warning(f"⚠️ {msg_vah}")

        # Метод по характеристике намагничивания
        if use_bn and bn_data and bn_params and BN_KEYS[0] in res:
            st.markdown("#### Метод по характеристике намагничивания (п. 5.4)")
            valid_bn, msg_bn = validate_bn_usage(ct_m, kz, bn_data,
                                                 bn_params['w2'], bn_params['s'], bn_params['l'])
            if valid_bn:
                st.success(f"✅ {msg_bn}")
                bn_rows = []
                for k in BN_KEYS:
                    r = res.get(k)
                    if r is None:
                        continue
                    extra = ""
                    if r.status == ST_OK and r.theta_star is not None:
                        tag = "θ (вручную)" if r.theta_manual else "θ*"
                        extra = f"   ({tag} = {math.degrees(r.theta_star):.1f}°)"
                    bn_rows.append({
                        "Сценарий": "Без остаточной намагниченности" if "without" in k else f"С K_r = {K_R_PRED}",
                        "Время до насыщения": fmt_t(r) + extra,
                    })
                st.table(bn_rows)
                for k in BN_KEYS:
                    r = res.get(k)
                    if r is None:
                        continue
                    for note in r.notes:
                        if note not in seen:
                            seen.add(note)
                            st.caption(f"• {note}")
                with st.expander("📈 Характеристика намагничивания B(H)", expanded=False):
                    render_bn_chart(bn_data)
            else:
                st.warning(f"⚠️ {msg_bn}")

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
    report_bytes = build_report(ct3, chain, results, verdict_lines, verdict, t_req, method,
                                vah_data=vah_data, bn_data=bn_data, bn_params=bn_params)
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
               "Kном = 20, расчёт выполнен при Kном = 18) — в эталоне принято Kном = 18.")

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
        "Все методы решают одно и то же уравнение переходного процесса (п. Г.6.2):\n\n"
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
        "где **ρ** — удельное сопротивление жилы при 20 °С: медь 0,0175 Ом·мм²/м, алюминий "
        "0,0281 Ом·мм²/м; **L** — длина кабеля в одну сторону, м; **S** — сечение жилы, мм²; "
        "**kсх** — коэффициент расчётной длины по Приложению А ГОСТ Р 58669-2019."
    )
    st.markdown("""
| Схема соединения | Трёхфазное КЗ | Однофазное КЗ | Пояснение |
|---|---|---|---|
| Полная звезда (3 ТТ) | 1 | 2 | при симметрии ток нулевого провода равен нулю |
| Неполная звезда (2 ТТ) | √3 ≈ 1,73 | √3 ≈ 1,73 | общий провод несёт ток неповреждённой фазы |
| Треугольник | 3 | 3 | токи циркулируют по трём проводам |
| Один ТТ (2 провода) | 2 | 2 | ток идёт по двум проводам (туда и обратно) |
""")
    st.caption("Индуктивное сопротивление кабеля (~0,06–0,08 Ом/км) на длинах в десятки метров "
               "пренебрежимо мало, поэтому учитывается только активная составляющая.")

    st.markdown("### 2. Исходные величины")
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
    st.code(
        "K_п.р(t) = sin α · cos θ · e^(−t/T_p)\n"
        "         + cos α · cos θ · ω·T_p · ( 1 − e^(−t/T_p) )\n"
        "         − sin( ω·t + α + θ ) + cos α · sin θ                        (Г.15)\n"
        "\n"
        "t_нас:   K_п.р(t_нас) = A·(1 − K_r),  минимум по θ ∈ (−90°, +90°)",
        language="text")
    st.markdown(
        "**Начальная фаза θ.** По умолчанию приложение автоматически находит наихудшую θ* "
        "(минимум t_нас, п. Г.3.7). При необходимости конкретную фазу можно задать вручную."
    )

    st.markdown("### 5. Метод по ВАХ (п. 5.3)")
    st.code("A = U* / U2sin                                                   (19)", language="text")
    st.markdown(
        "где **U*** — напряжение на ВАХ, соответствующее полной погрешности ε; "
        "**U2sin** — напряжение на вторичной обмотке при фактическом токе КЗ:\n\n"
        "`U2sin = I₂ном · Kфакт · z2Σ`\n\n"
        "Параметр A, полученный по ВАХ, используется в графическом методе."
    )
    st.markdown("**Условие применимости (16):**")
    st.code("I₀(ε) / U(ε) / (Iлин / Uлин) > 3", language="text")

    st.markdown("### 6. Метод по характеристике намагничивания (п. 5.4)")
    st.code("A = Bт / Bт(Hг)                                                  (23)", language="text")
    st.markdown(
        "где **Bт** — амплитуда магнитной индукции, рассчитываемая по формуле (24):\n"
        "`Bт = U2sin / (222 · w2 · s)`\n\n"
        "**Hг** — действующее значение напряжённости магнитного поля по формуле (22):\n"
        "`Hг = I₀ε · w2 / l`\n\n"
        "**Bт(Hг)** — значение индукции при H = Hг из характеристики намагничивания.\n"
        "Здесь: **w2** — число витков вторичной обмотки, **s** — сечение сердечника (м²), "
        "**l** — средняя длина силовой линии (м), **I₀ε = 0,1 · I₂ном · Kфакт**."
    )
    st.markdown("**Условие применимости (21):** `Bт > 1,8 Тл` — иначе метод неприменим.")

    st.markdown("### 7. Порядок расчёта по стандарту")
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
- метод по ВАХ (п. 5.3) — построение типовой ВАХ по параметрам U* и I₀*, проверка условия (16),
  расчёт параметра A по формуле (19), использование результата в графическом методе;
- метод по характеристике намагничивания (п. 5.4) — типовая B(H), расчёт A по формуле (23),
  проверка условия (21);
- нагрузка вторичной цепи из параметров всей цепи (п. 4.2.6, Приложение А): приборы, кабель
  (материал, длина, сечение, схема соединения — полная/неполная звезда, треугольник, один ТТ),
  переходные контакты.

**История релизов:**
- **Релиз 1.7 (23.10.2026):** метод по характеристике намагничивания (п. 5.4); графики ВАХ
  и B(H) в Word-отчёте; добавлена схема «треугольник»; исправлены коэффициенты расчётной
  длины для неполной звезды по Приложению А ГОСТ Р 58669-2019.
- **Релиз 1.6:** метод по ВАХ (п. 5.3).
- **Релиз 1.5:** нагрузка вторичной цепи из параметров всей цепи (кабель, приборы, контакты).
- **Релиз 1.4:** графики K_п.р(t) в Word-отчёте; ручное задание начальной фазы θ.
- **Релиз 1.3:** графический метод по паспортным данным, динамические графики.
- **Релиз 1.2:** модульная структура, диагностика структуры файлов.
- **Релиз 1.1:** исправлена формула времени до насыщения, самопроверка.
- **Релиз 1.0:** аналитический метод, отчёт в Word.

**Планы развития:**
- релиз 1.8 — ГОСТ Р 71879-2024: классы 5PR/10PR/TPY/TPZ, циклы АПВ (второе КЗ);
- релиз 1.9 — выбор ТТ по ГОСТ Р 71403-2024;
- релиз 2.0 — справочные данные ГОСТ Р 70507.2-2024;
- релиз 2.1 — проверка эксплуатируемых ТТ по РД 153-34.0-35.301-2002 и ГОСТ 7746-2015;
- релиз 2.2 — чек-лист требований ПУЭ;
- релиз 2.3 — ввод фактических таблиц ВАХ и B(H) из файла.

**Ограничения текущего релиза:**
- ТТ классов точности P / PX / TPX с замкнутым магнитопроводом;
- одноэкспоненциальная апериодическая составляющая (T_р.экв);
- типовые ВАХ и B(H); для точного расчёта требуются фактические характеристики конкретного ТТ;
- сопротивления приведены к 20 °С (п. 4.2.1).
""")

# === КОНЕЦ ФАЙЛА app.py ===
