"""
Storm & Roof Damage Inspection App - STREAMLINED
Mobile-friendly field rep tool for Belmont Construction
Wind data automated | Hail data manual entry (from Hailstrike Go)
Generates professional adjuster-grade PDF reports + customer quotes
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
    Image as RLImage, KeepTogether, Flowable
)
from reportlab.lib.enums import TA_CENTER


class BreakToPageTwo(Flowable):
    """
    Pushes whatever follows to the top of page 2 -- but only if the
    document is still on page 1. If earlier content (e.g. a long Scope
    of Work) has already pushed the layout onto page 2 or beyond, this
    does nothing and lets content continue flowing naturally.
    """
    def __init__(self):
        Flowable.__init__(self)
        self.width = 0
        self.height = 0

    def wrap(self, availWidth, availHeight):
        try:
            current_page = self.canv.getPageNumber()
        except Exception:
            current_page = 1
        if current_page <= 1:
            # Report we need more room than is left -> forces a page break
            return (availWidth, availHeight + 1)
        return (0, 0)

    def draw(self):
        pass
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
QUOTE_JOB_TYPES = [
    "Roof Replacement", "Roof Repair", "Siding", "Gutters",
    "Deck", "Fence", "Remodel", "Other"
]
DEFAULT_QUOTE_TERMS = (
    "1. Payment Terms: A deposit is due upon signing, with the remaining balance due upon completion of work, unless otherwise agreed in writing.\n"
    "2. Pricing Validity: Material and labor costs tend to increase over time. This quote price is guaranteed for 30 days from the date above. After that, pricing is subject to change.\n"
    "3. Scope of Work: Work is limited to the items listed above. Any additional work requested will be quoted separately.\n"
    "4. Warranty: Workmanship is warranted for a period to be specified at contract signing. Manufacturer warranties apply to materials as provided by the manufacturer.\n"
    "5. Permits: Unless otherwise noted, permit acquisition (if required) is the responsibility of Belmont Construction and will be included in the final contract."
)
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
def generate_narrative(property_address: str, dol: str, inspection_finding: str, damage_type: str, hail_size: float, wind_mph: float, damage_notes: str = "") -> str:
    """Generate inspection narrative with damage description based on damage type"""

    # Severity-based observation
    if "Severe" in inspection_finding:
        severity = "Severe"
    elif "Moderate" in inspection_finding:
        severity = "Moderate"
    elif "Minor" in inspection_finding:
        severity = "Minor"
    else:
        return "Pre-inspection meteorological analysis conducted to establish site exposure prior to physical on-site verification."

    # Damage type-based observation
    if "Hail + Wind" in damage_type:
        obs = f"On-site physical roof inspection confirmed direct {severity.lower()} storm damage. Hail impact marks visible on shingles with displaced tab integrity. Wind damage evident from lifted/creased shingles and mechanical impact marks to soft metals and elevated components including vents, pipe boots, and flashing."
    elif "Hail" in damage_type and "Wind" not in damage_type:
        obs = f"On-site physical roof inspection confirmed direct {severity.lower()} hail damage. Multiple impact marks visible on shingles with compromised tab integrity. Hail strikes evident on soft metals, gutters, and roof-mounted equipment."
    elif "Wind" in damage_type and "Hail" not in damage_type:
        obs = f"On-site physical roof inspection confirmed direct {severity.lower()} wind damage. Shingles exhibiting wind-creased and lifted conditions with displaced tab integrity. Mechanical impact marks visible on soft metals, vents, pipe boots, and flashing consistent with high-velocity wind event."
    else:
        obs = "On-site physical inspection conducted to assess storm exposure."

    hail_text = f"{hail_size:.2f}\" hail" if hail_size > 0 else "hail exposure"
    wind_text = f"{wind_mph:.0f} mph winds" if wind_mph > 0 else "wind exposure"

    narrative = f"<b>Field Observation:</b> {obs}<br/><br/><b>Meteorological Context:</b> Property at <b>{property_address}</b> on <b>{dol}</b> experienced {wind_text} and {hail_text}."

    if damage_notes:
        narrative += f"<br/><br/><b>Storm Reports (Hailstrike Go):</b> {damage_notes}"

    return narrative
# ============================================================================
# PDF GENERATION: STORM REPORT
# ============================================================================
def generate_adjuster_pdf(
    inspector_name: str, inspector_phone: str, inspector_email: str,
    property_address: str, customer_name: str, customer_phone: str, dol: str, inspection_date: str,
    report_type: str, local_office: str, inspection_finding: str, damage_type: str,
    hail_size: float, wind_mph: float, wind_sources: list,
    photo_categories_data: Dict[str, List[Dict]],
    damage_notes: str = "",
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
        [Paragraph(f"HQ: {COMPANY_HQ}", NORMAL_STYLE)],
        [Paragraph(f"Local Office: {local_office}", NORMAL_STYLE)],
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
        [Paragraph("<b>Customer Phone:</b>", NORMAL_STYLE), Paragraph(customer_phone, NORMAL_STYLE)],
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
        ["Data Source", "Radar indicated hail and wind confirmed by local storm reports"],
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
    narrative = generate_narrative(property_address, dol, inspection_finding, damage_type, hail_size, wind_mph if isinstance(wind_mph, (int, float)) else 0, damage_notes)
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
        story.append(Paragraph("APPENDIX: High-Resolution Photo Evidence", APPENDIX_TITLE_STYLE))
        story.append(Spacer(1, 0.1*inch))
        story.append(Paragraph(
            "This appendix contains high-resolution photographs from the on-site inspection. Each image is embedded in full resolution to enable detailed adjuster examination, precise damage assessment, and professional documentation of storm-related losses. These photos serve as the primary visual evidence supporting this inspection report and the estimated repair scope.",
            APPENDIX_CAPTION_STYLE
        ))
        story.append(Spacer(1, 0.15*inch))

        for idx, photo in enumerate(all_photos):
            # Group heading, image, and filename together so they don't break across pages
            photo_block = [
                Paragraph(f"<b>{photo['ref_id']}</b> — {photo['category']}", HEADING_STYLE),
                Spacer(1, 6),
                get_aspect_rl_image(photo['bytes'], 7.0, 5.0),
                Spacer(1, 4),
                Paragraph(f"<i>{photo['filename']}</i>", FOOTNOTE_STYLE),
            ]

            story.append(KeepTogether(photo_block))

            # Add spacing between photos except after the last one
            if idx < len(all_photos) - 1:
                story.append(Spacer(1, 0.25*inch))

    # CONCLUSION
    story.append(PageBreak())
    story.append(Paragraph("CONCLUSION", TITLE_STYLE))
    story.append(Spacer(1, 0.1*inch))
    conclusion_text = """Based on the physical evidence of wind and hail damage documented during this inspection, the property has sustained functional damage to the roofing system and exterior components that warrants professional repair.<br/><br/>It is strongly recommended that the homeowner contact their insurance provider to initiate a claim for these storm-related damages. Furthermore, we advise having an insurance adjuster come out to the property for a physical re-inspection, with a Belmont Construction representative present on-site during the walkthrough. Having our professional representation on-site ensures that all damaged areas—including the roof, siding, doors, fencing and etc—are fully accounted for and properly documented to help secure a complete and accurate approval for property restoration."""
    story.append(Paragraph(conclusion_text, NORMAL_STYLE))
    story.append(Spacer(1, 0.3*inch))

    # FOOTER
    story.append(Paragraph("_" * 80, FOOTNOTE_STYLE))
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph(f"Report Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", FOOTNOTE_STYLE))
    story.append(Paragraph(f"Inspector: {inspector_name} | Phone: {inspector_phone} | Email: {inspector_email}", FOOTNOTE_STYLE))
    story.append(Spacer(1, 0.05*inch))
    story.append(Paragraph("© Belmont Construction - Professional Storm Damage Inspections", FOOTNOTE_STYLE))

    doc.build(story)
    return pdf_buffer.getvalue()
# ============================================================================
# PDF GENERATION: QUOTE
# ============================================================================
def generate_quote_pdf(
    inspector_name: str, inspector_phone: str, inspector_email: str,
    customer_name: str, customer_address: str, customer_phone: str, customer_email: str,
    job_type: str, quote_date: str,
    line_items: List[Dict],
    tax_rate: float, discount: float, deposit_pct: float,
    scope_notes: str, terms_text: str,
    logo_path: str = "BELMONT_LOGO.png"
) -> bytes:
    """Generate a professional quote PDF matching the storm report's header/footer style"""

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=0.5*inch, leftMargin=0.5*inch, topMargin=0.5*inch, bottomMargin=0.5*inch)
    story = []

    # HEADER (matches storm report header)
    logo_file = os.path.abspath(logo_path)
    if os.path.exists(logo_file):
        header_img = get_aspect_rl_image(logo_file, 2.2, 0.75)
    else:
        header_img = None
    left_data = [
        [header_img] if header_img else [],
        [Paragraph(f"<b>{COMPANY_NAME}</b>", NORMAL_STYLE)],
        [Paragraph(f"HQ: {COMPANY_HQ}", NORMAL_STYLE)],
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

    # TITLE
    story.append(Paragraph("PROJECT QUOTE", TITLE_STYLE))

    # CUSTOMER / JOB METADATA
    metadata_rows = [
        [Paragraph("<b>Customer Name:</b>", NORMAL_STYLE), Paragraph(customer_name, NORMAL_STYLE)],
        [Paragraph("<b>Property Address:</b>", NORMAL_STYLE), Paragraph(customer_address, NORMAL_STYLE)],
    ]
    if customer_phone:
        metadata_rows.append([Paragraph("<b>Phone:</b>", NORMAL_STYLE), Paragraph(customer_phone, NORMAL_STYLE)])
    if customer_email:
        metadata_rows.append([Paragraph("<b>Email:</b>", NORMAL_STYLE), Paragraph(customer_email, NORMAL_STYLE)])
    metadata_rows.append([Paragraph("<b>Job Type:</b>", NORMAL_STYLE), Paragraph(job_type, NORMAL_STYLE)])
    metadata_rows.append([Paragraph("<b>Quote Date:</b>", NORMAL_STYLE), Paragraph(quote_date, NORMAL_STYLE)])

    metadata_table = Table(metadata_rows, colWidths=[2*inch, 4.5*inch])
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
    story.append(Spacer(1, 0.25*inch))

    # LINE ITEMS BY CATEGORY
    story.append(Paragraph("LINE ITEMS", TITLE_STYLE))
    categories_order = ["Materials", "Labor", "Other"]
    subtotal = 0.0
    for cat in categories_order:
        cat_items = [i for i in line_items if i.get("category", "Materials") == cat]
        if not cat_items:
            continue
        story.append(Paragraph(cat.upper(), HEADING_STYLE))
        table_data = [["Description", "Qty", "Unit Price", "Line Total"]]
        for item in cat_items:
            line_total = item["quantity"] * item["unit_price"]
            subtotal += line_total
            table_data.append([
                item["description"],
                f'{item["quantity"]:g}',
                f'${item["unit_price"]:,.2f}',
                f'${line_total:,.2f}'
            ])
        items_table = Table(table_data, colWidths=[3.5*inch, 0.8*inch, 1.1*inch, 1.1*inch])
        items_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c5aa0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#e8f0f7')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(items_table)
        story.append(Spacer(1, 0.15*inch))

    # PRICING SUMMARY
    discount_clamped = min(discount, subtotal) if subtotal > 0 else 0.0
    tax_amount = (subtotal - discount_clamped) * (tax_rate / 100)
    grand_total = subtotal - discount_clamped + tax_amount
    deposit_amount = grand_total * (deposit_pct / 100)

    summary_rows = [["Subtotal", f"${subtotal:,.2f}"]]
    if discount_clamped > 0:
        summary_rows.append(["Discount", f"-${discount_clamped:,.2f}"])
    if tax_rate > 0:
        summary_rows.append([f"Tax ({tax_rate:.1f}%)", f"${tax_amount:,.2f}"])
    total_row_idx = len(summary_rows)
    summary_rows.append(["TOTAL", f"${grand_total:,.2f}"])
    if deposit_pct > 0:
        summary_rows.append([f"Deposit Due ({deposit_pct:.0f}%)", f"${deposit_amount:,.2f}"])

    summary_table = Table(summary_rows, colWidths=[4.5*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('LINEABOVE', (0, total_row_idx), (-1, total_row_idx), 1, colors.HexColor('#2c5aa0')),
        ('FONTNAME', (0, total_row_idx), (-1, total_row_idx), 'Helvetica-Bold'),
        ('FONTSIZE', (0, total_row_idx), (-1, total_row_idx), 11),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 0.25*inch))

    # SCOPE OF WORK
    if scope_notes and scope_notes.strip():
        story.append(Paragraph("SCOPE OF WORK", TITLE_STYLE))
        story.append(Paragraph(scope_notes.replace("\n", "<br/>"), NORMAL_STYLE))
        story.append(Spacer(1, 0.2*inch))

    # TERMS & CONDITIONS -- always starts at the top of page 2, unless a
    # long Scope of Work already pushed the layout there, in which case
    # it simply continues wherever the flow landed on page 2.
    story.append(BreakToPageTwo())
    story.append(Paragraph("TERMS & CONDITIONS", TITLE_STYLE))
    story.append(Paragraph(terms_text.replace("\n", "<br/>"), NORMAL_STYLE))
    story.append(Spacer(1, 0.35*inch))

    # SIGNATURE -- label sits above the line so long labels never collide
    # with the signature/date underline.
    sig_line_style = TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
    ])

    story.append(Paragraph("<b>Customer Signature:</b>", NORMAL_STYLE))
    story.append(Spacer(1, 0.35*inch))
    cust_sig_table = Table(
        [["_______________________________", "", "Date:", "______________"]],
        colWidths=[3.2*inch, 0.4*inch, 0.5*inch, 1.7*inch]
    )
    cust_sig_table.setStyle(sig_line_style)
    story.append(cust_sig_table)
    story.append(Spacer(1, 0.3*inch))

    story.append(Paragraph(f"<b>{COMPANY_NAME} Representative:</b>", NORMAL_STYLE))
    story.append(Spacer(1, 0.35*inch))
    rep_sig_table = Table(
        [["_______________________________", "", "Date:", "______________"]],
        colWidths=[3.2*inch, 0.4*inch, 0.5*inch, 1.7*inch]
    )
    rep_sig_table.setStyle(sig_line_style)
    story.append(rep_sig_table)
    story.append(Spacer(1, 0.3*inch))

    # FOOTER
    story.append(Paragraph("_" * 80, FOOTNOTE_STYLE))
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph(f"Quote Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", FOOTNOTE_STYLE))
    story.append(Paragraph(f"Prepared By: {inspector_name} | Phone: {inspector_phone} | Email: {inspector_email}", FOOTNOTE_STYLE))
    story.append(Spacer(1, 0.05*inch))
    story.append(Paragraph(f"© {COMPANY_NAME} - Professional Contracting Services", FOOTNOTE_STYLE))

    doc.build(story)
    return pdf_buffer.getvalue()
