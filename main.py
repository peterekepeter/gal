sock_pool = {}
http_cache = {}
font_cache = {}
http_cache_dir = None
http_cache_blob_dir = None
default_rtl = False
default_style_sheet = None
default_search_engine = "https://lite.duckduckgo.com/lite?q="


class URL:
    def __init__(self, url, parent=None):
        self.fragment = ""
        self.search = ""
        if parent:
            self.scheme = parent.scheme
            self.path = parent.path
            if hasattr(parent, "host"):
                self.host = parent.host
            if hasattr(parent, "port"):
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
        if url.startswith("//"):
            self.host, url = url[2:].split("/", 1)
        if url.startswith("/") and parent:
            self.path = url
            return
        if "://" not in url:
            if parent and url.startswith("#"):
                self.fragment = url
            elif parent and not url.startswith("/"):
                self.path = "/".join(self.path.split("/")[:-1] + [url])
                if self.path.startswith("./"):
                    self.path = self.path[2:]
            else:
                if parent is None:
                    self.scheme = "file"
                else:
                    if "/" not in url:
                        url = "/" + url
                self.path = url
            if "#" in self.path:
                self.path, self.fragment = self.path.split("#", 1)
                self.fragment = "#" + self.fragment
            return
        self.scheme, url = url.split("://", 1)
        supported = ["http", "https", "file"]
        assert self.scheme in supported
        if self.scheme == "file":
            self.host = ""
            self.path = url
        else:
            if "#" in url:
                url, self.fragment = url.split("#", 1)
                self.fragment = "#" + self.fragment
            if "?" in url:
                url, self.search = url.split("?", 1)
                self.search = "?" + self.search
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

    def request(self, max_redirect=3, readcache=True):
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
            return self.request_socket(max_redirect, readcache)

    def request_file(self):
        with open(self.path) as f:
            return f.read()

    def request_socket(self, max_redirect=3, readcache=True):
        global sock_pool
        global http_cache
        global http_cache_blob_dir

        if http_cache_dir:
            import os
            import json

            http_cache_blob_dir = http_cache_dir + "/cache"

            if not os.path.isdir(http_cache_blob_dir):
                os.makedirs(http_cache_blob_dir)

            cache_index = http_cache_dir + "/__cache.json"
            if os.path.isfile(cache_index):
                try:
                    with open(cache_index, "r", encoding="utf8") as f:
                        http_cache = json.load(f)
                except Exception as err:
                    print("Warning: Failed to load cache index", err)
                    http_cache = {}

        cache_key = self.get_cache_key()
        if cache_key in http_cache and readcache:
            cache_entry = http_cache[cache_key]
            expires = cache_entry["expires"]
            expired = False
            if expires > 0:
                import time

                if time.time() >= expires:
                    expired = True
            if expired:
                del http_cache[cache_key]
                if http_cache_blob_dir and "blob_id" in cache_entry:
                    import os

                    blob_id = cache_entry["blob_id"]
                    os.remove(http_cache_blob_dir + "/" + blob_id)
            else:
                if "content" in cache_entry:
                    content = cache_entry["content"]
                    print("CACHED GET", cache_key)
                    return content
                if http_cache_blob_dir and "blob_id" in cache_entry:
                    blob_id = cache_entry["blob_id"]
                    with open(http_cache_blob_dir + "/" + blob_id, "rb") as f:
                        bytes = f.read()
                        content = bytes.decode("utf8")
                        print("CACHED GET", cache_key)
                        return content

        key = (self.scheme, self.host, self.port)
        s = None
        f = None
        if key in sock_pool:
            (s, f) = sock_pool[key]  # reuse existing socket
        else:
            import socket  # init new TCP/IP connection

            s = socket.socket(
                family=socket.AF_INET,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
            s.connect((self.host, self.port))
            if self.scheme == "https":
                import ssl  # need encryption

                ctx = ssl.create_default_context()
                s = ctx.wrap_socket(s, server_hostname=self.host)
            f = s.makefile("rb", encoding="utf8", newline="\r\n")

        method = "GET"
        reqlines = [
            f"{method} {self.path}{self.search} HTTP/1.1\r\n",
            f"Host: {self.host}\r\n",
            "Connection: keep-alive\r\n",
            "Accept-Encoding: gzip\r\n",
            "\r\n",
        ]
        request = "".join(reqlines)
        bytestosend = request.encode("utf8")
        bytessent = s.send(bytestosend)
        assert bytessent == len(bytestosend)
        response = f

        statusline = response.readline().decode("utf8")
        version, status, explanation = statusline.split(" ", 2)
        print(status, explanation.strip(), "GET", cache_key)
        response_headers = {}
        while True:
            line = response.readline().decode("utf8")
            if line == "\r\n":
                break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()

        chunked = False
        gzip = False
        if "content-encoding" in response_headers:
            content_encoding = response_headers["content-encoding"]
            assert content_encoding == "gzip"  # others not supported
            gzip = True

        if "transfer-encoding" in response_headers:
            transfer_encoding = response_headers["transfer-encoding"]
            if "chunked" in response_headers["transfer-encoding"]:
                chunked = True
            if "gzip" in transfer_encoding:
                gzip = True
            assert "compress" not in transfer_encoding  # not supported
            assert "deflate" not in transfer_encoding  # not supported

        keep_alive = response_headers.get("connection") == "keep-alive"
        # print(response_headers)

        if chunked:
            chunks = []
            is_transfer = True
            while is_transfer:
                chunk_size_str = response.readline().decode("utf8")
                chunk_size = int(chunk_size_str, 16)
                chunk = response.read(chunk_size)
                assert len(chunk) == chunk_size
                response.readline()  # finish reading line
                chunks.append(chunk)
                if chunk_size == 0:
                    is_transfer = False
            bytes = b"".join(chunks)
            content_length = len(bytes)
        elif "content-length" in response_headers:
            content_length_str = response_headers["content-length"]
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

        content = bytes.decode("utf8")
        code = int(status)

        if keep_alive:
            sock_pool[key] = (s, f)
        elif key in sock_pool:
            del sock_pool[key]

        if 300 <= code < 400 and max_redirect > 0:
            location = response_headers.get("location")
            if location:
                url = URL(location, parent=self)
                content = url.request(max_redirect=max_redirect - 1)

        if code == 200 and method == "GET":
            cache_control = response_headers.get("cache-control")
            expires = 0
            store = True
            print("cache_control", cache_control)
            if cache_control is None:
                pass
            elif "no-store" in cache_control:
                store = False
            elif "max-age" in cache_control:
                try:
                    import time

                    now = time.time()
                    _, n = cache_control.split("=", 1)
                    seconds = int(n.strip())
                    expires = now + seconds * 1000
                except Exception as err:
                    print(err)
                    store = False
            else:
                # cache control not handled, better not cache
                store = False

            print("store", store)

            if store:
                cache_entry = {
                    "expires": expires,
                }
                http_cache[cache_key] = cache_entry
                if http_cache_blob_dir:
                    import uuid

                    blob_id = str(uuid.uuid4())
                    blob_path = http_cache_blob_dir + "/" + blob_id
                    cache_entry["blob_id"] = blob_id
                    with open(blob_path, "wb") as f:
                        f.write(bytes)
                    with open(cache_index, "w", encoding="utf8") as f:
                        json.dump(http_cache, f, indent=1)
                else:
                    cache_entry["content"] = content

        return content

    def get_cache_key(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}{self.path}{self.search}"

    def get_str(self) -> str:
        if self.scheme == "file":
            return f"{self.scheme}://{self.path}"

        if self.scheme == "https" and self.port == 443:
            port = ""
        elif self.scheme == "http" and self.port == 80:
            port = ""
        else:
            port = ":" + self.port
        return (
            f"{self.scheme}://{self.host}{port}{self.path}{self.search}{self.fragment}"
        )

    def __str__(self):
        return self.get_str()


class Text:
    def __init__(self, text, parent):
        self.text = text
        self.children = []
        self.parent = parent
        self.style = {}

    def get_text(self):
        return self.text

    def __repr__(self):
        return repr(self.text)


class Element:
    def __init__(self, tag, attributes, parent):
        self.tag = tag
        self.attributes = attributes
        self.children = []
        self.parent = parent
        self.style = {}

    def get_text(self):
        return "".join([c.get_text() for c in self.children])

    def __repr__(self):
        return "<" + self.tag + ">"

    @property
    def head(self):
        return self.get_child("head")

    @property
    def body(self):
        return self.get_child("body")

    @property
    def isvisited(self):
        if hasattr(self, "_visited"):
            return self._visited is True
        return False

    @property
    def href(self):
        if hasattr(self, "_href"):
            return self._href
        return None

    def get_child(self, tag):
        for node in self.children:
            if node.tag == tag:
                return node


def tree_to_list(tree, list):
    list.append(tree)
    for child in tree.children:
        tree_to_list(child, list)
    return list


def eval_visited(node, baseurl, visited_set):
    href = eval_href(node, baseurl)
    if not href:
        return False
    visited = href in visited_set
    node._visited = visited
    return visited


def eval_href(node, baseurl):
    href = None
    if isinstance(node, Element):
        hrefstr = node.attributes.get("href")
        if hrefstr:
            href = URL(hrefstr, parent=baseurl).get_str()
        node._href = href
    return href


def print_tree(node, indent=0):
    print(" " * indent, node)
    for child in node.children:
        print_tree(child, indent + 2)


class JsonFileState:
    def __init__(self, path):
        self.path = path
        self.data = None  # initially not laoded

    def load(self):
        import json
        import os

        if os.path.isfile(self.path):
            with open(self.path, "r", encoding="utf8") as f:
                self.data = json.load(f)
                return True

        return False

    def save(self):
        import json

        with open(self.path, "w", encoding="utf8") as f:
            json.dump(self.data, f, indent=1)


class BrowserState:
    def __init__(self, profile_dir):
        self.file = (
            JsonFileState(profile_dir + "/__state.json") if profile_dir else None
        )
        self.data = {"tabs": []}
        self.dirty = False

    def restore(self):
        if self.file:
            if self.file.load():
                self.data = self.file.data

    def save(self):
        if self.file and self.dirty:
            self.file.data = self.data
            self.file.save()
            self.dirty = False

    def set_title(self, str):
        str = str.strip()
        if self.get_title() != str:
            item = self._get_current_item()
            item["title"] = str
            if not str:
                item.pop("title")
            self.dirty = True

    def get_title(self):
        index = self.get_active_tab_index()
        return self.get_title_by_index(index)

    def get_title_by_index(self, index):
        tab = self.data.get("tabs", [])
        if not tab:
            return ""
        item = self.data["tabs"][index]
        result = item.get("title")
        if not result:
            result = f"Tab {self.get_active_tab_index() + 1}"
        return result.strip()

    def get_url(self) -> str:
        item = self._get_current_item()
        return item.get("url", "")

    def get_scroll(self) -> int:
        item = self._get_current_item()
        return item.get("scroll")

    def get_history(self) -> dict:
        item = self._get_current_item()
        return item.get("history", None)

    def newtab(self, url: str):
        tabs = self.data.get("tabs", [])
        tabs.append({"url": url})
        self.data["active_tab_index"] = len(tabs) - 1
        self.data["tabs"] = tabs
        self.dirty = True

    def closetab(self):
        self.closetabindex(self.get_active_tab_index())

    def closetabindex(self, index):
        tabs = [v for (k, v) in enumerate(self.data.get("tabs", [])) if k != index]
        active = self.data.get("active_tab_index", 0)
        active = active - 1 if index <= active else active
        if tabs != self.data.get("tabs", []):
            self.data["tabs"] = tabs
            self.data["active_tab_index"] = active
            self.dirty = True

    def pushlocation(self, url):
        item = self._get_current_item()
        to_return_to = self._create_return_item()
        history_list = item.get("history", [])
        history_list.append(to_return_to)
        item["history"] = history_list
        if "future" in item:
            item.pop("future")
        self.replacelocation(url)
        self.dirty = True

    def replacelocation(self, url):
        item = self._get_current_item()
        if item.get("url", "") != url:
            item["url"] = url
            if "scroll" in item:
                item.pop("scroll")
            self.dirty = True

    def can_back(self):
        return self._get_current_item().get("history")

    def back(self):
        item = self._get_current_item()
        history = item.get("history")
        if history:
            to_return_to = self._create_return_item()
            future_list = item.get("future", [])
            future_list.append(to_return_to)
            item["future"] = future_list
            to_restore = history.pop()
            self._copy_item_locaiton_state(src=to_restore, dst=item)
            self.dirty = True

    def can_forward(self):
        return self._get_current_item().get("future")

    def forward(self):
        item = self._get_current_item()
        future = item.get("future")
        if future:
            to_return_to = self._create_return_item()
            list = item.get("history", [])
            list.append(to_return_to)
            item["history"] = list
            to_restore = future.pop()
            self._copy_item_locaiton_state(src=to_restore, dst=item)
            self.dirty = True

    def set_scroll(self, pos: int):
        item = self._get_current_item()
        if item.get("scroll") != pos:
            item["scroll"] = pos
            if pos is None:
                item.pop("scroll")
            self.dirty = True

    def set_window_size(self, w: int, h: int):
        self.data["width"] = w
        self.data["height"] = h
        self.dirty = True

    def get_window_size(self):
        return self.data.get("width", 800), self.data.get("height", 600)

    def get_tab_count(self):
        return len(self.data.get("tabs", []))

    def get_active_tab_index(self):
        return self.data.get("active_tab_index", 0)

    def set_active_tab_index(self, index):
        if self.get_active_tab_index() != index:
            self.data["active_tab_index"] = index
            self.dirty = True
            if index == 0:
                self.data.pop("active_tab_index")

    def switchtab(self, index, relative=False):
        tab_count = self.get_tab_count()
        if relative:
            index += self.get_active_tab_index()
            if index < 0:
                index = tab_count - 1
            if index >= tab_count:
                index = 0
        if index >= tab_count:
            index = tab_count - 1
        if index < 0:
            index = 0
        self.set_active_tab_index(index)

    def _get_current_item(self):
        if "tabs" in self.data:
            idx = self.get_active_tab_index()
            return self.data["tabs"][idx]
        else:
            return self.data

    def _create_return_item(self):
        url = self.get_url()
        if not url:
            return None
        backitem = {"url": url}
        scroll = self.get_scroll()
        if scroll:
            backitem["scroll"] = scroll
        return backitem

    def _copy_item_locaiton_state(self, src, dst):
        dst["url"] = src.get("url", "")
        dst["scroll"] = src.get("scroll", 0)
        if dst["scroll"] == 0:
            dst.pop("scroll")
        if dst["url"] == "":
            dst.pop("url")


class BrowserHistory:
    def __init__(self, profile_dir):
        self.file = (
            JsonFileState(profile_dir + "/__history.json") if profile_dir else None
        )
        self.data = {"history": []}
        self._urlindex = {}
        self.dirty = False
        self.needreindex = False

    def restore(self):
        if self.file:
            if self.file.load():
                self.data = self.file.data
                self.dirty = False
                self.needreindex = True

    def save(self):
        if self.file and self.dirty:
            self.file.data = self.data
            self.file.save()
            self.dirty = False

    def visited(self, urlstr):
        import time

        self.data["history"].append({"url": urlstr, "time": time.time()})
        self.needreindex = True
        self.dirty = True

    def is_visited(self, urlstr) -> bool:
        if self.needreindex:
            self.reindex()
        return urlstr in self._urlindex

    def reindex(self):
        self._urlindex = {}
        for item in self.data["history"]:
            url = item.get("url", "")
            self._urlindex[url] = item

    def get_visited_set(self):
        if self.needreindex:
            self.reindex()
        return self._urlindex


class BrowserBookmarks:
    def __init__(self, profile_dir):
        self.file = (
            JsonFileState(profile_dir + "/__bookmarks.json") if profile_dir else None
        )
        self.data = {"bookmarks": {}}
        self.dirty = False

    def restore(self):
        if self.file:
            if self.file.load():
                self.data = self.file.data
                self.dirty = False

    def save(self):
        if self.file and self.dirty:
            self.file.data = self.data
            self.file.save()
            self.dirty = False


    def get_count(self) -> int:
        return len(self.data["bookmarks"])

    def toggle(self, url: str, title: str):
        item = self._get_item(url)
        if not item:
            item = self._create_new_item(url, title)
            self.data["bookmarks"][url] = item
        else:
            self._remove_item(url)
        self.dirty = True

    def contains(self, url: str):
        return url in self.data["bookmarks"]

    def get_urls(self):
        return list(self.data["bookmarks"].keys())

    def _get_item(self, url: str):
        return self.data["bookmarks"].get(url)

    def _create_new_item(self, url: str, title:str):
        return {"url": url, "title": title}

    def _remove_item(self, url: str):
        if self.contains(url):
            self.data["bookmarks"].pop(url)
            self.dirty = True


class CLI:
    def browse(self, urlstr, max_redirect=5):
        print("navigating to", urlstr)
        url = URL(urlstr)
        result = url.request(max_redirect=max_redirect)
        if url.viewsource:
            print(result)
        else:
            print(HTMLParser(result).parse().get_text())


class GUIBrowser:
    def __init__(self):
        self.window = None
        self.canvas = None
        self.chrome = None
        self.active_tab = None
        pass

    def start(self, state, history, bookmarks):
        self.state: BrowserState = state
        self.history: BrowserHistory = history
        self.bookmarks: BrowserBookmarks = bookmarks

        import tkinter

        WIDTH, HEIGHT = state.get_window_size()
        HSTEP, VSTEP = 12, 18

        self.width = WIDTH
        self.height = HEIGHT
        self.vstep = VSTEP
        self.hstep = HSTEP

        self.window = tkinter.Tk()
        w = self.window
        w.bind("<Up>", lambda e: self.scrollposupdate(-100))
        w.bind("<Down>", lambda e: self.scrollposupdate(+100))
        w.bind("<MouseWheel>", lambda e: self.scrollposupdate(-e.delta))
        w.bind("<Button-1>", lambda e: self.click(e, 1))
        w.bind("<Button-2>", lambda e: self.click(e, 2))
        w.bind("<Button-3>", lambda e: self.click(e, 3))
        w.bind("<Button-4>", lambda e: self.scrollposupdate(-100))
        w.bind("<Button-5>", lambda e: self.scrollposupdate(+100))
        w.bind("<Prior>", lambda e: self.scrollposupdate(-self.height + 96))
        w.bind("<Next>", lambda e: self.scrollposupdate(+self.height - 96))
        w.bind("<Home>", lambda e: self.scrollposupdate(-1000_000_000))
        w.bind("<End>", lambda e: self.scrollposupdate(+1000_000_000))
        w.bind("<Alt-Left>", self.navigateback)
        w.bind("<Alt-Right>", self.navigateforward)
        w.bind("<BackSpace>", self.pressbackspace)
        w.bind("<Shift-BackSpace>", self.navigateforward)
        w.bind("<F5>", self.locationreload)
        w.bind("<Configure>", self.configure)
        w.bind("<Control-Tab>", lambda e: self.switchtab(+1, relative=True))
        w.bind("<Control-Shift-Tab>", lambda e: self.switchtab(-1, relative=True))
        w.bind(
            "<Control-Shift-KeyPress-Tab>",
            lambda e: self.switchtab(-1, relative=True),
        )
        w.bind("<Control-ISO_Left_Tab>", lambda e: self.switchtab(-1, relative=True))
        w.bind("<Control-Key-1>", lambda e: self.switchtab(0))
        w.bind("<Control-Key-2>", lambda e: self.switchtab(1))
        w.bind("<Control-Key-3>", lambda e: self.switchtab(2))
        w.bind("<Control-Key-4>", lambda e: self.switchtab(3))
        w.bind("<Control-Key-5>", lambda e: self.switchtab(4))
        w.bind("<Control-1>", lambda e: self.switchtab(0))
        w.bind("<Control-2>", lambda e: self.switchtab(1))
        w.bind("<Control-3>", lambda e: self.switchtab(2))
        w.bind("<Control-4>", lambda e: self.switchtab(3))
        w.bind("<Control-5>", lambda e: self.switchtab(4))
        w.bind("<Control-6>", lambda e: self.switchtab(5))
        w.bind("<Control-7>", lambda e: self.switchtab(6))
        w.bind("<Control-8>", lambda e: self.switchtab(7))
        w.bind("<Control-9>", lambda e: self.switchtab(-1))
        w.bind("<Control-v>", self.handlepaste)
        w.bind("<Control-t>", self.newtab)
        w.bind("<Control-F4>", self.closetab)
        w.bind("<Control-u>", self.viewsource)
        w.bind("<Key>", self.handlekey)
        w.bind("<Return>", self.pressenter)
        self.canvas = tkinter.Canvas(w, width=WIDTH, height=HEIGHT, bg="white")
        self.chrome = GUIChrome(self)
        self.restorestate()
        tkinter.mainloop()

    def scrollposupdate(self, amount=100):
        self.active_tab.scrollposupdate(amount)
        self.draw()

    def pressbackspace(self, e):
        if self.chrome.pressbackspace():
            self.draw()
        else:
            self.state.back()
            self.restorestate()

    def handlepaste(self, e):
        content = self.window.clipboard_get()
        self.chrome.input(content)
        self.draw()

    def handlekey(self, e):
        if len(e.char) == 0:
            return
        if not (0x20 <= ord(e.char) < 0x7F):
            return
        self.chrome.input(e.char)
        self.draw()

    def pressenter(self, e):
        self.chrome.enter()
        if self.state.dirty:
            self.state.save()
            self.restorestate()
        self.draw()

    def navigateback(self, e):
        self.state.back()
        self.restorestate()

    def navigateforward(self, e):
        self.state.forward()
        self.restorestate()

    def locationreload(self, e):
        self.restorestate(readcache=False)

    def restorestate(self, readcache=True):
        if not self.active_tab:
            self.active_tab = GUIBrowserTab(self)
            self.resize_active_tab()
        self.active_tab.restorestate(readcache)
        self.draw()
        url = self.state.get_url()
        self.history.visited(url)
        self.history.save()

    def click(self, e, button):
        x, y = e.x, e.y
        if e.y < self.chrome.bottom:
            self.chrome.click(x, y, button)
        else:
            self.active_tab.click(x, y - self.chrome.bottom, button)
        if self.state.dirty:
            self.state.save()
            self.restorestate()
        self.draw()

    def configure(self, e):
        if self.width == e.width and self.height == e.height:
            return
        self.width = e.width
        self.height = e.height
        self.resize_active_tab()
        self.draw()
        self.state.set_window_size(self.width, self.height)
        self.state.save()

    def resize_active_tab(self):
        tab = self.active_tab
        width = self.width
        tab.top = self.chrome.bottom + 2
        height = self.height - tab.top
        tab.hstep = self.hstep
        tab.vstep = self.vstep
        tab.resize(width, height)

    def draw(self):
        import tkinter

        # print(tkinter.font.families())
        self.canvas.delete("all")
        self.active_tab.draw(self.canvas)

        for cmd in self.chrome.paint():
            cmd.execute(0, self.canvas)

        self.canvas.pack(fill=tkinter.BOTH, expand=1)
        self.state.save()

    def switchtab(self, index=0, relative=False):
        self.state.switchtab(index, relative)
        self.restorestate()
        self.state.save()

    def newtab(self, e):
        self.state.newtab("about:blank")
        self.chrome.focusaddressbar()
        self.restorestate()
        self.state.save()

    def closetab(self, e):
        self.state.closetab()
        self.restorestate()

    def viewsource(self, e):
        url = self.state.get_url()
        if not url.startswith("view-source:"):
            self.state.newtab("view-source:" + url)
            self.restorestate()
            self.state.save()

    def title(self, str):
        self.window.title(f"{str} \u2014 Gal")

    def toggle_bookmark(self):
        url = self.state.get_url()
        title = self.state.get_title()
        self.bookmarks.toggle(url, title)
        self.bookmarks.save()


class GUIChrome:
    def __init__(self, browser: GUIBrowser):
        self.browser = browser
        self.font = get_font("", 12, "normal", "roman")
        self.font_height = self.font.metrics("linespace")
        # base layout
        self.width = browser.width
        self.padding = 5
        self.tabwidth = 150
        self.tabbar_top = 0
        self.tabbar_bottom = self.font_height + 2 * self.padding
        self.bottom = self.tabbar_bottom + self.font_height + self.padding
        # buttons
        plus_width = self.font.measure("+") + 2 * self.padding
        self.newtab_rect = Rect(
            self.padding,
            self.padding,
            self.padding + plus_width,
            self.padding + self.font_height,
        )
        # urlbar
        self.urlbar_top = self.tabbar_bottom
        self.urlbar_bottom = self.urlbar_top + self.font_height + 2 * self.padding
        self.bottom = self.urlbar_bottom

        back_width = self.font.measure("<") + 2 * self.padding
        self.back_rect = Rect(
            self.padding,
            self.urlbar_top + self.padding,
            self.padding + back_width,
            self.urlbar_bottom - self.padding,
        )

        self.forward_rect = Rect(
            self.back_rect.right + self.padding,
            self.urlbar_top + self.padding,
            self.back_rect.right + self.padding + back_width,
            self.urlbar_bottom - self.padding,
        )

        self.reload_rect = Rect(
            self.forward_rect.right + self.padding,
            self.urlbar_top + self.padding,
            self.forward_rect.right + self.padding + back_width,
            self.urlbar_bottom - self.padding,
        )

        self.bookmark_rect = Rect(
            self.reload_rect.right + self.padding,
            self.urlbar_top + self.padding,
            self.reload_rect.right + self.padding + back_width,
            self.urlbar_bottom - self.padding,
        )

        self.address_rect = Rect(
            self.bookmark_rect.right + self.padding,
            self.urlbar_top + self.padding,
            self.width - self.padding,
            self.urlbar_bottom - self.padding,
        )
        self.address_txt_rect = Rect(
            self.address_rect.left + self.padding,
            self.address_rect.top,
            self.address_rect.right,
            self.address_rect.bottom,
        )
        self.focus = None
        self.address_bar = ""

    def click(self, x, y, button):
        state: BrowserState = self.browser.state
        self.focus = None
        if self.newtab_rect.contains_point(x, y):
            state.newtab("about:empty")
        elif self.back_rect.contains_point(x, y):
            state.back()
        elif self.forward_rect.contains_point(x, y):
            state.forward()
        elif self.reload_rect.contains_point(x, y):
            self.browser.restorestate(readcache=False)
        elif self.bookmark_rect.contains_point(x, y):
            self.browser.toggle_bookmark()
        elif self.address_rect.contains_point(x, y):
            self.focusaddressbar()
        else:
            for i in range(state.get_tab_count()):
                bounds = self.tab_rect(i)
                if bounds.contains_point(x, y):
                    if button == 1 or button == 3:
                        state.switchtab(i)
                    elif button == 2:
                        state.closetabindex(i)
                    break

    def focusaddressbar(self):
        self.focus = "address bar"
        self.address_bar = ""

    def input(self, char):
        if self.focus == "address bar":
            self.address_bar += char

    def enter(self):
        if self.focus == "address bar":
            state = self.browser.state
            location = self.address_bar
            if "/" not in location:
                location = default_search_engine + location
            state.pushlocation(location)
            self.focus = None

    def pressbackspace(self):
        if self.focus == "address bar":
            self.address_bar = self.address_bar[:-1]
            return True
        return False

    def paint(self):
        width = self.browser.width
        state = self.browser.state
        cmds = []

        cmds.append(DrawRect(Rect(0, 0, width, self.bottom), "white"))
        cmds.append(DrawLine(0, self.bottom, width, self.bottom, "black", 1))
        self._paint_button(cmds, self.newtab_rect, "+")

        active_tab_index = state.get_active_tab_index()
        for i in range(state.get_tab_count()):
            bounds = self.tab_rect(i)
            cmds.append(
                DrawLine(bounds.left, 0, bounds.left, bounds.bottom, "black", 1)
            )
            cmds.append(
                DrawLine(bounds.right, 0, bounds.right, bounds.bottom, "black", 1)
            )

            if i == active_tab_index:
                cmds.append(
                    DrawLine(0, bounds.bottom, bounds.left, bounds.bottom, "black", 1)
                )
                cmds.append(
                    DrawLine(
                        bounds.right, bounds.bottom, width, bounds.bottom, "black", 1
                    )
                )

            str = state.get_title_by_index(i)
            substr = ""
            for i in range(len(str) + 1):
                checkstr = str[0:i]
                if len(checkstr) < len(str):
                    checkstr += "..."
                if self.font.measure(checkstr) < self.tabwidth:
                    substr = checkstr
                else:
                    break
            textbound = Rect(
                bounds.left + self.padding,
                bounds.top + self.padding,
                bounds.right - self.padding,
                bounds.bottom - self.padding,
            )
            cmds.append(DrawText(textbound, substr, self.font, "black"))
            # cmds.append(DrawText(bounds, "Tab {}".format(i), self.font, "black"))

        # address bar buttons
        back_color = "black" if state.can_back() else "gray"
        forward_color = "black" if state.can_forward() else "gray"
        self._paint_button(cmds, self.back_rect, "<", color=back_color)
        self._paint_button(cmds, self.forward_rect, ">", color=forward_color)
        self._paint_button(cmds, self.reload_rect, "\u21ba", color=forward_color)
        bookmark_icon = "\u2605" if self.browser.bookmarks.contains(self.browser.state.get_url()) else "\u2606"
        self._paint_button(cmds, self.bookmark_rect, bookmark_icon, color=forward_color)

        # address bar input
        cmds.append(DrawOutline(self.address_rect, "black", 1))
        if self.focus == "address bar":
            cmds.append(
                DrawText(self.address_txt_rect, self.address_bar, self.font, "black")
            )
            w = self.font.measure(self.address_bar)
            cmds.append(
                DrawLine(
                    self.address_rect.left + self.padding + w,
                    self.address_rect.top,
                    self.address_rect.left + self.padding + w,
                    self.address_rect.bottom,
                    "red",
                    1,
                )
            )
        else:
            url = state.get_url()
            cmds.append(DrawText(self.address_txt_rect, url, self.font, "black"))

        return cmds

    def tab_rect(self, i):
        tabs_start = self.newtab_rect.right + self.padding
        tab_width = self.tabwidth + 2 * self.padding
        return Rect(
            tabs_start + tab_width * i,
            self.tabbar_top,
            tabs_start + tab_width * (i + 1),
            self.tabbar_bottom,
        )

    def _layout_button_text(self, outline_rect, txt, vpad=0):
        size = self.font.measure(txt)
        x = (outline_rect.left + outline_rect.right - size) // 2
        return Rect(x, outline_rect.top + vpad, x + size, outline_rect.bottom - vpad)

    def _paint_button(self, cmds, outline_rect, txt, vpad=0, color="black"):
        r = self._layout_button_text(outline_rect, txt, vpad)
        cmds.append(DrawOutline(outline_rect, color, 1))
        cmds.append(DrawText(r, txt, self.font, color))


class GUIBrowserTab:
    def __init__(self, browser):
        self.window = None
        self.canvas = None
        self.browser = browser
        self.state: BrowserState = browser.state
        self.scroll = 0
        self.width = 0
        self.height = 0
        self.nodes = None

    def browse(self, url):
        self.state.browse(url)
        self.start(self.state)

    def restorestate(self, readcache):
        self.scroll = self.state.get_scroll() or 0
        self.load(self.state.get_url(), readcache)

    def load(self, urlstr, readcache):
        global default_style_sheet

        if urlstr == "" or urlstr.isspace():
            urlstr = "about:blank"

        if default_style_sheet is None:
            with open("browser.css") as f:
                text = f.read()
                default_style_sheet = CSSParser(text).parse()

        self.title(urlstr)
        try:
            url = URL(urlstr)
        except Exception as err:
            import traceback

            print("Error: failed to parse URL", err)
            print(traceback.format_exc())
            url = URL("about:blank")

        result = url.request(max_redirect=5, readcache=readcache)

        parser_class = HTMLParser if not url.viewsource else HTMLSourceParser

        self.nodes = parser_class(result).parse()

        # resolve CSS
        rules = default_style_sheet.copy()
        nodelist = tree_to_list(self.nodes, [])
        for node in nodelist:
            if isinstance(node, Element):
                eval_visited(node, url, self.browser.history.get_visited_set())
                if node.tag == "link":
                    if (
                        node.attributes.get("rel") == "stylesheet"
                        and "href" in node.attributes
                    ):
                        link = node.attributes["href"]
                        style_url = URL(link, parent=url)
                        try:
                            body = style_url.request()
                        except Exception:
                            continue
                        rules.extend(CSSParser(body).parse())
                elif node.tag == "style":
                    rules.extend(CSSParser(node.get_text()).parse())
                elif node.tag == "title":
                    self.title(node.get_text())

        style(self.nodes, sorted(rules, key=cascade_priority))
        # print_tree(self.nodes)

        self.layout()
        # print_tree(self.document)

        if hasattr(url, "fragment") and len(url.fragment) > 1:
            target_id = url.fragment[1:]
            layoutlist = tree_to_list(self.document, [])
            for item in layoutlist:
                if isinstance(item.node, Element):
                    if item.node.attributes.get("id") == target_id:
                        self.scroll = item.y
                        self.limitscrollinbounds()
                        break

    def draw(self, canvas):
        for cmd in self.display_list:
            if cmd.rect.top > self.scroll + self.height:
                continue
            if cmd.rect.bottom < self.scroll:
                continue
            cmd.execute(self.scroll - self.top, canvas)

        # scrollbar
        if self.scroll_bottom > self.height:
            pos_0 = self.scroll / self.scroll_bottom
            pos_1 = (self.scroll + self.height) / self.scroll_bottom
            canvas.create_rectangle(
                self.width - 8,
                self.top + self.height * pos_0,
                self.width,
                self.top + self.height * pos_1,
                fill="#000",
            )

    def scrollposupdate(self, amount=100):
        self.scroll += amount
        self.limitscrollinbounds()
        self.state.set_scroll(self.scroll)
        self.state.save()

    def limitscrollinbounds(self):
        if self.scroll + self.height > self.scroll_bottom:
            self.scroll = self.scroll_bottom - self.height
        if self.scroll < 0:
            self.scroll = 0

    def click(self, x, y, button):
        y += self.scroll

        objs = [
            obj
            for obj in tree_to_list(self.document, [])
            if obj.x <= x < obj.x + obj.width and obj.y <= y < obj.y + obj.height
        ]

        if not objs:
            return
        elt = objs[-1].node

        while elt:
            if isinstance(elt, Text):
                pass
            elif elt.tag == "a" and "href" in elt.attributes:
                parent = URL(self.state.get_url())
                url = URL(elt.attributes["href"], parent=parent).get_str()
                if button == 1:
                    state.pushlocation(url)
                elif button == 2:
                    state.newtab(url)
                else:
                    pass
            elt = elt.parent

    def resize(self, width, height):
        if self.width == width and self.height == height:
            return
        self.width = width
        self.height = height
        if self.nodes:
            self.layout()
            self.limitscrollinbounds()

    def layout(self):
        self.document = DocumentLayout(self.nodes)
        self.document.set_size(self.width, self.height)
        self.document.set_step(self.hstep, self.vstep)
        self.document.layout()
        self.display_list = []
        paint_tree(self.document, self.display_list)
        self.scroll_bottom = self.document.height

    def title(self, str):
        state.set_title(str)
        self.browser.title(str)


class DocumentLayout:
    def __init__(self, node):
        self.node = node
        self.parent = None
        self.children = []
        self.x = None
        self.y = None
        self.width = None
        self.height = None

    def layout(self):
        self.width = self.width - self.hstep * 2
        self.x = self.hstep
        self.y = self.vstep
        child = BlockLayout(self.node, self, None)
        child.set_size(self.width, self.height)
        child.set_step(self.hstep, self.vstep)
        self.children.append(child)
        child.layout()
        self.height = child.height

    def set_size(self, w, h):
        self.width = w
        self.height = h

    def set_step(self, h, v):
        self.hstep = h
        self.vstep = v

    def paint(self):
        return []

    def __repr__(self):
        return f"Document {self.node} {self.x} {self.y} {self.width} {self.height}"


class BlockLayout:
    def __init__(self, node, parent, previous):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children = []
        self.x = None
        self.y = None
        self.width = None
        self.height = None

    def set_size(self, w, h):
        self.width = w
        self.height = h

    def set_step(self, h, v):
        self.hstep = h
        self.vstep = v

    def self_rect(self):
        return Rect(self.x, self.y, self.x + self.width, self.y + self.height)

    def paint(self):
        cmds = []

        if isinstance(self.node, Element):
            bgcolor = self.node.style.get("background-color", "transparent")

            if bgcolor != "transparent":
                rect = DrawRect(self.self_rect(), bgcolor)
                cmds.append(rect)

            if self.node.tag == "li":
                x = self.x - 8
                y = self.y + 14
                rect = Rect(x - 2, y - 2, x + 2, y + 2)
                cmd = DrawRect(rect, "#000")
                cmds.append(cmd)

        return cmds

    def layout(self):
        # calculate start of block
        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y
        self.x = self.parent.x

        # todo move this to browser.css
        if isinstance(self.node, Element):
            if self.node.tag in ["ul", "ol"]:
                self.x += 48

        self.width = self.parent.width
        self.weight = "normal"  # bold|normal
        self.style = "roman"  # roman|italic
        self.align = "auto"  # auto|center
        self.vert_align = "baseline"
        self.upper = "normal"
        self.size = 12
        self.lineheight = 16
        self.cursor_x = 0
        self.cursor_y = 0

        # determine display mode for this block
        if isinstance(self.node, Element):
            mode = self.node.style.get("display", "inline")
        elif isinstance(self.node, Text):
            mode = "inline"
        elif isinstance(self.node, list):
            mode = "inline"
        else:
            raise Exception("unreachable layout mode!!")

        if mode == "none":
            self.width = 0
            self.height = 0

        elif mode == "block":
            previous = None

            # group text-like nodes
            groups = []
            group = []
            run_in_next = False
            run_in = False
            for child in self.node.children:
                child_display = child.style.get("display")

                if child_display == "none":
                    continue

                if isinstance(child, Element) and child.tag == "h6":
                    run_in = True

                if (
                    isinstance(child, Element)
                    and child_display == "block"
                    and not run_in
                    and not run_in_next
                ):
                    if group:
                        groups.append(group)
                        group = []
                    groups.append(child)
                else:
                    group.append(child)

                run_in_next = run_in
                run_in = False
            if group:
                groups.append(group)
                group = []

            for group in groups:
                child = group
                if isinstance(child, Element):
                    if child.tag == "nav" and child.attributes.get("id") == "toc":
                        # insert table of contest title
                        element = Element("pre", {}, self.node)
                        element.children.append(Text("Table of Contents", element))
                        next = BlockLayout(element, self, previous)
                        self.children.append(next)
                        previous = next

                next = BlockLayout(group, self, previous)
                self.children.append(next)
                previous = next

            # recursive block layout
            for child in self.children:
                child.set_size(self.width, self.height)
                child.set_step(self.hstep, self.vstep)
                child.layout()
            self.height = sum([child.height for child in self.children])

        elif mode == "inline":
            self.newline()
            self.cursor_x = 0
            self.cursor_y = 0
            self.weight = "normal"
            self.style = "roman"
            self.size = 12
            self.line = []
            if isinstance(self.node, list):
                for item in self.node:
                    self.recurse(item)
            else:
                self.recurse(self.node)

            # TODO new branch
            for child in self.children:
                child.layout()
            self.height = sum([child.height for child in self.children])

    def open_tag(self, tag):
        if tag == "br/":
            self.newline()
        elif tag == "p" or tag.startswith("p "):
            pass
            self.cursor_y += self.vstep
        elif tag == "sup":
            self.size = 8
            self.vert_align = "top"
        elif tag == "abbr":
            self.upper = "all"
            self.size = 10
            self.weight = "bold"

    def close_tag(self, tag):
        if tag == "p":
            self.newline()
            self.cursor_y += self.vstep
        elif tag == "h1":
            self.newline()
            self.cursor_y += self.vstep
        elif tag == "h2":
            self.newline()
            self.cursor_y += self.vstep
        elif tag == "sup":
            self.size = 12
            self.vert_align = "baseline"
        elif tag == "abbr":
            self.upper = "normal"
            self.size = 12
            self.weight = "normal"

    def recurse(self, tree):
        if isinstance(tree, Text):
            self.word(tree)
        else:
            self.open_tag(tree.tag)
            for child in tree.children:
                self.recurse(child)
            self.close_tag(tree.tag)

    def word(self, node: Text):
        # TODO remove duplicate, this should be part of TextLayout

        # parse font style
        style = node.style.get("font-style", "normal")
        if style == "inherit":
            style = "roman"  # todo actually inherit
        elif style == "oblique" or style == "italic":
            style = "italic"  # tk inter only supports
        else:
            style = "roman"  # normal style and default to roman

        # parse font size
        size_str = node.style.get("font-size", "16px")
        if size_str == "inherit":
            size = int(16 * 0.75)
        else:
            try:
                size = int(float(size_str[:-2]) * 0.75)
            except Exception as e:
                print("Failed to parse size", size_str, e)
                size = int(16 * 0.75)

        font_family = node.style.get("font-family")

        # parse font weight
        weight = "normal"
        font_weight = node.style.get("font-weight", "normal")
        if font_weight.isnumeric():
            if int(font_weight) >= 500:
                weight = "bold"
        elif font_weight == "bold":
            weight = "bold"

        font = get_font(font_family, size, weight, style)
        color = node.style.get("color", "black")
        space_width = font.measure(" ")

        # line = self.children[-1]
        # previous_word = line.children[-1] if line.children else None
        # text = TextLayout(node, word, line, previous_word)
        # line.children.append(text)
        whitespace = node.style.get("white-space")

        if whitespace == "pre":
            isnewline = False
            for line in node.text.split(
                "\n",
            ):
                if isnewline:
                    self.newline()
                w = font.measure(line)
                self.append_to_current_line(
                    self.cursor_x, line, font, self.vert_align, node
                )
                self.cursor_x += w
                isnewline = True
            return

        for word in node.text.split():
            if self.upper == "all":
                word = word.upper()
            txt = word
            if "\N{SOFT HYPHEN}" in txt:
                txt = "".join(word.split("\N{SOFT HYPHEN}"))
            w = font.measure(txt)
            if self.cursor_x + w > self.width:
                if self.tryhypenate(font, word, node):
                    continue
                else:
                    self.newline()
            self.append_to_current_line(self.cursor_x, txt, font, self.vert_align, node)
            self.cursor_x += w + space_width

    def append_to_current_line(self, x, txt, font, vert_align, node):
        line = self.children[-1]
        previous = line.children[-1] if line.children else None
        text = TextLayout(node, txt, line, previous, x, font, vert_align)
        line.children.append(text)

    def newline(self):
        self.cursor_x = 0
        last_line = self.children[-1] if self.children else None
        new_line = LineLayout(self.node, self, last_line)
        self.children.append(new_line)

    def tryhypenate(self, font, txt, node):
        if "\N{SOFT HYPHEN}" in txt:
            isnewline = False
            space_width = font.measure(" ")
            parts = txt.split("\N{SOFT HYPHEN}")
            while parts:
                failed = True
                for i in range(0, len(parts)):
                    partsrange = parts[0 : len(parts) - i]
                    rangetxt = "".join(partsrange)
                    if len(partsrange) != len(parts):
                        rangetxt += "-"
                    w = font.measure(rangetxt)
                    if self.cursor_x + w > self.width - self.hstep:
                        continue
                    failed = False
                    isnewline = False
                    self.append_to_current_line(
                        self.cursor_x, rangetxt, font, self.vert_align, node
                    )
                    self.cursor_x += w
                    parts = parts[len(parts) - i :]
                    break
                if failed:
                    if isnewline:
                        # must put at least one fragment to avoid infinite loop
                        rangetxt = parts[0] + "-"
                        self.append_to_current_line(
                            self.cursor_x, rangetxt, font, self.vert_align, node
                        )
                    self.newline()  # continue hypenation on next line
            self.cursor_x += space_width
            return True

        return False

    def __repr__(self):
        return f"Block {self.node} {self.x},{self.y} {self.width},{self.height}"


class LineLayout:
    def __init__(self, node, parent, previous):
        self.node = node
        self.parent = parent
        self.previous = previous
        self.children = []

    def layout(self):
        self.width = self.parent.width  # lines stack vertically
        self.x = self.parent.x
        if self.previous:
            self.y = self.previous.y + self.previous.height
        else:
            self.y = self.parent.y

        for word in self.children:
            word.layout()

        max_ascent = 0
        max_descent = 0
        if self.children:
            max_ascent = max([word.font.metrics("ascent") for word in self.children])
            baseline = self.y + 1.25 * max_ascent
            for word in self.children:
                word.y = baseline - word.font.metrics("ascent")
            max_descent = max([word.font.metrics("descent") for word in self.children])

        self.height = 1.25 * (max_ascent + max_descent)

    # def flush(self, forceline=False):
    # if not self.line:
    #     if forceline:
    #         self.cursor_y += self.lineheight
    #     return
    # scaler = 1.25
    # metrics = [font.metrics() for x, word, font, vert, color in self.line]
    # max_ascent = max([metric["ascent"] for metric in metrics])
    # baseline = self.cursor_y + scaler * max_ascent

    # if self.align == "center":
    #     horiz_align = (self.width - self.cursor_x) // 2
    # elif self.align == "right":
    #     horiz_align = self.width - self.cursor_x
    # else:
    #     horiz_align = 0

    # for x, word, font, valign, color in self.line:
    #     if valign == "top":
    #         y = baseline - scaler * max_ascent
    #     else:
    #         y = baseline - font.metrics("ascent")
    #     self.display_list.append(
    #         (x + horiz_align + self.x, y + self.y, word, font, color)
    #     )

    # max_descent = max([metric["descent"] for metric in metrics])
    # self.cursor_y = baseline + scaler * max_descent
    # self.lineheight = (max_descent + max_ascent) * scaler

    # self.cursor_x = 0
    # self.line = []

    def paint(self):
        return []

    def __repr__(self):
        return f"Line {self.x},{self.y} {self.width},{self.height}"


class TextLayout:
    def __init__(self, node, word, parent, previous, x, font, vert_align):
        self.node = node
        self.word = word
        self.children = []
        self.parent = parent
        self.previous = previous

    def layout(self):
        node = self.node

        # parse font style
        style = node.style.get("font-style", "normal")
        if style == "inherit":
            style = "roman"  # todo actually inherit
        elif style == "oblique" or style == "italic":
            style = "italic"  # tk inter only supports
        else:
            style = "roman"  # normal style and default to roman

        # parse font size
        size_str = node.style.get("font-size", "16px")
        if size_str == "inherit":
            size = int(16 * 0.75)
        else:
            try:
                size = int(float(size_str[:-2]) * 0.75)
            except Exception as e:
                print("Failed to parse size", size_str, e)
                size = int(16 * 0.75)

        font_family = node.style.get("font-family")

        # parse font weight
        weight = "normal"
        font_weight = node.style.get("font-weight", "normal")
        if font_weight.isnumeric():
            if int(font_weight) >= 500:
                weight = "bold"
        elif font_weight == "bold":
            weight = "bold"

        font = get_font(font_family, size, weight, style)
        self.color = node.style.get("color", "black")
        space_width = font.measure(" ")

        self.font = get_font(font_family, size, weight, style)

        self.width = self.font.measure(self.word)

        if self.previous:
            space = self.previous.font.measure(" ")
            self.x = self.previous.x + space + self.previous.width
        else:
            self.x = self.parent.x

        self.height = self.font.metrics("linespace")

    def paint(self):
        rect = Rect(self.x, self.y, self.x + self.width, self.y + self.height)
        return [DrawText(rect, self.word, self.font, self.color)]

    def __repr__(self):
        return f"Text {repr(self.word)} {self.x},{self.y} {self.width},{self.height}"


def paint_tree(layout_object, display_list):
    display_list.extend(layout_object.paint())

    for child in layout_object.children:
        paint_tree(child, display_list)


def get_font(family, size, weight, style):
    FONTS = font_cache
    key = (family, size, weight, style)
    if key not in FONTS:
        import tkinter.font

        font = tkinter.font.Font(family=family, size=size, weight=weight, slant=style)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)
    return FONTS[key][0]


