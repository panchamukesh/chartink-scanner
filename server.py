"""
MarketScan Pro — minimal static file server for VM deployment.
Run: python server.py
"""
import os
import http.server
import socketserver

PORT = int(os.environ.get("PORT", 5002))
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, fmt, *args):
        print(f"[marketscan] {self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        httpd.allow_reuse_address = True
        print(f"[marketscan] Serving on http://0.0.0.0:{PORT}")
        httpd.serve_forever()
