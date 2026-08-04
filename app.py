"""
Storm & Roof Damage Inspection App
Mobile-friendly field rep tool for Belmont Construction
Generates professional adjuster-grade PDF reports with photo inspection grids & High-Res Appendix
"""

import os
import hashlib
import base64
import math
import re
import urllib.parse
import streamlit as st
from streamlit import session_state as ss
from PIL import Image, ImageOps
import io
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional
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

# Browser-like headers to prevent cloud IP/User-Agent blocks across all external APIs
GEOCODE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9'
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
APPENDIX_TITLE_STYLE = ParagraphStyle(
    'AppendixTitle',
    parent=STYLES['Heading1'],
    fontSize=18,
    textColor=colors.HexColor('#1f4788'),
    spaceAfter=6,
    fontName='Helvetica-Bold'
)
APPENDIX_CAPTION_STYLE = ParagraphStyle(
    'AppendixCaption',
    parent=STYLES['Normal'],
    fontSize=9,
    textColor=colors.HexColor('#2d3748'),
    spaceBefore=4,
    spaceAfter=6
)

# ============================================================================
# UTILITY: BASE64 IMAGE ENCODER FOR HTML INJECTION
# ============================================================================

def get_image_base64(image_path: str) -> str:
    """Reads a local image file and converts it into a base64 Data URI for inline HTML rendering."""
    if not os.path.exists(image_path):
        return ""
    with open(image_path, "rb") as img_file:
        encoded = base64.b64encode(img_file.read()).decode("utf-8")
    ext = os.path.splitext(image_path)[1].replace(".", "").lower()
    mime_type = "jpeg" if ext in ["jpg", "jpeg"] else ext
    return f"data:image/{mime_type};base64,{encoded}"

# ============================================================================
# UTILITY: BULLETPROOF MULTI-ENGINE GEOCODER
# ============================================================================

def geocode_address_resilient(address_str: str) -> Tuple[Optional[float], Optional[float], str]:
    """
    Multi-engine geocoder supporting standard addresses, city/state, or 5-digit zip codes.
    Tries: 1. ArcGIS World Geocoder -> 2. US Census Bureau API -> 3. OpenStreetMap Nominatim
    """
    if not address_str or len(address_str.strip()) < 3:
        return None, None, "Please enter a valid property address or zip code."

    clean_addr = re.sub(r'\b(Apt|Ste|Suite|Unit|Building|Bldg|#)\s*[\w-]+', '', address_str, flags=re.IGNORECASE).strip()

    # 1. ESRI ArcGIS World Geocoding
    try:
        arcgis_url = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"
        params = {
            'f': 'json',
            'singleLine': clean_addr,
            'maxLocations': 1,
            'outFields': 'Match_addr'
        }
        res = requests.get(arcgis_url, params=params, headers=GEOCODE_HEADERS, timeout=5.0)
        if res.status_code == 200:
            data = res.json()
            candidates = data.get('candidates', [])
            if candidates:
                loc = candidates[0].get('location', {})
                lat = float(loc.get('y'))
                lon = float(loc.get('x'))
                matched_name = candidates[0].get('address', address_str)
                return lat, lon, matched_name
    except Exception:
        pass

    # 2. US Census Bureau Geocoder
    try:
        census_url = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
        params = {
            'address': clean_addr,
            'benchmark': 'Public_AR_Current',
            'format': 'json'
        }
        res = requests.get(census_url, params=params, headers=GEOCODE_HEADERS, timeout=5.0)
        if res.status_code == 200:
            data = res.json()
            matches = data.get('result', {}).get('addressMatches', [])
            if matches:
                coords = matches[0].get('coordinates', {})
                lat = float(coords.get('y'))
                lon = float(coords.get('x'))
                matched_name = matches[0].get('matchedAddress', address_str)
                return lat, lon, matched_name
    except Exception:
        pass

    # 3. OpenStreetMap Nominatim
    try:
        nom_url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(clean_addr)}&format=json&countrycodes=us&limit=1"
        res = requests.get(nom_url, headers=GEOCODE_HEADERS, timeout=5.0)
        if res.status_code == 200 and res.json():
            data = res.json()[0]
            lat = float(data['lat'])
            lon = float(data['lon'])
            matched_name = data.get('display_name', address_str)
            return lat, lon, matched_name
    except Exception:
        pass

    return None, None, f"Could not locate '{address_str}'. Please verify details."