class DrawText:
    def __init__(self, rect, text, font, color):
        self.rect = rect
        self.text = text
        self.font = font
        self.color = color

    def execute(self, scroll, canvas):
        canvas.create_text(
            self.rect.left,
            self.rect.top - scroll,
            text=self.text,
            font=self.font,
            anchor="nw",
            fill=self.color,
        )


class DrawRect:
    def __init__(self, rect, color):
        self.rect = rect
        self.color = color

    def execute(self, scroll, canvas):
        canvas.create_rectangle(
            self.rect.left,
            self.rect.top - scroll,
            self.rect.right,
            self.rect.bottom - scroll,
            width=0,
            fill=self.color,
        )


class DrawOutline:
    def __init__(self, rect, color, thickness):
        self.rect = rect
        self.color = color
        self.thickness = thickness

    def execute(self, scroll, canvas):
        canvas.create_rectangle(
            self.rect.left,
            self.rect.top - scroll,
            self.rect.right,
            self.rect.bottom - scroll,
            width=self.thickness,
            outline=self.color,
        )


class DrawLine:
    def __init__(self, x1, y1, x2, y2, color, thickness):
        self.rect = Rect(x1, y1, x2, y2)
        self.color = color
        self.thickness = thickness

    def execute(self, scroll, canvas):
        canvas.create_line(
            self.rect.left,
            self.rect.top - scroll,
            self.rect.right,
            self.rect.bottom - scroll,
            fill=self.color,
            width=self.thickness,
        )


