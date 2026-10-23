"""Загрузка и ввод характеристик ВАХ и B(H) из файлов и вручную. Релиз 2.0."""
from __future__ import annotations

import io
import pandas as pd

MIN_POINTS = 5

VAH_TEMPLATE = (
    "I0_A;U_V\n"
    "0.01;5.0\n0.05;24.0\n0.10;47.0\n0.30;98.0\n0.60;120.0\n1.20;132.0\n"
)
BN_TEMPLATE = (
    "H_A_per_m;B_T\n"
    "10;0.18\n30;0.54\n60;1.05\n100;1.62\n200;1.76\n500;1.79\n"
)


def read_uploaded_curve(uploaded) -> pd.DataFrame:
    """Читает CSV / TXT / XLSX в DataFrame."""
    name = (getattr(uploaded, "name", "") or "").lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded)
    raw = uploaded.getvalue().decode("utf-8-sig", errors="replace")
    try:
        return pd.read_csv(io.StringIO(raw), sep=None, engine="python")
    except Exception:
        return pd.read_csv(io.StringIO(raw), sep=";", engine="python")


def _to_numeric(series: pd.Series) -> pd.Series:
    if series.dtype == object:
        series = series.astype(str).str.strip().str.replace(",", ".", regex=False)
    return pd.to_numeric(series, errors="coerce")


def dataframe_to_curve(df: pd.DataFrame):
    """Первые две числовые колонки -> (x, y). Нечисловые/пустые строки отбрасываются."""
    cols = {c: _to_numeric(df[c]) for c in df.columns}
    num = [c for c in cols if cols[c].notna().any()]
    if len(num) < 2:
        raise ValueError("Нужно минимум две числовые колонки (аргумент и значение).")
    x, y = cols[num[0]], cols[num[1]]
    mask = x.notna() & y.notna()
    return x[mask].astype(float).tolist(), y[mask].astype(float).tolist()


def validate_curve(x, y, min_points=MIN_POINTS):
    """Очистка и проверка. Возвращает (пригодно, предупреждения, xs, ys)."""
    warns = []
    pairs = [(float(xi), float(yi)) for xi, yi in zip(x, y)
             if xi == xi and yi == yi and xi is not None and yi is not None
             and float(xi) > 0 and float(yi) >= 0]
    if not pairs:
        return False, ["Нет корректных точек (нужны положительные значения)."], [], []
    pairs.sort(key=lambda p: p[0])
    uniq, seen = [], set()
    for xi, yi in pairs:
        if xi in seen:
            continue
        seen.add(xi)
        uniq.append((xi, yi))
    if len(uniq) < len(pairs):
        warns.append("Удалены повторяющиеся значения аргумента.")
    xs = [p[0] for p in uniq]
    ys = [p[1] for p in uniq]
    if len(xs) < min_points:
        warns.append(f"Точек {len(xs)} при рекомендуемом минимуме {min_points} — "
                     "интерполяция может быть неточной.")
    return True, warns, xs, ys


def curve_from_dataframe(df: pd.DataFrame, min_points=MIN_POINTS):
    """Обёртка: (пригодно, предупреждения, xs, ys)."""
    x, y = dataframe_to_curve(df)
    return validate_curve(x, y, min_points)


# === КОНЕЦ ФАЙЛА methods/curve_io.py ===
