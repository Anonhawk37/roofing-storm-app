"""
Storm & Roof Damage Inspection App - STREAMLINED
Mobile-friendly field rep tool for Belmont Construction
Wind data automated | Hail data manual entry (from Hailstrike Go)
Generates professional adjuster-grade PDF reports
"""

import os
import base64
import re
import urllib.parse
import streamlit as st
from streamlit import session_state as ss
from PIL import Image, ImageOps
import io
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional
import requests

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
    Image as RLImage, KeepTogether
)
from reportlab.lib.enums import TA_CENTER

# ============================================================================
# CONFIGURATION
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

CARRIER_HOTLINES = [
    ("State Farm", "18007325246"),
    ("Progressive", "18007764737"),
    ("Allstate", "18002557828"),
    ("Liberty Mutual", "18002252467"),
    ("Travelers", "18002254633"),
    ("USAA", "18005318722"),
    ("Chubb", "18002524670"),
    ("Nationwide", "18004213535"),
    ("Farmers", "18004357764"),
    ("American Family", "18006926326"),
    ("Hartford", "18002435860"),
    ("Auto Owners", "18882524626"),
    ("Cincinnati", "18772422544"),
    ("Country Financial", "18662686879"),
    ("Shelter", "18007435837"),
    ("PURE", "18888137873"),
    ("Farm Bureau", "18002266383"),
    ("American Modern", "18003752075")
]

GEOCODE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9'
}

# ReportLab Styles
STYLES = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle('CustomTitle', parent=STYLES['Heading1'], fontSize=16, textColor=colors.HexColor('#1f4788'), spaceAfter=12, fontName='Helvetica-Bold')
HEADING_STYLE = ParagraphStyle('CustomHeading', parent=STYLES['Heading2'], fontSize=12, textColor=colors.HexColor('#2c5aa0'), spaceAfter=8, fontName='Helvetica-Bold')
NORMAL_STYLE = ParagraphStyle('CustomNormal', parent=STYLES['Normal'], fontSize=9, spaceAfter=6)
FOOTNOTE_STYLE = ParagraphStyle('CustomFootnote', parent=STYLES['Italic'], fontSize=8, textColor=colors.HexColor('#4A5568'), spaceAfter=4)
APPENDIX_TITLE_STYLE = ParagraphStyle('AppendixTitle', parent=STYLES['Heading1'], fontSize=18, textColor=colors.HexColor('#1f4788'), spaceAfter=6, fontName='Helvetica-Bold')
APPENDIX_CAPTION_STYLE = ParagraphStyle('AppendixCaption', parent=STYLES['Normal'], fontSize=9, textColor=colors.HexColor('#2d3748'), spaceBefore=4, spaceAfter=6)

# ============================================================================
# UTILITIES
# ============================================================================

def get_image_base64(image_path: str) -> str:
    """Convert image to base64 Data URI"""
    if not os.path.exists(image_path):
        return ""
    with open(image_path, "rb") as img_file:
        encoded = base64.b64encode(img_file.read()).decode("utf-8")
    ext = os.path.splitext(image_path)[1].replace(".", "").lower()
    mime_type = "jpeg" if ext in ["jpg", "jpeg"] else ext
    return f"data:image/{mime_type};base64,{encoded}"

def geocode_address_resilient(address_str: str) -> Tuple[Optional[float], Optional[float], str]:
    """Multi-engine geocoder: ArcGIS → Census → OpenStreetMap"""
    if not address_str or len(address_str.strip()) < 3:
        return None, None, "Please enter a valid address or zip code."
    
    clean_addr = re.sub(r'\b(Apt|Ste|Suite|Unit|Building|Bldg|#)\s*[\w-]+', '', address_str, flags=re.IGNORECASE).strip()

    # 1. ArcGIS
    try:
        res = requests.get(
            "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates",
            params={'f': 'json', 'singleLine': clean_addr, 'maxLocations': 1, 'outFields': 'Match_addr'},
            headers=GEOCODE_HEADERS, timeout=5.0
        )
        if res.status_code == 200:
            candidates = res.json().get('candidates', [])
            if candidates:
                loc = candidates[0].get('location', {})
                return float(loc.get('y')), float(loc.get('x')), candidates[0].get('address', address_str)
    except:
        pass

    # 2. Census Bureau
    try:
        res = requests.get(
            "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
            params={'address': clean_addr, 'benchmark': 'Public_AR_Current', 'format': 'json'},
            headers=GEOCODE_HEADERS, timeout=5.0
        )
        if res.status_code == 200:
            matches = res.json().get('result', {}).get('addressMatches', [])
            if matches:
                coords = matches[0].get('coordinates', {})
                return float(coords.get('y')), float(coords.get('x')), matches[0].get('matchedAddress', address_str)
    except:
        pass

    # 3. OpenStreetMap
    try:
        res = requests.get(
            f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(clean_addr)}&format=json&countrycodes=us&limit=1",
            headers=GEOCODE_HEADERS, timeout=5.0
        )
        if res.status_code == 200 and res.json():
            data = res.json()[0]
            return float(data['lat']), float(data['lon']), data.get('display_name', address_str)
    except:
        pass

    return None, None, f"Could not locate '{address_str}'."