# ============================================================================
# STREAMLIT UI
# ============================================================================
def apply_branding():
    st.markdown("""
        <style>
        .main .block-container { padding-top: 1rem; max-width: 1100px; }

        /* Logo Styles */
        img[alt="Belmont Logo"] {
            max-width: 150px !important;
            height: auto !important;
            margin: 0 auto !important;
            display: block !important;
        }

        /* Mobile adjustments */
        @media (max-width: 640px) {
            img[alt="Belmont Logo"] {
                max-width: 120px !important;
            }
            .main .block-container { padding-top: 0.5rem; }
        }

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
    st.set_page_config(page_title="Belmont Construction - Inspection Suite", page_icon="https://raw.githubusercontent.com/Anonhawk37/roofing-storm-app/main/BELMONT_LOGO.png", layout="wide", initial_sidebar_state="expanded")
    apply_branding()
    # LOGO & HEADER
    logo_path = os.path.abspath("BELMONT_LOGO.png")
    logo_base64 = get_image_base64(logo_path)

    if logo_base64:
        st.markdown(f"""
            <div style="text-align: center; margin-bottom: 20px;">
                <img src="{logo_base64}" alt="Belmont Logo" style="max-width: 150px; height: auto; display: block; margin: 0 auto;">
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("<h2 style='text-align: center; margin-top: 0;'>🏢 BELMONT</h2>", unsafe_allow_html=True)

    st.markdown("""
        <div style="background-color: #FAF8F5; border-left: 6px solid #D4AF37; padding: 18px 24px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">
            <div style="color: #1E293B; font-size: 26px; font-weight: 700; margin: 0;">Field Inspection & Adjuster Claims Portal</div>
            <div style="color: #D4AF37; font-size: 15px; font-weight: 600; margin-top: 4px;">Belmont Construction | Hailstrike Go-Reported | Rep-Estimated Wind</div>
        </div>
    """, unsafe_allow_html=True)
    if 'photo_data' not in ss:
        ss.photo_data = {cat: [] for cat in PHOTO_CATEGORIES.keys()}
    if 'geocoded_data' not in ss:
        ss.geocoded_data = None
    if 'raw_address_input' not in ss:
        ss.raw_address_input = ""
    if 'quote_items' not in ss:
        ss.quote_items = [{"category": "Materials", "description": "", "quantity": 1.0, "unit_price": 0.0}]
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
        customer_phone = st.text_input("Customer Phone Number", placeholder="(555) 123-4567", help="Phone number to include on inspection report")
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
    tab_report, tab_quote, tab_claims = st.tabs(["📋 Inspection Report", "🧾 Quote", "📞 Claims Hotlines"])
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

        damage_type = st.segmented_control(
            "Storm Damage Type:",
            options=["🧊 Hail Damage", "💨 Wind Damage", "🧊💨 Hail + Wind Damage"],
            default="🧊💨 Hail + Wind Damage",
            help="Select based on what you observed on the roof"
        )

        inspection_finding = st.segmented_control(
            "Severity Level:",
            options=["🔴 Severe", "🟡 Moderate", "🟢 Minor", "🔍 Pre-Inspection Only"],
            default="🔴 Severe"
        )
        st.markdown('<div class="section-header">⛈️ Storm Data (from Hailstrike Go)</div>', unsafe_allow_html=True)

        st.caption(f"📸 **{total_photos} Photos Attached**")

        # LOCATION INFO
        if ss.geocoded_data and ss.geocoded_data.get('lat'):
            st.markdown(f"""
                <div class="gps-box">
                    <h4>📍 Location</h4>
                    <p><b>Address:</b> {ss.geocoded_data['matched']}</p>
                    <p><b>Coordinates:</b> {ss.geocoded_data['lat']:.4f}, {ss.geocoded_data['lon']:.4f}</p>
                    <a href="https://www.google.com/maps?q={ss.geocoded_data['lat']},{ss.geocoded_data['lon']}" target="_blank" class="maps-btn">View on Maps</a>
                </div>
            """, unsafe_allow_html=True)
        else:
            st.warning("⚠️ Lock GPS coordinates in sidebar first")
        # HAIL & WIND MANUAL ENTRY
        st.markdown("### 🌧️ Storm Measurements")

        col_hail, col_wind = st.columns(2)

        with col_hail:
            st.markdown("**Hail Size**")
            hail_size = st.number_input(
                "Hail (inches)", min_value=0.0, max_value=4.0, step=0.1, value=0.0,
                key="hail_input", help="Open Hailstrike Go → filter to DOL → find max hail"
            )
            if hail_size > 0:
                st.success(f"✓ {hail_size}\"")

        with col_wind:
            st.markdown("**Wind Speed**")
            wind_speed = st.number_input(
                "Wind (mph)", min_value=0.0, max_value=150.0, step=5.0, value=0.0,
                key="wind_input", help="Use damage description below + reference guide"
            )
            if wind_speed > 0:
                st.success(f"✓ {wind_speed:.0f} mph")

        # Damage Description
        st.markdown("### 📋 Damage Description (from Hailstrike Go LSRs)")
        damage_notes = st.text_area(
            "Describe storm damage seen in Hailstrike Go reports:",
            placeholder="e.g., 'Multiple large tree limbs (4-5\" diameter) snapped. 3 injuries reported. Structural damage to homes.'",
            height=80,
            help="Copy/summarize the damage descriptions from Hailstrike Go LSRs. This goes in the PDF to show your reasoning."
        )

        # Wind damage reference guide
        with st.expander("📖 Wind Speed Damage Reference"):
            st.markdown("""
            **Use Hailstrike Go LSR damage descriptions to estimate wind speed:**

            - **30-40 mph** — Light branches down, minor roof damage
            - **40-50 mph** — Small tree limbs snapped, shingles lifted
            - **50-60 mph** — Large tree limbs (4-5") down, structural damage, fences damaged
            - **60-75 mph** — Trees snapped/uprooted, severe home damage, injuries possible
            - **75+ mph** — Widespread destruction, major structural failure

            **Examples:**
            - LSR: "tree limb down" → Estimate: **55 mph**
            - LSR: "trees uprooted" → Estimate: **70 mph**
            - LSR: "structural damage, injuries" → Estimate: **65+ mph**
            """)
        st.divider()
        if st.button("📄 Build PDF Report", type="primary", use_container_width=True):
            if not all([inspector_name, inspector_phone, inspector_email, property_address, customer_name, customer_phone]):
                st.error("❌ Complete all required fields in sidebar (including customer phone)")
            elif total_photos == 0:
                st.error("❌ Upload at least one photo")
            elif hail_size == 0 and wind_speed == 0:
                st.error("❌ Enter hail size or wind speed")
            elif wind_speed > 0 and not damage_notes.strip():
                st.warning("⚠️ Wind speed entered but no damage description. Add damage notes from Hailstrike Go.")

            if inspector_name and property_address and customer_name and total_photos > 0 and (hail_size > 0 or wind_speed > 0):
                # Only allow PDF if wind has damage notes
                if wind_speed > 0 and not damage_notes.strip():
                    st.error("❌ Please add damage description to support wind speed estimate")
                else:
                    with st.spinner("Generating PDF..."):
                        try:
                            filtered_photos = {k: v for k, v in ss.photo_data.items() if v}
                            wind_sources = [f"Manual Entry (Hailstrike Go: {damage_notes[:50]}...)" if damage_notes else "Manual Entry"]

                            pdf_bytes = generate_adjuster_pdf(
                                inspector_name, inspector_phone, inspector_email,
                                property_address, customer_name, customer_phone, dol,
                                inspection_date_val.strftime("%Y-%m-%d"),
                                report_type, local_office, inspection_finding, damage_type,
                                hail_size, wind_speed, wind_sources,
                                filtered_photos, damage_notes
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
    with tab_quote:
        st.markdown('<div class="section-header">🧾 Customer & Job Information</div>', unsafe_allow_html=True)
        col_q1, col_q2 = st.columns(2)
        with col_q1:
            quote_customer_name = st.text_input("Customer Name", key="quote_customer_name", placeholder="e.g. John Smith")
            quote_customer_address = st.text_input("Customer Address", key="quote_customer_address", placeholder="123 Main St, City, MO")
        with col_q2:
            quote_customer_phone = st.text_input("Customer Phone", key="quote_customer_phone", placeholder="(555) 123-4567")
            quote_customer_email = st.text_input("Customer Email", key="quote_customer_email", placeholder="customer@email.com")

        col_q3, col_q4 = st.columns(2)
        with col_q3:
            quote_job_type = st.selectbox("Job Type", QUOTE_JOB_TYPES, key="quote_job_type")
        with col_q4:
            quote_date_val = st.date_input("Quote Date", value=date.today(), key="quote_date")

        st.markdown('<div class="section-header">📝 Line Items</div>', unsafe_allow_html=True)
        st.caption("Add or remove as many line items as the job needs.")

        item_to_remove = None
        for idx, item in enumerate(ss.quote_items):
            row_cols = st.columns([1.4, 3, 0.9, 1.2, 1.2, 0.5])
            with row_cols[0]:
                item["category"] = st.selectbox(
                    "Category", ["Materials", "Labor", "Other"],
                    index=["Materials", "Labor", "Other"].index(item.get("category", "Materials")),
                    key=f"quote_cat_{idx}"
                )
            with row_cols[1]:
                item["description"] = st.text_input(
                    "Description", value=item.get("description", ""),
                    key=f"quote_desc_{idx}", placeholder="e.g. Architectural shingles - 30yr"
                )
            with row_cols[2]:
                item["quantity"] = st.number_input(
                    "Qty", min_value=0.0, value=float(item.get("quantity", 1.0)),
                    step=1.0, key=f"quote_qty_{idx}"
                )
            with row_cols[3]:
                item["unit_price"] = st.number_input(
                    "Unit Price ($)", min_value=0.0, value=float(item.get("unit_price", 0.0)),
                    step=1.0, key=f"quote_price_{idx}"
                )
            with row_cols[4]:
                line_total = item["quantity"] * item["unit_price"]
                st.markdown("&nbsp;")
                st.markdown(f"**${line_total:,.2f}**")
            with row_cols[5]:
                st.markdown("&nbsp;")
                if st.button("🗑️", key=f"quote_remove_{idx}"):
                    item_to_remove = idx

        if item_to_remove is not None:
            ss.quote_items.pop(item_to_remove)
            st.rerun()

        if st.button("➕ Add Line Item"):
            ss.quote_items.append({"category": "Materials", "description": "", "quantity": 1.0, "unit_price": 0.0})
            st.rerun()

        st.divider()

        subtotal = sum(i["quantity"] * i["unit_price"] for i in ss.quote_items)

        st.markdown('<div class="section-header">💲 Pricing Summary</div>', unsafe_allow_html=True)
        col_q5, col_q6, col_q7 = st.columns(3)
        with col_q5:
            tax_rate = st.number_input("Tax Rate (%)", min_value=0.0, max_value=20.0, value=0.0, step=0.1, key="quote_tax_rate")
        with col_q6:
            discount = st.number_input("Discount ($)", min_value=0.0, value=0.0, step=10.0, key="quote_discount")
        with col_q7:
            deposit_pct = st.number_input("Deposit Required (%)", min_value=0.0, max_value=100.0, value=50.0, step=5.0, key="quote_deposit_pct")

        discount_clamped = min(discount, subtotal) if subtotal > 0 else 0.0
        tax_amount = (subtotal - discount_clamped) * (tax_rate / 100)
        grand_total = subtotal - discount_clamped + tax_amount
        deposit_amount = grand_total * (deposit_pct / 100)

        st.markdown(f"""
        **Subtotal:** ${subtotal:,.2f}
        **Discount:** -${discount_clamped:,.2f}
        **Tax ({tax_rate:.1f}%):** ${tax_amount:,.2f}
        **Total:** ${grand_total:,.2f}
        **Deposit Due ({deposit_pct:.0f}%):** ${deposit_amount:,.2f}
        """)

        st.markdown('<div class="section-header">📋 Scope of Work</div>', unsafe_allow_html=True)
        scope_notes = st.text_area(
            "Describe the scope of work for this project:",
            height=100, key="quote_scope_notes",
            placeholder="e.g. Full tear-off and replacement of existing roof with architectural shingles, including new underlayment, flashing, and ridge vent."
        )

        st.markdown('<div class="section-header">📜 Terms & Conditions</div>', unsafe_allow_html=True)
        terms_text = st.text_area("Terms shown on the quote:", value=DEFAULT_QUOTE_TERMS, height=150, key="quote_terms_text")

        st.divider()
        if st.button("📄 Build Quote PDF", type="primary", use_container_width=True, key="build_quote_pdf"):
            valid_items = [i for i in ss.quote_items if i["description"].strip() and i["quantity"] > 0]
            if not all([inspector_name, inspector_phone, inspector_email]):
                st.error("❌ Complete your Name/Phone/Email in the sidebar")
            elif not quote_customer_name or not quote_customer_address:
                st.error("❌ Enter customer name and address")
            elif not valid_items:
                st.error("❌ Add at least one line item with a description and quantity")
            else:
                with st.spinner("Generating Quote PDF..."):
                    try:
                        pdf_bytes = generate_quote_pdf(
                            inspector_name, inspector_phone, inspector_email,
                            quote_customer_name, quote_customer_address, quote_customer_phone, quote_customer_email,
                            quote_job_type, quote_date_val.strftime("%Y-%m-%d"),
                            valid_items,
                            tax_rate, discount_clamped, deposit_pct,
                            scope_notes, terms_text
                        )
                        st.download_button(
                            label=f"📥 Download Quote PDF ({len(pdf_bytes) / 1024:.0f} KB)",
                            data=pdf_bytes,
                            file_name=f"Belmont_Quote_{quote_customer_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
                        st.success("✅ Quote ready!")
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
