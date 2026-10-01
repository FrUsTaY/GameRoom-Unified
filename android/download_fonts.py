#!/usr/bin/env python3
import re
import os
import urllib.request

FONTS_DIR = "app/src/main/assets/fonts"
FONTS_DIR_ABS = os.path.join(os.path.dirname(os.path.abspath(__file__)), FONTS_DIR)

def get_font_url_from_css(font_family, weight=None):
    """Get the actual Google Fonts URL from the CSS response"""
    if font_family == "Jura":
        url = "https://fonts.googleapis.com/css2?family=Jura:wght@400;500;700&display=swap"
    elif font_family == "Russo One":
        url = "https://fonts.googleapis.com/css2?family=Russo+One&display=swap"
    else:
        return None
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            css_content = response.read().decode('utf-8')
            return css_content
    except Exception as e:
        print(f"Error fetching CSS: {e}")
        return None

def extract_font_urls(css_content, font_family):
    """Extract font URLs from Google Fonts CSS"""
    # Pattern to match src URLs in @font-face rules
    url_pattern = r'src:\s+url\(([^)]+)\)\s+format\(([^)]+)\)'
    family_pattern = r'font-family:\s*\'([^\']+)\''
    
    font_urls = []
    matches = list(re.finditer(url_pattern, css_content))
    
    if matches:
        for match in matches:
            url = match.group(1)
            # Convert https://fonts.gstatic.com/... to direct URL
            if url.startswith('https://'):
                font_urls.append(url)
    
    return font_urls

def download_font_file(url, output_path):
    """Download a font file"""
    if os.path.exists(output_path):
        print(f"[OK] Already exists: {output_path}")
        return True
    
    try:
        print(f"[DOWN] Downloading to {output_path}...")
        urllib.request.urlretrieve(url, output_path)
        print(f"[OK] Downloaded: {output_path}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to download {url}: {e}")
        return False

if __name__ == "__main__":
    print("=== Downloading Fonts for GameRoom ===\n")
    
    os.makedirs(os.path.join(FONTS_DIR_ABS, "Jura"), exist_ok=True)
    os.makedirs(os.path.join(FONTS_DIR_ABS, "RussoOne"), exist_ok=True)
    
    # Download Jura fonts
    print("Downloading Jura fonts...")
    css = get_font_url_from_css("Jura")
    if css:
        urls = extract_font_urls(css, "Jura")
        for i, url in enumerate(urls[:3]):  # First 3 are Jura weights
            ext = url.split('.')[-1]
            filename = f"Jura/Jura-{['Regular', 'Medium', 'Bold'][i]}.{ext}"
            download_font_file(url, os.path.join(FONTS_DIR_ABS, filename))
    
    # Download Russo One fonts
    print("\nDownloading Russo One fonts...")
    css = get_font_url_from_css("Russo One")
    if css:
        urls = extract_font_urls(css, "Russo One")
        for url in urls[:1]:
            ext = url.split('.')[-1]
            filename = f"RussoOne/RussoOne-Regular.{ext}"
            download_font_file(url, os.path.join(FONTS_DIR_ABS, filename))
    
    print("\n=== Done! ===")