def compress_image(uploaded_file, max_width: int = 1200, max_height: int = 900, quality: int = 75) -> Tuple[bytes, int]:
    """Compress and convert image to JPEG"""
    try:
        img = Image.open(uploaded_file)
        img = ImageOps.exif_transpose(img)
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb_img
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        return output.getvalue(), len(output.getvalue()) / 1024
    except Exception as e:
        st.error(f"Image error: {e}")
        return None, 0

def get_aspect_rl_image(img_input, max_w_inches: float, max_h_inches: float) -> RLImage:
    """Resize image to fit PDF while maintaining aspect ratio"""
    if isinstance(img_input, bytes):
        pil_img = Image.open(io.BytesIO(img_input))
        img_source = io.BytesIO(img_input)
    else:
        pil_img = Image.open(img_input)
        img_source = img_input
    
    w, h = pil_img.size
    aspect = h / float(w)
    max_w, max_h = max_w_inches * inch, max_h_inches * inch
    
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
    """Process and compress uploaded photos"""
    processed_photos = []
    if uploaded_files:
        for file in uploaded_files:
            compressed_bytes, size_kb = compress_image(file)
            if compressed_bytes:
                processed_photos.append({
                    "filename": file.name,
                    "compressed_bytes": compressed_bytes,
                    "file_size_kb": size_kb
                })
    return processed_photos

# ============================================================================
# WEATHER ENGINE: WIND DATA ONLY
# ============================================================================

def fetch_wind_data(lat: float, lon: float, dol: str) -> Dict:
    """Fetch wind data from NWS + Visual Crossing"""
    max_wind_mph = 0.0
    sources = []

    # Try NWS
    try:
        res = requests.get(f"https://api.weather.gov/points/{lat},{lon}", headers=GEOCODE_HEADERS, timeout=5.0)
        if res.status_code == 200:
            grid_data = res.json()
            alerts_url = grid_data.get('properties', {}).get('alerts')
            if alerts_url:
                alerts_res = requests.get(alerts_url, headers=GEOCODE_HEADERS, timeout=5.0)
                if alerts_res.status_code == 200:
                    for alert in alerts_res.json().get('features', []):
                        desc = str(alert.get('properties', {}).get('description', '')).lower()
                        # Extract wind speed if mentioned
                        match = re.search(r'(\d+)\s+mph', desc)
                        if match:
                            wind_speed = int(match.group(1))
                            if wind_speed > max_wind_mph:
                                max_wind_mph = wind_speed
            if max_wind_mph > 0:
                sources.append("✓ NWS Alerts")
    except:
        pass

    # Try Visual Crossing as fallback
    api_key = st.secrets.get("VISUAL_CROSSING_KEY", "")
    if api_key and max_wind_mph == 0:
        try:
            res = requests.get(
                f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{lat},{lon}/{dol}/{dol}",
                params={'unitGroup': 'us', 'key': api_key, 'include': 'days'},
                headers=GEOCODE_HEADERS, timeout=10.0
            )
            if res.status_code == 200:
                days = res.json().get('days', [])
                if days:
                    day = days[0]
                    wind = float(day.get('windgust') or day.get('windspeed') or 0)
                    if wind > 0:
                        max_wind_mph = wind
                        sources.append("✓ Visual Crossing")
        except:
            pass

    wind_display = f"{max_wind_mph:.0f} mph" if max_wind_mph > 0 else "No data"
    
    return {
        "wind_mph": max_wind_mph,
        "wind_display": wind_display,
        "sources": sources if sources else ["No wind data found"]
    }