# ============================================================================
# UTILITY: IMAGE COMPRESSION & ASPECT RATIO MANAGEMENT
# ============================================================================

def compress_image(uploaded_file, max_width: int = 1200, max_height: int = 900, quality: int = 75) -> Tuple[bytes, int]:
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
        compressed_bytes = output.getvalue()
        file_size_kb = len(compressed_bytes) / 1024
       
        return compressed_bytes, file_size_kb
    except Exception as e:
        st.error(f"Error compressing image: {e}")
        return None, 0


def get_aspect_rl_image(img_input, max_w_inches: float, max_h_inches: float) -> RLImage:
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
    processed_photos = []
    if uploaded_files:
        for file in uploaded_files:
            compressed_bytes, size_kb = compress_image(file)
            if compressed_bytes:
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
# WEATHER DATA ENGINE: VISUAL CROSSING TIMELINE API (WITH SEVERE EVENTS)
# ============================================================================

def fetch_noaa_data(lat: float, lon: float, matched_addr: str, dol: str, max_radius_miles: float = 30.0) -> Dict:
    """
    Direct property-level weather engine using Visual Crossing Timeline API.
    Pulls historical hail and severe wind data for the specific date of loss.
    """
    max_hail_in = 0.0
    max_wind_mph = 0.0
    citation_notes = []

    # Get API Key from Streamlit Secrets
    api_key = st.secrets.get("VISUAL_CROSSING_KEY", "")

    if not api_key:
        return {
            "lat": lat,
            "lon": lon,
            "matched_address": matched_addr,
            "maps_url": f"https://www.google.com/maps?q={lat},{lon}",
            "peak_hail_size_inches": "API Key Required",
            "radar_reflectivity_dbz": "Config Needed",
            "wind_gust_speed_mph": "N/A",
            "raw_wind": 0.0,
            "raw_hail": 0.0,
            "storm_timestamp": dol,
            "data_source_citation": "Visual Crossing Weather API",
            "citation_details": "Please configure VISUAL_CROSSING_KEY in Streamlit Secrets."
        }

    try:
        # CRITICAL FIX: Use ONLY valid Timeline API parameters
        # - Removed unsupported 'maxDistance' 
        # - Changed 'include' to valid values: 'days,alerts' (NOT 'events')
        vc_url = f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{lat},{lon}/{dol}/{dol}"
        params = {
            'unitGroup': 'us',
            'key': api_key,
            'include': 'days,alerts'  # FIXED: Removed invalid 'events' value
        }
        
        res = requests.get(vc_url, params=params, headers=GEOCODE_HEADERS, timeout=10.0)
        
        if res.status_code == 200:
            data = res.json()
            days = data.get('days', [])
            
            # PRIMARY METHOD: Extract hail and wind from daily metrics
            # (NOT from event objects - Timeline API doesn't structure it that way)
            if days:
                day_data = days[0]
                
                # Read hail size from the day's hail metric (in inches)
                try:
                    hail_value = day_data.get('hail')
                    if hail_value is not None:
                        max_hail_in = float(hail_value)
                except (ValueError, TypeError):
                    max_hail_in = 0.0
                
                # Read wind gust from the day's windgust metric
                try:
                    windgust_value = day_data.get('windgust')
                    if windgust_value is not None:
                        max_wind_mph = float(windgust_value)
                    else:
                        # Fallback to windspeed if windgust not available
                        windspeed_value = day_data.get('windspeed')
                        if windspeed_value is not None:
                            max_wind_mph = float(windspeed_value)
                except (ValueError, TypeError):
                    max_wind_mph = 0.0
                
                # SECONDARY CHECK: Look for severe event alerts
                alerts = data.get('alerts', [])
                if alerts:
                    for alert in alerts:
                        alert_desc = str(alert.get('description', '')).lower()
                        if 'hail' in alert_desc:
                            citation_notes.append(f"National Weather Service Alert detected: Severe Hail Event")
                        if 'wind' in alert_desc or 'tornado' in alert_desc:
                            citation_notes.append(f"National Weather Service Alert detected: Severe Wind Event")
            
            # Build citation based on what was found
            if max_hail_in > 0:
                citation_notes.insert(0, 
                    f"Visual Crossing historical weather data verified {max_hail_in:.2f}\" hail diameter on {dol}."
                )
            else:
                citation_notes.insert(0, 
                    f"Visual Crossing weather scan for {dol}: No hail in historical archives (may require ground spotter reports)."
                )
                
            if max_wind_mph > 0:
                citation_notes.append(f"Peak surface wind gust recorded: {max_wind_mph:.0f} mph")
        
        else:
            citation_notes.append(f"Visual Crossing API error: HTTP {res.status_code}")
            # Add response text for debugging
            try:
                error_msg = res.json().get('message', '')
                if error_msg:
                    citation_notes.append(f"Error detail: {error_msg}")
            except:
                pass

    except Exception as e:
        citation_notes.append(f"Weather query error: {str(e)}")

    # Formatted display labels for PDF and Streamlit UI
    if max_hail_in > 0:
        hail_display = f'{max_hail_in:.2f}" Hail Verified'
    else:
        hail_display = "No Hail in Historical Data"
        
    wind_display = f"{max_wind_mph:.0f} mph" if max_wind_mph > 0 else "Data Unavailable"

    # Dynamic Radar Reflectivity Classification
    if max_hail_in >= 1.75:
        dbz_display = "65+ dBZ (Golf Ball+ Hail Core)"
    elif max_hail_in >= 1.0:
        dbz_display = "55-60 dBZ (Quarter+ Hail Core)"
    elif max_hail_in > 0:
        dbz_display = "50-55 dBZ (Sub-Severe Hail)"
    elif max_wind_mph >= 50:
        dbz_display = "45-50 dBZ (High Wind Cell)"
    else:
        dbz_display = "Standard/Unavailable"

    return {
        "lat": lat,
        "lon": lon,
        "matched_address": matched_addr,
        "maps_url": f"https://www.google.com/maps?q={lat},{lon}",
        "peak_hail_size_inches": hail_display,
        "radar_reflectivity_dbz": dbz_display,
        "wind_gust_speed_mph": wind_display,
        "raw_wind": max_wind_mph,
        "raw_hail": max_hail_in,
        "storm_timestamp": f"{dol} Historical Window",
        "data_source_citation": "Visual Crossing Weather API",
        "citation_details": " | ".join(citation_notes)
    }


