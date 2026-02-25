import socket
import urllib.request
import json
import sys
import os

# DNS-over-HTTPS resolver for environments where system DNS can't resolve YouTube
# (e.g., Hugging Face Docker containers)
_dns_cache = {}
_orig_getaddrinfo = socket.getaddrinfo

def _resolve_via_doh(hostname):
    """Resolve hostname via Google's DNS-over-HTTPS."""
    if hostname in _dns_cache:
        return _dns_cache[hostname]
    try:
        req = urllib.request.Request(
            f'https://8.8.8.8/resolve?name={hostname}&type=A',
            headers={'User-Agent': 'Mozilla/5.0', 'Host': 'dns.google'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if 'Answer' in data:
                for ans in data['Answer']:
                    if ans['type'] == 1:  # A record
                        ip = ans['data']
                        _dns_cache[hostname] = ip
                        return ip
    except Exception:
        pass
    return None

def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if hasattr(host, "decode"):
        host_str = host.decode('utf-8')
    else:
        host_str = str(host)
    
    # Only intercept YouTube/Google video domains
    yt_domains = (".youtube.com", ".googlevideo.com", ".ytimg.com", ".google.com")
    is_yt = any(host_str.endswith(d) or host_str == d.lstrip('.') for d in yt_domains)
    
    if is_yt:
        # First try the original resolver
        try:
            result = _orig_getaddrinfo(host, port, family, type, proto, flags)
            if result:
                return result
        except socket.gaierror:
            pass
        
        # System DNS failed — resolve via DoH
        ip = _resolve_via_doh(host_str)
        if ip:
            # Return a valid addrinfo tuple with the resolved IP
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port or 443))]
    
    return _orig_getaddrinfo(host, port, family, type, proto, flags)

# Only patch if system DNS is broken (test with a quick resolution)
try:
    _orig_getaddrinfo("www.youtube.com", 443)
except socket.gaierror:
    # System DNS can't resolve YouTube — activate the bypass
    socket.getaddrinfo = _patched_getaddrinfo

# Execute standard yt_dlp through our patched environment
if __name__ == '__main__':
    from yt_dlp import main
    sys.exit(main())