class Rect:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom

    def contains_point(self, x, y):
        return x >= self.left and x < self.right and y >= self.top and y < self.bottom


class HTMLParser:
    ENTITY_MAP = {
        "&nbsp;": " ",
        "&lt;": "<",
        "&gt;": ">",
        "&amp;": "&",
        "&quot;": '"',
        "&apos;": "'",
        "&cent;": "¢",
        "&pound;": "£",
        "&yen;": "¥",
        "&euro;": "€",
        "&copy;": "©",
        "&reg;": "®",
        "&ndash;": "–",
        "&mdash;": "—",
        "&#39;": "'",
        "&shy;": "­",
    }

    SELF_CLOSING_TAGS = [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]

    HEAD_TAGS = [
        "base",
        "basefont",
        "bgsound",
        "noscript",
        "link",
        "meta",
        "title",
        "style",
        "script",
    ]

    FORMATTING_TAGS = [
        "b",
        "i",
    ]

    def __init__(self, body):
        self.body = body
        self.unfinished = []

    def parse(self):
        body = self.body
        in_tag = False
        in_quoted_value = False
        quote_terminator = "'"
        in_entity = False
        in_special_tag = False
        in_comment = False
        in_script = False
        text = ""
        parsed_dash = 0
        for c in body:
            if in_quoted_value:
                if c == quote_terminator:
                    in_quoted_value = False
                text += c
            elif in_special_tag:
                if in_script:
                    text += c
                    if text.endswith("</script>"):
                        text = text[:-9]  # remove </script>
                        self.add_text(text)
                        text = ""
                        in_special_tag = False
                        in_script = False
                        in_tag = False
                        self.add_tag("/script")
                elif in_comment:
                    if c == "-":
                        parsed_dash -= 1
                        if parsed_dash < 0:
                            parsed_dash = 0
                    elif c == ">" and parsed_dash == 0:
                        in_comment = False
                        in_special_tag = False
                        in_tag = False
                    else:
                        parsed_dash = 2  # reset
                else:
                    if c == "-":
                        parsed_dash += 1
                    elif c == ">":
                        in_special_tag = False
                        in_tag = False
                    elif parsed_dash == 2:
                        in_comment = True
                    else:
                        parsed_dash = 0
            elif in_tag and c == "!":
                in_special_tag = True
                parsed_dash = 0
                text = ""
            elif in_tag and (c == '"' or c == "'"):
                in_quoted_value = True
                quote_terminator = c
                text += c
            elif c == "&":
                in_entity = True
                entity = "&"
            elif in_entity:
                entity += c
                if c == ";":
                    in_entity = False
                    entity = HTMLParser.ENTITY_MAP.get(entity, entity)
                    text += entity
            elif c == "<" and not in_tag:
                in_tag = True
                if text:
                    self.add_text(text)
                text = ""
            elif c == ">" and in_tag:
                in_tag = False
                if text == "script" or text.startswith("script "):
                    in_special_tag = True
                    in_script = True
                self.add_tag(text)
                text = ""
            else:
                text += c
        if not in_tag and text:
            self.add_text(text)
        return self.finish()

    def add_text(self, text, force=False):
        self.implicit_tags(None)
        parent = self.unfinished[-1] if self.unfinished else None
        node = Text(text, parent)

        if self.unfinished:
            parent.children.append(node)
        else:
            self.unfinished.append(node)

    def add_tag(self, tag):
        tag, attributes = self.get_attributes(tag)
        if tag.startswith("!"):
            return
        self.implicit_tags(tag)
        if tag.startswith("/"):
            # closing tags
            name = tag[1:]
            popped = None
            while len(self.unfinished) > 1 and self.unfinished[-1].tag != name:
                if not popped:
                    popped = []
                node = self.unfinished.pop()
                parent = self.unfinished[-1]
                parent.children.append(node)
                popped.append(node)
            if len(self.unfinished) == 1:
                return
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
            # reopen formatting tags
            if popped:
                for node in popped:
                    if node.tag in self.FORMATTING_TAGS:
                        self.add_tag(node.tag)
        elif tag in self.SELF_CLOSING_TAGS:
            # self closing
            parent = self.unfinished[-1]
            node = Element(tag, attributes, parent)
            parent.children.append(node)
        else:
            # open new tag
            parent = self.unfinished[-1] if self.unfinished else None
            node = Element(tag, attributes, parent)
            self.unfinished.append(node)

    def finish(self):
        if not self.unfinished:
            self.implicit_tags(None)
        while len(self.unfinished) > 1:
            node = self.unfinished.pop()
            parent = self.unfinished[-1]
            parent.children.append(node)
        return self.unfinished.pop()

    def get_attributes(self, text):
        part = ""
        parts = []
        in_quote = False
        quote_char = ""
        for c in text:
            if in_quote:
                if c == quote_char:
                    in_quote = False
                part += c
            elif c.isspace():
                if part:
                    parts.append(part)
                    part = ""
            elif c == "'" or c == '"':
                in_quote = True
                quote_char = c
                part += c
            else:
                part += c
        if part:
            parts.append(part)

        tag = parts[0].casefold()
        attributes = {}
        for attrpair in parts[1:]:
            if "=" in attrpair:
                key, value = attrpair.split("=", 1)
                if len(value) > 2 and value[0] in ["'", '"']:
                    value = value[1:-1]
                attributes[key.casefold()] = value
            else:
                attributes[attrpair.casefold()] = ""
        return tag, attributes

    def implicit_tags(self, tag):
        while True:
            open_tags = [node.tag for node in self.unfinished]
            if open_tags == [] and tag != "html":
                self.add_tag("html")
            elif open_tags == ["html"] and tag not in ["head", "body", "/html"]:
                if tag in self.HEAD_TAGS:
                    self.add_tag("head")
                else:
                    self.add_tag("body")
            elif (
                open_tags == ["html", "head"] and tag not in ["/head"] + self.HEAD_TAGS
            ):
                self.add_tag("/head")
            elif open_tags and open_tags[-1] == tag and tag in ["p", "li"]:
                self.add_tag("/" + tag)
            elif open_tags and open_tags[-1] == "li" and tag in ["/ul", "/ol"]:
                self.add_tag("/li")
            else:
                break


