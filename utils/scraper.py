import os, requests, socket, ipaddress
from wsgiref import headers
import xml.etree.ElementTree as ET
from firecrawl import Firecrawl
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin


# =========================================
# URL SAFETY VALIDATION — SSRF PREVENTION
# =========================================

# Blocked hostnames that should never be scraped
BLOCKED_HOSTS = {
    'localhost', '127.0.0.1', '0.0.0.0', '::1',
    '169.254.169.254',          # Cloud metadata (AWS/GCP/DO)
    'metadata.google.internal', # GCP metadata
    'metadata.internal',        # Generic cloud metadata
}

# Blocked URL schemes
ALLOWED_SCHEMES = {'http', 'https'}


def is_safe_url(url):
    """
    Validates a URL is safe to scrape (prevents SSRF attacks).
    
    Blocks:
    - Private/internal IP ranges (10.x, 172.16-31.x, 192.168.x, 127.x)
    - Loopback addresses (localhost, 127.0.0.1, ::1)
    - Link-local addresses (169.254.x.x)
    - Cloud metadata endpoints (169.254.169.254, metadata.google.internal)
    - Non-HTTP schemes (file://, ftp://, gopher://, etc.)
    
    Returns: (is_safe: bool, error_message: str or None)
    """
    if not url or not url.strip():
        return False, "URL cannot be empty."
    
    url = url.strip()
    
    # 1. Parse URL
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format."
    
    # 2. Scheme check
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"Invalid URL scheme '{parsed.scheme}'. Only http:// and https:// are allowed."
    
    # 3. Must have a hostname
    hostname = parsed.hostname
    if not hostname:
        return False, "URL must contain a valid hostname."
    
    # 4. Block known dangerous hostnames
    if hostname.lower() in BLOCKED_HOSTS:
        return False, f"Scraping '{hostname}' is not allowed for security reasons."
    
    # 5. Resolve hostname to IP and check if it's private/internal
    try:
        resolved_ips = socket.getaddrinfo(hostname, None)
        for entry in resolved_ips:
            ip_str = entry[4][0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
                    return False, f"URL resolves to a private/internal address ({ip_str}). Scraping blocked."
            except ValueError:
                continue
    except socket.gaierror:
        return False, f"Could not resolve hostname '{hostname}'. Please check the URL."
    except Exception:
        # If DNS resolution fails for any other reason, allow it through
        # (Firecrawl will handle the actual request and fail gracefully)
        pass
    
    # 6. Block URLs with authentication credentials
    if parsed.username or parsed.password:
        return False, "URLs with embedded credentials are not allowed."
    
    # 7. Block extremely long URLs (potential abuse)
    if len(url) > 2048:
        return False, "URL exceeds maximum length (2048 characters)."
    
    return True, None


def init_firecrawl():
    """Initializes the Firecrawl client using the API key from .env"""
    api_key = os.getenv('FIRECRAWL_API_KEY')
    if not api_key:
        raise ValueError("FIRECRAWL_API_KEY is missing from environment variables.")
    return Firecrawl(api_key=api_key)

def scrape_single_url(url, timeout_ms=45000):
    """
    Scrapes a single webpage and returns the markdown content.
    Hard timeout (default 45s) so a slow/heavy site can't hang the worker forever.
    """
    try:
        app = init_firecrawl()

        # Firecrawl v4 accepts `timeout` in milliseconds. Pass it so heavy JS
        # sites (e.g. bmw.in) fail fast instead of hanging indefinitely.
        try:
            result = app.scrape(url, formats=['markdown'], timeout=timeout_ms)
        except TypeError:
            # Older SDK signature without timeout kwarg — fall back gracefully.
            result = app.scrape(url, formats=['markdown'])
        
        if hasattr(result, 'markdown') and result.markdown:
            title = 'Scraped Document'
            if hasattr(result, 'metadata') and hasattr(result.metadata, 'title'):
                title = result.metadata.title

            return {
                "success": True,
                "title": title,
                "content": result.markdown
            }
        else:
            return {"success": False, "error": "No markdown content found on this page."}
            
    except Exception as e:
        return {"success": False, "error": str(e)}

def extract_sitemap_urls(sitemap_url, max_urls=10):
    """
    Fetches a sitemap.xml, parses it, and returns a list of URLs.
    Filters out media files (images, PDFs) and dives into nested sitemaps.
    """
    BAD_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.pdf', '.mp4', '.zip')

    def _fetch_urls(url, visited, current_list):
        if url in visited or len(current_list) >= max_urls:
            return
        
        visited.add(url)
        
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=10)
            
            if resp.status_code != 200: 
                return
            
            root = ET.fromstring(resp.content)
            
            for elem in root.iter():
                if len(current_list) >= max_urls:
                    break
                    
                if 'loc' in elem.tag and elem.text:
                    loc = elem.text.strip()
                    
                    clean_loc = loc.split('?')[0].lower() 
                    
                    if clean_loc.endswith('.xml'):
                        _fetch_urls(loc, visited, current_list)
                    elif not clean_loc.endswith(BAD_EXTENSIONS) and loc not in current_list:
                        current_list.append(loc)
                        
        except Exception as e:
            print(f"Skipping {url} due to error: {e}")

    try:
        final_urls = []
        _fetch_urls(sitemap_url, set(), final_urls)
        
        return {
            "success": True,
            "total_found": len(final_urls),
            "urls_to_scrape": final_urls
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}
    import requests

def crawl_website_links(start_url, max_pages=50):
    """
    Finds internal links by physically 'reading' the HTML of each page.
    No Sitemap required.
    """
    print(f"Spider starting at: {start_url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    visited = set()
    queue = [start_url]
    found_urls = []
    
    domain = urlparse(start_url).netloc 

    while queue and len(found_urls) < max_pages:
        current_url = queue.pop(0)
        
        if current_url in visited:
            continue
            
        visited.add(current_url)
        found_urls.append(current_url)
        
        try:
            response = requests.get(current_url, headers=headers, timeout=5)
            
            if response.status_code != 200:
                print(f"  Blocked or Not Found ({response.status_code}): {current_url}")
                continue

            soup = BeautifulSoup(response.text, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                full_url = urljoin(current_url, link['href']).split('?')[0]
                
                if (urlparse(full_url).netloc == domain and 
                    full_url not in visited and 
                    full_url not in queue and
                    not full_url.lower().endswith(('.pdf', '.jpg', '.png', '.xml', '.zip', '.css', '.js'))):
                    
                    queue.append(full_url)
            
            print(f"  Found {len(queue)} links in queue... (Total found: {len(found_urls)})")
                    
        except Exception as e:
            print(f"  Skipping {current_url} due to error: {e}")

    return {
        "success": True, 
        "urls": found_urls,
        "remaining_queue": len(queue)  # How many undiscovered links were left when we stopped
    }