"""
Расчётное ядро: ГОСТ Р 58669-2019.
Методы определения времени до насыщения:
1) АНАЛИТИЧЕСКИЙ (раздел 5.1)
2) ГРАФИЧЕСКИЙ ПО ПАСПОРТНЫМ ДАННЫМ (раздел 5.2, приложение Б)
3) ГРАФИЧЕСКИЙ С ИСПОЛЬЗОВАНИЕМ ВАХ (раздел 5.3)
4) ГРАФИЧЕСКИЙ С ИСПОЛЬЗОВАНИЕМ ХАРАКТЕРИСТИКИ НАМАГНИЧИВАНИЯ (раздел 5.4)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

try:
    import numpy as np
except ImportError:
    np = None

OMEGA = 2.0 * math.pi * 50.0
K_R_PRED = 0.86
T_NAS_MIN_MS = 15.0
T_P_RANGE_S = (0.03, 0.30)
B_T_THRESHOLD = 1.8

ST_OK = "ok"
ST_NO_SAT = "no_saturation"
ST_STEADY = "steady_saturation"
ST_GRAPHIC_REQUIRED = "graphic_required"

NOTE_A_LE_1 = ("A ≤ 1: ток КЗ превышает ток предельной кратности ТТ — эксплуатация "
               "недопустима (условие (5) ГОСТ).")


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
        return math.sqrt(self.r_total ** 2 + self.x_total ** 2)

    @property
    def alpha(self) -> float:
        return math.atan2(self.x_total, self.r_total) if self.z2_sigma > 0 else 0.0

    @property
    def cos_alpha(self) -> float:
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
        raise ValueError("Полное сопротивление вторичной цепи равно нулю.")
    return (ct.i1_nom * ct.k_nom * ct.z2_sigma_nom) / (kz.i_kz * ct.z2_sigma)


def _analytic(ct, kz, k_r, a) -> SaturationResult:
    notes: List[str] = []
    effective = a * (1.0 - k_r)

    if not (T_P_RANGE_S[0] <= kz.t_p <= T_P_RANGE_S[1]):
        notes.append(f"T_p = {kz.t_p * 1000:.0f} мс выходит за диапазон "
                     f"{T_P_RANGE_S[0] * 1000:.0f}–{T_P_RANGE_S[1] * 1000:.0f} мс.")

    if k_r == 0.0 and a <= 1.0:                       # условие (5)
        notes.append(NOTE_A_LE_1)
        return SaturationResult(a, k_r, ST_STEADY, 0.0, notes, "analytic", None, ct.cos_alpha)

    if effective <= 1.0:                              # условие (8)
        notes.append("Условие (8) ГОСТ не выполняется: A·(1−K_r) ≤ 1 — аналитический метод "
                     "неприменим. Используйте графические методы (п. 5.1.5).")
        return SaturationResult(a, k_r, ST_GRAPHIC_REQUIRED, None, notes, "analytic", None, ct.cos_alpha)

    denom = OMEGA * kz.t_p + 1.0 - effective          # условие (7)
    if denom <= 0.0:
        notes.append("Условие (7) ГОСТ не выполняется: ω·T_p + 1 ≤ A·(1−K_r) — насыщения нет.")
        return SaturationResult(a, k_r, ST_NO_SAT, None, notes, "analytic", None, ct.cos_alpha)

    t_nas = kz.t_p * math.log((OMEGA * kz.t_p) / denom)
    if t_nas * 1000.0 < T_NAS_MIN_MS:
        notes.append(f"t_нас = {t_nas * 1000:.1f} мс < {T_NAS_MIN_MS:.0f} мс — уточните "
                     "графическим методом (п. 5.1.7).")
    return SaturationResult(a, k_r, ST_OK, t_nas, notes, "analytic", None, ct.cos_alpha)


def k_pr(t, t_p: float, alpha: float, theta: float):
    """Коэффициент переходного режима K_п.р(t) — формула (Г.15)."""
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
    """Численное воспроизведение универсальных характеристик приложения Б."""
    if np is None:
        raise RuntimeError("Для графического метода требуется numpy.")
    eff = a * (1.0 - k_r)
    if eff <= 0.0:
        return None, None, "invalid"

    t_max = max(0.25, 6.0 * t_p)
    n_t = int(min(12000, max(n_t, t_max / 0.0002)))
    t = np.linspace(0.0, t_max, n_t)

    thetas = ([float(theta_fixed)] if theta_fixed is not None
              else np.linspace(-np.pi / 2.0, np.pi / 2.0, n_theta))

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

    if k_r == 0.0 and a <= 1.0:                       # условие (5)
        notes.append(NOTE_A_LE_1)
        return SaturationResult(a, k_r, ST_STEADY, 0.0, notes, "graphic", th, ct.cos_alpha, manual)

    if why == ST_NO_SAT or t is None:
        notes.append("Насыщение магнитопровода отсутствует.")
        return SaturationResult(a, k_r, ST_NO_SAT, None, notes, "graphic", None, ct.cos_alpha, manual)

    if manual:
        notes.append(f"Время до насыщения при заданной фазе θ = {math.degrees(th):.1f}°.")
    else:
        notes.append(f"Наименьшее время до насыщения при θ* = {math.degrees(th):.1f}° (п. Г.3.7).")
    return SaturationResult(a, k_r, ST_OK, t, notes, "graphic", th, ct.cos_alpha, manual)


# ---------------------------------------------------------------------------
# МЕТОД ПО ВАХ (п. 5.3)
# ---------------------------------------------------------------------------

def build_vah_default(u_star, i0_star, r2, n_points=100):
    """Типовая ВАХ ТТ."""
    i0_max = i0_star * 3.0
    i0_arr = np.linspace(0.001, i0_max, n_points)
    x = i0_arr / i0_star
    y_norm = u_star / i0_star
    u_arr = y_norm * i0_star * (1 - np.exp(-x)) / (1 + 0.1 * x ** 2)
    u_arr = np.clip(u_arr, 0, u_star * 1.2)
    return {
        'i0': i0_arr.tolist(),
        'u': u_arr.tolist(),
        'psi': (u_arr / OMEGA).tolist(),
        'u_star': u_star,
        'i0_star': i0_star,
    }


def calc_a_from_vah(u_star, u2sin):
    """Параметр режима A по формуле (19): A = U* / U2sin."""
    if u2sin <= 0:
        raise ValueError("U2sin должен быть больше нуля.")
    return u_star / u2sin


def calc_u2sin(ct, kz):
    """U2sin = I2ном · Kфакт · z2Σ."""
    k_fact = kz.i_kz / ct.i1_nom
    return ct.i2_nom * k_fact * ct.z2_sigma


def validate_vah_usage(u_star, i0_star, ct, kz):
    """Проверка условия (16) ГОСТ Р 58669-2019."""
    k_fact = kz.i_kz / ct.i1_nom
    i0_eps = 0.1 * ct.i2_nom * k_fact
    i_lin = i0_star * 0.1
    u_lin = u_star * 0.1
    u_eps = u_star * (i0_eps / i0_star) if i0_eps <= i0_star else u_star
    if i_lin == 0 or u_lin == 0 or u_eps == 0:
        return False, "Невозможно определить параметры линейного участка ВАХ."
    ratio = (i0_eps / u_eps) / (i_lin / u_lin)
    if ratio > 3:
        return True, f"Условие (16) выполняется: отношение = {ratio:.2f} > 3."
    return False, f"Условие (16) не выполняется: отношение = {ratio:.2f} ≤ 3."


def calculate_vah(ct, kz, u_star, i0_star, theta_override=None, k_r=K_R_PRED):
    """Метод по ВАХ. Возвращает результаты для обоих сценариев остаточной намагниченности."""
    valid, msg = validate_vah_usage(u_star, i0_star, ct, kz)
    if valid:
        u2sin = calc_u2sin(ct, kz)
        a_vah = calc_a_from_vah(u_star, u2sin)
        wo = _graphic(ct, kz, 0.0, a_vah, theta_override)
        w = _graphic(ct, kz, k_r, a_vah, theta_override)
        note = f"Метод по ВАХ: A = {a_vah:.3f} (формула 19), U* = {u_star:.1f} В"
        wo.notes.insert(0, note)
        w.notes.insert(0, note)
    else:
        wo = SaturationResult(0.0, 0.0, ST_GRAPHIC_REQUIRED, None,
                              [f"Метод по ВАХ неприменим: {msg}"], "vah", None, ct.cos_alpha)
        w = SaturationResult(0.0, k_r, ST_GRAPHIC_REQUIRED, None,
                             [f"Метод по ВАХ неприменим: {msg}"], "vah", None, ct.cos_alpha)
    return {"vah_without_residual": wo, "vah_with_residual": w}


# ---------------------------------------------------------------------------
# МЕТОД ПО ХАРАКТЕРИСТИКЕ НАМАГНИЧИВАНИЯ (п. 5.4)
# ---------------------------------------------------------------------------

def build_bn_default(b_sat=1.8, h_knee=100, n_points=100):
    """Типовая характеристика намагничивания B(H).

    Физически корректная форма: монотонный рост от нуля, линейный участок
    до точки излома (колена), затем плавное насыщение. Обе ветви сшиты в точке
    колена без разрыва, поэтому кривая нигде не падает и не имеет изломов вниз.
    """
    h_arr = np.linspace(0.0, h_knee * 5, n_points)
    b_knee = 0.9 * b_sat            # индукция в точке излома (~90 % от насыщения)
    mu_i = b_knee / h_knee          # начальная магнитная проницаемость (линейный участок)
    h_scale = 0.3 * h_knee          # масштаб экспоненты насыщения после колена
    b_arr = np.where(
        h_arr <= h_knee,
        mu_i * h_arr,                                                   # линейный участок
        b_sat - (b_sat - b_knee) * np.exp(-(h_arr - h_knee) / h_scale)  # насыщение
    )
    return {'h': h_arr.tolist(), 'b': b_arr.tolist(),
            'b_sat': b_sat, 'h_knee': h_knee}


def calc_b_from_bn(h_value, bn_data):
    """Интерполяция B по H из характеристики намагничивания."""
    h_arr = np.array(bn_data['h'], dtype=float)
    b_arr = np.array(bn_data['b'], dtype=float)
    if h_value <= h_arr[0]:
        return float(b_arr[0])
    if h_value >= h_arr[-1]:
        return float(b_arr[-1])
    idx = int(np.searchsorted(h_arr, h_value))
    h0, h1 = float(h_arr[idx - 1]), float(h_arr[idx])
    b0, b1 = float(b_arr[idx - 1]), float(b_arr[idx])
    if h1 == h0:
        return b0
    return float(b0 + (b1 - b0) * (h_value - h0) / (h1 - h0))


def calc_b_t(ct, kz, w2, s):
    """Амплитуда магнитной индукции по формуле (24): Bт = U2sin / (222·w2·s)."""
    if w2 <= 0 or s <= 0:
        return 0.0
    u2sin = calc_u2sin(ct, kz)
    return u2sin / (222.0 * float(w2) * float(s))


def calc_a_from_bn(ct, kz, bn_data, w2, s, l):
    """Параметр режима A по формуле (23): A = Bт / Bт(Hг)."""
    w2, s, l = float(w2), float(s), float(l)
    if w2 <= 0 or s <= 0 or l <= 0:
        raise ValueError("Параметры w2, s, l должны быть положительными.")
    b_t = calc_b_t(ct, kz, w2, s)
    k_fact = kz.i_kz / ct.i1_nom
    i0_eps = 0.1 * ct.i2_nom * k_fact
    h_g = i0_eps * w2 / l
    b_t_hg = calc_b_from_bn(h_g, bn_data)
    if b_t_hg <= 0:
        return 1.0
    return b_t / b_t_hg


def validate_bn_usage(ct, kz, bn_data, w2, s, l):
    """Проверка условия (21): Bт > 1.8 Тл."""
    if float(w2) <= 0 or float(s) <= 0 or float(l) <= 0:
        return False, "Параметры w2, s, l должны быть положительными."
    b_t = calc_b_t(ct, kz, w2, s)
    if b_t > B_T_THRESHOLD:
        return True, f"Условие (21) выполняется: Bт = {b_t:.3f} Тл > {B_T_THRESHOLD} Тл."
    return False, (f"Условие (21) не выполняется: Bт = {b_t:.3f} Тл ≤ {B_T_THRESHOLD} Тл — "
                   "магнитопровод не насыщается при данном токе КЗ.")


def calculate_bn(ct, kz, bn_data, w2, s, l, theta_override=None, k_r=K_R_PRED):
    """Метод по характеристике намагничивания. Всегда возвращает видимый результат."""
    valid, msg = validate_bn_usage(ct, kz, bn_data, w2, s, l)
    b_t = calc_b_t(ct, kz, w2, s)
    if valid:
        a_bn = calc_a_from_bn(ct, kz, bn_data, w2, s, l)
        wo = _graphic(ct, kz, 0.0, a_bn, theta_override)
        w = _graphic(ct, kz, k_r, a_bn, theta_override)
        note = f"Метод по B(H): A = {a_bn:.3f} (формула 23), Bт = {b_t:.2f} Тл"
        wo.notes.insert(0, note)
        w.notes.insert(0, note)
    else:
        wo = SaturationResult(0.0, 0.0, ST_NO_SAT, None,
                              [f"Метод по B(H): {msg}"], "bn", None, ct.cos_alpha)
        w = SaturationResult(0.0, k_r, ST_NO_SAT, None,
                             [f"Метод по B(H): {msg}"], "bn", None, ct.cos_alpha)
    return {"bn_without_residual": wo, "bn_with_residual": w}


ANALYTIC_KEYS = ("without_residual", "with_residual")
GRAPHIC_KEYS = ("graphic_without_residual", "graphic_with_residual")
VAH_KEYS = ("vah_without_residual", "vah_with_residual")
BN_KEYS = ("bn_without_residual", "bn_with_residual")
ALL_KEYS = ANALYTIC_KEYS + GRAPHIC_KEYS + VAH_KEYS + BN_KEYS


def calculate(ct: CTParams, kz: KZParams, method: str = "analytic",
              theta_override: Optional[float] = None, k_r: float = K_R_PRED) -> dict:
    """Расчёт для обоих вариантов остаточной намагниченности.

    k_r — коэффициент остаточной намагниченности для сценария «с остаточной
    намагниченностью». По умолчанию 0,86 (класс P, п. 5.1.3); для классов
    5PR/10PR или по заводским данным может задаваться пользователем (например 0,1).
    """
    a = calc_a_param(ct, kz)
    out = {
        "without_residual": _analytic(ct, kz, 0.0, a),
        "with_residual": _analytic(ct, kz, k_r, a),
    }
    if method in ("graphic", "both"):
        out["graphic_without_residual"] = _graphic(ct, kz, 0.0, a, theta_override)
        out["graphic_with_residual"] = _graphic(ct, kz, k_r, a, theta_override)
    return out


# === КОНЕЦ ФАЙЛА methods/gost_58669.py ===