class HTMLSourceParser(HTMLParser):
    def parse(self):
        self.add_tag("pre")
        text = ""
        in_tag = False
        in_quoted_value = False
        in_special_tag = False
        quote_type = "'"
        for c in self.body:
            if in_tag:
                if c == "!" and text == "<":
                    in_special_tag = True
                    text += c
                elif in_quoted_value:
                    if c == quote_type:
                        in_quoted_value = False
                    text += c
                elif c in ["'", '"']:
                    in_quoted_value = True
                    quote_type = c
                    text += c
                elif c == ">":
                    text += c
                    if in_special_tag:
                        self.add_tag("i")
                    self.add_text(text, force=True)
                    if in_special_tag:
                        self.add_tag("/i")
                    text = ""
                    in_tag = False
                    in_special_tag = False
                else:
                    text += c
            else:
                # not in tag
                if c == "<":
                    self.add_tag("b")
                    self.add_text(text, force=True)
                    self.add_tag("/b")
                    text = c
                    in_tag = True
                else:
                    text += c
        self.add_tag("/pre")
        return self.finish()


class CSSParser:
    def __init__(self, s):
        self.s = s
        self.i = 0

    def parse(self):
        rules = []
        pairs = {}
        important_pairs = {}
        while self.i < len(self.s):
            try:
                self.whitespace()
                selector = self.selector()
                self.literal("{")
                self.whitespace()
                self.body(pairs, important_pairs)
                if pairs:
                    rules.append((selector, pairs))
                    pairs = {}
                if important_pairs:
                    rules.append((ImportantSelector(selector), important_pairs))
                    important_pairs = {}
                self.literal("}")
            except Exception:
                why = self.ignore_until(["}"])
                if why == "}":
                    self.literal("}")
                    self.whitespace()
                else:
                    break
        return rules

    def selector(self):
        out = self.makeSelector(self.word().casefold())
        self.whitespace()
        while self.i < len(self.s) and self.s[self.i] != "{":
            if self.s[self.i] == ",":
                self.literal(",")
                self.whitespace()
                tag = self.word().casefold()
                self.whitespace()
                sibling = self.makeSelector(tag)
                if isinstance(out, OrSelector):
                    out.append(sibling)
                else:
                    out = OrSelector([out, sibling])
            elif self.s[self.i] == ":":
                self.literal(":")
                word = self.word()
                self.whitespace()
                if word == "has":
                    self.literal("(")
                    self.whitespace()
                    tag = self.word().casefold()
                    self.whitespace()
                    self.literal(")")
                    self.whitespace()
                    musthave = self.makeSelector(tag)
                    out = HasSelector(out, musthave)
                if word == "visited":
                    self.whitespace()
                    out = VisitedSelector(out)
                else:
                    continue  # misparse
            else:
                tag = self.word()
                descendant = self.makeSelector(tag.casefold())
                if isinstance(out, DescendantSelector):
                    out.append(descendant)
                else:
                    out = DescendantSelector(out, descendant)
                self.whitespace()
        return out

    def makeSelector(self, s):
        start = -1
        inside = False
        out = None
        for i in range(0, len(s)):
            if s[i] == ".":
                if inside:
                    out = self.makeLeaftAndAddToSequence(s[start:i], out)
                start = i
                inside = True
            elif not inside and s[i].isalnum():
                start = i
                inside = True
        if inside:
            out = self.makeLeaftAndAddToSequence(s[start:], out)
        return out

    def makeLeaftAndAddToSequence(self, s, out):
        node = self.makeLeafSelector(s)
        if out:
            if isinstance(out, SequenceSelector):
                out.append(node)
            else:
                out = SequenceSelector([out, node])
        else:
            out = node
        return out

    def makeLeafSelector(self, s):
        if s.startswith("."):
            return ClassSelector(s[1:])
        else:
            return TagSelector(s)

    def body(self, pairs: dict, important_pairs: dict):
        while self.i < len(self.s):
            try:
                self.pair(pairs, important_pairs)
                self.literal(";")
                self.whitespace()
            except Exception:
                why = self.ignore_until([";", "}"])
                if why == ";":
                    self.literal(";")
                    self.whitespace()
                else:
                    break

    def whitespace(self):
        L = len(self.s)
        while self.i < L:
            if self.s[self.i].isspace():
                self.i += 1
            elif self.s[self.i] == "/" and self.i + 1 < L and self.s[self.i + 1] == "*":
                self.i += 2  # start of comment
                while self.i < L:
                    if (
                        self.s[self.i] == "*"
                        and self.i + 1 < L
                        and self.s[self.i + 1] == "/"
                    ):
                        self.i += 2
                        break  # end of comment
                    else:
                        self.i += 1
            else:
                break

    def word(self):
        start = self.i
        while self.i < len(self.s):
            if self.s[self.i].isalnum() or self.s[self.i] in "#-.%!":
                self.i += 1
            else:
                break
        if not (self.i > start):
            raise Exception("Parsing error")
        return self.s[start : self.i]

    def literal(self, literal):
        if self.i >= len(self.s):
            raise Exception(f"Parse reached end while expecting {literal}")
        if self.s[self.i] != literal:
            raise Exception(
                f"Parsing expected: {literal} error found: {self.s[self.i]}"
            )
        self.i += 1

    def pair(self, pairs: dict, important_pairs: dict):
        self.whitespace()
        prop = self.word()
        self.whitespace()
        self.literal(":")
        self.whitespace()
        expression = []
        while self.i < len(self.s) and self.s[self.i] not in [";", "}"]:
            expression.append(self.word())
            self.whitespace()
        if expression[-1] == "!important":
            pairs = important_pairs  # save to important pairs
            expression.pop()
        prop = prop.casefold()
        if prop == "font":
            for item in expression:
                if item == "italic":
                    pairs["font-style"] = "italic"
                elif item == "bold":
                    pairs["font-weight"] = "bold"
                elif item.endswith("%"):
                    pairs["font-size"] = item
                else:
                    pairs["font-family"] = item
        elif prop == "background":
            parsed_color = False
            for item in expression:
                if not parsed_color:
                    pairs["background-color"] = item
                    parsed_color = True
        elif len(expression) == 1:
            pairs[prop] = expression[0]

    def ignore_until(self, chars):
        while self.i < len(self.s):
            if self.s[self.i] in chars:
                return self.s[self.i]
            else:
                self.i += 1
        return None


