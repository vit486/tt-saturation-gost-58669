"""
Расчётное ядро: ГОСТ Р 58669-2019, раздел 5.
1) аналитический (5.1); 2) графический по паспортным данным (5.2);
3) графический по ВАХ (5.3); 4) графический по характеристике намагничивания (5.4).
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
B_ME_THRESHOLD = 1.8   # п. 5.4.2, условие (21): B_me(H) >= 1,8 Тл

ST_OK = "ok"
ST_NO_SAT = "no_saturation"
ST_STEADY = "steady_saturation"
ST_GRAPHIC_REQUIRED = "graphic_required"

NOTE_A_LE_1 = ("A ≤ 1: ток КЗ превышает ток предельной кратности ТТ — насыщение в "
               "установившемся режиме, эксплуатация недопустима (условие (5) ГОСТ).")

ANALYTIC_KEYS = ("without_residual", "with_residual")
GRAPHIC_KEYS = ("graphic_without_residual", "graphic_with_residual")
VAH_KEYS = ("vah_without_residual", "vah_with_residual")
BN_KEYS = ("bn_without_residual", "bn_with_residual")


@dataclass
class CTParams:
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
    detail: str = ""


# ---------------------------------------------------------------------------
# Аналитический метод (5.1)
# ---------------------------------------------------------------------------

def calc_a_param(ct: CTParams, kz: KZParams) -> float:
    if kz.i_kz <= 0:
        raise ValueError("Ток КЗ должен быть больше нуля.")
    if ct.z2_sigma == 0:
        raise ValueError("Полное сопротивление вторичной цепи равно нулю.")
    return (ct.i1_nom * ct.k_nom * ct.z2_sigma_nom) / (kz.i_kz * ct.z2_sigma)


def _analytic(ct, kz, k_r, a) -> SaturationResult:
    notes: List[str] = []
    effective = a * (1.0 - k_r)

    if not (T_P_RANGE_S[0] <= kz.t_p <= T_P_RANGE_S[1]):
        notes.append(f"T_p = {kz.t_p * 1000:.0f} мс вне диапазона приложения Б "
                     f"({T_P_RANGE_S[0] * 1000:.0f}–{T_P_RANGE_S[1] * 1000:.0f} мс).")

    if k_r == 0.0 and a <= 1.0:                       # условие (5)
        notes.append(NOTE_A_LE_1)
        return SaturationResult(a, k_r, ST_STEADY, 0.0, notes, "analytic",
                                cos_alpha=ct.cos_alpha)

    if effective <= 1.0:                              # условие (8)
        notes.append("Условие (8) не выполняется: A·(1−K_r) ≤ 1 — аналитический метод "
                     "неприменим, требуется графический (п. 5.1.5).")
        return SaturationResult(a, k_r, ST_GRAPHIC_REQUIRED, None, notes, "analytic",
                                cos_alpha=ct.cos_alpha)

    denom = OMEGA * kz.t_p + 1.0 - effective
    if denom <= 0.0:                                  # условие (7)
        notes.append("Условие (7) не выполняется: насыщение отсутствует.")
        return SaturationResult(a, k_r, ST_NO_SAT, None, notes, "analytic",
                                cos_alpha=ct.cos_alpha)

    t = kz.t_p * math.log((OMEGA * kz.t_p) / denom)
    if t * 1000.0 < T_NAS_MIN_MS:
        notes.append(f"t_нас = {t * 1000:.1f} мс < 15 мс — уточнить графическим "
                     "методом (п. 5.1.7).")
    return SaturationResult(a, k_r, ST_OK, t, notes, "analytic", cos_alpha=ct.cos_alpha)


# ---------------------------------------------------------------------------
# Графический метод по паспортным данным (5.2), формула (Г.15)
# ---------------------------------------------------------------------------

def k_pr(t, t_p, alpha, theta):
    if np is None:
        raise RuntimeError("Требуется numpy.")
    t_arr = np.asarray(t, dtype=float)
    e = np.exp(-t_arr / t_p)
    return (math.sin(alpha) * math.cos(theta) * e
            + math.cos(alpha) * math.cos(theta) * OMEGA * t_p * (1.0 - e)
            - np.sin(OMEGA * t_arr + alpha + theta)
            + math.cos(alpha) * math.sin(theta))


def t_nas_graphic(a, t_p, alpha, k_r=0.0, n_theta=361, n_t=4000,
                  theta_fixed=None) -> Tuple[Optional[float], Optional[float], str]:
    if np is None:
        raise RuntimeError("Требуется numpy.")
    eff = a * (1.0 - k_r)
    if eff <= 0.0:
        return None, None, "invalid"
    t_max = max(0.25, 6.0 * t_p)
    n_t = int(min(12000, max(n_t, t_max / 0.0002)))
    t = np.linspace(0.0, t_max, n_t)
    thetas = ([float(theta_fixed)] if theta_fixed is not None
              else np.linspace(-np.pi / 2.0, np.pi / 2.0, n_theta))
    best_t = best_th = None
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


def build_kpr_curve(t_p, alpha, theta, t_end_ms, n=1200):
    t = np.linspace(0.0, max(t_end_ms, 1.0) / 1000.0, n)
    return t * 1000.0, np.asarray(k_pr(t, t_p, alpha, theta), dtype=float)


def _graphic(ct, kz, k_r, a, theta_override=None, method="graphic", detail="") \
        -> SaturationResult:
    notes: List[str] = []
    manual = theta_override is not None

    # Условие (5) не зависит от K_r: при A <= 1 оба сценария одинаковы
    if a <= 1.0:
        notes.append(NOTE_A_LE_1)
        return SaturationResult(a, k_r, ST_STEADY, 0.0, notes, method,
                                cos_alpha=ct.cos_alpha, theta_manual=manual, detail=detail)

    t, th, why = t_nas_graphic(a, kz.t_p, ct.alpha, k_r, theta_fixed=theta_override)
    if why == ST_NO_SAT or t is None:
        notes.append("Насыщение магнитопровода отсутствует (уровень A·(1−K_r) недостижим).")
        return SaturationResult(a, k_r, ST_NO_SAT, None, notes, method,
                                cos_alpha=ct.cos_alpha, theta_manual=manual, detail=detail)
    if manual:
        notes.append(f"Время до насыщения при заданной фазе θ = {math.degrees(th):.1f}°.")
    else:
        notes.append(f"Наименьшее время до насыщения при θ* = {math.degrees(th):.1f}° "
                     "(п. Г.3.7).")
    return SaturationResult(a, k_r, ST_OK, t, notes, method, th, ct.cos_alpha,
                            manual, detail)


# ---------------------------------------------------------------------------
# ВАХ (5.3): условие (16), формулы (17), (19), (20)
# ---------------------------------------------------------------------------

def build_vah_default(u_star, i0_star, r2, n_points=200):
    """Типовая монотонная ВАХ: линейный участок до I0*, далее пологий рост."""
    if np is None:
        raise RuntimeError("Требуется numpy.")
    i0_arr = np.linspace(0.0, 3.0 * i0_star, n_points)
    x = i0_arr / i0_star
    u_arr = np.where(x <= 1.0, u_star * x,
                     u_star * (1.0 + 0.15 * (1.0 - np.exp(-(x - 1.0)))))
    return {'i0': i0_arr.tolist(), 'u': u_arr.tolist(),
            'u_star': u_star, 'i0_star': i0_star}


def _interp(x, xs, ys):
    if np is None:
        raise RuntimeError("Требуется numpy.")
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    return float(np.interp(x, xs, ys))


def calc_u2sin(ct, kz):
    """Формула (20): U2sin = Kфакт · I2ном · z2Σ."""
    return (kz.i_kz / ct.i1_nom) * ct.i2_nom * ct.z2_sigma


def validate_vah_usage(u_star, i0_star, ct, kz, eps=10.0, vah_table=None):
    """Условие (16): (I0ε/Uε)/(Iлин/Uлин) > 3 — отношение проводимостей.

    I0ε — по формуле (17): I0ε = (ε/100)·I2ном·Kфакт.
    """
    table = vah_table or build_vah_default(u_star, i0_star, ct.r2)
    i0s, us = table['i0'], table['u']
    k_fact = kz.i_kz / ct.i1_nom
    i0_eps = (eps / 100.0) * ct.i2_nom * k_fact                  # (17)
    u_eps = _interp(i0_eps, i0s, us)
    if u_eps <= 0 or i0_eps <= 0:
        return False, "Не удалось определить Uε по ВАХ.", ""
    # Линейный участок: последняя точка с током не более 10% от I0ε
    lin_idx = [i for i, v in enumerate(i0s) if 0 < v <= 0.1 * i0_eps]
    if not lin_idx:
        return False, "На ВАХ не выделен линейный участок.", ""
    i_lin, u_lin = i0s[lin_idx[-1]], us[lin_idx[-1]]
    if u_lin <= 0:
        return False, "Неверный линейный участок ВАХ.", ""
    ratio = (i0_eps / u_eps) / (i_lin / u_lin)
    detail = (f"I0ε = {i0_eps:.3f} А, Uε = {u_eps:.1f} В; "
              f"отношение проводимостей = {ratio:.2f} (нужно > 3)")
    if ratio > 3.0:
        return True, f"Условие (16) выполняется: {detail}.", detail
    return False, f"Условие (16) не выполняется: {detail}.", detail


def calculate_vah(ct, kz, u_star, i0_star, theta_override=None, k_r=K_R_PRED,
                  eps=10.0, vah_table=None):
    valid, msg, detail = validate_vah_usage(u_star, i0_star, ct, kz, eps, vah_table)
    if not valid:
        return {
            "vah_without_residual": SaturationResult(
                0.0, 0.0, ST_GRAPHIC_REQUIRED, None, [msg], "vah", cos_alpha=ct.cos_alpha),
            "vah_with_residual": SaturationResult(
                0.0, k_r, ST_GRAPHIC_REQUIRED, None, [msg], "vah", cos_alpha=ct.cos_alpha),
        }
    table = vah_table or build_vah_default(u_star, i0_star, ct.r2)
    i0_eps = (eps / 100.0) * ct.i2_nom * (kz.i_kz / ct.i1_nom)
    u_eps = _interp(i0_eps, table['i0'], table['u'])
    u2sin = calc_u2sin(ct, kz)
    a = u_eps / u2sin                                           # (19)
    det = f"U2sin = {u2sin:.1f} В, Uε = {u_eps:.1f} В, A = {a:.3f}"
    wo = _graphic(ct, kz, 0.0, a, theta_override, "vah", det)
    w = _graphic(ct, kz, k_r, a, theta_override, "vah", det)
    for r in (wo, w):
        r.notes.insert(0, "Метод по ВАХ (п. 5.3): " + det)
    return {"vah_without_residual": wo, "vah_with_residual": w}


# ---------------------------------------------------------------------------
# Характеристика намагничивания (5.4): (21), (22), (17), (23), (24)
# ---------------------------------------------------------------------------

def build_bn_default(b_sat=1.8, h_knee=100, n_points=200):
    """Монотонная B(H): линейный рост до колена, затем плавное насыщение."""
    if np is None:
        raise RuntimeError("Требуется numpy.")
    h_arr = np.linspace(0.0, h_knee * 20, n_points)
    b_knee = 0.9 * b_sat
    mu_i = b_knee / h_knee
    h_scale = 0.3 * h_knee
    b_arr = np.where(h_arr <= h_knee, mu_i * h_arr,
                     b_sat - (b_sat - b_knee) * np.exp(-(h_arr - h_knee) / h_scale))
    return {'h': h_arr.tolist(), 'b': b_arr.tolist(),
            'b_sat': b_sat, 'h_knee': h_knee}


def calc_b_from_bn(h_value, bn_data):
    return _interp(h_value, bn_data['h'], bn_data['b'])


def calc_b_m(ct, kz, w2, s):
    """Формула (24): рабочая амплитуда индукции B_m = U2sin/(222·w2·s), с — в м²."""
    if w2 <= 0 or s <= 0:
        return 0.0
    return calc_u2sin(ct, kz) / (222.0 * float(w2) * float(s))


def validate_bn_inputs(w2, s, l, b_sat, h_knee):
    """Контроль корректности вводимых конструктивных параметров."""
    errs = []
    if w2 < 1 or w2 > 100000:
        errs.append("w2 вне разумного диапазона 1…100000 витков")
    if not (1e-5 <= s <= 0.1):
        errs.append("s вне диапазона 0,1…1000 см²")
    if not (0.01 <= l <= 10.0):
        errs.append("l вне диапазона 0,01…10 м")
    if not (0.5 <= b_sat <= 2.5):
        errs.append("Bнас вне диапазона 0,5…2,5 Тл для электротехнической стали")
    if not (1.0 <= h_knee <= 10000.0):
        errs.append("Hколено вне диапазона 1…10000 А/м")
    return (len(errs) == 0), "; ".join(errs)


def validate_bn_usage(ct, kz, bn_data, w2, s, l, eps=10.0):
    """П. 5.4.2, условие (21): B_me(H_e) >= 1,8 Тл.

    H_e = I0ε·w2/l — формула (22); I0ε — формула (17).
    B_me берётся ИЗ ХАРАКТЕРИСТИКИ НАМАГНИЧИВАНИЯ, а не является рабочей B_m.
    """
    ok, msg = validate_bn_inputs(w2, s, l, bn_data.get('b_sat', 1.8),
                                 bn_data.get('h_knee', 100))
    if not ok:
        return False, "Проверка входов: " + msg + ".", "", ""
    i0_eps = (eps / 100.0) * ct.i2_nom * (kz.i_kz / ct.i1_nom)       # (17)
    h_e = i0_eps * float(w2) / float(l)                             # (22)
    b_me = calc_b_from_bn(h_e, bn_data)
    b_m = calc_b_m(ct, kz, w2, s)                                   # (24)
    detail = f"H_e = {h_e:.1f} А/м, B_me(H_e) = {b_me:.3f} Тл, B_m = {b_m:.3f} Тл"
    if b_me >= B_ME_THRESHOLD:
        return True, f"Условие (21) выполняется: {detail}.", detail, b_me
    return False, (f"Условие (21) НЕ выполняется: {detail}. "
                   f"Нужно B_me(H_e) ≥ {B_ME_THRESHOLD} Тл — метод неприменим "
                   "к данной характеристике при этом токе КЗ."), detail, b_me


def calculate_bn(ct, kz, bn_data, w2, s, l, theta_override=None, k_r=K_R_PRED,
                 eps=10.0):
    valid, msg, detail, b_me = validate_bn_usage(ct, kz, bn_data, w2, s, l, eps)
    if not valid:
        return {
            "bn_without_residual": SaturationResult(
                0.0, 0.0, ST_GRAPHIC_REQUIRED, None, [msg], "bn",
                cos_alpha=ct.cos_alpha, detail=detail),
            "bn_with_residual": SaturationResult(
                0.0, k_r, ST_GRAPHIC_REQUIRED, None, [msg], "bn",
                cos_alpha=ct.cos_alpha, detail=detail),
        }
    b_m = calc_b_m(ct, kz, w2, s)
    a = b_me / b_m if b_m > 0 else 0.0        # формула (23): A = B_me / B_m
    det = detail + f", A = {a:.3f}"
    wo = _graphic(ct, kz, 0.0, a, theta_override, "bn", det)
    w = _graphic(ct, kz, k_r, a, theta_override, "bn", det)
    for r in (wo, w):
        r.notes.insert(0, "Метод по характеристике намагничивания (п. 5.4): " + det)
    return {"bn_without_residual": wo, "bn_with_residual": w}


def calculate(ct: CTParams, kz: KZParams, method: str = "both",
              theta_override: Optional[float] = None, k_r: float = K_R_PRED) -> dict:
    a = calc_a_param(ct, kz)
    out = {"without_residual": _analytic(ct, kz, 0.0, a),
           "with_residual": _analytic(ct, kz, k_r, a)}
    if method in ("graphic", "both"):
        out["graphic_without_residual"] = _graphic(ct, kz, 0.0, a, theta_override)
        out["graphic_with_residual"] = _graphic(ct, kz, k_r, a, theta_override)
    return out


# === КОНЕЦ ФАЙЛА methods/gost_58669.py ===
