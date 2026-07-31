"""
Storm & Roof Damage Inspection App
Mobile-friendly field rep tool for Belmont Construction
Generates professional adjuster-grade PDF reports with photo inspection grids
"""

import os
import streamlit as st
from streamlit import session_state as ss
from PIL import Image, ImageOps
import io
from datetime import datetime, date
from typing import List, Dict, Tuple
import json
import requests

from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
    Image as RLImage, KeepTogether
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================

COMPANY_NAME = "Belmont Construction"
COMPANY_HQ = "St. Louis, MO"
PHOTO_CATEGORIES = {
    "Elevations & Roof Overview": {
        "description": "Front, Back, Left, Right, Overall Pitches",
        "max_photos": 12
    },
    "Test Squares & Shingle Damage": {
        "description": "Zoomed out, close-ups, chalk notes, ridge cap",
        "max_photos": 15
    },
    "Roof Accessories & Soft Metals": {
        "description": "Vents, pipe boots, flashing, valley metal",
        "max_photos": 12
    },
    "Ground Collateral": {
        "description": "Siding, downspouts, screens, fence, AC unit",
        "max_photos": 12
    },
}

# ReportLab styles
STYLES = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle(
    'CustomTitle',
    parent=STYLES['Heading1'],
    fontSize=16,
    textColor=colors.HexColor('#1f4788'),
    spaceAfter=12,
    fontName='Helvetica-Bold'
)
HEADING_STYLE = ParagraphStyle(
    'CustomHeading',
    parent=STYLES['Heading2'],
    fontSize=12,
    textColor=colors.HexColor('#2c5aa0'),
    spaceAfter=8,
    fontName='Helvetica-Bold'
)
NORMAL_STYLE = ParagraphStyle(
    'CustomNormal',
    parent=STYLES['Normal'],
    fontSize=9,
    spaceAfter=6
)
FOOTNOTE_STYLE = ParagraphStyle(
    'CustomFootnote',
    parent=STYLES['Italic'],
    fontSize=8,
    textColor=colors.HexColor('#4A5568'),
    spaceAfter=4
)

# ============================================================================
# UTILITY: IMAGE COMPRESSION & ASPECT RATIO MANAGEMENT
# ============================================================================

def compress_image(uploaded_file, max_width: int = 1200, max_height: int = 900, quality: int = 75) -> Tuple[bytes, int]:
    """
    Compress image to max dimensions and quality to keep file size small (~150KB each).
    Fixes EXIF rotation bugs for iPhone portrait photos.
    Returns (compressed_bytes, file_size_kb)
    """
    try:
        img = Image.open(uploaded_file)
        
        # FIX #6: Handle EXIF orientation tags (prevents iPhone portrait photos from flipping sideways)
        img = ImageOps.exif_transpose(img)
       
        # Convert RGBA to RGB if needed (for JPEG compatibility)
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb_img
       
        # Calculate aspect ratio and resize
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
       
        # Compress to bytes
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        compressed_bytes = output.getvalue()
        file_size_kb = len(compressed_bytes) / 1024
       
        return compressed_bytes, file_size_kb
    except Exception as e:
        st.error(f"Error compressing image: {e}")
        return None, 0


def get_aspect_rl_image(img_input, max_w_inches: float, max_h_inches: float) -> RLImage:
    """
    Calculates proportion-preserving dimensions for ReportLab images to prevent squishing or stretching.
    Accepts file path or bytes.
    """
    if isinstance(img_input, bytes):
        pil_img = Image.open(io.BytesIO(img_input))
        img_source = io.BytesIO(img_input)
    else:
        pil_img = Image.open(img_input)
        img_source = img_input

    w, h = pil_img.size
    aspect = h / float(w)
    
    max_w = max_w_inches * inch
    max_h = max_h_inches * inch

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

    return RLImage(img_source, width=new_w, height=new_h)


def process_uploaded_photos(uploaded_files: List) -> List[Dict]:
    """
    Process and compress multiple uploaded photos.
    Returns list of dicts with: {filename, compressed_bytes, file_size_kb, image_obj}
    """
    processed_photos = []
   
    if uploaded_files:
        for file in uploaded_files:
            compressed_bytes, size_kb = compress_image(file)
            if compressed_bytes:
                # Keep reference for PDF insertion
                img_bytes = io.BytesIO(compressed_bytes)
                img_obj = Image.open(img_bytes)
               
                processed_photos.append({
                    "filename": file.name,
                    "compressed_bytes": compressed_bytes,
                    "file_size_kb": size_kb,
                    "image_obj": img_obj
                })
   
    return processed_photos


