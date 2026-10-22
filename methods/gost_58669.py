"""
Расчётное ядро: ГОСТ Р 58669-2019.

Реализованы два метода определения времени до насыщения:

1) АНАЛИТИЧЕСКИЙ (раздел 5.1): формулы (9), (10), (11), (3), (6);
   условия (4), (5), (7), (8); пп. 5.1.3, 5.1.7.

       t_нас = T_p · ln( ω·T_p / ( ω·T_p + 1 - A·(1 - K_r) ) )

2) ГРАФИЧЕСКИЙ ПО ПАСПОРТНЫМ ДАННЫМ (раздел 5.2, приложение Б) в численной
   форме по формуле (Г.15):

       K_п.р(t) = sin α · cos θ · e^(-t/T_p)
                + cos α · cos θ · ω·T_p · (1 - e^(-t/T_p))
                - sin(ω·t + α + θ) + cos α · sin θ                        (Г.15)

       cos α = (R2 + Rн.факт) / z2Σ                                      (12)

   По умолчанию время до насыщения ищется минимизацией по начальной фазе θ
   (п. Г.3.7). Поддерживается и фиксированная θ, заданная пользователем
   (параметр theta_override).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

OMEGA = 2.0 * math.pi * 50.0
K_R_PRED = 0.86
T_NAS_MIN_MS = 15.0
T_P_RANGE_S = (0.03, 0.30)

ST_OK = "ok"
ST_NO_SAT = "no_saturation"
ST_STEADY = "steady_saturation"
ST_GRAPHIC_REQUIRED = "graphic_required"


@dataclass
class CTParams:
    """Паспортные данные трансформатора тока."""
    i1_nom: float
    i2_nom: float
    k_nom: float
    s_nom: float
    cos_phi_nom: float
    r2: float
    x2: float
    r_load_fact: float
    x_load_fact: float

    @property
    def z_n_nom(self) -> float:
        return self.s_nom / (self.i2_nom ** 2)

    @property
    def z2_sigma_nom(self) -> float:
        """Формула (10)."""
        sin_phi = math.sqrt(max(0.0, 1.0 - self.cos_phi_nom ** 2))
        return math.sqrt((self.r2 + self.z_n_nom * self.cos_phi_nom) ** 2
                         + (self.x2 + self.z_n_nom * sin_phi) ** 2)

    @property
    def r_total(self) -> float:
        return self.r2 + self.r_load_fact

    @property
    def x_total(self) -> float:
        return self.x2 + self.x_load_fact

    @property
    def z2_sigma(self) -> float:
        """Формула (11)."""
        return math.sqrt(self.r_total ** 2 + self.x_total ** 2)

    @property
    def alpha(self) -> float:
        """Угол сопротивления ветви вторичного тока, рад (п. 5.2.2)."""
        return math.atan2(self.x_total, self.r_total) if self.z2_sigma > 0 else 0.0

    @property
    def cos_alpha(self) -> float:
        """Формула (12): cos α = (R2 + Rн.факт) / z2Σ."""
        z = self.z2_sigma
        return self.r_total / z if z > 0 else 1.0


@dataclass
class KZParams:
    i_kz: float
    t_p: float
    label: str = "трёхфазное КЗ"


@dataclass
class SaturationResult:
    a: float
    k_r: float
    status: str
    t_nas: Optional[float]
    notes: List[str] = field(default_factory=list)
    method: str = "analytic"
    theta_star: Optional[float] = None
    cos_alpha: float = 1.0
    theta_manual: bool = False


def calc_a_param(ct: CTParams, kz: KZParams) -> float:
    """Параметр режима A — формула (9)."""
    if kz.i_kz <= 0:
        raise ValueError("Ток КЗ должен быть больше нуля.")
    if ct.z2_sigma == 0:
        raise ValueError("Полное сопротивление вторичной цепи равно нулю — проверьте исходные данные.")
    return (ct.i1_nom * ct.k_nom * ct.z2_sigma_nom) / (kz.i_kz * ct.z2_sigma)


def _analytic(ct, kz, k_r, a) -> SaturationResult:
    notes: List[str] = []
    effective = a * (1.0 - k_r)

    if not (T_P_RANGE_S[0] <= kz.t_p <= T_P_RANGE_S[1]):
        notes.append(f"T_p = {kz.t_p * 1000:.0f} мс выходит за диапазон "
                     f"{T_P_RANGE_S[0] * 1000:.0f}–{T_P_RANGE_S[1] * 1000:.0f} мс, для которого "
                     "построены универсальные характеристики (приложение Б).")

    if k_r == 0.0 and a <= 1.0:                                  # условие (5)
        notes.append("Условие (5) ГОСТ не выполняется: A ≤ 1 — действующий ток КЗ превышает "
                     "ток предельной кратности ТТ. Эксплуатация ТТ в таких условиях недопустима.")
        return SaturationResult(a, k_r, ST_STEADY, 0.0, notes, "analytic", None, ct.cos_alpha)

    if effective <= 1.0:                                          # условие (8)
        notes.append("Условие (8) ГОСТ не выполняется: A·(1−K_r) ≤ 1 — аналитический метод "
                     "неприменим. Согласно п. 5.1.5 следует использовать графический метод "
                     "по паспортным данным или по ВАХ.")
        return SaturationResult(a, k_r, ST_GRAPHIC_REQUIRED, None, notes, "analytic", None, ct.cos_alpha)

    denom = OMEGA * kz.t_p + 1.0 - effective                      # условие (7)
    if denom <= 0.0:
        notes.append("Условие (7) ГОСТ не выполняется: ω·T_p + 1 ≤ A·(1−K_r) — насыщение "
                     "магнитопровода в переходном процессе отсутствует.")
        return SaturationResult(a, k_r, ST_NO_SAT, None, notes, "analytic", None, ct.cos_alpha)

    t_nas = kz.t_p * math.log((OMEGA * kz.t_p) / denom)           # формулы (3)/(6)
    if t_nas * 1000.0 < T_NAS_MIN_MS:
        notes.append(f"t_нас = {t_nas * 1000:.1f} мс < {T_NAS_MIN_MS:.0f} мс — согласно п. 5.1.7 "
                     "результат следует уточнить графическим методом по паспортным данным.")
    return SaturationResult(a, k_r, ST_OK, t_nas, notes, "analytic", None, ct.cos_alpha)


def k_pr(t, t_p: float, alpha: float, theta: float):
    """Коэффициент переходного режима K_п.р(t) — формула (Г.15). t в секундах."""
    if np is None:
        raise RuntimeError("Для графического метода требуется numpy.")
    t_arr = np.asarray(t, dtype=float)
    e = np.exp(-t_arr / t_p)
    return (math.sin(alpha) * math.cos(theta) * e
            + math.cos(alpha) * math.cos(theta) * OMEGA * t_p * (1.0 - e)
            - np.sin(OMEGA * t_arr + alpha + theta)
            + math.cos(alpha) * math.sin(theta))


def t_nas_graphic(a: float, t_p: float, alpha: float, k_r: float = 0.0,
                  n_theta: int = 361, n_t: int = 4000,
                  theta_fixed: Optional[float] = None) -> Tuple[Optional[float], Optional[float], str]:
    """Численное воспроизведение универсальных характеристик приложения Б.

    Если theta_fixed = None — минимум по θ первого пересечения K_п.р(t) = A·(1-K_r)
    (п. Г.3.7). Если theta_fixed задан — время до насыщения для этой конкретной θ.
    Возвращает (t_нас [с], θ [рад], статус)."""
    if np is None:
        raise RuntimeError("Для графического метода требуется numpy.")
    eff = a * (1.0 - k_r)
    if eff <= 0.0:
        return None, None, "invalid"

    t_max = max(0.25, 6.0 * t_p)
    n_t = int(min(12000, max(n_t, t_max / 0.0002)))
    t = np.linspace(0.0, t_max, n_t)

    if theta_fixed is not None:
        thetas = [float(theta_fixed)]
    else:
        thetas = np.linspace(-np.pi / 2.0, np.pi / 2.0, n_theta)

    best_t: Optional[float] = None
    best_th: Optional[float] = None
    for th in thetas:
        k_arr = k_pr(t, t_p, alpha, float(th))
        hit = np.nonzero(k_arr >= eff)[0]
        if hit.size == 0 or hit[0] == 0:
            continue
        j = int(hit[0])
        lo, hi = float(t[j - 1]), float(t[j])
        for _ in range(45):
            mid = 0.5 * (lo + hi)
            if float(k_pr(mid, t_p, alpha, float(th))) >= eff:
                hi = mid
            else:
                lo = mid
        tc = 0.5 * (lo + hi)
        if best_t is None or tc < best_t:
            best_t, best_th = tc, float(th)

    if best_t is None:
        return None, None, ST_NO_SAT
    return best_t, best_th, ST_OK


def build_kpr_curve(t_p: float, alpha: float, theta: float, t_end_ms: float, n: int = 1200):
    """Массивы (t [мс], K_п.р) для построения графика."""
    t = np.linspace(0.0, max(t_end_ms, 1.0) / 1000.0, n)
    return t * 1000.0, np.asarray(k_pr(t, t_p, alpha, theta), dtype=float)


def _graphic(ct, kz, k_r, a, theta_override=None) -> SaturationResult:
    notes: List[str] = []
    manual = theta_override is not None
    t, th, why = t_nas_graphic(a, kz.t_p, ct.alpha, k_r, theta_fixed=theta_override)

    if k_r == 0.0 and a <= 1.0:
        notes.append("A ≤ 1 — действующий ток КЗ превышает ток предельной кратности ТТ: "
                     "погрешность ТТ превышает допустимую уже в установившемся режиме. "
                     "Эксплуатация недопустима (условие (5) ГОСТ).")
        if t is not None:
            notes.append(f"Расчётное время первого насыщения при этом {t * 1000:.2f} мс (справочно).")
        return SaturationResult(a, k_r, ST_STEADY, 0.0, notes, "graphic", th, ct.cos_alpha, manual)

    if why == ST_NO_SAT or t is None:
        notes.append("Уравнение K_п.р(t) = A·(1−K_r) не имеет решения: максимальное значение "
                     "коэффициента переходного режима ниже уровня насыщения — насыщение "
                     "магнитопровода в переходном процессе отсутствует.")
        return SaturationResult(a, k_r, ST_NO_SAT, None, notes, "graphic", None, ct.cos_alpha, manual)

    if manual:
        notes.append(f"Время до насыщения рассчитано при заданной вручную начальной фазе "
                     f"θ = {math.degrees(th):.1f}°.")
    else:
        notes.append(f"Наименьшее время до насыщения соответствует начальной фазе "
                     f"θ* = {math.degrees(th):.1f}° (п. Г.3.7: универсальные характеристики "
                     "построены для θ, при которых t_нас наименьшее).")
    return SaturationResult(a, k_r, ST_OK, t, notes, "graphic", th, ct.cos_alpha, manual)


ANALYTIC_KEYS = ("without_residual", "with_residual")
GRAPHIC_KEYS = ("graphic_without_residual", "graphic_with_residual")
ALL_KEYS = ANALYTIC_KEYS + GRAPHIC_KEYS


def calculate(ct: CTParams, kz: KZParams, method: str = "analytic",
              theta_override: Optional[float] = None) -> dict:
    """Расчёт для обоих вариантов остаточной намагниченности (п. 4.3 ГОСТ).
    method: "analytic" | "graphic" | "both".
    theta_override: начальная фаза θ [рад] для графического метода (None — авто)."""
    a = calc_a_param(ct, kz)
    out = {
        "without_residual": _analytic(ct, kz, 0.0, a),
        "with_residual": _analytic(ct, kz, K_R_PRED, a),
    }
    if method in ("graphic", "both"):
        out["graphic_without_residual"] = _graphic(ct, kz, 0.0, a, theta_override)
        out["graphic_with_residual"] = _graphic(ct, kz, K_R_PRED, a, theta_override)
    return out
# ---------------------------------------------------------------------------
# МЕТОД ПО ВАХ (п. 5.3 ГОСТ Р 58669-2019)
# ---------------------------------------------------------------------------

def build_vah_default(u_star, i0_star, r2, n_points=100):
    """Построение типовой ВАХ (вольт-амперной характеристики) ТТ.
    
    ВАХ описывается как U = f(I₀) — зависимость напряжения на выводах
    вторичной обмотки от тока намагничивания.
    
    Типовая форма:
    - Линейный участок: U = k · I₀ (I₀ < I₀_лин)
    - Переходная область: плавное насыщение
    - Насыщение: U → U_max
    
    Параметры:
    - u_star: напряжение при номинальной предельной кратности (или при 10% погрешности)
    - i0_star: ток намагничивания при u_star
    - r2: активное сопротивление вторичной обмотки
    - n_points: количество точек в таблице
    
    Возвращает:
    - dict с массивами: {'i0': [...], 'u': [...], 'psi': [...]}
    """
    i0_max = i0_star * 3.0  # выходим за точку u_star для показа насыщения
    i0_arr = np.linspace(0.001, i0_max, n_points)
    
    # Нормализованные координаты
    x = i0_arr / i0_star
    y_norm = u_star / i0_star
    
    # Эмпирическая формула для типовой ВАХ (аппроксимация реальных характеристик)
    # Линейный участок + плавный переход в насыщение
    u_arr = y_norm * i0_star * (1 - np.exp(-x)) / (1 + 0.1 * x**2)
    u_arr = np.clip(u_arr, 0, u_star * 1.2)  # ограничение сверху
    
    # Потокосцепление: Ψ = U / ω
    psi_arr = u_arr / OMEGA
    
    return {
        'i0': i0_arr.tolist(),
        'u': u_arr.tolist(),
        'psi': psi_arr.tolist(),
        'u_star': u_star,
        'i0_star': i0_star,
    }


def calc_a_from_vah(u_star, u2sin):
    """Параметр режима A по формуле (19) ГОСТ Р 58669-2019.
    
    A = U* / U2sin
    
    Параметры:
    - u_star: напряжение на ВАХ, соответствующее полной погрешности ε
    - u2sin: напряжение на вторичной обмотке при фактическом токе КЗ
    
    Возвращает:
    - float: параметр A
    """
    if u2sin <= 0:
        raise ValueError("U2sin должен быть больше нуля.")
    return u_star / u2sin


def calc_u2sin(ct, kz):
    """Напряжение на вторичной обмотке при фактическом токе КЗ.
    
    U2sin = Iкз · z2Σ / Kном
    
    Параметры:
    - ct: CTParams (параметры ТТ)
    - kz: KZParams (параметры КЗ)
    
    Возвращает:
    - float: U2sin в вольтах
    """
    k_fact = kz.i_kz / ct.i1_nom
    return ct.i2_nom * k_fact * ct.z2_sigma


def validate_vah_usage(u_star, i0_star, ct, kz):
    """Проверка условия (16) ГОСТ Р 58669-2019 для применения метода по ВАХ.
    
    I₀(ε) / U(ε) / (Iлин / Uлин) > 3
    
    Где:
    - I₀(ε) = 0,1 · I₂ном · Kфакт
    - U(ε) — напряжение на ВАХ при I₀(ε)
    - Iлин, Uлин — середина линейного участка ВАХ
    
    Для типовой ВАХ принимаем Iлин = 0,1 · I₀_star, Uлин = U(Iлин)
    """
    k_fact = kz.i_kz / ct.i1_nom
    i0_eps = 0.1 * ct.i2_nom * k_fact
    
    # Для типовой ВАХ: линейный участок при малых токах
    i_lin = i0_star * 0.1
    u_lin = u_star * 0.1  # приблизительно, для линейного участка
    
    # Напряжение при I₀(ε) — интерполяция по типовой ВАХ
    # Для упрощения: U(ε) ≈ u_star * (i0_eps / i0_star) для линейного участка
    u_eps = u_star * (i0_eps / i0_star) if i0_eps <= i0_star else u_star
    
    # Проверка условия
    if i_lin == 0 or u_lin == 0:
        return False, "Невозможно определить параметры линейного участка ВАХ."
    
    ratio = (i0_eps / u_eps) / (i_lin / u_lin)
    if ratio > 3:
        return True, f"Условие (16) выполняется: отношение = {ratio:.2f} > 3."
    else:
        return False, f"Условие (16) не выполняется: отношение = {ratio:.2f} ≤ 3."


def _vah_method(ct, kz, u_star, i0_star, theta_override=None):
    """Метод по ВАХ: расчёт параметра A и времени до насыщения.
    
    Параметры:
    - ct: CTParams
    - kz: KZParams
    - u_star: напряжение на ВАХ при полной погрешности
    - i0_star: ток намагничивания при u_star
    - theta_override: начальная фаза θ (None — авто)
    
    Возвращает:
    - dict с результатами для обоих сценариев K_r
    """
    # Проверка условия (16)
    valid, msg = validate_vah_usage(u_star, i0_star, ct, kz)
    if not valid:
        notes = [f"Метод по ВАХ неприменим: {msg}"]
        return {
            "vah_without_residual": SaturationResult(0, 0, ST_GRAPHIC_REQUIRED, None, notes, "vah"),
            "vah_with_residual": SaturationResult(0, 0, ST_GRAPHIC_REQUIRED, None, notes, "vah"),
        }
    
    # Расчёт параметра A
    u2sin = calc_u2sin(ct, kz)
    a = calc_a_from_vah(u_star, u2sin)
    
    # Графический метод с параметром A
    out = {
        "vah_without_residual": _graphic(ct, kz, 0.0, a, theta_override),
        "vah_with_residual": _graphic(ct, kz, K_R_PRED, a, theta_override),
    }
    
    # Добавляем пометку о методе
    for key in ["vah_without_residual", "vah_with_residual"]:
        out[key].method = "vah"
        out[key].notes.insert(0, f"Метод по ВАХ: A = {a:.3f} (формула 19)")
    
    return out


VAH_KEYS = ("vah_without_residual", "vah_with_residual")

# === КОНЕЦ ФАЙЛА methods/gost_58669.py ===
