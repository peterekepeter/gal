sock_pool = {}
http_cache = {}
font_cache = {}
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
        if "://" not in url:
            self.scheme = "file"
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
        
class Text:
    def __init__(self, text):
        self.text = text

class Tag:
    def __init__(self, tag):
        self.tag = tag

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
    '&#39;': '\'',
    '&shy;': '­',
}

def lex(body):
    in_tag = False
    in_entity = False
    out = []
    buffer = ""
    for c in body:
        if c == "&":
            in_entity = True
            entity = "&"
        elif in_entity:
            entity += c
            if c == ";":
                in_entity = False
                entity = entity_map.get(entity, entity)
                buffer += entity
        elif c == "<":
            in_tag = True
            if buffer: out.append(Text(buffer))
            buffer = ""
        elif c == ">":
            in_tag = False
            out.append(Tag(buffer))
            buffer = ""
        else:
            buffer += c
    if not in_tag and buffer:
        out.append(Text(buffer))
    return out


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

    def browse(self, url):
        import tkinter

        WIDTH, HEIGHT = 800, 600
        HSTEP, VSTEP = 12, 18

        self.width = WIDTH
        self.height = HEIGHT
        self.vstep = VSTEP
        self.hstep = HSTEP

        if not self.window:
            print("creating window")
            self.window = tkinter.Tk()
            self.window.bind("<Up>", self.scrollup)
            self.window.bind("<Down>", self.scrolldown)
            self.window.bind("<MouseWheel>", self.mousewheel)
            self.window.bind("<Configure>", self.configure)
        window = self.window
        if not self.canvas:
            self.canvas = tkinter.Canvas(window, width=WIDTH, height=HEIGHT)
        canvas = self.canvas
        self.load(url)

    def load(self, url):
        import tkinter

        print("navigating to", url)
        self.window.title(url)
        try:
            url = URL(url)
        except Exception as err:
            import traceback
            print("Error: failed to parse URL")
            print(traceback.format_exc())
            url = URL("about:blank")
            
        result = url.request(max_redirect=5)
            
        self.tokens = lex(result)
        self.layout()
        self.draw()
        self.canvas.pack(fill=tkinter.BOTH, expand=1)
        tkinter.mainloop()

    def draw(self):
        import tkinter as tk
        import tkinter.font
        canvas = self.canvas
        self.canvas.delete("all")
        # print(tkinter.font.families())
      
        for x, y, c, font in self.display_list:
            if y > self.scroll + self.height: continue
            if y + self.vstep < self.scroll: continue
            self.canvas.create_text(x, y - self.scroll, text=c, font=font, anchor='nw')

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
        if self.scroll + self.height > self.scroll_bottom:
            self.scroll = self.scroll_bottom - self.height
        if self.scroll < 0:
            self.scroll = 0

    def configure(self, e):
        self.width = e.width
        self.height = e.height
        self.layout()
        self.limitscrollinbounds()
        self.draw()

    def layout(self):
        layout = Layout(self.tokens, self.width, self.height, self.hstep, self.vstep)
        self.display_list = layout.display_list
        self.scroll_bottom = layout.scroll_bottom