def generate_narrative(property_address: str, dol: str, inspection_finding: str, hail_size: float, wind_mph: float) -> str:
    """Generate inspection narrative"""
    if "Severe" in inspection_finding:
        obs = "On-site physical roof inspection confirmed direct storm damage, including wind-creased/lifted shingles, displaced tab integrity, and/or mechanical impact marks to soft metals and elevated components."
    elif "Moderate" in inspection_finding:
        obs = "On-site physical evaluation revealed localized collateral damage, gutter/fascia impacts, and minor shingle compromise consistent with severe weather exposure."
    elif "Normal" in inspection_finding:
        obs = "On-site physical inspection noted general age-related weathering and normal wear. No functional storm-created openings or direct loss was observed."
    else:
        obs = "Pre-inspection meteorological analysis conducted to establish site exposure prior to physical on-site verification."
    
    hail_text = f"{hail_size:.2f}\" hail" if hail_size > 0 else "no recorded hail"
    wind_text = f"{wind_mph:.0f} mph winds" if wind_mph > 0 else "no recorded wind"
    
    return f"<b>Field Observation:</b> {obs}<br/><br/><b>Meteorological Context:</b> Property at <b>{property_address}</b> on <b>{dol}</b> experienced {wind_text} and {hail_text}."

# ============================================================================
# PDF GENERATION
# ============================================================================

