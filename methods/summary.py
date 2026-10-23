"""
Каскадный разбор методов (п. 4.1, п. 5.1.5, п. 5.1.7 ГОСТ Р 58669-2019).

Порядок: аналитический -> графический по паспортным данным ->
(при наличии данных и включении) ВАХ -> (при наличии) характеристика намагничивания.
Итог выносится по САМОМУ ТОЧНОМУ ИЗ ДОСТУПНЫХ методов; остальные показываются.
"""
from __future__ import annotations

from methods.gost_58669 import (
    ANALYTIC_KEYS, GRAPHIC_KEYS, VAH_KEYS, BN_KEYS,
    ST_OK, ST_NO_SAT, ST_STEADY, ST_GRAPHIC_REQUIRED,
)

# От грубого к точному
METHOD_ORDER = [
    ("analytic", "Аналитический (п. 5.1)", ANALYTIC_KEYS),
    ("graphic", "Графический по паспортным данным (п. 5.2)", GRAPHIC_KEYS),
    ("vah", "По ВАХ (п. 5.3)", VAH_KEYS),
    ("bn", "По характеристике намагничивания (п. 5.4)", BN_KEYS),
]
PRIORITY = ["bn", "vah", "graphic", "analytic"]   # самый точный первым


def _evaluate_method(results, keys):
    """Минимум времени по всем режимам и обоим сценариям для одного метода."""
    times, steady, no_sat, applicable = [], False, True, False
    detail = ""
    for _, _, res in results:
        for key in keys:
            r = res.get(key)
            if r is None:
                continue
            applicable = True
            if r.status == ST_STEADY:
                steady = True
                no_sat = False
            elif r.status == ST_OK and r.t_nas is not None:
                times.append(r.t_nas * 1000.0)
                no_sat = False
            elif r.status != ST_NO_SAT:
                applicable = False
            if r.detail:
                detail = r.detail
    if not applicable:
        return None
    if steady:
        return {"t_ms": 0.0, "status": ST_STEADY, "detail": detail}
    if times:
        return {"t_ms": min(times), "status": ST_OK, "detail": detail}
    if no_sat:
        return {"t_ms": None, "status": ST_NO_SAT, "detail": detail}
    return None


def build_summary(results, vah_on=False, bn_on=False, t_req_ms=0.0):
    """Возвращает (rows, verdict, lines, primary_id).

    rows — сводка по всем методам; lines — пояснение каскада;
    primary_id — метод, по которому вынесен итог.
    """
    available = {"analytic": True, "graphic": True, "vah": vah_on, "bn": bn_on}
    evaluated, rows = {}, []
    for mid, title, keys in METHOD_ORDER:
        if not available.get(mid):
            rows.append({"Метод": title, "Статус": "не включён / нет данных",
                         "t_нас, мс": "—", "Пояснение": "пропущен"})
            continue
        ev = _evaluate_method(results, keys)
        evaluated[mid] = ev
        if ev is None:
            rows.append({"Метод": title, "Статус": "неприменим",
                         "t_нас, мс": "—", "Пояснение": "см. примечания раздела"})
        elif ev["status"] == ST_STEADY:
            rows.append({"Метод": title, "Статус": "насыщение в установившемся режиме",
                         "t_нас, мс": "0", "Пояснение": ev["detail"]})
        elif ev["status"] == ST_NO_SAT:
            rows.append({"Метод": title, "Статус": "насыщения нет",
                         "t_нас, мс": "∞", "Пояснение": ev["detail"]})
        else:
            rows.append({"Метод": title, "Статус": "рассчитано",
                         "t_нас, мс": f"{ev['t_ms']:.2f}", "Пояснение": ev["detail"]})

    primary_id = None
    for mid in PRIORITY:                       # самый точный из применимых
        ev = evaluated.get(mid)
        if ev is not None and ev["status"] in (ST_OK, ST_NO_SAT, ST_STEADY):
            primary_id = mid
            break

    lines = []
    if primary_id is None:
        return rows, "warning", [
            "Ни один из включённых методов не дал применимого результата. "
            "Проверьте исходные данные и условия применимости (п. 5.1.5, п. 5.3.2, п. 5.4.2). "
            "Добавьте данные ВАХ или характеристики намагничивания."], None

    primary_title = next(t for m, t, _ in METHOD_ORDER if m == primary_id)
    ev = evaluated[primary_id]
    skipped = [t for m, t, _ in METHOD_ORDER
               if m in evaluated and evaluated[m] is None and m != primary_id]
    if skipped:
        lines.append("Неприменимые методы пропущены: " + "; ".join(skipped) + ".")

    if ev["status"] == ST_STEADY:
        return rows, "danger", lines + [
            f"Определяющий метод: {primary_title}. A ≤ 1 — насыщение в установившемся "
            "режиме, эксплуатация недопустима."], primary_id

    if ev["status"] == ST_NO_SAT:
        return rows, "success", lines + [
            f"Определяющий метод: {primary_title}. Насыщение магнитопровода отсутствует "
            "во всех расчётных режимах."], primary_id

    t_min = ev["t_ms"]
    lines.append(f"Определяющий метод: {primary_title}. Наименьшее t_нас = {t_min:.2f} мс.")
    verdict = "success"
    if t_req_ms > 0:
        if t_min >= t_req_ms:
            lines.append(f"Требование выполняется: {t_min:.2f} ≥ {t_req_ms:g} мс.")
        else:
            verdict = "danger"
            lines.append(f"Требование НЕ выполняется: {t_min:.2f} < {t_req_ms:g} мс. "
                         "Рекомендация: ТТ с большей Kном/Sном или меньшее сопротивление "
                         "вторичной цепи (сечение/длина кабеля).")
    if primary_id == "analytic" and t_min < 15.0:
        verdict = "danger" if verdict == "danger" else "warning"
        lines.append("t_нас < 15 мс: аналитический метод недостаточно точен (п. 5.1.7) — "
                     "включите графический метод.")
    return rows, verdict, lines, primary_id


# === КОНЕЦ ФАЙЛА methods/summary.py ===