INHERITED_PROPERTIES = {
    "font-size": "16px",
    "font-style": "normal",
    "font-weight": "normal",
    "font-family": "",
    "color": "black",
    "white-space": "normal",
}


def style(node, rules, depth=0):
    node.style = {}

    for property, default_value in INHERITED_PROPERTIES.items():
        if node.parent:
            node.style[property] = node.parent.style[property]
        else:
            node.style[property] = default_value

    for selector, body in rules:
        if not selector.matches(node):
            continue
        for property, value in body.items():
            node.style[property] = value

    if isinstance(node, Element) and "style" in node.attributes:
        pairs = {}
        CSSParser(node.attributes["style"]).body(pairs, pairs)
        for property, value in pairs.items():
            node.style[property] = value

    if node.style["font-size"].endswith("%"):
        if node.parent:
            parent_font_size = node.parent.style["font-size"]
        else:
            parent_font_size = INHERITED_PROPERTIES["font-size"]
        node_pct = float(node.style["font-size"][:-1]) / 100
        parent_px = float(parent_font_size[:-2])
        node.style["font-size"] = str(node_pct * parent_px) + "px"

    for child in node.children:
        style(child, rules, depth=depth + 1)


def cascade_priority(rule):
    selector, body = rule
    return selector.priority


class ImportantSelector:
    def __init__(self, child):
        self.child = child
        self.priority = child.priority + 10_000

    def __repr__(self):
        return "Important'" + repr(self.child)

    def matches(self, node):
        return self.child.matches(node)


