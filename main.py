sock_pool = {}
http_cache = {}
http_cache_dir = None
default_rtl = False

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
        if url.startswith("about:"):
            self.scheme, self.path = url.split(":", 1)
            return
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
        if self.scheme == "about":
            if self.path == "blank":
                return ""
            else:
                return "page not found"
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
    
        if http_cache_dir:
            import os
            import json
            if not os.path.isdir(http_cache_dir):
                os.makedirs(http_cache_dir)
            cache_index = http_cache_dir + "/__cache.json"
            if os.path.isfile(cache_index):
                try:
                    with open(cache_index, "r", encoding="utf8") as f:
                        http_cache = json.load(f)
                except:
                    print("Warning: Failed to load cache index")
                    http_cache = {}

        cache_key = self.get_cache_key()
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
                if http_cache_dir:
                    import os
                    os.remove(http_cache_dir + "/" + blob_id)
            else:
                if "content" in cache_entry:
                    content = cache_entry["content"]
                    return content
                if http_cache_dir and "blob_id" in cache_entry:
                    blob_id = cache_entry["blob_id"]
                    with open(http_cache_dir + "/" + blob_id, "rb") as f:
                        bytes = f.read()
                        content = bytes.decode("utf8")
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

        print(response_headers)
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
            store = True
            if cache_control == None:
                pass
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
                cache_entry = {
                    "expires": expires,
                }
                http_cache[cache_key] = cache_entry
                if http_cache_dir:
                    import uuid
                    blob_id = str(uuid.uuid4())
                    blob_path = http_cache_dir + "/" + blob_id
                    cache_entry["blob_id"] = blob_id
                    with open(blob_path, "wb") as f:
                        f.write(bytes)
                    with open(cache_index, "w", encoding="utf8") as f:
                        json.dump(http_cache, f, indent=1)
                else:
                    cache_entry["content"] = content
        
        return content

    def get_cache_key(self) -> str:
        return f'{self.scheme}://{self.host}:{self.port}{self.path}'

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

def lex(body):
    in_tag = False
    in_entity = False
    text = ""
    for c in body:
        if c == "&":
            in_entity = True
            entity = "&"
        elif in_entity:
            entity += c
            if c == ";":
                in_entity = False
                entity = entity_map.get(entity, entity)
                text += entity
        elif c == "<":
            in_tag = True
        elif c == ">":
            in_tag = False
        elif not in_tag:
            text += c
    return text


class CLI:

    def browse(self, urlstr, max_redirect=5):
        print("navigating to", urlstr)
        url = URL(urlstr)
        result = url.request(max_redirect=max_redirect)
        if url.viewsource:
            print(result)
        else:
            print(lex(result))

class GUI:

    def __init__(self):
        self.window = None
        self.canvas = None
        self.scroll = 0

    def browse(self, urlstr, max_redirect=5):
        WIDTH, HEIGHT = 800, 600
        HSTEP, VSTEP = 12, 18

        print("navigating to", urlstr)
        try:
            url = URL(urlstr)
        except Exception as err:
            import traceback
            print("Error: failed to parse URL")
            print(traceback.format_exc())
            url = URL("about:blank")

        result = url.request(max_redirect=max_redirect)
        import tkinter
        if not self.window:
            self.window = tkinter.Tk()
            self.window.bind("<Up>", self.scrollup)
            self.window.bind("<Down>", self.scrolldown)
            self.window.bind("<MouseWheel>", self.mousewheel)
            self.window.bind("<Configure>", self.configure)
        window = self.window
        if not self.canvas:
            self.canvas = tkinter.Canvas(window, width=WIDTH, height=HEIGHT)
        canvas = self.canvas

        window.title(urlstr)
        self.text = lex(result)
        self.width = WIDTH
        self.height = HEIGHT
        self.vstep = VSTEP
        self.hstep = HSTEP
        self.display_list, self.scroll_bottom = layout(self.text, WIDTH, HEIGHT, HSTEP, VSTEP, RTL=default_rtl)
        self.draw()
        canvas.pack(fill=tkinter.BOTH, expand=1)
        tkinter.mainloop()

    def draw(self):
        import tkinter as tk
        self.canvas.delete("all")

        for x, y, c in self.display_list:
            if y > self.scroll + self.height: continue
            if y + self.vstep < self.scroll: continue
            self.canvas.create_text(x, y - self.scroll, text=c)
        if self.scroll_bottom > self.height:
            pos_0 = self.scroll / self.scroll_bottom
            pos_1 = (self.scroll + self.height) / self.scroll_bottom
            self.canvas.create_rectangle(
                self.width-8, self.height*pos_0, 
                self.width, self.height*pos_1, 
                fill="#000"
            )

    def scrollup(self, e):
        SCROLL_STEP = 100
        self.scroll -= SCROLL_STEP
        self.limitscrollinbounds()
        self.draw()

    def scrolldown(self, e):
        SCROLL_STEP = 100
        self.scroll += SCROLL_STEP
        self.limitscrollinbounds()
        self.draw()

    def mousewheel(self, e):
        self.scroll -= e.delta
        self.limitscrollinbounds()
        self.draw()

    def limitscrollinbounds(self):
        if self.scroll < 0:
            self.scroll = 0
        elif self.scroll + self.height > self.scroll_bottom:
            self.scroll = self.scroll_bottom - self.height

    def configure(self, e):
        self.width = e.width
        self.height = e.height
        self.display_list, self.scroll_bottom = layout(self.text, self.width, self.height, self.hstep, self.vstep, RTL=default_rtl)
        self.draw()



def layout(text, WIDTH=800, HEIGHT=600, HSTEP=12, VSTEP=18, RTL=False):
    display_list = []
    cursor_x, cursor_y = HSTEP, VSTEP
    x_start = cursor_x
    line = []
    for c in text:
        line.append((cursor_x, cursor_y, c))
        cursor_x += x_step
        if c == "\n" or cursor_x >= WIDTH - HSTEP:
            x_end = cursor_x
            for item in line:
                x,y,c = item
                if RTL:
                    x=x+WIDTH-x_end
                display_list.append((x,y,c))
            cursor_y += VSTEP
            cursor_x = x_start
            line_start_at = len(display_list)
    return display_list, cursor_y + VSTEP


def test():
    print("run tests")
    test_URL()
    test_show()

def test_show():
    f = lex
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
    interface = GUI()
    keyname = None
    for arg in sys.argv[1:]:
        if keyname:
            if keyname == "--cache-dir":
                http_cache_dir = arg
            keyname = None
        elif arg.startswith('-'):
            flag = arg
            if "--gui" == flag:
                interface = GUI()
            elif "--cli" == flag:
                interface = CLI()
            elif "--test" == flag:
                test()
            elif "--version" == flag:
                print("1.0.0")
            elif "--help" == flag:
                print("gal web browser")
            elif flag == "--rtl":
                default_rtl = True
            elif "--cache-dir" == flag:
                keyname = flag
            else:
                print(f"unknown flag '{flag}'")
        else:
            url = arg
            interface.browse(url)