def generate_adjuster_pdf(
    inspector_name: str, inspector_phone: str, inspector_email: str,
    property_address: str, customer_name: str, dol: str, inspection_date: str,
    report_type: str, local_office: str, inspection_finding: str,
    hail_size: float, wind_mph: float, wind_sources: list,
    photo_categories_data: Dict[str, List[Dict]],
    logo_path: str = "BELMONT_LOGO.png"
) -> bytes:
    
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=0.5*inch, leftMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch)
    story = []
    
    # Flatten photos
    all_photos = []
    for cat_name, p_list in photo_categories_data.items():
        for idx, p in enumerate(p_list, 1):
            all_photos.append({
                "ref_id": f"{cat_name[0]}-{idx}",
                "category": cat_name,
                "filename": p["filename"],
                "bytes": p["compressed_bytes"]
            })

    # HEADER
    logo_file = os.path.abspath(logo_path)
    if os.path.exists(logo_file):
        header_img = get_aspect_rl_image(logo_file, 2.2, 0.75)
    else:
        header_img = None

    left_data = [
        [header_img] if header_img else [],
        [Paragraph(f"<b>{COMPANY_NAME}</b>", NORMAL_STYLE)],
        [Paragraph(f"HQ: {COMPANY_HQ} | {local_office}", NORMAL_STYLE)],
    ]
    
    right_data = [
        [Paragraph("<b>PREPARED BY:</b>", NORMAL_STYLE)],
        [Paragraph(inspector_name, NORMAL_STYLE)],
        [Paragraph(f"Phone: {inspector_phone}", NORMAL_STYLE)],
        [Paragraph(f"Email: {inspector_email}", NORMAL_STYLE)],
    ]
    
    header_table = Table([[Table(left_data, colWidths=[3.25*inch]), Table(right_data, colWidths=[3.25*inch])]], colWidths=[3.5*inch, 3.5*inch])
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
    
    # METADATA
    story.append(Paragraph("PROPERTY INSPECTION DETAILS", TITLE_STYLE))
    metadata_table = Table([
        [Paragraph("<b>Property Address:</b>", NORMAL_STYLE), Paragraph(property_address, NORMAL_STYLE)],
        [Paragraph("<b>Customer Name:</b>", NORMAL_STYLE), Paragraph(customer_name, NORMAL_STYLE)],
        [Paragraph("<b>Date of Loss:</b>", NORMAL_STYLE), Paragraph(dol, NORMAL_STYLE)],
        [Paragraph("<b>Inspection Date:</b>", NORMAL_STYLE), Paragraph(inspection_date, NORMAL_STYLE)],
        [Paragraph("<b>Physical Finding:</b>", NORMAL_STYLE), Paragraph(inspection_finding, NORMAL_STYLE)],
        [Paragraph("<b>Report Type:</b>", NORMAL_STYLE), Paragraph(report_type, NORMAL_STYLE)],
    ], colWidths=[2*inch, 4.5*inch])
    metadata_table.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, colors.HexColor('#f0f0f0')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(metadata_table)
    story.append(Spacer(1, 0.2*inch))
    
    # WEATHER DATA
    story.append(Paragraph("METEOROLOGICAL DATA", TITLE_STYLE))
    weather_table = Table([
        ["Metric", "Value"],
        ["Hail Size", f"{hail_size:.2f}\"" if hail_size > 0 else "Field Observed"],
        ["Peak Wind Gust", wind_mph if isinstance(wind_mph, str) else f"{wind_mph:.0f} mph"],
        ["Data Source", " | ".join(wind_sources)],
    ], colWidths=[2.5*inch, 4*inch])
    weather_table.setStyle(TableStyle([
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
    story.append(weather_table)
    story.append(Spacer(1, 0.15*inch))
    
    # NARRATIVE
    story.append(Paragraph("ASSESSMENT", TITLE_STYLE))
    narrative = generate_narrative(property_address, dol, inspection_finding, hail_size, wind_mph if isinstance(wind_mph, (int, float)) else 0)
    story.append(Paragraph(narrative, NORMAL_STYLE))
    story.append(PageBreak())
    
    # PHOTO GRIDS
    for category_name, photo_list in photo_categories_data.items():
        if not photo_list:
            continue
        story.append(Paragraph(f"{category_name.upper()}", TITLE_STYLE))
        story.append(Spacer(1, 0.15*inch))
        
        for i in range(0, len(photo_list), 2):
            row_data = []
            for photo in photo_list[i:i+2]:
                try:
                    img = get_aspect_rl_image(photo['compressed_bytes'], 3.25, 2.35)
                    cell = Table([[img]], colWidths=[3.25*inch])
                    cell.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F8FAFC")), ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
                    row_data.append(cell)
                except:
                    row_data.append(Paragraph("Image Error", NORMAL_STYLE))
            
            while len(row_data) < 2:
                row_data.append(Paragraph("", NORMAL_STYLE))
            
            grid = Table([row_data], colWidths=[3.4*inch, 3.4*inch])
            grid.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4), ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
            story.append(grid)
            story.append(Spacer(1, 0.15*inch))
        
        if category_name != list(photo_categories_data.keys())[-1]:
            story.append(PageBreak())
    
    # APPENDIX
    if all_photos:
        story.append(PageBreak())
        story.append(Paragraph("APPENDIX: High-Resolution Photos", APPENDIX_TITLE_STYLE))
        story.append(Spacer(1, 0.15*inch))
        
        for photo in all_photos:
            story.append(Paragraph(f"<b>{photo['ref_id']}</b> — {photo['category']}", HEADING_STYLE))
            story.append(Spacer(1, 6))
            img = get_aspect_rl_image(photo['bytes'], 7.0, 5.0)
            story.append(img)
            story.append(Spacer(1, 4))
            story.append(Paragraph(f"<i>{photo['filename']}</i>", FOOTNOTE_STYLE))
            story.append(Spacer(1, 0.2*inch))
    
    doc.build(story)
    return pdf_buffer.getvalue()

# ============================================================================
# STREAMLIT UI
# ============================================================================

def apply_branding():
    st.markdown("""
        <style>
        .main .block-container { padding-top: 1.5rem; max-width: 1100px; }
        [data-testid="stSidebar"] { background-color: #1E293B !important; }
        [data-testid="stSidebar"] h3, [data-testid="stSidebar"] label, [data-testid="stSidebar"] .stMarkdown p {
            color: #D4AF37 !important; font-weight: 600 !important;
        }
        .section-header {
            background-color: #1E293B; color: #FFFFFF !important; border-left: 5px solid #D4AF37;
            padding: 10px 16px; border-radius: 4px; margin-top: 24px; margin-bottom: 16px;
            font-size: 18px; font-weight: 700 !important;
        }
        .gps-box {
            background-color: #1E293B; border: 1px solid #D4AF37; border-radius: 8px; padding: 16px;
            color: #FFFFFF;
        }
        .gps-box h4 { color: #D4AF37; margin-top: 0; margin-bottom: 8px; }
        .gps-box p { margin: 4px 0; font-size: 0.9rem; color: #E2E8F0; }
        .maps-btn { display: inline-block; margin-top: 8px; padding: 6px 14px; background-color: #D4AF37;
            color: #1E293B !important; font-weight: 700; border-radius: 4px; text-decoration: none; font-size: 0.85rem;
        }
        [data-testid="stMetricValue"] { color: #D4AF37 !important; font-weight: 700; }
        </style>
    """, unsafe_allow_html=True)

def main():
    st.set_page_config(page_title="Belmont Construction - Inspection Suite", page_icon="🏢", layout="wide", initial_sidebar_state="expanded")
    apply_branding()

    # HEADER
    st.markdown("""
        <div style="background-color: #FAF8F5; border-left: 6px solid #D4AF37; padding: 18px 24px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">
            <div style="color: #1E293B; font-size: 26px; font-weight: 700; margin: 0;">Field Inspection & Adjuster Claims Portal</div>
            <div style="color: #D4AF37; font-size: 15px; font-weight: 600; margin-top: 4px;">Belmont Construction | Wind-Tracked Hail-Reported</div>
        </div>
    """, unsafe_allow_html=True)

    if 'photo_data' not in ss:
        ss.photo_data = {cat: [] for cat in PHOTO_CATEGORIES.keys()}
    if 'geocoded_data' not in ss:
        ss.geocoded_data = None
    if 'raw_address_input' not in ss:
        ss.raw_address_input = ""

    # SIDEBAR
    with st.sidebar:
        st.markdown("### 📋 Inspection Metadata")
        inspector_name = st.text_input("Inspector Name", value="Matt Caesar")
        inspector_phone = st.text_input("Inspector Phone", placeholder="(314) 555-0199")
        inspector_email = st.text_input("Inspector Email", placeholder="matt@belmontconstruction.com")
        
        st.divider()
        st.markdown("### 📍 Property Details")
        property_address = st.text_input("Property Address or Zip Code", value=ss.raw_address_input, placeholder="e.g. 123 Main St, IL or 62221")
        ss.raw_address_input = property_address

        if st.button("📍 Lock GPS & Verify", type="primary", use_container_width=True):
            if property_address and len(property_address.strip()) >= 3:
                with st.spinner("Geocoding..."):
                    lat, lon, matched = geocode_address_resilient(property_address)
                    if lat and lon:
                        ss.geocoded_data = {"lat": lat, "lon": lon, "matched": matched}
                        st.success("✅ Coordinates Locked!")
                    else:
                        st.error("❌ Address not found")
            else:
                st.warning("Enter a valid address or zip code")

        customer_name = st.text_input("Customer Name", placeholder="e.g. Smith Residence")
        dol_val = st.date_input("Date of Loss (DOL)", value=date.today())
        dol = dol_val.strftime("%Y-%m-%d")
        
        col1, col2 = st.columns([2, 1])
        with col1:
            inspection_date_val = st.date_input("Inspection Date", value=date.today())
        with col2:
            st.write("")
            st.write("")
            if st.button("Today"):
                inspection_date_val = date.today()

        report_type = st.radio("Report Type", options=["Post-Inspection Claims Report", "Pre-Inspection Assessment"], index=0)
        local_office = st.text_input("Local Office", value="St. Louis, MO")

    # MAIN TABS
    tab_report, tab_claims = st.tabs(["📋 Inspection Report", "📞 Claims Hotlines"])

    with tab_report:
        st.markdown('<div class="section-header">📷 Photo Documentation</div>', unsafe_allow_html=True)
        total_photos = 0
        
        for category_name, cat_info in PHOTO_CATEGORIES.items():
            with st.expander(f"📁 {category_name}"):
                files = st.file_uploader(f"Upload photos", type=["jpg", "jpeg", "png"], accept_multiple_files=True, key=f"uploader_{category_name}")
                if files:
                    processed = process_uploaded_photos(files)
                    ss.photo_data[category_name] = processed
                    total_photos += len(processed)
                    st.success(f"✅ {len(processed)} photos")
                    cols = st.columns(min(4, len(processed)))
                    for idx, photo in enumerate(processed[:4]):
                        with cols[idx]:
                            st.image(photo['compressed_bytes'], width=100)

        st.markdown('<div class="section-header">🔍 Field Observation</div>', unsafe_allow_html=True)
        inspection_finding = st.segmented_control("Select Finding:", options=["🔴 Severe Damage", "🟡 Moderate Damage", "🟢 Normal Wear", "🔍 Pre-Inspection Only"], default="🔴 Severe Damage")

        st.markdown('<div class="section-header">⛈️ Storm Data</div>', unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            fetch_wind = st.checkbox("Fetch Wind Data", value=True)
        with col2:
            st.caption(f"**{total_photos} Photos**")
        with col3:
            pass

        # HAIL ENTRY (Primary)
        st.markdown("### 🌧️ Hail Size (from Hailstrike Go)")
        hail_size = st.number_input("Enter hail size observed (inches):", min_value=0.0, max_value=4.0, step=0.1, value=0.0, help="Open Hailstrike Go, filter to DOL, find max hail size, enter here")
        if hail_size > 0:
            st.info(f"✓ Hail size: {hail_size}\"")

        # WIND DATA (Automated)
        wind_data = None
        if fetch_wind:
            if ss.geocoded_data and ss.geocoded_data.get('lat'):
                with st.spinner("Fetching wind data..."):
                    wind_data = fetch_wind_data(ss.geocoded_data['lat'], ss.geocoded_data['lon'], dol)
                
                st.markdown(f"""
                    <div class="gps-box">
                        <h4>📍 Location Locked</h4>
                        <p><b>Address:</b> {ss.geocoded_data['matched']}</p>
                        <p><b>Coordinates:</b> {ss.geocoded_data['lat']:.4f}, {ss.geocoded_data['lon']:.4f}</p>
                        <a href="https://www.google.com/maps?q={ss.geocoded_data['lat']},{ss.geocoded_data['lon']}" target="_blank" class="maps-btn">View on Maps</a>
                    </div>
                """, unsafe_allow_html=True)
                
                if wind_data['wind_mph'] > 0:
                    st.success(f"✅ Wind: {wind_data['wind_display']}")
                else:
                    st.info("Wind: No automated data found")
            else:
                st.warning("⚠️ Lock GPS coordinates to fetch wind data")
                wind_data = None

        st.divider()

        if st.button("📄 Build PDF Report", type="primary", use_container_width=True):
            if not all([inspector_name, inspector_phone, inspector_email, property_address, customer_name]):
                st.error("❌ Complete all required fields in sidebar")
            elif total_photos == 0:
                st.error("❌ Upload at least one photo")
            elif hail_size == 0:
                st.warning("⚠️ No hail size entered. Wind-only report will be generated.")
            
            if inspector_name and property_address and customer_name and total_photos > 0:
                with st.spinner("Generating PDF..."):
                    try:
                        filtered_photos = {k: v for k, v in ss.photo_data.items() if v}
                        wind_sources = wind_data['sources'] if wind_data else ["Manual Entry"]
                        wind_display = wind_data['wind_display'] if wind_data else "No data"
                        
                        pdf_bytes = generate_adjuster_pdf(
                            inspector_name, inspector_phone, inspector_email,
                            property_address, customer_name, dol,
                            inspection_date_val.strftime("%Y-%m-%d"),
                            report_type, local_office, inspection_finding,
                            hail_size, wind_data['wind_mph'] if wind_data else 0, wind_sources,
                            filtered_photos
                        )
                        
                        st.download_button(
                            label=f"📥 Download PDF ({len(pdf_bytes) / (1024*1024):.1f} MB)",
                            data=pdf_bytes,
                            file_name=f"Belmont_Inspection_{customer_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
                        st.success("✅ Report ready!")
                    except Exception as e:
                        st.error(f"❌ Error: {e}")

    with tab_claims:
        st.markdown('<div class="section-header">📞 Direct Claims Hotlines</div>', unsafe_allow_html=True)
        st.caption("Tap to call for First Notice of Loss (FNOL)")
        
        col_left, col_right = st.columns(2)
        for idx, (carrier, phone) in enumerate(CARRIER_HOTLINES):
            if idx % 2 == 0:
                with col_left:
                    st.markdown(f'<a href="tel:{phone}" style="display:block; background:#1E293B; color:#D4AF37; border:1.5px solid #D4AF37; padding:12px; border-radius:25px; text-align:center; font-weight:700; margin-bottom:12px; text-decoration:none;">{carrier}</a>', unsafe_allow_html=True)
            else:
                with col_right:
                    st.markdown(f'<a href="tel:{phone}" style="display:block; background:#1E293B; color:#D4AF37; border:1.5px solid #D4AF37; padding:12px; border-radius:25px; text-align:center; font-weight:700; margin-bottom:12px; text-decoration:none;">{carrier}</a>', unsafe_allow_html=True)

    st.divider()
    st.caption("© Belmont Construction | Field Inspection Suite")

if __name__ == "__main__":
    main()