def generate_storm_risk_summary(noaa_data: Dict, report_type: str, inspection_date: str, property_address: str, dol: str, inspection_finding: str) -> str:
    """Generates an adjuster-ready narrative combining physical field findings with meteorological context."""
    
    # Physical Observation Narrative Clause
    if "Severe" in inspection_finding:
        obs_clause = "On-site physical roof inspection confirmed direct storm damage, including wind-creased/lifted shingles, displaced tab integrity, and/or mechanical impact marks to soft metals and elevated components."
    elif "Moderate" in inspection_finding:
        obs_clause = "On-site physical evaluation revealed localized collateral damage, gutter/fascia impacts, and minor shingle compromise consistent with severe weather exposure."
    elif "Normal" in inspection_finding:
        obs_clause = "On-site physical inspection noted general age-related weathering and normal wear. No functional storm-created openings or direct loss was observed from this specific event."
    else:
        obs_clause = "Pre-inspection meteorological analysis conducted to establish site exposure prior to physical on-site verification."

    # Weather Correlation Clause
    weather_clause = (
        f"Historical meteorological archives for <b>{property_address}</b> on loss date <b>{dol}</b> "
        f"log peak recorded surface gusts of <b>{noaa_data.get('wind_gust_speed_mph', 'N/A')}</b> "
        f"and verified regional hail activity of <b>{noaa_data.get('peak_hail_size_inches', 'N/A')}</b>."
    )

    return f"<b>Field Observation:</b> {obs_clause}<br/><br/><b>Meteorological Context:</b> {weather_clause}"

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
    inspection_finding: str,
    noaa_data: Dict,
    photo_categories_data: Dict[str, List[Dict]],
    logo_path: str = "BELMONT_LOGO.png"
) -> bytes:
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
    
    all_photos_flat = []
    photo_id_counter = 1
    for cat_name, p_list in photo_categories_data.items():
        for p_dict in p_list:
            item = dict(p_dict)
            item["ref_id"] = f"A-{photo_id_counter}"
            item["category"] = cat_name
            all_photos_flat.append(item)
            photo_id_counter += 1

    # PAGE 1: HEADER & METADATA
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
   
    metadata_title = Paragraph("PROPERTY INSPECTION DETAILS", TITLE_STYLE)
    story.append(metadata_title)
   
    metadata_data = [
        [Paragraph("<b>Property Address:</b>", NORMAL_STYLE), Paragraph(property_address, NORMAL_STYLE)],
        [Paragraph("<b>Customer Name:</b>", NORMAL_STYLE), Paragraph(customer_name, NORMAL_STYLE)],
        [Paragraph("<b>Date of Loss (DOL):</b>", NORMAL_STYLE), Paragraph(dol, NORMAL_STYLE)],
        [Paragraph("<b>Inspection Date:</b>", NORMAL_STYLE), Paragraph(inspection_date, NORMAL_STYLE)],
        [Paragraph("<b>Physical Finding:</b>", NORMAL_STYLE), Paragraph(inspection_finding, NORMAL_STYLE)],
        [Paragraph("<b>Report Type:</b>", NORMAL_STYLE), Paragraph(report_type, NORMAL_STYLE)],
    ]
   
    metadata_table = Table(metadata_data, colWidths=[2*inch, 4.5*inch])
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
   
    noaa_title = Paragraph("NOAA & METEOROLOGICAL RADAR ANALYSIS", TITLE_STYLE)
    story.append(noaa_title)
   
    noaa_data_table_data = [
        ["Metric", "Value"],
        ["Verified Hail Diameter", f"{noaa_data.get('peak_hail_size_inches', 'N/A')}"],
        ["Peak Surface Wind Gust", f"{noaa_data.get('wind_gust_speed_mph', 'N/A')}"],
        ["Radar Reflectivity Classification", f"{noaa_data.get('radar_reflectivity_dbz', 'N/A')}"],
        ["Observation Window", noaa_data.get('storm_timestamp', 'N/A')],
        ["Primary Data Sources", noaa_data.get('data_source_citation', 'Visual Crossing Weather API')],
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
    story.append(Paragraph(f"*<i>Citation Footnote: {noaa_data.get('citation_details', '')}</i>", FOOTNOTE_STYLE))
    story.append(Spacer(1, 0.15*inch))
   
    risk_title = Paragraph("STORM IMPACT ASSESSMENT & FIELD SUMMARY", TITLE_STYLE)
    story.append(risk_title)
   
    risk_summary = generate_storm_risk_summary(noaa_data, report_type, inspection_date, property_address, dol, inspection_finding)
    story.append(Paragraph(risk_summary, NORMAL_STYLE))
   
    story.append(PageBreak())
   
    # PHOTO GRIDS
    for category_name, photo_list in photo_categories_data.items():
        if not photo_list:
            continue
       
        category_heading = Paragraph(f"{category_name.upper()}", TITLE_STYLE)
        story.append(category_heading)
        story.append(Spacer(1, 0.15*inch))
       
        for i in range(0, len(photo_list), 2):
            row_photos = photo_list[i:i+2]
            row_data = []
            
            for photo_dict in row_photos:
                try:
                    img_bytes = photo_dict['compressed_bytes']
                    img = get_aspect_rl_image(img_bytes, max_w_inches=3.25, max_h_inches=2.35)
                    
                    cell_stack = Table([[img]], colWidths=[3.25*inch])
                    cell_stack.setStyle(TableStyle([
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                        ('TOPPADDING', (0, 0), (-1, -1), 6),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ]))
                    row_data.append(cell_stack)
                except Exception:
                    row_data.append(Paragraph("<font size=8>Image Error</font>", NORMAL_STYLE))
           
            while len(row_data) < 2:
                row_data.append(Paragraph("", NORMAL_STYLE))
           
            grid_table = Table([row_data], colWidths=[3.4*inch, 3.4*inch])
            grid_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))
           
            story.append(grid_table)
            story.append(Spacer(1, 0.15*inch))
       
        if category_name != list(photo_categories_data.keys())[-1]:
            story.append(PageBreak())

    # APPENDIX
    if all_photos_flat:
        story.append(PageBreak())
        story.append(Paragraph("APPENDIX: High-Resolution Evidence Vault", APPENDIX_TITLE_STYLE))
        story.append(Paragraph(
            "<i>The photos below are embedded in full resolution to allow precise adjuster examination, zoom analysis, "
            "and raw JPEG extraction for insurance claim evaluation.</i>",
            APPENDIX_CAPTION_STYLE
        ))
        story.append(Spacer(1, 0.15*inch))

        for idx, item in enumerate(all_photos_flat):
            ref_id = item["ref_id"]
            cat_name = item["category"]
            filename = item["filename"]
            img_bytes = item["compressed_bytes"]

            header_paragraph = Paragraph(f"<b>Photo Reference {ref_id}</b> — <i>{cat_name}</i>", HEADING_STYLE)
            app_img = get_aspect_rl_image(img_bytes, max_w_inches=7.0, max_h_inches=5.0)

            appendix_block = [
                header_paragraph,
                Spacer(1, 4),
                app_img,
                Spacer(1, 4),
                Paragraph(f"<b>File Reference:</b> {filename} | <b>Category:</b> {cat_name}", FOOTNOTE_STYLE),
                Spacer(1, 8)
            ]

            story.append(KeepTogether(appendix_block))

            if idx < len(all_photos_flat) - 1:
                story.append(Spacer(1, 0.25*inch))

    doc.build(story)
    return pdf_buffer.getvalue()

