import streamlit as st
import math
from docx import Document
from docx.shared import Pt, Inches
import io
from datetime import datetime

st.set_page_config(page_title="Расчет ТТ по ГОСТ Р 58669-2019", layout="wide", page_icon="⚡")

st.title("⚡ Калькулятор времени до насыщения ТТ")
st.markdown("Расчет выполняется аналитическим методом в соответствии с **ГОСТ Р 58669-2019**.")

st.sidebar.header("⚙️ Параметры трансформатора тока (ТТ)")
i1_nom = st.sidebar.number_input("Номинальный первичный ток I₁ном (А)", min_value=1.0, value=1000.0, step=10.0)
i2_nom = st.sidebar.number_input("Номинальный вторичный ток I₂ном (А)", min_value=1.0, max_value=5.0, value=5.0, step=1.0)
k_nom = st.sidebar.number_input("Номинальная предельная кратность Kном", min_value=1.0, value=10.0, step=1.0)
s_nom = st.sidebar.number_input("Номинальная мощность вторичной нагрузки Sном (ВА)", min_value=1.0, value=15.0, step=1.0)
cos_phi_nom = st.sidebar.number_input("cos φ номинальной нагрузки", min_value=0.1, max_value=1.0, value=0.8, step=0.1)
r2 = st.sidebar.number_input("Активное сопротивление вторичной обмотки R₂ (Ом)", min_value=0.0, value=0.15, step=0.01)
x2 = st.sidebar.number_input("Индуктивное сопротивление вторичной обмотки X₂ (Ом)", min_value=0.0, value=0.0, step=0.01)

st.sidebar.header("⚙️ Параметры цепи и КЗ")
r_n_fakt = st.sidebar.number_input("Фактическое активное сопротивление нагрузки Rн.факт (Ом)", min_value=0.0, value=0.5, step=0.01)
x_n_fakt = st.sidebar.number_input("Фактическое индуктивное сопротивление нагрузки Xн.факт (Ом)", min_value=0.0, value=0.0, step=0.01)
i_kz = st.sidebar.number_input("Действующее значение тока КЗ Iкз (А)", min_value=1.0, value=15000.0, step=100.0)
t_p = st.sidebar.number_input("Постоянная времени затухания апериодической составляющей Tр (с)", min_value=0.001, value=0.05, step=0.001)

st.sidebar.header("⚙️ Дополнительные настройки")
use_residual = st.sidebar.checkbox("Учитывать остаточную намагниченность (класс P, Kr=0.86)", value=True)
k_r = 0.86 if use_residual else 0.0

# --- РАСЧЕТНАЯ ЧАСТЬ ---
omega = 2 * math.pi * 50  # 314.159 рад/с для 50 Гц

z_n_nom = s_nom / (i2_nom ** 2)
z_2_sigma_nom = math.sqrt((r2 + z_n_nom * cos_phi_nom)**2 + (x2 + z_n_nom * math.sin(math.acos(cos_phi_nom)))**2)
z_2_sigma = math.sqrt((r2 + r_n_fakt)**2 + (x2 + x_n_fakt)**2)

a_param = (i1_nom * k_nom * z_2_sigma_nom) / (i_kz * z_2_sigma)

# Расчет времени до насыщения
def calc_t_nas(tp, a, kr):
    denom = omega * tp + 1 - a * (1 - kr)
    if denom <= 0:
        return float('inf')
    return tp * math.log((omega * tp + 1) / denom)

t_nas_val = calc_t_nas(t_p, a_param, k_r)
t_nas_no_res = calc_t_nas(t_p, a_param, 0.0)

# --- ВЫВОД РЕЗУЛЬТАТОВ ---
st.markdown("---")
st.subheader("📊 Результаты расчета")

col1, col2, col3 = st.columns(3)
col1.metric("Параметр режима (A)", f"{a_param:.3f}")
col2.metric("Время до насыщения (t_нас)", f"{t_nas_val*1000:.1f} мс" if t_nas_val != float('inf') else "∞ (не насыщается)")
col3.metric("Ток предельной кратности", f"{i1_nom * k_nom:.0f} А")