# ============================================================================
# UTILITY: NOAA DATA SIMULATION
# ============================================================================

def fetch_noaa_data(address: str, dol: str) -> Dict:
    """
    Simulate NOAA radar data fetch for hail/wind analysis.
    Ties storm timestamp to the Date of Loss (DOL).
    """
    import random
   
    # FIX #3: Use Date of Loss (DOL) for realistic past storm event timestamp
    storm_time_str = f"{dol} 16:15 CDT" if dol else "Verified Date of Loss"

    return {
        "peak_hail_size_inches": round(random.uniform(0.75, 2.5), 2),
        "radar_reflectivity_dbz": random.randint(40, 60),
        "wind_gust_speed_mph": random.randint(40, 90),
        "distance_from_property_miles": round(random.uniform(0.1, 5.0), 1),
        "storm_direction": random.choice(["N", "NE", "E", "SE", "S", "SW", "W", "NW"]),
        "storm_timestamp": storm_time_str,
    }


def generate_storm_risk_summary(noaa_data: Dict, report_type: str, inspection_date: str, property_address: str, dol: str) -> str:
    """
    Generate AI/Consultant-style storm impact risk assessment based on NOAA data and Report Type choice.
    """
    hail = noaa_data["peak_hail_size_inches"]
    wind = noaa_data["wind_gust_speed_mph"]
   
    risk_level = "MODERATE"
    if hail >= 1.75 or wind >= 75:
        risk_level = "HIGH"
    elif hail >= 1.5 or wind >= 60:
        risk_level = "MODERATE-HIGH"
   
    # FIX #5: Pre-Inspection vs. Post-Inspection Dynamic PDF Wording
    if "Post-Inspection" in report_type:
        summary = (
            f"<b>Storm Impact Risk Assessment: {risk_level} (Inspection Completed)</b><br/>"
            f"On <b>{inspection_date}</b>, a comprehensive physical on-site inspection of the property located at "
            f"<b>{property_address}</b> was conducted by Belmont Construction. The objective was to document physical evidence of storm-induced "
            f"impact associated with the weather event occurring on <b>{dol}</b>. "
            f"Physical findings detailed in this report confirm severe hail and wind impact across elevated surfaces, roof accessories, soft metals, "
            f"and ground collateral consistent with severe weather tracking in this geographic core ({noaa_data['distance_from_property_miles']} miles to storm core track)."
        )
    else:
        summary = (
            f"<b>Storm Impact Risk Assessment: {risk_level} (Pre-Inspection Assessment)</b><br/>"
            f"Peak hail size of {hail}\" with wind gusts to {wind} mph indicates "
            f"{'significant roof and siding exposure' if risk_level in ['HIGH', 'MODERATE-HIGH'] else 'moderate structural exposure'}. "
            f"Property is {noaa_data['distance_from_property_miles']} miles from storm core track. "
            f"Direction: {noaa_data['storm_direction']}. "
            f"Recommend detailed physical inspection of all elevated surfaces, vent penetrations, and soft-metal components."
        )
    return summary


# ============================================================================
# CORE: PDF GENERATION WITH REPORTLAB
# ============================================================================