# ============================================================================
# STREAMLIT UI WITH DARK SLATE SIDEBAR & GOLD BRANDING
# ============================================================================

def apply_belmont_branding():
    st.markdown(
        """
        <style>
        .main .block-container {
            padding-top: 1.5rem;
            max-width: 1100px;
        }

        [data-testid="stHorizontalBlock"] {
            align-items: flex-start !important;
        }
        [data-testid="stColumn"] {
            align-self: flex-start !important;
            padding-top: 0px !important;
            margin-top: 0px !important;
        }
        [data-testid="stColumn"] > div {
            padding-top: 0px !important;
            margin-top: 0px !important;
        }

        .belmont-header {
            background-color: #FAF8F5;
            border-left: 6px solid #D4AF37;
            padding: 18px 24px;
            border-radius: 8px;
            margin-bottom: 20px;
            margin-top: 0px !important;
            box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        }
        .belmont-title {
            color: #1E293B;
            font-size: 26px;
            font-weight: 700;
            margin: 0;
            line-height: 1.2;
        }
        .belmont-subtitle {
            color: #D4AF37;
            font-size: 15px;
            font-weight: 600;
            margin-top: 4px;
            margin-bottom: 0;
        }

        .logo-container {
            display: flex !important;
            justify-content: center !important;
            align-items: flex-start !important;
            width: 100%;
            margin-top: 0px !important;
            margin-bottom: 12px !important;
            padding-top: 0px !important;
            padding-bottom: 0px !important;
        }
        .logo-container img {
            width: 85px;
            height: auto;
            display: block;
            margin-top: 0px !important;
        }

        [data-testid="stSidebar"] {
            background-color: #1E293B !important;
        }
        
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] .stMarkdown p {
            color: #D4AF37 !important;
            font-weight: 600 !important;
        }

        [data-testid="stSidebar"] [data-testid="stRadioButton"] p,
        [data-testid="stSidebar"] [data-testid="stRadioButton"] label {
            color: #D4AF37 !important;
            font-size: 14px !important;
            font-weight: 500 !important;
        }
        
        [data-testid="stSidebar"] hr {
            border-color: #D4AF37 !important;
            opacity: 0.3;
        }

        [data-testid="stSidebar"] .stCaption p {
            color: #CBD5E1 !important;
        }

        .section-header {
            background-color: #1E293B;
            color: #FFFFFF !important;
            border-left: 5px solid #D4AF37;
            padding: 10px 16px;
            border-radius: 4px;
            margin-top: 24px;
            margin-bottom: 16px;
            font-size: 18px;
            font-weight: 700 !important;
            letter-spacing: 0.3px;
        }

        .gps-verification-box {
            background-color: #1E293B;
            border: 1px solid #D4AF37;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
            color: #FFFFFF;
        }
        .gps-verification-box h4 {
            color: #D4AF37;
            margin-top: 0;
            margin-bottom: 8px;
            font-size: 1.05rem;
        }
        .gps-verification-box p {
            margin: 4px 0;
            font-size: 0.9rem;
            color: #E2E8F0;
        }
        .maps-link-btn {
            display: inline-block;
            margin-top: 8px;
            padding: 6px 14px;
            background-color: #D4AF37;
            color: #1E293B !important;
            font-weight: 700;
            border-radius: 4px;
            text-decoration: none;
            font-size: 0.85rem;
        }

        .carrier-call-btn {
            display: flex;
            align-items: center;
            justify-content: center;
            background-color: #1E293B;
            color: #D4AF37 !important;
            border: 1.5px solid #D4AF37;
            border-radius: 25px;
            padding: 14px 10px;
            font-size: 1rem;
            font-weight: 700;
            text-decoration: none;
            text-align: center;
            margin-bottom: 12px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
            transition: all 0.2s ease;
        }
        .carrier-call-btn:hover {
            background-color: #D4AF37;
            color: #1E293B !important;
        }

        [data-testid="stMetricValue"] {
            color: #D4AF37 !important;
            font-weight: 700;
        }
        </style>
        """,
        unsafe_allow_html=True
    )