class ClassSelector:
    def __init__(self, class_name):
        self.class_name = class_name
        self.priority = 1

    def __repr__(self):
        return "ClassSelector" + repr(self.class_name)

    def matches(self, node):
        return isinstance(node, Element) and self.class_name == node.attributes.get(
            "class", ""
        )


class TagSelector:
    def __init__(self, tag):
        self.tag = tag
        self.priority = 1

    def __repr__(self):
        return "TagSelector" + repr(self.tag)

    def matches(self, node):
        return isinstance(node, Element) and self.tag == node.tag


class DescendantSelector:
    def __init__(self, ancestor, descendant):
        self.list = [ancestor, descendant]
        self.priority = ancestor.priority + descendant.priority

    def matches(self, node):
        i = len(self.list) - 1
        if not self.list[i].matches(node):
            return False
        i -= 1
        while node.parent and i >= 0:
            node = node.parent
            if self.list[i].matches(node):
                i -= 1
        return i < 0

    def append(self, node):
        self.list.append(node)
        self.priority += node.priority

    def __repr__(self):
        return "DescendantSelector" + repr(self.list)


class SequenceSelector:
    def __init__(self, list=[]):
        self.list = list
        self.priority = 0
        for item in list:
            self.priority += item.priority

    def matches(self, node):
        for sel in self.list:
            if not sel.matches(node):
                return False
        return True

    def append(self, node):
        self.list.append(node)
        self.priority += node.priority

    def __repr__(self):
        return "SequenceSelector" + repr(self.list)