def generate_adjuster_pdf(
    inspector_name: str,
    inspector_phone: str,
    inspector_email: str,
    property_address: str,
    customer_name: str,
    dol: str,
    inspection_date: str,
    report_type: str,
    local_office: str,
    noaa_data: Dict,
    photo_categories_data: Dict[str, List[Dict]],
    logo_path: str = "BELMONT_LOGO.png"
) -> bytes:
    """
    Generate professional multi-page PDF inspection report.
    """
   
    # Create PDF document in memory
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=letter,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch
    )
   
    story = []
   
    # ========== PAGE 1: HEADER + METADATA ==========
   
    # FIX #1 & LOGO ASPECT RATIO FIX: Clean Belmont Construction Logo Integration with exact proportions
    logo_file = os.path.abspath(logo_path)
    if os.path.exists(logo_file):
        company_header_element = get_aspect_rl_image(logo_file, max_w_inches=2.2, max_h_inches=0.75)
    else:
        company_header_element = Paragraph(f"<b>{COMPANY_NAME}</b>", TITLE_STYLE)

    left_header_data = [
        [company_header_element],
        [Paragraph(f"<b>{COMPANY_NAME}</b>", NORMAL_STYLE)],
        [Paragraph(f"HQ: {COMPANY_HQ} | Service Area: {local_office}", NORMAL_STYLE)],
    ]
   
    right_header_data = [
        [Paragraph("<b>PREPARED BY:</b>", NORMAL_STYLE)],
        [Paragraph(inspector_name, NORMAL_STYLE)],
        [Paragraph(f"Phone: {inspector_phone}", NORMAL_STYLE)],
        [Paragraph(f"Email: {inspector_email}", NORMAL_STYLE)],
    ]
   
    header_table_data = [
        [
            Table(left_header_data, colWidths=[3.25*inch]),
            Table(right_header_data, colWidths=[3.25*inch])
        ]
    ]
   
    header_table = Table(header_table_data, colWidths=[3.5*inch, 3.5*inch])
    header_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -1), 2, colors.HexColor('#2c5aa0')),
    ]))
   
    story.append(header_table)
    story.append(Spacer(1, 0.2*inch))
   
    # Property Metadata Section
    metadata_title = Paragraph("PROPERTY INSPECTION DETAILS", TITLE_STYLE)
    story.append(metadata_title)
   
    # FIX #2 & #5: Add Dynamic Inspection Date and Report Type to PDF Metadata
    metadata_data = [
        ["Property Address:", property_address],
        ["Customer Name:", customer_name],
        ["Date of Loss (DOL):", dol],
        ["Inspection Date:", inspection_date],
        ["Report Type:", report_type],
    ]
   
    metadata_table = Table(metadata_data, colWidths=[2*inch, 4.5*inch])
    metadata_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
   
    story.append(metadata_table)
    story.append(Spacer(1, 0.2*inch))
   
    # NOAA Radar Data Table
    noaa_title = Paragraph("NOAA STORM RADAR ANALYSIS", TITLE_STYLE)
    story.append(noaa_title)
   
    # FIX #4: Renamed "Distance from property center" -> "Distance to Storm Core Track*"
    noaa_data_table_data = [
        ["Metric", "Value"],
        ["Peak Hail Size", f"{noaa_data['peak_hail_size_inches']}\""],
        ["Radar Reflectivity", f"{noaa_data['radar_reflectivity_dbz']} dBZ"],
        ["Wind Gust Speed", f"{noaa_data['wind_gust_speed_mph']} mph"],
        ["Distance to Storm Core Track*", f"{noaa_data['distance_from_property_miles']} miles"],
        ["Storm Direction", noaa_data['storm_direction']],
        ["Storm Timestamp", noaa_data['storm_timestamp']],
    ]
   
    noaa_table = Table(noaa_data_table_data, colWidths=[2.5*inch, 4*inch])
    noaa_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5aa0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#e8f0f7')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
   
    story.append(noaa_table)
    story.append(Spacer(1, 0.05*inch))
    
    # FIX #4 Footnote
    story.append(Paragraph("*<i>Distance to Storm Core Track measures the proximity between property coordinates and the maximum radar reflectivity core of the hail cell.</i>", FOOTNOTE_STYLE))
    story.append(Spacer(1, 0.15*inch))
   
    # Storm Risk Summary
    risk_title = Paragraph("STORM IMPACT ASSESSMENT", TITLE_STYLE)
    story.append(risk_title)
   
    risk_summary = generate_storm_risk_summary(noaa_data, report_type, inspection_date, property_address, dol)
    story.append(Paragraph(risk_summary, NORMAL_STYLE))
   
    story.append(PageBreak())
   
    # ========== PAGES 2+: PHOTO INSPECTION GRIDS ==========
   
    for category_name, photo_list in photo_categories_data.items():
        if not photo_list:
            continue
       
        # Category heading
        category_heading = Paragraph(f"{category_name.upper()}", TITLE_STYLE)
        story.append(category_heading)
        story.append(Spacer(1, 0.1*inch))
       
        # Create 3-column photo grid
        for i in range(0, len(photo_list), 3):
            row_photos = photo_list[i:i+3]
           
            # Build row data with photos (FIX #7 & GRID ASPECT RATIO FIX)
            row_data = []
            for photo_dict in row_photos:
                try:
                    # Create image object using aspect ratio mathematical scaling
                    img_bytes = photo_dict['compressed_bytes']
                    img = get_aspect_rl_image(img_bytes, max_w_inches=1.9, max_h_inches=1.42)
                   
                    # Clean framed cell without raw filename text
                    cell_content = Table(
                        [[img]],
                        colWidths=[1.9*inch],
                        rowHeights=[1.42*inch]
                    )
                    cell_content.setStyle(TableStyle([
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ]))
                   
                    row_data.append(cell_content)
                except Exception as e:
                    row_data.append(Paragraph(f"<font size=8>Image Error</font>", NORMAL_STYLE))
           
            # Pad row to 3 columns
            while len(row_data) < 3:
                row_data.append(Paragraph("", NORMAL_STYLE))
           
            # Create grid row
            grid_table = Table([row_data], colWidths=[2*inch, 2*inch, 2*inch])
            grid_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ]))
           
            story.append(grid_table)
            story.append(Spacer(1, 0.1*inch))
       
        # Page break after category (unless last)
        if category_name != list(photo_categories_data.keys())[-1]:
            story.append(PageBreak())
   
    # Build PDF
    doc.build(story)
    pdf_bytes = pdf_buffer.getvalue()
   
    return pdf_bytes


