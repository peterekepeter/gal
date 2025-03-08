sock_pool = {}
http_cache = {}

class URL:
    def __init__(self, url, parent=None):
        if parent:
            self.scheme = parent.scheme
            self.host = parent.host
            self.port = parent.port
        self.viewsource = False
        if url.startswith("view-source:"):
            url = url[12:]
            self.viewsource = True
        if url.startswith("data:"):
            self.scheme, url = url.split(":", 1)
            self.mimetype, self.content = url.split(",", 1)
            return
        if url.startswith("/"):
            self.path = url
            return
        self.scheme, url = url.split("://")
        supported = ["http", "https", "file"]
        assert self.scheme in supported
        if self.scheme == "file":
            self.host = ""
            self.path = url
        else:
            if "/" not in url:
                url = url + "/"  
            self.host, url = url.split("/", 1)
            self.path = "/" + url
      
        if ":" in self.host:
            self.host, port = self.host.split(":", 1)
            self.port = int(port)
        elif self.scheme == "http":
            self.port = 80
        elif self.scheme == "https":
            self.port = 443
    
    def request(self, max_redirect=3):
        if self.scheme == "data":
            return self.content
        elif self.scheme == "file":
            return self.request_file()
        else:
            return self.request_socket(max_redirect)

    def request_file(self):
        with open(self.path) as f:
            return f.read()

    def request_socket(self, max_redirect=3):
        global sock_pool
        global http_cache
    
        cache_key = (self.scheme, self.host, self.port, self.path)
        if cache_key in http_cache:
            cache_entry = http_cache[cache_key]
            expires = cache_entry["expires"]
            expired = False
            if expires > 0:
                import time
                if time.time() >= expires:
                    expired = True
            if expired:
                del http_cache[cache_key]
            else:
                content = cache_entry["content"]
                return content

        key = (self.scheme, self.host, self.port)
        s = None
        f = None
        if key in sock_pool:
            (s,f) = sock_pool[key] # reuse existing socket
        else:
            import socket # init new TCP/IP connection
            s = socket.socket(
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
            s.connect((self.host, self.port))
            if self.scheme == "https":
                import ssl # need encryption
                ctx = ssl.create_default_context()
                s = ctx.wrap_socket(s, server_hostname=self.host)
            f = s.makefile("rb", encoding="utf8", newline="\r\n")
            
        method = 'GET'
        reqlines = [
            f'{method} {self.path} HTTP/1.1\r\n',
            f'Host: {self.host}\r\n',
            f'Connection: keep-alive\r\n',
            f'Accept-Encoding: gzip\r\n',
            '\r\n',
        ]
        request = "".join(reqlines)
        bytessent = s.send(request.encode('utf8'))
        response = f

        statusline = response.readline().decode("utf8")
        version, status, explanation = statusline.split(" ",2)
        print(status, explanation.strip(), "GET", self.host, self.path)
        response_headers = {}
        while True:
            line = response.readline().decode("utf8")
            if line == "\r\n": break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        chunked = False
        gzip = False
        if "content-encoding" in response_headers:
            content_encoding = response_headers["content-encoding"]
            assert content_encoding == "gzip" # others not supported
            gzip = True

        if "transfer-encoding" in response_headers:
            transfer_encoding = response_headers["transfer-encoding"]
            if "chunked" in response_headers["transfer-encoding"]:
                chunked = True
            if "gzip" in transfer_encoding:
                gzip = True
            assert "compress" not in transfer_encoding # not supported
            assert "deflate" not in transfer_encoding # not supported
            
        keep_alive = response_headers.get("connection") == "keep-alive"

        if chunked:
            chunks = []
            is_transfer = True
            while is_transfer:
                chunk_size_str = response.readline().decode("utf8")
                chunk_size = int(chunk_size_str, 16)
                chunk = response.read(chunk_size)
                assert len(chunk) == chunk_size
                endline = response.readline()
                chunks.append(chunk)
                if chunk_size == 0:
                    is_transfer = False
            bytes = b''.join(chunks)
            content_length = len(bytes)
        elif 'content-length' in response_headers:
            content_length_str = response_headers['content-length']
            content_length = int(content_length_str)
            bytes = response.read(content_length)
            assert len(bytes) == content_length
        else:
            # HTTP/1.0 fallback length unknown -> read until end of socket
            keep_alive = False 
            bytes = response.read()
            s.close()
        
        if gzip:
            import gzip
            bytes = gzip.decompress(bytes)
            content_length = len(bytes)

        content = bytes.decode('utf8')
        code = int(status)

        if keep_alive:
            sock_pool[key] = (s,f)
        elif key in sock_pool:
            del sock_pool[key]

        if 300 <= code < 400 and max_redirect > 0:
            location = response_headers.get('location')
            if location:
                url = URL(location, parent=self)
                content = url.request(max_redirect=max_redirect-1)

        if code == 200 and method == 'GET':
            cache_control = response_headers.get('cache-control')
            expires = 0
            if cache_control == None:
                store = True
            elif 'no-store' in cache_control:
                store = False
            elif 'max-age' in cache_control:
                import time
                now = time.time()
                _, n = cache_control.split("=", 1)
                seconds = int(n)
                expires = now + seconds * 1000
            else:
                # cache control not handled, better not cache
                store = False 
            
            if store:
                http_cache[cache_key] = {
                    "content": content,
                    "expires": expires
                }
        
        return content


entity_map = {
    '&nbsp;': ' ',
    '&lt;': '<',
    '&gt;': '>',
    '&amp;': '&',
    '&quot;': '\"',
    '&apos;': '\'',
    '&cent;': '¢', 	
    '&pound;': '£', 	
    '&yen;': '¥', 	
    '&euro;': '€', 	
    '&copy;': '©', 	
    '&reg;': '®',
    '&ndash;': '–',
    '&mdash;': '—',
}

def show(body, outp=print):
    in_tag = False
    in_entity = False
    limit = 10000
    for c in body:
        limit -= 1
        if limit <= 0: break
        if c == "&":
            in_entity = True
            entity = "&"
        elif in_entity:
            entity += c
            if c == ";":
                in_entity = False
                entity = entity_map.get(entity, entity)
                outp(entity, end="")
        elif c == "<":
            in_tag = True
        elif c == ">":
            in_tag = False
        elif not in_tag:
            outp(c, end="")


def showtostr(body) -> str:
    arr = []
    fn = lambda x, end="": arr.append(x)
    show(body, fn)
    return "".join(arr)


def browse(urlstr, max_redirect=5):
    print("navigating to", urlstr)
    url = URL(urlstr)
    result = url.request(max_redirect=max_redirect)
    if url.viewsource:
        print(result)
    else:
        show(result)
    
def test():
    print("run tests")
    test_URL()
    test_show()

def test_show():
    f = showtostr
    assert f("x") == "x"
    assert f("<h1>Hi!</h1>") == "Hi!"
    assert f("&lt;") == "<"
    assert f("&lt;div&gt;") == "<div>"

def test_URL():
    
    url = URL("http://example.org")
    assert url.scheme == "http"
    assert url.host == "example.org"
    assert url.path == "/"
    assert url.port == 80

    url = URL("https://example.org")
    assert url.scheme == "https"
    assert url.port == 443

    url = URL("https://example.org:8080")
    assert url.port == 8080

    url = URL("file:///path/to/file/index.html")
    assert url.scheme == "file"
    assert url.path == "/path/to/file/index.html"

    url = URL("data:text/html,Hello world!")
    assert url.scheme == "data"
    assert url.mimetype == "text/html"
    assert url.content == "Hello world!"
    assert url.request() == "Hello world!"

    url = URL("view-source:http://example.org/")
    assert url.viewsource == True
    assert url.scheme == "http"
    assert url.host == "example.org"

    url = URL("https://example.org")
    url = URL("/404.html", parent=url)
    assert url.path == "/404.html"
    assert url.host == "example.org"
    assert url.port == 443
    assert url.scheme == "https"


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        if arg.startswith('-'):
            flag = arg
            if "--test" == flag:
                test()
            elif "--version" == flag:
                print("1.0.0")
            elif "--help" == flag:
                print("gal web browser")
            elif arg.startswith("-"):
                print(f"unknown flag '{flag}'")
        else:
            url = arg
            browse(url)