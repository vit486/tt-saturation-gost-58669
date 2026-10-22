"""
Расчёт времени до насыщения трансформаторов тока.
Методика: ГОСТ Р 58669-2019, раздел 5.1 (аналитический метод).

Проверяемые условия стандарта:
  - формула (9)  — параметр режима A;
  - условие (5)  — A > 1 (иначе ток КЗ больше предельной кратности);
  - условие (8)  — A*(1-Kr) > 1 (иначе нужен графический метод, п. 5.1.5);
  - условие (7)  — w*Tp + 1 > A*(1-Kr) (иначе насыщения нет);
  - пункт 5.1.7  — при t_нас < 15 мс требуется графический метод;
  - пункт 4.3    — расчёт без остаточной намагниченности и с предельной (Kr = 0.86);
  - приложение Б — предупреждение при выходе Tp за диапазон 30–300 мс.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

OMEGA = 2.0 * math.pi * 50.0   # угловая частота, рад/с (50 Гц)
K_R_PRED = 0.86                # предельный коэффициент остаточной намагниченности (п. 5.1.3)
T_NAS_MIN_MS = 15.0            # порог применимости аналитического метода (п. 5.1.7)
T_P_RANGE_S = (0.03, 0.30)     # диапазон Tp универсальных характеристик (приложение Б)


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
        """Полное сопротивление номинальной нагрузки, Ом."""
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
    """Результат расчёта для одного режима КЗ и одного значения остаточной намагниченности."""
    a: float                            # параметр режима, формула (9)
    k_r: float                          # коэффициент остаточной намагниченности
    status: str                         # ok | no_saturation | steady_saturation | graphic_required
    t_nas: Optional[float]              # время до насыщения, с (для status == "ok")
    notes: List[str] = field(default_factory=list)

    @property
    def t_nas_ms(self) -> Optional[float]:
        return None if self.t_nas is None else self.t_nas * 1000.0


def _calc_one_mode(ct: CTParams, kz: KZParams, k_r: float) -> SaturationResult:
    """Расчёт времени до насыщения для заданного коэффициента остаточной намагниченности."""
    notes: List[str] = []

    if kz.i_kz <= 0:
        raise ValueError("Ток КЗ должен быть больше нуля.")
    if ct.z2_sigma == 0:
        raise ValueError(
            "Полное сопротивление вторичной цепи равно нулю. Проверьте R2 и сопротивление нагрузки."
        )

    # Параметр режима A — формула (9)
    a = (ct.i1_nom * ct.k_nom * ct.z2_sigma_nom) / (kz.i_kz * ct.z2_sigma)

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
        return SaturationResult(a=a, k_r=k_r, status="steady_saturation", t_nas=0.0, notes=notes)

    # Условие (8): A*(1-Kr) > 1, иначе формула даёт отрицательное время
    if effective <= 1.0:
        notes.append(
            "Условие (8) ГОСТ не выполняется: A·(1−K_r) ≤ 1 — аналитический метод "
            "неприменим. Согласно п. 5.1.5 следует использовать графический метод "
            "по паспортным данным или по ВАХ."
        )
        return SaturationResult(a=a, k_r=k_r, status="graphic_required", t_nas=None, notes=notes)

    # Условие (7): если оно не выполняется, насыщение отсутствует
    denom = OMEGA * kz.t_p + 1.0 - effective
    if denom <= 0.0:
        notes.append(
            "Условие (7) ГОСТ не выполняется: ω·T_p + 1 ≤ A·(1−K_r) — "
            "насыщение магнитопровода в переходном процессе отсутствует."
        )
        return SaturationResult(a=a, k_r=k_r, status="no_saturation", t_nas=None, notes=notes)

    # Формула (6) / (3)
    t_nas = kz.t_p * math.log((OMEGA * kz.t_p + 1.0) / denom)

    if t_nas * 1000.0 < T_NAS_MIN_MS:
        notes.append(
            f"t_нас = {t_nas * 1000:.1f} мс < {T_NAS_MIN_MS:.0f} мс — согласно п. 5.1.7 "
            "результат следует уточнить графическим методом по паспортным данным."
        )

    return SaturationResult(a=a, k_r=k_r, status="ok", t_nas=t_nas, notes=notes)


def calculate(ct: CTParams, kz: KZParams) -> dict:
    """Расчёт для обоих вариантов остаточной намагниченности (п. 4.3 ГОСТ)."""
    return {
        "without_residual": _calc_one_mode(ct, kz, 0.0),
        "with_residual": _calc_one_mode(ct, kz, K_R_PRED),
    }