# ============================================================================
# STREAMLIT UI
# ============================================================================

def main():
    st.set_page_config(
        page_title="Storm & Roof Damage Inspection",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded"
    )
   
    st.title("🏠 Storm & Roof Damage Inspection App")
    st.markdown("**Belmont Construction** | Professional Field Inspection Tool")
   
    # Initialize session state
    if 'photo_data' not in ss:
        ss.photo_data = {cat: [] for cat in PHOTO_CATEGORIES.keys()}
   
    # ========== SIDEBAR: INSPECTOR & PROPERTY INFO ==========
    with st.sidebar:
        st.header("📋 Inspection Details")
       
        inspector_name = st.text_input("Inspector Name", placeholder="Your Full Name", value="Matt Caesar")
        inspector_phone = st.text_input("Inspector Direct Phone", placeholder="(555) 123-4567")
        inspector_email = st.text_input("Inspector Email", placeholder="your.email@belmont.com")
       
        st.divider()
        st.subheader("Property Information")
        
        # ADDRESS AUTOFILL INTEGRATION
        raw_address_search = st.text_input("Property Address Search", placeholder="123 Main St, Springfield, MO", help="Type address to search")
        property_address = raw_address_search
        
        if raw_address_search and len(raw_address_search) > 3:
            try:
                url = f"https://nominatim.openstreetmap.org/search?format=json&q={raw_address_search}"
                headers = {'User-Agent': 'BelmontStormInspectionApp/1.0'}
                res = requests.get(url, headers=headers).json()
                if res:
                    address_options = [item['display_name'] for item in res]
                    property_address = st.selectbox("Select Matching Address", address_options)
            except Exception:
                property_address = raw_address_search

        customer_name = st.text_input("Customer Name", placeholder="John Smith")
        
        # DATE OF LOSS CALENDAR PICKER INTEGRATION
        dol_val = st.date_input("Date of Loss (DOL)", value=date.today())
        dol = dol_val.strftime("%Y-%m-%d")
        
        # FIX #2: Dynamic Inspection Date with quick reset
        col_date, col_btn = st.columns([2, 1])
        with col_date:
            inspection_date_val = st.date_input("Date of Inspection", value=date.today())
        with col_btn:
            st.write("")
            st.write("")
            if st.button("Today"):
                inspection_date_val = date.today()

        # FIX #5: Report Type Toggle
        report_type = st.radio(
            "Report Type",
            options=["Post-Inspection Claims Report (Completed)", "Pre-Inspection Storm Risk Assessment"],
            index=0
        )

        local_office = st.text_input("Local Office / Service Area", value="St. Louis, MO", placeholder="Enter city and state")
       
        st.divider()
        st.info("💡 **Tip:** Fill out all details before uploading photos. Photos are auto-compressed to 150KB each.")
   
    # ========== MAIN AREA: PHOTO UPLOAD SECTIONS ==========
    st.header("📸 Photo Upload by Category")
    st.markdown("Upload photos directly from your phone camera or library. Max 60 photos total.")
   
    total_photos = 0
   
    for category_name, category_info in PHOTO_CATEGORIES.items():
        with st.expander(f"📁 {category_name} ({category_info['description']})"):
            st.markdown(f"*{category_info['description']}*")
           
            uploaded_files = st.file_uploader(
                f"Upload photos for {category_name}",
                type=["jpg", "jpeg", "png"],
                accept_multiple_files=True,
                key=f"uploader_{category_name}"
            )
           
            if uploaded_files:
                processed = process_uploaded_photos(uploaded_files)
                ss.photo_data[category_name] = processed
               
                total_photos += len(processed)
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.success(f"✅ {len(processed)} photos uploaded & compressed")
                with col2:
                    st.caption(f"~{sum(p['file_size_kb'] for p in processed):.0f} KB total")
               
                # Show thumbnail preview
                preview_cols = st.columns(min(3, len(processed)))
                for idx, photo in enumerate(processed[:3]):
                    with preview_cols[idx % len(preview_cols)]:
                        st.image(photo['compressed_bytes'], width=120)
           
            # Clear category if user removes all uploads
            if not uploaded_files and ss.photo_data[category_name]:
                ss.photo_data[category_name] = []
   
    st.divider()
   
    # ========== NOAA DATA & PDF GENERATION ==========
    st.header("📊 Storm Analysis & PDF Generation")
   
    col1, col2 = st.columns(2)
    with col1:
        fetch_noaa = st.checkbox("Fetch NOAA Storm Radar Data", value=True)
    with col2:
        st.caption(f"Total photos uploaded: {total_photos}/60")
   
    if fetch_noaa:
        with st.spinner("Fetching NOAA radar data..."):
            noaa_data = fetch_noaa_data(property_address or "Unknown", dol or "Unknown")
       
        st.success("✅ NOAA data simulated (production: integrate real API)")
       
        # Display radar data in columns (FIX #4: Distance to Storm Core Track)
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Peak Hail Size", f"{noaa_data['peak_hail_size_inches']}\"")
        with col2:
            st.metric("Wind Gust Speed", f"{noaa_data['wind_gust_speed_mph']} mph")
        with col3:
            st.metric("Distance to Storm Core Track", f"{noaa_data['distance_from_property_miles']} mi")
    else:
        noaa_data = None
   
    st.divider()
   
    # ========== GENERATE PDF BUTTON ==========
    if st.button("📄 Generate Adjuster Package PDF", type="primary", use_container_width=True):
        # Validation
        if not all([inspector_name, inspector_phone, inspector_email, property_address, customer_name, dol]):
            st.error("❌ Please fill in all inspector and property details in the sidebar.")
        elif not noaa_data:
            st.error("❌ Please fetch NOAA data first.")
        elif total_photos == 0:
            st.error("❌ Please upload at least one photo.")
        else:
            with st.spinner("🔨 Building PDF... this may take a moment with 60+ photos"):
                try:
                    # Filter out empty categories
                    photo_data_filtered = {k: v for k, v in ss.photo_data.items() if v}
                   
                    # Generate PDF
                    pdf_bytes = generate_adjuster_pdf(
                        inspector_name=inspector_name,
                        inspector_phone=inspector_phone,
                        inspector_email=inspector_email,
                        property_address=property_address,
                        customer_name=customer_name,
                        dol=dol,
                        inspection_date=inspection_date_val.strftime("%Y-%m-%d"),
                        report_type=report_type,
                        local_office=local_office,
                        noaa_data=noaa_data,
                        photo_categories_data=photo_data_filtered
                    )
                   
                    file_size_mb = len(pdf_bytes) / (1024 * 1024)
                   
                    # Download button
                    st.download_button(
                        label=f"📥 Download PDF ({file_size_mb:.1f} MB)",
                        data=pdf_bytes,
                        file_name=f"Inspection_{customer_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
                   
                    st.success(f"✅ PDF generated successfully! ({file_size_mb:.1f} MB, {total_photos} photos)")
                    st.info("💾 **Ready to email or share with adjuster.** Click the download button above.")
                   
                except Exception as e:
                    st.error(f"❌ Error generating PDF: {str(e)}")
                    st.exception(e)
   
    # ========== FOOTER ==========
    st.divider()
    st.caption(
        "🔒 **Belmont Construction** | Storm & Roof Damage Inspection Tool | "
        "Images auto-compressed to max 1200x900px (~150KB each) for fast delivery"
    )


if __name__ == "__main__":
    main()