# Анализ условий
st.markdown("### 📝 Анализ условий")
if a_param <= 1:
    st.error("⚠️ **Внимание!** A ≤ 1. Ток КЗ превышает ток предельной кратности ТТ. Трансформатор насыщается уже в установившемся режиме. Проверка некорректна.")
elif t_nas_val == float('inf'):
    st.success("✅ Насыщение магнитопровода в переходном процессе **не происходит** (условие ω·Tp + 1 > A·(1-Kr) выполняется).")
elif t_nas_val * 1000 < 15:
    st.warning(f"⚠️ Время до насыщения составляет **{t_nas_val*1000:.1f} мс** (< 15 мс). Согласно п. 5.1.7 ГОСТ Р 58669-2019, рекомендуется уточнить расчет графическим методом по паспортным данным или ВАХ.")
else:
    st.success(f"✅ Время до насыщения **{t_nas_val*1000:.1f} мс**. Значение находится в допустимых пределах для аналитической оценки.")

# --- ГЕНЕРАЦИЯ ОТЧЕТА WORD ---
st.markdown("---")
st.subheader("📥 Экспорт отчета")

def generate_report():
    doc = Document()
    doc.add_heading('Отчет о проверке трансформатора тока', 0)
    doc.add_paragraph(f'Дата формирования: {datetime.now().strftime("%d.%m.%Y %H:%M")}')
    doc.add_paragraph('Методика: ГОСТ Р 58669-2019, аналитический метод определения времени до насыщения.')
    
    doc.add_heading('1. Исходные данные', level=1)
    table = doc.add_table(rows=1, cols=2)
    table.style = 'Light Grid Accent 1'
    hdr_cells = table.rows[0].cells
    hdr_cells[0].text = 'Параметр'
    hdr_cells[1].text = 'Значение'
    
    params = {
        "I₁ном": f"{i1_nom} А", "I₂ном": f"{i2_nom} А", "Kном": k_nom,
        "Sном": f"{s_nom} ВА", "cos φном": cos_phi_nom, "R₂": f"{r2} Ом",
        "X₂": f"{x2} Ом", "Rн.факт": f"{r_n_fakt} Ом", "Xн.факт": f"{x_n_fakt} Ом",
        "Iкз": f"{i_kz} А", "Tр": f"{t_p} с", "Учет остаточной намагниченности": "Да" if use_residual else "Нет"
    }
    for k, v in params.items():
        row_cells = table.add_row().cells
        row_cells[0].text = str(k)
        row_cells[1].text = str(v)
        
    doc.add_heading('2. Промежуточные расчеты', level=1)
    table2 = doc.add_table(rows=1, cols=2)
    table2.style = 'Light Grid Accent 1'
    hdr_cells2 = table2.rows[0].cells
    hdr_cells2[0].text = 'Параметр'
    hdr_cells2[1].text = 'Значение'
    
    intermediate = {
        "zн.ном": f"{z_n_nom:.4f} Ом",
        "z₂Σ.ном": f"{z_2_sigma_nom:.4f} Ом",
        "z₂Σ": f"{z_2_sigma:.4f} Ом",
        "Параметр режима (A)": f"{a_param:.4f}",
        "ω (угловая частота)": f"{omega:.2f} рад/с"
    }
    for k, v in intermediate.items():
        row_cells = table2.add_row().cells
        row_cells[0].text = str(k)
        row_cells[1].text = str(v)

    doc.add_heading('3. Итоговый результат', level=1)
    res_text = f"{t_nas_val*1000:.2f} мс" if t_nas_val != float('inf') else "∞ (насыщение не происходит)"
    p = doc.add_paragraph()
    runner = p.add_run(f"Время до насыщения (t_нас): {res_text}")
    runner.bold = True
    runner.font.size = Pt(14)
    
    conclusion = "Трансформатор тока удовлетворяет требованиям по времени до насыщения." if (t_nas_val == float('inf') or t_nas_val * 1000 >= 15) else "Требуется дополнительный анализ (графический метод или выбор ТТ с другими характеристиками)."
    doc.add_paragraph(conclusion, style='Intense Quote')
    
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()

if st.button("📄 Сформировать и скачать отчет в Word"):
    doc_bytes = generate_report()
    st.download_button(
        label="Скачать .docx",
        data=doc_bytes,
        file_name=f"OTchet_TT_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )