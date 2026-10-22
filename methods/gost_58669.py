"""
Расчётное ядро: ГОСТ Р 58669-2019
«Релейная защита. Трансформаторы тока измерительные индуктивные с замкнутым
магнитопроводом для защиты. Методические указания по определению времени до
насыщения при коротких замыканиях».

Реализованные методы:

1. Аналитический метод (раздел 5.1):
  - параметр режима A — формула (9), п. 5.1.6;
  - z2Σном — формула (10); z2Σ — формула (11);
  - время до насыщения — формулы (3)/(6);
  - условия (4), (5), (7), (8) — пп. 5.1.4, 5.1.5;
  - порог 15 мс — п. 5.1.7; Kr = 0.86 — п. 5.1.3.

    t_нас = T_p * ln( ω*T_p / (ω*T_p + 1 - A*(1-K_r)) )

  ВАЖНО: «+1» — только в знаменателе. Контрольный пример стандарта
  (Приложение В, п. В.1.1.8):

    t(3) = 0.128 * ln( 314*0.128 / (314*0.128 - 5.785 + 1) ) = 16.22 мс

2. Графический метод по паспортным данным (раздел 5.2, приложение Б):
  численный эквивалент универсальных характеристик — коэффициент переходного
  режима K_п.р(t) по формуле (Г.15), время до насыщения из решения

    K_п.р(t_нас) = A * (1 - K_r)

  при наихудшей начальной фазе апериодической составляющей θ (п. Г.3.7);
  угол ветви вторичного тока α — формула (12).

Корректность обеих веток подтверждается автоматической самопроверкой по
эталонным примерам Приложений В и Б (methods/reference_examples.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

OMEGA = 2.0 * math.pi * 50.0   # угловая частота, рад/с (f = 50 Гц)
K_R_PRED = 0.86                # предельный коэффициент остаточной намагниченности (п. 5.1.3)
T_NAS_MIN_MS = 15.0            # порог применимости аналитического метода (п. 5.1.7)
T_P_RANGE_S = (0.03, 0.30)     # диапазон Tp универсальных характеристик (приложение Б)

# Параметры численного расчёта графического метода
GRAPH_T_MAX_S = 0.30           # расчётное окно, с (300 мс)
GRAPH_DT_S = 2.0e-4            # шаг по времени, с (0.2 мс)
GRAPH_N_THETA = 360            # число начальных фаз θ на интервале 0..2π


@dataclass
class CTParams:
    """Паспортные данные трансформатора тока."""
    i1_nom: float          # номинальный первичный ток, А
    i2_nom: float          # номинальный вторичный ток, А
    k_nom: float           # номинальная предельная кратность
    s_nom: float           # номинальная мощность вторичной нагрузки, ВА
    cos_phi_nom: float     # коэффициент мощности номинальной нагрузки
    r2: float              # активное сопротивление вторичной обмотки, Ом
    x2: float              # индуктивное сопротивление вторичной обмотки, Ом
    r_load_fact: float     # фактическое активное сопротивление нагрузки, Ом
    x_load_fact: float     # фактическое индуктивное сопротивление нагрузки, Ом

    @property
    def z_n_nom(self) -> float:
        """Полное сопротивление номинальной нагрузки, Ом (zн.ном = Sном / I2ном²)."""
        return self.s_nom / (self.i2_nom ** 2)

    @property
    def z2_sigma_nom(self) -> float:
        """Номинальное полное сопротивление вторичной нагрузки ТТ, Ом (формула 10)."""
        sin_phi = math.sqrt(max(0.0, 1.0 - self.cos_phi_nom ** 2))
        return math.sqrt(
            (self.r2 + self.z_n_nom * self.cos_phi_nom) ** 2
            + (self.x2 + self.z_n_nom * sin_phi) ** 2
        )

    @property
    def z2_sigma(self) -> float:
        """Полное сопротивление ветви вторичного тока, Ом (формула 11)."""
        return math.sqrt(
            (self.r2 + self.r_load_fact) ** 2
            + (self.x2 + self.x_load_fact) ** 2
        )


@dataclass
class KZParams:
    """Параметры короткого замыкания."""
    i_kz: float            # действующее значение тока КЗ (первичная сторона), А
    t_p: float             # постоянная времени затухания апериодической составляющей, с
    label: str = "трёхфазное КЗ"


@dataclass
class SaturationResult:
    """Результат для одного режима КЗ и одного значения остаточной намагниченности."""
    a: float                            # параметр режима, формула (9)
    k_r: float                          # коэффициент остаточной намагниченности
    status: str                         # ok | no_saturation | steady_saturation | graphic_required
    t_nas: Optional[float]              # время до насыщения, с (только при status == "ok")
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Аналитический метод (п. 5.1)
# ---------------------------------------------------------------------------

def _calc_one_mode(ct: CTParams, kz: KZParams, k_r: float) -> SaturationResult:
    """Расчёт времени до насыщения для заданного коэффициента остаточной намагниченности."""
    notes: List[str] = []

    if kz.i_kz <= 0:
        raise ValueError("Ток КЗ должен быть больше нуля.")
    if ct.z2_sigma == 0:
        raise ValueError(
            "Полное сопротивление вторичной цепи равно нулю — проверьте исходные данные."
        )

    # Параметр режима A — формула (9) ГОСТ Р 58669-2019
    a = (ct.i1_nom * ct.k_nom * ct.z2_sigma_nom) / (kz.i_kz * ct.z2_sigma)

    # Приложение Б: универсальные характеристики построены для Tp = 30–300 мс
    if not (T_P_RANGE_S[0] <= kz.t_p <= T_P_RANGE_S[1]):
        notes.append(
            f"T_p = {kz.t_p * 1000:.0f} мс выходит за диапазон "
            f"{T_P_RANGE_S[0] * 1000:.0f}–{T_P_RANGE_S[1] * 1000:.0f} мс, "
            "для которого построены универсальные характеристики (приложение Б)."
        )

    effective = a * (1.0 - k_r)

    # Условие (5): A > 1 — только для варианта без остаточной намагниченности
    if k_r == 0.0 and a <= 1.0:
        notes.append(
            "Условие (5) ГОСТ не выполняется: A ≤ 1 — действующий ток КЗ превышает "
            "ток предельной кратности ТТ. Эксплуатация ТТ в таких условиях недопустима."
        )
        return SaturationResult(a, k_r, "steady_saturation", 0.0, notes)

    # Условие (8): A*(1-Kr) > 1, иначе формула даёт отрицательное время
    if effective <= 1.0:
        notes.append(
            "Условие (8) ГОСТ не выполняется: A·(1−K_r) ≤ 1 — аналитический метод "
            "неприменим. Согласно п. 5.1.5 следует использовать графический метод "
            "по паспортным данным или по ВАХ."
        )
        return SaturationResult(a, k_r, "graphic_required", None, notes)

    # Условие (7)/(4): если не выполняется — насыщения нет
    denom = OMEGA * kz.t_p + 1.0 - effective
    if denom <= 0.0:
        notes.append(
            "Условие (7) ГОСТ не выполняется: ω·T_p + 1 ≤ A·(1−K_r) — "
            "насыщение магнитопровода в переходном процессе отсутствует."
        )
        return SaturationResult(a, k_r, "no_saturation", None, notes)

    # Формулы (3)/(6) ГОСТ Р 58669-2019:
    # t_нас = T_p * ln( ω*T_p / (ω*T_p + 1 - A*(1-K_r)) )
    # «+1» — только в знаменателе (см. пример стандарта В.1.1.8).
    t_nas = kz.t_p * math.log(
        (OMEGA * kz.t_p) / (OMEGA * kz.t_p + 1.0 - effective)
    )

    # Пункт 5.1.7
    if t_nas * 1000.0 < T_NAS_MIN_MS:
        notes.append(
            f"t_нас = {t_nas * 1000:.1f} мс < {T_NAS_MIN_MS:.0f} мс — согласно п. 5.1.7 "
            "результат следует уточнить графическим методом по паспортным данным."
        )

    return SaturationResult(a, k_r, "ok", t_nas, notes)


def calculate(ct: CTParams, kz: KZParams) -> dict:
    """Аналитический метод: расчёт для обоих вариантов остаточной намагниченности (п. 4.3)."""
    return {
        "without_residual": _calc_one_mode(ct, kz, 0.0),
        "with_residual": _calc_one_mode(ct, kz, K_R_PRED),
    }


# ---------------------------------------------------------------------------
# Графический метод по паспортным данным (п. 5.2, приложение Б)
# ---------------------------------------------------------------------------

def _k_np_matrix(t_p: float, alpha: float, theta_arr, t_arr):
    """Матрица значений K_п.р(t): строки — θ, столбцы — t. Формула (Г.15)."""
    sin_a = math.sin(alpha)
    cos_a = math.cos(alpha)
    exp_t = np.exp(-t_arr / t_p)
    base = OMEGA * t_p
    cos_th = np.cos(theta_arr)[:, None]
    sin_th = np.sin(theta_arr)[:, None]
    return (
        sin_a * cos_th * exp_t[None, :]
        + cos_a * cos_th * base * (1.0 - exp_t)[None, :]
        - np.sin(OMEGA * t_arr[None, :] + alpha + theta_arr[:, None])
        + cos_a * sin_th
    )


def _first_crossings(k_mat, t_arr, a_eff: float):
    """Время первого пересечения уровня a_eff для каждого θ (с линейной интерполяцией)."""
    mask = k_mat >= a_eff
    has = mask.any(axis=1)
    idx = np.argmax(mask, axis=1)
    t_cross = np.zeros(len(idx), dtype=float)
    for i in np.where(has)[0]:
        j = idx[i]
        if j == 0:
            t_cross[i] = t_arr[0]
            continue
        k0, k1 = k_mat[i, j - 1], k_mat[i, j]
        if k1 > k0:
            t_cross[i] = (t_arr[j - 1]
                          + (a_eff - k0) * (t_arr[j] - t_arr[j - 1]) / (k1 - k0))
        else:
            t_cross[i] = t_arr[j]
    return has, t_cross


def calculate_graphical(ct: CTParams, kz: KZParams) -> Tuple[Dict[str, SaturationResult], Dict]:
    """Графический метод по паспортным данным (п. 5.2).

    Численный эквивалент универсальных характеристик приложения Б:
    K_п.р(t) по формуле (Г.15), наихудшая начальная фаза θ (п. Г.3.7).

    Возвращает (результаты по сценариям, данные для графиков).
    """
    if kz.i_kz <= 0:
        raise ValueError("Ток КЗ должен быть больше нуля.")
    if ct.z2_sigma == 0:
        raise ValueError(
            "Полное сопротивление вторичной цепи равно нулю — проверьте исходные данные."
        )

    # Параметр режима A — формула (9)
    a = (ct.i1_nom * ct.k_nom * ct.z2_sigma_nom) / (kz.i_kz * ct.z2_sigma)

    # Угол ветви вторичного тока — формула (12)
    cos_alpha = (ct.r2 + ct.r_load_fact) / ct.z2_sigma
    sin_alpha = (ct.x2 + ct.x_load_fact) / ct.z2_sigma
    alpha = math.atan2(sin_alpha, cos_alpha)

    t_arr = np.arange(GRAPH_DT_S, GRAPH_T_MAX_S + GRAPH_DT_S, GRAPH_DT_S)
    theta_arr = np.linspace(0.0, 2.0 * math.pi, GRAPH_N_THETA + 1)[:-1]

    k_mat = _k_np_matrix(kz.t_p, alpha, theta_arr, t_arr)
    k_theta0 = k_mat[0]  # кривая для θ = 0 (максимальная апериодическая составляющая)

    results: Dict[str, SaturationResult] = {}
    scenarios: Dict[str, Optional[Dict]] = {}

    for key, k_r in (("without_residual", 0.0), ("with_residual", K_R_PRED)):
        notes: List[str] = []

        # Условие (5): при A ≤ 1 насыщение наступает в установившемся режиме
        if a <= 1.0:
            notes.append(
                "A ≤ 1 — ток КЗ превышает ток предельной кратности ТТ: насыщение "
                "наступает в установившемся режиме независимо от переходного процесса."
            )
            results[key] = SaturationResult(a, k_r, "steady_saturation", 0.0, notes)
            scenarios[key] = None
            continue

        a_eff = a * (1.0 - k_r)
        has, t_cross = _first_crossings(k_mat, t_arr, a_eff)

        if not has.any():
            notes.append(
                f"Пересечение уровня A·(1−K_r) = {a_eff:.3f} не найдено в диапазоне "
                f"до {GRAPH_T_MAX_S * 1000:.0f} мс — насыщение магнитопровода отсутствует."
            )
            results[key] = SaturationResult(a, k_r, "no_saturation", None, notes)
            scenarios[key] = None
            continue

        i_worst = int(np.argmin(np.where(has, t_cross, np.inf)))
        t_nas = float(t_cross[i_worst])
        theta_worst = float(theta_arr[i_worst])
        notes.append(
            f"Наихудшая начальная фаза апериодической составляющей: "
            f"θ = {theta_worst:.2f} рад ({math.degrees(theta_worst):.0f}°)."
        )
        results[key] = SaturationResult(a, k_r, "ok", t_nas, notes)
        scenarios[key] = {
            "a_eff": a_eff,
            "t_nas_ms": t_nas * 1000.0,
            "k_worst": k_mat[i_worst],
            "k_theta0": k_theta0,
        }

    chart_data = {
        "t_ms": (t_arr * 1000.0).tolist(),
        "scenarios": scenarios,
        "cos_alpha": cos_alpha,
        "alpha_deg": math.degrees(alpha),
    }
    return results, chart_data


# === КОНЕЦ ФАЙЛА methods/gost_58669.py ===