def main():
    st.set_page_config(
        page_title="Belmont Construction - Inspection Suite",
        page_icon="🏢",
        layout="wide",
        initial_sidebar_state="expanded"
    )
   
    apply_belmont_branding()

    # HEADER LOGO & TITLE
    logo_path = os.path.abspath("BELMONT_LOGO.png")
    logo_base64 = get_image_base64(logo_path)
    
    col_logo, col_title = st.columns([1, 4])
    with col_logo:
        if logo_base64:
            st.markdown(
                f'<div class="logo-container"><img src="{logo_base64}" alt="Belmont Logo"></div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown("<h3 style='text-align: center; margin-top: 0;'>🏢 <b>BELMONT</b></h3>", unsafe_allow_html=True)
            
    with col_title:
        st.markdown(
            """
            <div class="belmont-header">
                <div class="belmont-title">Field Inspection & Adjuster Claims Portal</div>
                <div class="belmont-subtitle">Belmont Construction | Adjuster-Grade Evidence & Radar Reporting</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    # INITIALIZE SESSION STATE FOR PERSISTENT DATA
    if 'photo_data' not in ss:
        ss.photo_data = {cat: [] for cat in PHOTO_CATEGORIES.keys()}
    if 'geocoded_data' not in ss:
        ss.geocoded_data = None
    if 'raw_address_input' not in ss:
        ss.raw_address_input = ""

    # SIDEBAR INPUTS
    with st.sidebar:
        st.markdown("### 📋 Inspection Metadata")
       
        inspector_name = st.text_input("Inspector Name", value="Matt Caesar")
        inspector_phone = st.text_input("Inspector Direct Phone", placeholder="(314) 555-0199")
        inspector_email = st.text_input("Inspector Email", placeholder="matt@belmontconstruction.com")
       
        st.divider()
        st.markdown("### 📍 Property Details")
        
        # 1. TEXT INPUT FOR ADDRESS OR ZIP CODE
        property_address = st.text_input(
            "Property Address or Zip Code", 
            value=ss.raw_address_input,
            placeholder="e.g. 123 Main St, Belleville IL or 62221"
        )
        ss.raw_address_input = property_address

        # 2. ISOLATED BUTTON FOR MULTI-ENGINE GEOCODING
        if st.button("📍 Lock GPS & Verify Coordinates", type="primary", use_container_width=True):
            if property_address and len(property_address.strip()) >= 3:
                with st.spinner("Geocoding across GIS engines & locking coordinates..."):
                    lat, lon, matched_name = geocode_address_resilient(property_address)
                    if lat is not None and lon is not None:
                        ss.geocoded_data = {
                            "lat": lat,
                            "lon": lon,
                            "matched_address": matched_name
                        }
                        st.success("✅ Target Coordinates Locked!")
                    else:
                        ss.geocoded_data = None
                        st.error("❌ Location match failed. Check street, city, state, or zip code.")
            else:
                st.warning("Please enter a valid property address or zip code first.")

        customer_name = st.text_input("Customer / Claim Name", placeholder="e.g. Smith Residence")
        
        dol_val = st.date_input("Date of Loss (DOL)", value=date.today())
        dol = dol_val.strftime("%Y-%m-%d")
        
        col_date, col_btn = st.columns([2, 1])
        with col_date:
            inspection_date_val = st.date_input("Inspection Date", value=date.today())
        with col_btn:
            st.write("")
            st.write("")
            if st.button("Today"):
                inspection_date_val = date.today()

        report_type = st.radio(
            "Report Type",
            options=["Post-Inspection Claims Report (Completed)", "Pre-Inspection Storm Risk Assessment"],
            index=0
        )

        local_office = st.text_input("Local Office / Service Area", value="St. Louis, MO", placeholder="Enter city and state")
       
        st.divider()
        st.caption("🔒 **Internal Tool:** Photos compress automatically to optimize layout rendering.")

    # MAIN NAVIGATION TABS
    tab_report, tab_claims = st.tabs(["📋 Storm Inspection Report", "📞 Call in Claims"])

    # TAB 1: STORM INSPECTION REPORT & PDF GENERATOR
    with tab_report:
        st.markdown('<div class="section-header">📷 Field Photo Documentation</div>', unsafe_allow_html=True)
       
        total_photos = 0
       
        for category_name, category_info in PHOTO_CATEGORIES.items():
            with st.expander(f"📁 {category_name} — {category_info['description']}"):
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
                        st.success(f"✅ {len(processed)} photos attached")
                    with col2:
                        st.caption(f"Payload: ~{sum(p['file_size_kb'] for p in processed):.0f} KB")
                   
                    preview_cols = st.columns(min(4, len(processed)))
                    for idx, photo in enumerate(processed[:4]):
                        with preview_cols[idx % len(preview_cols)]:
                            st.image(photo['compressed_bytes'], width=110)
               
                if not uploaded_files and ss.photo_data[category_name]:
                    ss.photo_data[category_name] = []

        # PHYSICAL OBSERVATION SELECTOR
        st.markdown('<div class="section-header">🔍 Field Observation (Quick Selection)</div>', unsafe_allow_html=True)
        inspection_finding = st.segmented_control(
            "Select Physical Inspection Finding:",
            options=["🔴 Severe Damage", "🟡 Moderate Damage", "🟢 Normal Wear", "🔍 Pre-Inspection Only"],
            default="🔴 Severe Damage"
        )

        st.markdown('<div class="section-header">📊 Meteorological Radar Verification</div>', unsafe_allow_html=True)
       
        col1, col2 = st.columns([2, 1])
        with col1:
            fetch_noaa = st.checkbox("Include Radar & Weather Verification", value=True)
        with col2:
            st.caption(f"Total Attached Evidence: **{total_photos} Photos**")
       
        if fetch_noaa:
            if ss.geocoded_data and ss.geocoded_data.get('lat') is not None:
                lat = ss.geocoded_data['lat']
                lon = ss.geocoded_data['lon']
                matched_addr = ss.geocoded_data['matched_address']

                noaa_data = fetch_noaa_data(lat, lon, matched_addr, dol or "Unknown", max_radius_miles=30.0)
               
                # GPS Verification Card
                st.markdown(
                    f"""
                    <div class="gps-verification-box">
                        <h4>📍 Property GPS & Roof Pin Verification</h4>
                        <p><b>Target Location:</b> {property_address or 'Not Entered'}</p>
                        <p><b>Geocoded Match:</b> {noaa_data['matched_address']}</p>
                        <p><b>Coordinates:</b> {noaa_data['lat']}, {noaa_data['lon']}</p>
                        <a href="{noaa_data['maps_url']}" target="_blank" class="maps-link-btn">📍 Verify Roof Pin on Google Maps</a>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                m1, m2, m3 = st.columns(3)
                with m1:
                    st.metric("Peak Surface Wind", noaa_data["wind_gust_speed_mph"])
                with m2:
                    st.metric("Verified Hail Size", noaa_data["peak_hail_size_inches"])
                with m3:
                    st.metric("Radar Reflectivity", noaa_data["radar_reflectivity_dbz"])

                # Generated Narrative Preview
                narrative_preview = generate_storm_risk_summary(
                    noaa_data=noaa_data,
                    report_type=report_type,
                    inspection_date=inspection_date_val.strftime("%Y-%m-%d"),
                    property_address=noaa_data['matched_address'],
                    dol=dol,
                    inspection_finding=inspection_finding
                )
                st.markdown("##### Generated Narrative Preview")
                st.info(narrative_preview, icon="📝")

            else:
                noaa_data = None
                st.warning("⚠️ **GPS Coordinates Not Locked:** Please enter an address/zip in the sidebar and click **'📍 Lock GPS & Verify Coordinates'** to fetch weather radar metrics.")
        else:
            noaa_data = None
       
        st.divider()
       
        if st.button("📄 Build Adjuster Package (PDF)", type="primary", use_container_width=True):
            if not all([inspector_name, inspector_phone, inspector_email, property_address, customer_name, dol]):
                st.error("❌ Please complete required property and inspector details in the sidebar.")
            elif fetch_noaa and not noaa_data:
                st.error("❌ Please click '📍 Lock GPS & Verify Coordinates' in the sidebar before building the PDF.")
            elif total_photos == 0:
                st.error("❌ Upload at least one inspection photo before building the PDF.")
            else:
                with st.spinner("Compiling high-resolution report and grid layouts..."):
                    try:
                        photo_data_filtered = {k: v for k, v in ss.photo_data.items() if v}
                       
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
                            inspection_finding=inspection_finding,
                            noaa_data=noaa_data or {},
                            photo_categories_data=photo_data_filtered
                        )
                       
                        file_size_mb = len(pdf_bytes) / (1024 * 1024)
                       
                        st.download_button(
                            label=f"📥 Download Belmont Adjuster PDF ({file_size_mb:.1f} MB)",
                            data=pdf_bytes,
                            file_name=f"Belmont_Inspection_{customer_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
                       
                        st.success(f"✅ Package ready! Size: {file_size_mb:.1f} MB across {total_photos} photos.")
                       
                    except Exception as e:
                        st.error(f"❌ PDF Compilation Error: {str(e)}")
                        st.exception(e)

    # TAB 2: CALL IN CLAIMS DASHBOARD
    with tab_claims:
        st.markdown('<div class="section-header">📞 Direct Claims Filing Hotlines</div>', unsafe_allow_html=True)
        st.caption("Tap any carrier button below to directly launch your phone dialer for First Notice of Loss (FNOL).")
        st.write("")

        col_left, col_right = st.columns(2)

        for idx, (carrier, phone_num) in enumerate(CARRIER_HOTLINES):
            btn_html = f'<a href="tel:{phone_num}" class="carrier-call-btn">{carrier}</a>'
            
            if idx % 2 == 0:
                with col_left:
                    st.markdown(btn_html, unsafe_allow_html=True)
            else:
                with col_right:
                    st.markdown(btn_html, unsafe_allow_html=True)

    st.divider()
    st.caption("© Belmont Construction | Field Representative Claim System | Confidential & Proprietary")


if __name__ == "__main__":
    main()
