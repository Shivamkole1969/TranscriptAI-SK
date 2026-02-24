import socket
import urllib.request
import json
import sys

# In-memory DoH (DNS-over-HTTPS) cache to bypass corporate/cloud DNS blocks
_dns_cache = {}
_orig_getaddrinfo = socket.getaddrinfo

def _patched_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if hasattr(host, "decode"):
        host_str = host.decode('utf-8')
    else:
        host_str = str(host)
        
    if host_str.endswith(".youtube.com") or host_str == "youtube.com" or "googlevideo.com" in host_str or "ytimg.com" in host_str:
        if host_str in _dns_cache:
            ip = _dns_cache[host_str]
            return _orig_getaddrinfo(ip, port, family, type, proto, flags)
            
        try:
            req = urllib.request.Request(
                f'https://dns.google/resolve?name={host_str}&type=A',
                headers={'User-Agent': 'Mozilla/5.0'}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                if 'Answer' in data:
                    for ans in data['Answer']:
                        if ans['type'] == 1: # A record
                            ip = ans['data']
                            _dns_cache[host_str] = ip
                            return _orig_getaddrinfo(ip, port, family, type, proto, flags)
        except Exception:
            pass # fallback to original system DNS if DoH fails
            
    return _orig_getaddrinfo(host, port, family, type, proto, flags)

# Override system DNS resolver
socket.getaddrinfo = _patched_getaddrinfo

# Execute standard yt_dlp through our patched environment
if __name__ == '__main__':
    from yt_dlp import main
    sys.exit(main())