class HasSelector:
    def __init__(self, base, musthave):
        self.base = base
        self.musthave = musthave
        self.priority = base.priority + musthave.priority

    def matches(self, node):
        if not self.base.matches(node):
            return False
        if not isinstance(node, Element):
            return False
        for child in node.children:
            if self.musthave.matches(child):
                return True
        return False

    def __repr__(self):
        return f"Has({self.base}, {self.musthave})"


class VisitedSelector:
    def __init__(self, base):
        self.base = base
        self.priority = base.priority + 1

    def matches(self, node):
        if not self.base.matches(node):
            return False
        if not isinstance(node, Element):
            return False
        return node.isvisited

    def __repr__(self):
        return f"Visited({self.base})"


class OrSelector:
    def __init__(self, list=[]):
        self.list = list
        self.priority = 0
        for node in list:
            self.priority = max(self.priority, node.priority)

    def append(self, node):
        self.list.append(node)
        self.priority = max(self.priority, node.priority)

    def matches(self, node):
        for item in self.list:
            if item.matches(node):
                return True
        return False

    def __repr__(self):
        return f"Or({repr(self.list)})"


def test():
    print("run tests")
    test_URL()
    test_CSS_parse()
    test_HTML_parse_tree()
    test_HTML_parse_and_get_text()
    test_CSS_selectors()
    test_BrowserState()
    test_BrowserBookmarks()


def test_CSS_selectors():
    def matchcount(selector, html, visited={}):
        nodes = HTMLParser(html).parse()
        css = CSSParser(selector + "{ color: red }").parse()
        count = 0
        baseurl = ""
        for node in tree_to_list(nodes, []):
            eval_visited(node, baseurl, visited)
            for rule in css:
                if rule[0].matches(node):
                    count += 1
        return count

    assert matchcount("a", "<div></div>") == 0
    assert matchcount("div", "<div></div>") == 1
    assert matchcount("a", "<a></a><a></a>") == 2
    assert matchcount(".a", '<div class="a"></div>') == 1
    assert matchcount(".a", '<div class="b"></div>') == 0
    assert matchcount("a a", "<a><a></a></a>") == 1
    assert matchcount("a a", "<div><a></a></div>") == 0
    assert matchcount("a.red", '<a class="red"></a>') == 1
    assert matchcount("a.blue", '<a class="red"></a>') == 0
    assert matchcount("a:has(span)", "<a>x</a>") == 0
    assert matchcount("a:has(span)", "<a><span>x</span></a>") == 1
    assert matchcount("strong,b", "<b></b><strong></strong>") == 2
    assert matchcount("a:visited", "<a>x</a>") == 0
    assert matchcount("a:visited", '<a href="file:///test">x</a>') == 0
    assert (
        matchcount("a:visited", '<a href="file:///t">x</a>', visited=["file:///t"]) == 1
    )