class Layout:
    def __init__(self, tokens, width, height, hstep, vstep):
        self.vstep = vstep
        self.hstep = hstep
        self.width = width
        self.height = height
        self.line = []
        self.display_list = []
        self.cursor_x = hstep
        self.cursor_y = vstep
        self.weight = "normal" # bold|normal
        self.style = "roman" # roman|italic
        self.align = "auto" # auto|center
        self.vert_align = "baseline"
        self.whitespace = ''
        self.upper = "normal"
        self.fontfamily = ''
        self.size = 12
        self.lineheight = 16
        self.scroll_bottom = 0
        for tok in tokens:
            self.token(tok)
        self.flush()
    
    def token(self, tok):
        if isinstance(tok, Text):
            self.word(tok)
        elif tok.tag == "i":
            self.style = "italic"
        elif tok.tag == "/i":
            self.style = "roman"
        elif tok.tag == "b":
            self.weight = "bold"
        elif tok.tag == "/b":
            self.weight = "normal"
        elif tok.tag == "small":
            self.size -= 2
        elif tok.tag == "/small":
            self.size += 2
        elif tok.tag == "big":
            self.size += 4
        elif tok.tag == "/big":
            self.size -= 4
        elif tok.tag == "br/":
            self.flush(forceline=True)
        elif tok.tag == "p" or tok.tag.startswith("p "):
            pass
        elif tok.tag == "/p":
            self.flush()
            self.cursor_y += self.vstep
        elif tok.tag == "h1" or tok.tag.startswith("h1 "):
            self.size = 18
            self.weight = "bold"
            self.align = "center"
        elif tok.tag == "/h1":
            self.flush()
            self.size = 12
            self.weight = "normal"
            self.align = "auto"
            self.cursor_y += self.vstep
        elif tok.tag == "h2" or tok.tag.startswith("h2 "):
            self.size = 16
            self.weight = "bold"
        elif tok.tag == "/h2":
            self.flush()
            self.size = 12
            self.weight = "normal"
            self.cursor_y += self.vstep
        elif tok.tag == "sup":
            self.size = 8
            self.vert_align = "top"
        elif tok.tag == "/sup":
            self.size = 12
            self.vert_align = "baseline"
        elif tok.tag == "abbr":
            self.upper = "all"
            self.size = 10
            self.weight = "bold"
        elif tok.tag == "/abbr":
            self.upper = "normal"
            self.size = 12
            self.weight = "normal"
        elif tok.tag == "pre":
            self.whitespace = 'pre'
            self.fontfamily = 'Courier New'
        elif tok.tag == "/pre":
            self.whitespace = ''
            self.fontfamily = ''
        elif tok.tag == "code":
            self.fontfamily = 'Courier New'
        elif tok.tag == "/code":
            self.fontfamily = ''
        
    
    def word(self, tok):
        import tkinter.font
        font = get_font(self.fontfamily, self.size, self.weight, self.style)
        space_width = font.measure(" ")
      
        if self.whitespace == "pre":
            isnewline = False
            for line in tok.text.split("\n"):
                print(line)
                if isnewline: self.flush(forceline=True)
                w = font.measure(line)
                self.line.append((self.cursor_x, line, font, self.vert_align))
                self.cursor_x += w
                isnewline = True
            return

        for word in tok.text.split():
            if self.upper == "all":
                word = word.upper()
            txt = word
            if '\N{soft hyphen}' in txt:
                txt = "".join(word.split('\N{soft hyphen}'))
            w = font.measure(txt)
            if self.cursor_x + w > self.width - self.hstep:
                if self.tryhypenate(font, word):
                    continue
                else:
                    self.flush()
            self.line.append((self.cursor_x, txt, font, self.vert_align))
            self.cursor_x += w + space_width

    def tryhypenate(self, font, txt):
        if '\N{soft hyphen}' in txt:
            isnewline = False
            space_width = font.measure(" ")
            parts = txt.split('\N{soft hyphen}')
            while parts:
                failed = True
                for i in range(0,len(parts)):
                    partsrange = parts[0:len(parts)-i]
                    rangetxt = "".join(partsrange)
                    if len(partsrange) != len(parts):
                        rangetxt += "-"
                    w = font.measure(rangetxt)
                    if self.cursor_x + w > self.width - self.hstep:
                        continue
                    failed = False
                    isnewline = False
                    self.line.append((self.cursor_x, rangetxt, font, self.vert_align))
                    self.cursor_x += w
                    parts = parts[len(parts)-i:]
                    break
                if failed:
                    if isnewline:
                        # must put at least one fragment to avoid infinite loop
                        rangetxt = parts[0] + "-"
                        self.line.append((self.cursor_x, rangetxt, font, self.vert_align))
                    self.flush() # continue hypenation on next line
            self.cursor_x += space_width
            return True

        return False        
        
    def flush(self, forceline=False):
        if not self.line: 
            if forceline:
                self.cursor_y += self.lineheight
            return
        scaler = 1.25
        metrics = [font.metrics() for x, word, font, vert in self.line]
        max_ascent = max([metric["ascent"] for metric in metrics])
        baseline = self.cursor_y + scaler * max_ascent

        if self.align == "center":
            horiz_align = ( self.width - self.cursor_x ) // 2
        elif self.align == "right":
            horiz_align = self.width - self.cursor_x
        else:
            horiz_align = 0

        for x, word, font, valign in self.line:
            if valign == "top":
                y = baseline - scaler * max_ascent
            else:
                y = baseline - font.metrics("ascent")
            self.display_list.append((x + horiz_align, y, word, font))

        max_descent = max([metric["descent"] for metric in metrics])
        self.cursor_y = baseline + scaler * max_descent
        self.lineheight = (max_descent + max_ascent) * scaler

        self.cursor_x = self.hstep
        self.line = []
        self.scroll_bottom = self.cursor_y


def get_font(family, size, weight, style):
    FONTS = font_cache
    key = (family, size, weight, style)
    if key not in FONTS:
        import tkinter.font
        font = tkinter.font.Font(family=family, size=size, weight=weight, slant=style)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)
    return FONTS[key][0]


def test():
    print("run tests")
    test_URL()
    test_lex()
    test_show()

def test_lex():
    f = lex
    lexed = f("<h1>Hi!</h1>")
    assert len(lexed) == 3
    assert lexed[0].tag == "h1"
    assert lexed[1].text == "Hi!"
    assert lexed[2].tag == "/h1"


def test_show():
    f = lambda x: "".join([y.text for y in lex(x) if isinstance(y, Text)])
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

    url = URL("C:\\Users\\someone\\index.html")
    assert url.scheme == "file"
    assert url.path == "C:\\Users\\someone\\index.html"


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