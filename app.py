import streamlit as st
import datetime
import requests
from PIL import Image
import io

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

st.set_page_config(page_title="Storm Inspection Report", layout="wide")

st.title("Roof & Storm Damage Inspection Generator")

# --- 1. APP INPUTS & CALENDAR PICKER ---
col1, col2 = st.columns(2)

with col1:
    customer_name = st.text_input("Customer Name")
    
    # Address Autofill via Nominatim
    address_query = st.text_input("Search Customer Address", value="", help="Start typing to search address")
    selected_address = address_query
    
    if address_query and len(address_query) > 3:
        try:
            url = f"https://nominatim.openstreetmap.org/search?format=json&q={address_query}"
            headers = {'User-Agent': 'StormInspectorApp/1.0'}
            response = requests.get(url, headers=headers).json()
            if response:
                options = [item['display_name'] for item in response]
                selected_address = st.selectbox("Select Matching Address", options)
        except Exception:
            selected_address = address_query

with col2:
    # Date Pickers
    inspection_date = st.date_input("Inspection Date", value=datetime.date.today())
    date_of_loss = st.date_input("Date of Loss", value=datetime.date.today())

st.divider()

# --- FILE UPLOADS ---
logo_file = st.file_uploader("Upload Company Logo", type=["png", "jpg", "jpeg"])
uploaded_photos = st.file_uploader("Upload Inspection Photos", type=["png", "jpg", "jpeg"], accept_multiple_files=True)


# --- AUXILIARY FUNCTIONS FOR PDF ---
def get_aspect_image(file_bytes, max_w, max_h):
    """Calculates aspect ratio to prevent stretched images in ReportLab PDF"""
    img = Image.open(io.BytesIO(file_bytes))
    w, h = img.size
    aspect = h / float(w)
    
    if w > h:
        new_w = max_w
        new_h = max_w * aspect
        if new_h > max_h:
            new_h = max_h
            new_w = max_h / aspect
    else:
        new_h = max_h
        new_w = max_h / aspect
        if new_w > max_w:
            new_w = max_w
            new_h = max_w * aspect
            
    img_buffer = io.BytesIO(file_bytes)
    return RLImage(img_buffer, width=new_w, height=new_h)


# --- PDF GENERATION ENGINE ---
def generate_pdf():
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    styles = getSampleStyleSheet()

    # Header / Logo
    if logo_file:
        logo_img = get_aspect_image(logo_file.getvalue(), max_w=180, max_h=60)
        story.append(logo_img)
        story.append(Spacer(1, 12))

    # Title
    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontSize=20, leading=24, textColor=colors.HexColor("#1A365D"))
    story.append(Paragraph("Inspection & Damage Report", title_style))
    story.append(Spacer(1, 12))

    # Details Table
    data = [
        [Paragraph("<b>Customer Name:</b>", styles['Normal']), Paragraph(customer_name, styles['Normal'])],
        [Paragraph("<b>Property Address:</b>", styles['Normal']), Paragraph(selected_address, styles['Normal'])],
        [Paragraph("<b>Inspection Date:</b>", styles['Normal']), Paragraph(inspection_date.strftime("%m/%d/%Y"), styles['Normal'])],
        [Paragraph("<b>Date of Loss:</b>", styles['Normal']), Paragraph(date_of_loss.strftime("%m/%d/%Y"), styles['Normal'])],
    ]
    info_table = Table(data, colWidths=[130, 400])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F7FAFC")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 20))

    # Photos 3-Column Grid with Aspect Ratio Fix
    if uploaded_photos:
        story.append(Paragraph("<b>Inspection Photos</b>", styles['Heading2']))
        story.append(Spacer(1, 10))
        
        grid_data = []
        row = []
        
        for idx, photo in enumerate(uploaded_photos):
            photo_bytes = photo.getvalue()
            # Formats image proportionally into 3-column width max box (160x120)
            rl_img = get_aspect_image(photo_bytes, max_w=165, max_h=130)
            
            row.append(rl_img)
            
            if len(row) == 3 or idx == len(uploaded_photos) - 1:
                # Pad incomplete last row with empty strings
                while len(row) < 3:
                    row.append("")
                grid_data.append(row)
                row = []

        photo_table = Table(grid_data, colWidths=[180, 180, 180])
        photo_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 12),
        ]))
        story.append(photo_table)

    doc.build(story)
    buffer.seek(0)
    return buffer


if st.button("Generate Inspection PDF Report"):
    if not customer_name or not selected_address:
        st.warning("Please fill out customer name and address first.")
    else:
        pdf_out = generate_pdf()
        st.download_button(
            label="Download Completed PDF",
            data=pdf_out,
            file_name=f"Inspection_{customer_name.replace(' ', '_')}.pdf",
            mime="application/pdf"
        )