def test_CSS_parse():
    def parse(str):
        return CSSParser(str).parse()

    results = parse("p { background:red; color:white }")
    assert len(results) == 1
    assert isinstance(results[0][0], TagSelector)
    assert results[0][1]["background-color"] == "red"
    assert results[0][1]["color"] == "white"

    results = parse("nav li { background:red }")
    assert len(results) == 1
    assert isinstance(results[0][0], DescendantSelector)

    results = parse("h1 { color: red } h2 { color: red }")
    assert len(results) == 2

    results = parse("p { background:red; asdawdasd }")
    assert results[0][1]["background-color"] == "red"

    results = parse("p*p { color:blue; } h1 { color:red }")
    assert len(results) == 1
    assert results[0][1]["color"] == "red"

    results = parse(".red { background:red }")
    assert len(results) == 1
    assert isinstance(results[0][0], ClassSelector)
    assert results[0][0].class_name == "red"

    results = parse("/*.red { background:red }*/")
    assert len(results) == 0

    results = parse("/*.red { color:red }*/ .bg { color:blue }")
    assert len(results) == 1
    assert results[0][0].class_name == "bg"
    assert results[0][1]["color"] == "blue"

    results = parse("h1 { font: italic bold 100% Times }")
    assert results[0][1]["font-style"] == "italic"
    assert results[0][1]["font-weight"] == "bold"
    assert results[0][1]["font-size"] == "100%"
    assert results[0][1]["font-family"] == "Times"

    results = parse("h1 { background: #ffffff }")
    assert isinstance(results[0][0], TagSelector)
    assert results[0][1]["background-color"] == "#ffffff"

    results = parse("div { color: black !important; }")
    assert results[0][1]["color"] == "black"


def test_HTML_parse_tree():
    def f(x):
        return HTMLParser(x).parse()

    dom = f("<h1>Hi!</h1>")
    assert len(dom.children) == 1
    assert dom.tag == "html"
    assert len(dom.children[0].children) == 1
    assert dom.body.children[0].tag == "h1"
    assert dom.body.children[0].children[0].text == "Hi!"

    dom = f("<!-- ><comment>< --><h1>Hi!</h1>")
    assert dom.body.children[0].tag == "h1"
    assert dom.get_text() == "Hi!"

    dom = f("<!--><h1>Hi!</h1><!-- -->")
    assert dom.body.children[0].tag == "h1"
    assert dom.get_text() == "Hi!"

    dom = f("<!---><h1>Hi!</h1><!-- -->")
    assert dom.get_text() == "Hi!"

    dom = f("<p>hello<p>world</p>")
    assert dom.body.children[0].tag == "p"
    assert dom.body.children[1].tag == "p"

    dom = f("<li>1st<li>2nd</li>")
    assert dom.body.children[0].tag == "li"
    assert dom.body.children[1].tag == "li"

    dom = f("<ul><li><ul><li>nest1<li>nest2</ul><li>root2</ul>")
    assert dom.body.children[0].children[0].children[0].children[0].tag == "li"
    assert dom.body.children[0].children[0].children[0].children[1].tag == "li"
    assert dom.body.children[0].children[1].tag == "li"

    dom = f("<script>what='<h1>crap</h1>';</script><p>a")
    assert dom.head.children[0].tag == "script"
    assert dom.body.children[0].tag == "p"
    assert dom.head.children[0].children[0].text == "what='<h1>crap</h1>';"

    dom = f('<p class="<>">Parapgrah</p>')
    assert dom.get_text() == "Parapgrah"

    dom = f("<p class='<>'>Parapgrah</p>")
    assert dom.get_text() == "Parapgrah"

    dom = f("<p <>>badform</p>")
    assert dom.get_text() == ">badform"

    dom = f("<b>mis<i>nested</b>tags</i>")
    assert dom.body.children[0].tag == "b"
    assert dom.body.children[0].children[0].text == "mis"
    assert dom.body.children[0].children[1].tag == "i"
    assert dom.body.children[1].tag == "i"

    dom = f("<div class=x></div>")
    assert dom.body.children[0].attributes["class"] == "x"

    dom = f('<div class="x"></div>')
    assert dom.body.children[0].attributes["class"] == "x"

    dom = f('<div style="display: none;"></div>')
    assert dom.body.children[0].attributes["style"] == "display: none;"


def test_HTML_parse_and_get_text():
    def f(x):
        return HTMLParser(x).parse().get_text()

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
    assert url.viewsource is True
    assert url.scheme == "http"
    assert url.host == "example.org"

    url = URL("https://example.org")
    url = URL("/404.html", parent=url)
    assert url.path == "/404.html"
    assert url.host == "example.org"
    assert url.port == 443
    assert url.scheme == "https"

    url = URL("https://example.org/page?continue=https://example.org/something")
    assert url.host == "example.org"
    assert url.port == 443
    assert url.scheme == "https"

    url = URL("C:\\Users\\someone\\index.html")
    assert url.scheme == "file"
    assert url.path == "C:\\Users\\someone\\index.html"

    url = URL("/home/username/file.html")
    assert url.scheme == "file"
    assert url.path == "/home/username/file.html"

    url = URL("./file.html")
    assert url.scheme == "file"
    assert url.path == "./file.html"

    url = URL("../file.html")
    assert url.scheme == "file"
    assert url.path == "../file.html"

    url = URL("https://example.org")
    url = URL("style.css", parent=url)
    assert url.scheme == "https"
    assert url.host == "example.org"
    assert url.port == 443
    assert url.path == "/style.css"

    url = URL("./www/index.html")
    url = URL("block.html", parent=url)
    assert url.scheme == "file"
    assert url.path == "www/block.html"

    url = URL("https://example.com/page.html#main")
    assert url.path == "/page.html"
    assert url.fragment == "#main"
    url = URL("#other", url)
    assert url.path == "/page.html"
    assert url.fragment == "#other"

    url = URL("https://duckduckgo.com/?q=test&ia=web")
    assert url.search == "?q=test&ia=web"
    url = URL("//duckduckgo.com/dist/some.css", parent=url)
    assert url.path == "/dist/some.css"


def test_BrowserState():
    # 3 tabs to work with
    state = BrowserState(None)
    assert state.get_tab_count() == 0
    state.newtab("about:blank")
    assert state.get_tab_count() == 1
    state.newtab("about:config")
    assert state.get_tab_count() == 2
    state.newtab("about:test")
    assert state.get_tab_count() == 3
    assert state.get_active_tab_index() == 2
    assert state.get_url() == "about:test"

    # check relative switch wraparound
    state.switchtab(1, relative=True)
    assert state.get_active_tab_index() == 0
    state.switchtab(-1, relative=True)
    assert state.get_active_tab_index() == 2
    state.switchtab(-1, relative=True)
    assert state.get_active_tab_index() == 1

    # check clamping of absolute value
    state.switchtab(-1)
    assert state.get_active_tab_index() == 0
    state.switchtab(0)
    assert state.get_active_tab_index() == 0
    state.switchtab(1)
    assert state.get_active_tab_index() == 1
    state.switchtab(2)
    assert state.get_active_tab_index() == 2
    state.switchtab(3)
    assert state.get_active_tab_index() == 2

    # check scroll is local to tab
    state.switchtab(0)
    state.set_scroll(100)
    state.set_title("a")
    state.switchtab(1)
    state.set_scroll(200)
    state.set_title("b")
    assert state.get_title() == "b"
    assert state.get_scroll() == 200
    state.switchtab(0)
    assert state.get_scroll() == 100
    assert state.get_title() == "a"

    # title is stripped of whitespace
    state.set_title(" a ")
    assert state.get_title() == "a"

    # check pushlocation & back & forward
    state.switchtab(0)
    state.pushlocation("https://example.com")
    assert state.get_url() == "https://example.com"
    state.back()
    assert state.get_url() == "about:blank"
    state.forward()
    assert state.get_url() == "https://example.com"

    # each tab has own history
    state.switchtab(1)
    state.pushlocation("https://other.com")
    assert state.get_url() == "https://other.com"
    state.switchtab(0)
    assert state.get_url() == "https://example.com"
    state.switchtab(1)
    state.back()
    assert state.get_url() == "about:config"

    # futures deleted after pushlocation
    state.pushlocation("https://another.com")
    state.forward()
    assert state.get_url() == "https://another.com"

    # closetab
    state.switchtab(1)
    assert state.get_active_tab_index() == 1
    assert state.get_tab_count() == 3
    state.closetabindex(0)
    assert state.get_active_tab_index() == 0
    assert state.get_tab_count() == 2
    state.switchtab(1)
    state.closetabindex(1)
    assert state.get_url() == "https://another.com"
    assert state.get_tab_count() == 1


def test_BrowserBookmarks():
    bm = BrowserBookmarks(None)
    assert bm.get_count() == 0
    bm.toggle("https://example.com", "Example")
    assert bm.get_count() == 1
    assert bm.contains("https://example.com")
    assert bm.get_urls() == ["https://example.com"]
    bm.toggle("https://example.com", "Example")
    assert bm.get_count() == 0


if __name__ == "__main__":
    import sys

    ui = GUIBrowser()
    state = BrowserState(None)
    history = BrowserHistory(None)
    bookmarks = BrowserBookmarks(None)
    parsearg = None
    for arg in sys.argv[1:]:
        if parsearg:
            if parsearg == "--cache-dir":
                http_cache_dir = arg
                state = BrowserState(http_cache_dir)
                state.restore()
                history = BrowserHistory(http_cache_dir)
                history.restore()
                bookmarks = BrowserBookmarks(http_cache_dir)
                bookmarks.restore()
            parsearg = None
        elif arg.startswith("-"):
            flag = arg
            if "--gui" == flag:
                ui = GUIBrowser()
            elif "--cli" == flag:
                ui = CLI()
            elif "--test" == flag:
                test()
            elif "--version" == flag:
                print("1.0.0")
            elif "--help" == flag:
                print("gal web browser")
            elif flag == "--rtl":
                default_rtl = True
            elif "--cache-dir" == flag:
                parsearg = flag
            else:
                raise Exception(f"unknown flag '{flag}'")
        else:
            url = arg
            state.newtab(url)

    ui.start(state, history, bookmarks)
