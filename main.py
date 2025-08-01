#!/usr/bin/env python3
sock_pool = {}
http_cache = {}
font_cache = {}
http_cache_dir = None
http_cache_blob_dir = None
default_rtl = False
default_style_sheet = None
default_search_engine = "https://lite.duckduckgo.com/lite?q="
default_js_runtime = None


class URL:
    def __init__(self, url, parent=None):
        url = url.replace("\\", "/")
        self.fragment = ""
        self.search = ""
        self.host = "" # TODO not sure if safe
        self.port = 0
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
                    if ":" in url and url[1] != ":":
                        self.scheme = "http"
                        self.port = 80
                        self.host, url = url.split(":", 1)
                        if "/" in url:
                            portstr, url = url.split("/", 1)
                            self.port = int(portstr)
                        else:
                            self.port = int(url)
                            url = "/"
                    else:
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

    def origin(self):
        return self.scheme + "://" + self.host + ":" + str(self.port)

    def request(self, referrer=None, max_redirect=3, readcache=True, payload=None, cookies=None, method=None):
        if self.scheme == "about":
            if self.path == "blank":
                return "", self
            else:
                return "page not found", self
        if self.scheme == "data":
            return {}, self.content, self
        elif self.scheme == "file":
            if payload:
                raise Exception("cannot POST payload to file")
            return self.request_file()
        else:
            return self.request_socket(max_redirect, readcache, payload, cookies, referrer, method)

    def request_file(self):
        with open(self.path) as f:
            return {}, f.read(), self

    def request_socket(self, max_redirect=3, readcache=True, payload=None, cookies=None, referrer=None, method=None):
        global sock_pool
        global http_cache
        global http_cache_blob_dir

        if not method:
            method = "GET" if not payload else "POST"

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

        cache_key = self.get_cache_key() if method == "GET" else None
        if cache_key and cache_key in http_cache and readcache:
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
                    return content, self
                if http_cache_blob_dir and "blob_id" in cache_entry:
                    blob_id = cache_entry["blob_id"]
                    with open(http_cache_blob_dir + "/" + blob_id, "rb") as f:
                        bytes = f.read()
                        content = bytes.decode("utf8")
                        print("CACHED GET", cache_key)
                        return {}, content, self

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

        reqlines = [
            f"{method} {self.path}{self.search} HTTP/1.1\r\n",
            f"Host: {self.host}\r\n",
            "Connection: keep-alive\r\n",
            "Accept-Encoding: gzip\r\n",
        ]
        cookie_items = cookies.get_cookie_items_by_host(self.host) if cookies else []
        cookies_to_send = []
        for cookie_item in cookie_items:
            # TODO move cookie rule eval to cookie jar and then 
            # here just append the cookie string
            if cookie_item:
                cookie, params = cookie_item
                allow_cookie = True
                samesite = params.get("samesite", "none")
                if referrer and samesite == "lax":
                    if method != "GET":
                        allow_cookie = self.host == referrer.host
                if allow_cookie:
                    cookies_to_send.append(cookie)
        if cookies_to_send:
            cookies_str = "; ".join(cookies_to_send)
            reqlines.append("Cookie: {}\r\n".format(cookies_str))
        if payload:
            length = len(payload.encode("utf8"))
            reqlines.append("Content-Length: {}\r\n".format(length))
        reqlines.append("\r\n")  # end of headers
        if payload:
            reqlines.append(payload)
        request = "".join(reqlines)
        bytestosend = request.encode("utf8")
        bytessent = s.send(bytestosend)
        assert bytessent == len(bytestosend)
        response = f

        statusline = response.readline().decode("utf8")
        version, status, explanation = statusline.split(" ", 2)
        print(status, explanation.strip(), method, self.get_str())
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

        if "set-cookie" in response_headers and cookies:
            cookie = response_headers["set-cookie"]
            cookies.set_cookie_by_host(self.host, cookie)

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
                return url.request(max_redirect=max_redirect - 1, cookies=cookies, referrer=self)

        if code == 200 and method == "GET":
            cache_control = response_headers.get("cache-control")
            expires = 0
            store = True
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
                    import traceback

                    print("Failed to handle cache control", err)
                    print(traceback.format_exc())
                    store = False
            else:
                # cache control not handled, better not cache
                store = False

            print("store", store)

            if store and cache_key:
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
        
        return response_headers, content, self

    def get_cache_key(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}{self.path}{self.search}"

    def get_str(self) -> str:
        if self.scheme == "file":
            return f"{self.scheme}://{self.path}"
        if self.scheme == "about":
            return f"{self.scheme}:{self.path}"
        if self.scheme == "https" and self.port == 443:
            port = ""
        elif self.scheme == "http" and self.port == 80:
            port = ""
        else:
            port = f":{self.port}"
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
        self.is_focused = False
        self.cursor = 0

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

    def append_child(self, child):
        if child.parent:
            child.remove()
        self.children.append(child)
        child.parent = self
    
    def insert_before(self, child):
        for index, sibling in enumerate(self.parent.children):
            if sibling == self:
                self.parent.children.insert(index, child)
                child.parent = self.parent
                return
        
    def remove(self):
        if self.parent:
            self.parent.children.remove(self)
            self.parent = None


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


def format_tree_HTML(node):
    parts = []
    if isinstance(node, list):
        for item in node:
            collect_HTML_parts(item, parts)
    else:
        collect_HTML_parts(node, parts)
    return "".join(parts)


def collect_HTML_parts(node, parts):
    if isinstance(node, Element):
        parts.append("<")
        parts.append(node.tag)
        for key in node.attributes:
            value = node.attributes[key]
            parts.append(" ")
            parts.append(key)
            if value:
                parts.append('="')
                # TODO this should be escaped
                parts.append(value) 
                parts.append('"')
        parts.append(">")
        for child in node.children:
            collect_HTML_parts(child, parts)
        parts.append("</")
        parts.append(node.tag)
        parts.append(">")
    elif isinstance(node, Text):
        parts.append(node.text)
    else:
        raise Exception("collect_HTML_parts node type not handled")
    return parts


def input_element_handle_input(node: Element, input_txt: str):
    if node.tag != "input":
        return False
    attr = node.attributes
    type = attr.get("type")
    if type and type != "text" and type != "password":
        return False
    txt = attr.get("value", "")
    pos = node.cursor
    attr["value"] = txt[:pos] + input_txt + txt[pos:]
    node.cursor = max(0, min(len(txt) + 1, node.cursor + len(input_txt)))
    return True


def input_element_handle_backspace(node):
    if node.tag != "input":
        return False
    attr = node.attributes
    type = attr.get("type")
    if type and type != "text" and type != "password":
        return False
    txt = attr.get("value", "")
    pos = node.cursor
    node.cursor = max(0, node.cursor - 1)
    if pos > 0:
        attr["value"] = txt[: pos - 1] + txt[pos:]
        return True
    return False


def input_element_move_cursor(node, amount):
    if node.tag != "input":
        return False
    attr = node.attributes
    type = attr.get("type")
    if type and type != "text" and type != "password":
        return False
    txt = attr.get("value", "")
    node.cursor = max(0, min(len(txt) + 1, node.cursor + amount))
    return True


def input_element_handle_click(node):
    if node.tag != "input":
        return False
    nodetype = node.attributes.get("type")
    if nodetype == "checkbox":
        if hasattr(node, "ischecked"):
            node.ischecked = not node.ischecked
        else:
            node.ischecked = True
    else:
        node.cursor = len(node.attributes.get("value", ""))
    return True
        # node.attributes["value"] = ""


class JSContext:
    def is_feature_avaiable():
        try:
            import dukpy
            assert dukpy.evaljs("2 + 2") == 4
            return True
        except Exception as e:
            print("JavaScript not avaiable, please install dukjs to enable:", e)
            return False

    def __init__(self, tab):
        import dukpy

        self.interp = None
        self.tab = tab
        self.node_to_handle = {}
        self.handle_to_node = {}
        self.interp = dukpy.JSInterpreter()
        self._register_functions()
        self._load_runtime()

    def run(self, path, code):
        import dukpy

        try:
            return self.interp.evaljs(code)
        except dukpy.JSRuntimeError as e:
            print("Script", path, "crashed:\n", e)

    def dispatch_event(self, type, elt):
        handle = self.node_to_handle.get(elt, -1)
        if handle < 0:
            return
        code = "__dispatch_event(dukpy.handle, dukpy.type)"
        do_default = self.interp.evaljs(code, type=type, handle=handle)
        return not do_default

    def add_global_name(self, name, elt):
        handle = self._get_handle(elt)
        code = "__global_node(dukpy.name, dukpy.handle)"
        self.interp.evaljs(code, name=name, handle=handle)

    def remove_global_name(self, name, elt):
        handle = self._get_handle(elt)
        code = "__global_node_remove(dukpy.name, dukpy.handle)"
        self.interp.evaljs(code, name=name, handle=handle)

    def _load_runtime(self):
        self.run("runtine.js", get_js_runtime_code())


    def _register_functions(self):
        js = self.interp
        js.export_function("log", print)
        js.export_function("querySelectorAll", self._querySelectorAll)
        js.export_function("getAttribute", self._getAttribute)
        js.export_function("setAttribute", self._setAttribute)
        js.export_function("innerHTML_set", self._innerHTML_set)
        js.export_function("innerHTML_get", self._innerHTML_get)
        js.export_function("outerHTML_get", self._outerHTML_get)
        js.export_function("children_get", self._children_get)
        js.export_function("document_set_title", self.tab.set_title)
        js.export_function("document_get_title", self.tab.get_title)
        js.export_function("document_get_body", self._document_get_body)
        js.export_function("createElement", self._create_element)
        js.export_function("createTextNode", self._create_text_node)
        js.export_function("appendChild", self._append_child)
        js.export_function("insertBefore", self._insert_before)
        js.export_function("removeChild", self._remove_child)
        js.export_function("parent_get", self._node_parent_get)
        js.export_function("getComputedStyle", self._getComputedStyle)
        js.export_function("XHR_send", self._xhr_send)
        js.export_function("location_set", self._location_set)
        js.export_function("do_default", self._do_default)
        js.export_function("document_get_cookie", self._document_get_cookie)
        js.export_function("document_set_cookie", self._document_set_cookie)

    def _outerHTML_get(self, handle):
        elt = self.handle_to_node[handle]
        return format_tree_HTML(elt)

    def _innerHTML_get(self, handle):
        elt = self.handle_to_node[handle]
        return format_tree_HTML(elt.children)

    def _innerHTML_set(self, handle, html):
        doc = HTMLParser("<html><body>" + html + "</body></html>").parse()
        body = doc.children[0]
        for node in tree_to_list(body, []):
            if isinstance(node, Element) and node.attributes.get("id"):
                self.add_global_name(node.attributes.get("id"), node)
        new_nodes = body.children
        elt = self.handle_to_node[handle]
        for node in tree_to_list(elt, []):
            if node == elt: 
                continue
            if isinstance(node, Element) and node.attributes.get("id"):
                self.remove_global_name(node.attributes.get("id"), node)
        elt.children = new_nodes
        for child in elt.children:
            child.parent = elt
        self.tab.render()

    def _querySelectorAll(self, selector):
        nodes = query_selector_all(selector, self.tab.nodes)
        handles = [self._get_handle(node) for node in nodes]
        return handles

    def _getAttribute(self, handle, attr):
        elt = self.handle_to_node[handle]
        attr = elt.attributes.get(attr, None)
        return attr if attr else ""
    
    def _setAttribute(self, handle, attr, value):
        elt = self.handle_to_node[handle]
        elt.attributes[attr] = value

    def _children_get(self, handle):
        parent = self.handle_to_node[handle]
        return [self._get_handle(node) for node in parent.children if isinstance(node, Element)]

    def _document_get_body(self):
        return self._get_handle(self.tab.get_body())

    def _create_element(self, tag):
        element = Element(tag, {}, None)
        return self._get_handle(element)

    def _create_text_node(self, text):
        node = Text(text, None)
        return self._get_handle(node)

    def _append_child(self, hparent, hchild):
        parent = self.handle_to_node[hparent]
        child = self.handle_to_node[hchild]
        if isinstance(child, Element):
            self.tab.load_node(child)
        parent.append_child(child)

    def _insert_before(self, hparent, htoinsert, hreference):
        target = self.handle_to_node[hreference]
        toinsert = self.handle_to_node[htoinsert]
        if isinstance(toinsert, Element):
            self.tab.load_node(toinsert)
        target.insert_before(toinsert)
    
    def _remove_child(self, hparent, hchild):
        child = self.handle_to_node[hchild]
        child.remove()
        if isinstance(child, Element):
            self.tab.unload_node(child)

    def _node_parent_get(self, handle):
        if handle < 0: 
            return handle
        node = self.handle_to_node[handle]
        return self._get_handle(node.parent)
    
    def _getComputedStyle(self, handle):
        self.tab.render()
        node = self.handle_to_node[handle]
        return node.style

    def _xhr_send(self, method, url, body):
        parent_url = self.tab.url
        url = URL(url, parent=parent_url)
        if url.scheme != "data" and url.origin() != parent_url.origin():
            # always allow data: protocol (data hardcoded into url)
            # otherse compare origin
            # TODO: i think origin handling should be more standardized
            raise Exception("Cross-origin XHR request not allowed")
        if not self.tab.allowed_request(url):
            # TODO add wstest specifically for this
            print("Blocked XHR", url, "due to CSP")
            return None
        _, content, url = url.request(payload=body, cookies=self.tab.browser.cookies)
        return content

    def _location_set(self, value):
        travelurl = self.tab.resolve_url(value)
        self.tab.state.pushlocation(travelurl)
        self.tab.restorestate()
    
    def _do_default(self, handle, event_type):
        node = self.handle_to_node[handle]
        self.tab.do_default(node, event_type)

    def _document_get_cookie(self):
        # TODO this is error prone, make a more straightforward cookie access from tab object
        host = self.tab.url.host
        return self.tab.browser.cookies.get_cookie_value_by_host(host, is_script=True)

    def _document_set_cookie(self, value):
        # TODO this is error prone, make a more straightforward cookie access from tab object
        host = self.tab.url.host
        return self.tab.browser.cookies.set_cookie_by_host(host, value, is_script=True)

    def _get_handle(self, elt):
        if not elt:
            return -1
        if elt not in self.node_to_handle:
            handle = len(self.node_to_handle)
            self.node_to_handle[elt] = handle
            self.handle_to_node[handle] = elt
        else:
            handle = self.node_to_handle[elt]
        return handle


def get_js_runtime_code():
    global default_js_runtime

    if default_js_runtime is None:
        with open("runtime.js") as f:
            default_js_runtime = f.read()

    return default_js_runtime


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


class CustomDirPaths:
    def __init__(self, dirname):
        assert dirname
        self._dirname = dirname

    def ensure_exists(self):
        import os

        os.makedirs(self._dirname, exists_ok=True) # all same
        self.state_dir = self._dirname
        self.cache_dir = self._dirname
        self.data_dir = self._dirname
        self.config_dir = self._dirname

class UserDirPaths:
    def __init__(self, subdirname):
        self._subdir = subdirname
    
    def ensure_exists(self):
        import os
        self._home = os.environ.get("HOME")
        if not self._home:
            self._home = os.environ.get("USERPROFILE") # windows
        assert self._home
        self.state_dir = self._resolve("XDG_STATE_HOME", ".local/state")
        self.cache_dir = self._resolve("XDG_CACHE_HOME", ".cache")
        self.data_dir = self._resolve("XDG_DATA_HOME", ".local/share")
        self.config_dir = self._resolve("XDG_CONFIG_HOME", ".config")
        
    def _resolve(self, var, fallback):
        import os
        dir = os.environ.get(var) or os.path.join(self._home, fallback)    
        dir = os.path.join(dir, self._subdir)
        os.makedirs(dir, exist_ok=True)
        return dir

class NoDiskAccessPaths:
    def ensure_exists(self):
        self.state_dir = None
        self.cache_dir = None
        self.data_dir = None
        self.config_dir = None

class BrowserData:
    def __init__(self):
        self.is_private = False
        self.use_scripting = True
        self._custom_dir = None

    def restore(self):
        global http_cache_dir

        if self.is_private:
            self.paths = NoDiskAccessPaths()
        elif self._custom_dir:
            self.paths = CustomDirPaths(self._custom_dir)
        else:
            self.paths = UserDirPaths("gal")
        self.paths.ensure_exists()
        self.state = BrowserState(self.paths.state_dir)
        self.cookies = CookieJar(self.paths.data_dir)
        self.history = BrowserHistory(self.paths.data_dir)
        self.bookmarks = BrowserBookmarks(self.paths.data_dir)
        http_cache_dir = self.paths.cache_dir
        self.state.restore()
        self.history.restore()
        self.bookmarks.restore()
        self.cookies.restore()

    def makeprivate(self):
        self.is_private = True

    def disablejs(self):
        self.use_scripting = False

    def is_js_enabled(self):
        return self.use_scripting is True

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
        return str

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

    def get_payload(self) -> str:
        item = self._get_current_item()
        return item.get("payload")

    def get_method(self) -> str:
        item = self._get_current_item()
        method = item.get("method")
        if method:
            return method
        payload = item.get("payload")
        return "GET" if not payload else "POST"

    def get_scroll(self) -> int:
        item = self._get_current_item()
        return item.get("scroll")

    def get_history(self) -> dict:
        item = self._get_current_item()
        return item.get("history", None)

    def get_secure(self) -> str:
        item = self._get_current_item()
        return item.get("secure", "")

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

    def pushlocation(self, url, payload=None, method=None):
        item = self._get_current_item()
        to_return_to = self._create_return_item()
        history_list = item.get("history", [])
        history_list.append(to_return_to)
        item["history"] = history_list
        if "future" in item:
            item.pop("future")
        self.replacelocation(url, payload, method)
        self.dirty = True

    def replacelocation(self, url, payload=None, method=None):
        item = self._get_current_item()
        if item.get("url", "") != url:
            item["url"] = url
            if payload:
                item["payload"] = payload
            elif "payload" in item:
                del item["payload"]
            if "scroll" in item:
                item.pop("scroll")
            if method:
                item["method"] = method
            elif "method" in item:
                del item["method"]
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

    def set_secure(self, state: str):
        item = self._get_current_item()
        if item.get("secure", "") != state:
            item["secure"] = state
            if not state:
                item.pop("secure")
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
            tabs = self.data["tabs"]
            idx = self.get_active_tab_index()
            if idx >= len(tabs) or idx < 0:
                return {}
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
        payload = self.get_payload()
        if payload:
            backitem["payload"] = payload
        return backitem

    def _copy_item_locaiton_state(self, src, dst):
        dst["url"] = src.get("url", "")
        dst["scroll"] = src.get("scroll", 0)
        dst["payload"] = src.get("payload", None)
        dst["method"] = src.get("method", None)
        if dst["scroll"] == 0:
            dst.pop("scroll")
        if dst["url"] == "":
            dst.pop("url")
        if not dst["payload"]:
            dst.pop("payload")
        if not dst["method"]:
            dst.pop("method")


class CookieJar:
    def __init__(self, storage_dir):
        self.file_path = storage_dir + "/__cookies.json" if storage_dir else None
        self.file = JsonFileState(self.file_path) if storage_dir else None
        self.data = {}
        self.dirty = False

    def get_cookie_value_by_host(self, host, is_script=False):
        items = self.get_cookie_items_by_host(host)
        result = ''
        if items:
            result = '; '.join([x[0] for x in items if not (is_script and x[1].get("httponly"))])
        print("result is", result)
        return result

    def get_cookie_items_by_host(self, host):
        items = self.data.get(host, [])
        if isinstance(items, str):
            items = [parse_cookie(items)]
        if items and len(items) > 0 and isinstance(items[0], str):
            items = [items]
        return items

    def set_cookie_by_host(self, host, cookie, is_script=False):
        item = parse_cookie(cookie)
        if self.get_cookie_items_by_host(host) != item:
            if not isinstance(self.data.get(host), list):
                self.data[host] = []
            cookies = self.data[host]
            print(cookies)
            for other in cookies:
                print("other key is ", other[1].get("key"), "item key is", item[1].get("key"))
                if other[1].get("key") == item[1].get("key"):
                    if is_script and other[1].get("httponly"):
                        print("script cannot write http only cookie")
                        return
                    other[0] = item[0]
                    other[1] = item[1]
                    self.dirty = True
                    print("updating existing cookie")
                    return
            cookies.append(item)
            self.dirty = True
            print("setting new cookie value",self.data, self)
        else:
            print('no change')

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


def parse_cookie(cookie):
    params = {}
    if ";" in cookie:
        cookie, rest = cookie.split(";", 1)
        for param in rest.split(";"):
            if '=' in param:
                param, value = param.split("=", 1)
            else:
                value = "true"  
        params[param.strip().casefold()] = value.casefold()
    [key, value] = cookie.split("=")
    params["key"] = key
    params["value"] = value
    print("IS", cookie, params)
    return [cookie, params]


http_date_format = "%a, %d %b %Y %H:%M:%S GMT"


def parse_http_date(str):
    import time
    import calendar

    struct = time.strptime(str, http_date_format)
    return calendar.timegm(struct)


def format_http_date(t):
    import time
    struct = time.gmtime(t)
    return time.strftime(http_date_format, struct)


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

    def get_title(self, url: str) -> str:
        item = self._get_item(url)
        return item.get("title", "") if item else url

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

    def _create_new_item(self, url: str, title: str):
        return {"url": url, "title": title}

    def _remove_item(self, url: str):
        if self.contains(url):
            self.data["bookmarks"].pop(url)
            self.dirty = True


def generate_error_page(err: Exception, url) -> str:
    import traceback
    stack = traceback.format_exc()
    return f"""
        <title>Error - {url}</title>
        <h1>Error </h1>
        <h2>An error was encountered while trying to load the following url</h2>
        <code>{url}</code>
        <h2>{type(err).__name__}</h2>
        <code><pre>{err}</pre></code>
        <h2>Stack trace</h2>
        <code><pre>{stack}</pre></code>
    """
    

def generate_bookmarks_page(bookmarks: BrowserBookmarks) -> str:
    result = ["<title>Bookmarks</title><style>small { color:green }</style>"]
    for url in bookmarks.get_urls():
        title = bookmarks.get_title(url)
        result.append(
            f'<li><a href="{url}"><h2>{title}</h2><small>{url}</small></a></li>'
        )
    return f"<ul>{''.join(result)}</ul>"


class CLI:
    def browse(self, urlstr, max_redirect=5):
        print("navigating to", urlstr)
        url = URL(urlstr)
        _, result, url = url.request(max_redirect=max_redirect)
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
        self.focus = None

    def setup(self, data):
        self.data = data
        self.state: BrowserState = data.state
        self.history: BrowserHistory = data.history
        self.bookmarks: BrowserBookmarks = data.bookmarks
        self.cookies: CookieJar = data.cookies
        if not self.window:
            self.setup_window()
        self.restorestate(is_startup=True)

    def setup_window(self):
        import tkinter

        WIDTH, HEIGHT = self.state.get_window_size()
        HSTEP, VSTEP = 12, 18

        self.width = WIDTH
        self.height = HEIGHT
        self.vstep = VSTEP
        self.hstep = HSTEP

        self.window = tkinter.Tk()
        w = self.window
        w.bind("<Up>", lambda e: self.scrollposupdate(-100))
        w.bind("<Down>", lambda e: self.scrollposupdate(+100))
        w.bind("<Left>", self.pressarrowleft)
        w.bind("<Right>", self.pressarrowright)
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
        w.bind("<Control-n>", self.newwindow)
        w.bind("<Control-b>", self.newbookmarkstab)
        w.bind("<Control-l>", self.focusaddressbar)
        w.bind("<Control-d>", lambda e: self.toggle_bookmark())
        w.bind("<Key>", self.handlekey)
        w.bind("<Return>", self.pressenter)
        w.bind("<Control-Alt-c>", lambda e: self.toggle_chrome())
        self.canvas = tkinter.Canvas(w, width=WIDTH, height=HEIGHT, bg="white")
        # self.chrome = GUIChrome(self)
        self.chrome = HTMLChrome(self)

    def mainloop(self):
        import tkinter
        tkinter.mainloop()

    def scrollposupdate(self, amount=100):
        self.active_tab.scrollposupdate(amount)
        self.draw()

    def pressarrowleft(self, e):
        if self.chrome.pressarrowleft():
            self.draw()
        elif self.active_tab.pressarrowleft():
            self.draw()

    def pressarrowright(self, e):
        if self.chrome.pressarrowright():
            self.draw()
        elif self.active_tab.pressarrowright():
            self.draw()

    def pressbackspace(self, e):
        if self.chrome.pressbackspace():
            self.draw()
        elif self.active_tab.pressbackspace():
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
        if self.chrome.input(e.char):
            pass
        elif self.focus == "content":
            self.active_tab.input(e.char)
        self.draw()

    def pressenter(self, e):
        if self.chrome.enter():
            pass
        elif self.focus == "content":
            self.active_tab.pressenter()
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
        self.restorestate(isreload=True)

    def restorestate(self, is_startup=False, isreload=False):
        if self.state.get_tab_count() == 0:
            if is_startup:
                self.newtab(None)
            else:
                self.close_window()
        if not self.active_tab:
            self.active_tab = GUIBrowserTab(self)
            self.resize_active_tab()
        self.active_tab.restorestate(isreload=isreload)
        self.draw()
        url = self.state.get_url()
        self.history.visited(url)
        self.history.save()
        self.cookies.save()

    def click(self, e, button):
        x, y = e.x, e.y
        if e.y < self.chrome.bottom:
            self.focus = None
            self.chrome.click(x, y, button)
            self.active_tab.blur()
        else:
            self.focus = "content"
            self.chrome.blur()
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
        self.chrome.resize(self.width, self.height)
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

    def newbookmarkstab(self, e):
        self.state.newtab("about:bookmarks")
        self.chrome.focusaddressbar()
        self.restorestate()
        self.state.save()

    def focusaddressbar(self, e):
        self.chrome.focusaddressbar()

    def addressbarsubmit(self, value):
        if "/" not in value and ":" not in value:
            value = default_search_engine + value
        self.state.pushlocation(value)

    def closetab(self, e):
        self.state.closetab()
        self.restorestate()

    def newwindow(self, e):
        ui = GUIBrowser()
        state = BrowserState(None)
        history = self.history
        bookmarks = self.bookmarks
        ui.start(state, history, bookmarks)

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
        self.draw()

    def close_window(self):
        self.bookmarks.save()
        self.state.save()
        self.history.save()
        self.cookies.save()
        self.window.quit()

    def close_all_windows(self):
        self.bookmarks.save()
        self.state.save()
        self.history.save()
        self.cookies.save()

    def toggle_chrome(self):
        if isinstance(self.chrome, GUIChrome):
            self.chrome = HTMLChrome(self)
        else:
            self.chrome = GUIChrome(self)
        self.chrome.resize(self.width, self.height)
        self.resize_active_tab()
        self.draw()

    def is_js_enabled(self):
        return self.data.is_js_enabled()


class GUIChrome:
    def __init__(self, browser: GUIBrowser):
        self.browser = browser
        self.font = get_font("", 12, "normal", "roman")
        self.font_height = self.font.metrics("linespace")
        self.focus = None
        self.address_bar = ""
        self.address_bar_cursor = 0
        self.resize(browser.width, browser.height)

    def resize(self, width, height):
        # base layout
        self.width = width
        self.padding = 5
        self.tabwidth = 150
        self.tabbar_top = 0
        self.tabbar_bottom = self.font_height + 2 * self.padding
        self.bottom = self.tabbar_bottom + self.font_height + self.padding
        # buttons
        plus_width = self.font.measure("+") + 2 * self.padding
        self.button_width = plus_width
        self.bookmarks_rect = Rect(
            self.padding,
            self.padding,
            self.padding + plus_width,
            self.padding + self.font_height,
        )
        # urlbar
        self.newtab_rect = Rect(
            self.bookmarks_rect.right + self.padding,
            self.padding,
            self.bookmarks_rect.right + self.padding + plus_width,
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

    def click(self, x, y, button):
        state: BrowserState = self.browser.state
        self.focus = None
        if self.newtab_rect.contains_point(x, y):
            state.newtab("about:empty")
        if self.bookmarks_rect.contains_point(x, y):
            self.browser.newbookmarkstab(None)
        elif self.back_rect.contains_point(x, y):
            state.back()
        elif self.forward_rect.contains_point(x, y):
            state.forward()
        elif self.reload_rect.contains_point(x, y):
            self.browser.locationreload(None)
        elif self.bookmark_rect.contains_point(x, y):
            self.browser.toggle_bookmark()
        elif self.address_rect.contains_point(x, y):
            self.focusaddressbar()
        else:
            for i in range(state.get_tab_count()):
                bounds = self.tab_rect(i)
                if bounds.contains_point(x, y):
                    if x > bounds.right - self.padding - self.button_width:
                        state.closetabindex(i)
                    elif button == 1 or button == 3:
                        state.switchtab(i)
                    elif button == 2:
                        state.closetabindex(i)
                    break

    def blur(self):
        self.focus = None

    def focusaddressbar(self):
        self.focus = "address bar"
        self.address_bar = ""
        self.address_bar_cursor = 0

    def pressarrowleft(self):
        if self.focus == "address bar":
            self.move_address_bar_cursor(-1)
            return True
        return False

    def pressarrowright(self):
        if self.focus == "address bar":
            self.move_address_bar_cursor(+1)
            return True
        return False

    def move_address_bar_cursor(self, pos):
        nextpos = self.address_bar_cursor + pos
        if nextpos < 0:
            nextpos = 0
        if nextpos > len(self.address_bar):
            nextpos = len(self.address_bar)
        self.address_bar_cursor = nextpos

    def input(self, input_txt):
        if self.focus == "address bar":
            txt = self.address_bar
            pos = self.address_bar_cursor
            txt = txt[:pos] + input_txt + txt[pos:]
            self.address_bar = txt
            self.move_address_bar_cursor(len(input_txt))
            return True
        return False

    def enter(self):
        if self.focus == "address bar":
            location = self.address_bar
            self.browser.addressbarsubmit(location)
            self.focus = None

    def pressbackspace(self):
        if self.focus == "address bar":
            txt = self.address_bar
            pos = self.address_bar_cursor
            if pos > 0:
                txt = txt[: pos - 1] + txt[pos:]
                self.address_bar = txt
                self.move_address_bar_cursor(-1)
            return True
        return False

    def paint(self):
        width = self.browser.width
        state = self.browser.state
        cmds = []

        cmds.append(DrawRect(Rect(0, 0, width, self.bottom), "white", None))
        cmds.append(DrawLine(0, self.bottom, width, self.bottom, "black", 1))
        self._paint_button(cmds, self.bookmarks_rect, "☰")
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
            textwidth = self.tabwidth
            textbound = Rect(
                bounds.left + self.padding,
                bounds.top + self.padding,
                bounds.right - self.padding,
                bounds.bottom - self.padding,
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
                textwidth = self.tabwidth - self.button_width
                closebound = Rect(
                    bounds.right - self.padding - self.button_width,
                    bounds.top + self.padding,
                    bounds.right - self.padding,
                    bounds.bottom - self.padding,
                )
                self._paint_button(cmds, closebound, "x")

            str = state.get_title_by_index(i)
            substr = ""
            for i in range(len(str) + 1):
                checkstr = str[0:i]
                if len(checkstr) < len(str):
                    checkstr += "..."
                if self.font.measure(checkstr) < textwidth:
                    substr = checkstr
                else:
                    break
            cmds.append(DrawText(textbound, substr, self.font, "black", None))

        # address bar buttons
        back_color = "black" if state.can_back() else "gray"
        forward_color = "black" if state.can_forward() else "gray"
        self._paint_button(cmds, self.back_rect, "<", color=back_color)
        self._paint_button(cmds, self.forward_rect, ">", color=forward_color)
        self._paint_button(cmds, self.reload_rect, "\u21ba")
        bookmark_icon = (
            "\u2605"
            if self.browser.bookmarks.contains(self.browser.state.get_url())
            else "\u2606"
        )
        self._paint_button(cmds, self.bookmark_rect, bookmark_icon)

        # address bar input
        cmds.append(DrawOutline(self.address_rect, "black", 1, None))
        if self.focus == "address bar":
            cmds.append(
                DrawText(
                    self.address_txt_rect, self.address_bar, self.font, "black", None
                )
            )
            text_before_cursor = self.address_bar[: self.address_bar_cursor]
            w = self.font.measure(text_before_cursor)
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
            cmds.append(DrawText(self.address_txt_rect, url, self.font, "black", None))

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
        cmds.append(DrawOutline(outline_rect, color, 1, None))
        cmds.append(DrawText(r, txt, self.font, color, None))



class HTMLChrome:
    def __init__(self, browser):
        self.rect = Rect(0, 0, 600, 80)
        self.bottom = self.rect.bottom
        self._view = HTMLView(self.rect)
        self._renderred_bookmark_icon = ""
        self._renderred_url = ""
        self._renderred_tab_index = -1
        self._parsed_css = False
        self.browser = browser

    def click(self, x, y, button):
        self._view.click(x,y,button)
        node = self._view.click(x,y,button)
        state = self.browser.state
        while node:
            if isinstance(node, Element):
                attr = node.attributes
                action = attr.get("formaction") or attr.get("href")
                
                if action == None:
                    pass
                elif action == "bookmarks":
                    self.browser.newbookmarkstab(None)
                elif action == "newtab":
                    state.newtab("about:blank")
                elif action == "back":
                    state.back()
                elif action == "forward":
                    state.forward()
                elif action == "reload":
                    self.browser.locationreload(None)
                elif action == "bookmark":
                    self.browser.toggle_bookmark()
                elif action.startswith("showtab/"):
                    _, var = action.split("/")
                    if button == 2:
                        state.closetabindex(int(var))
                    else:
                        state.switchtab(int(var))
                elif action.startswith("close/"):
                    _, var = action.split("/")
                    state.closetabindex(int(var))
                elif not action:
                    pass
                else:
                    print("action not handled:", action)
                break
            node=node.parent

    def blur(self):
        self._view.blur()

    def focusaddressbar(self):
        node = query_selector("input", self._view.nodes)
        self._view.focus_on_node(node)
        pass

    def pressarrowleft(self):
        return self._view.pressarrowleft()

    def pressarrowright(self):
        return self._view.pressarrowright()

    def input(self, input_txt):
        return self._view.input(input_txt)

    def enter(self):
        if not self._view.enter() and self._view.focus:
            node = self._view.focus
            if node.attributes.get("name") == "url":
                value = node.attributes.get("value", "")
                self.browser.addressbarsubmit(value)

    def pressbackspace(self):
        return self._view.pressbackspace()

    def resize(self, width, height):
        self.rect = Rect(0, 0, width, height)
        self._view.set_rect(self.rect)
        self._view.layout()
        self._view.paint()

    def paint(self):
        self._renderHTML()
        return self._view.display_list

    def _renderHTML(self):
        state = self.browser.state
        active_tab_index = state.get_active_tab_index()
        url = state.get_url()
        bookmark_icon = (
            "\u2605"
            if self.browser.bookmarks.contains(self.browser.state.get_url())
            else "\u2606"
        )

        # HTML re-render is expensive, check if really needed
        if active_tab_index == self._renderred_tab_index and url == self._renderred_url and bookmark_icon == self._renderred_bookmark_icon:
            return
        self._renderred_tab_index = active_tab_index
        self._renderred_url = url
        self._renderred_bookmark_icon = bookmark_icon

        if not self._parsed_css:
            self._view.set_CSS("""
                body { background:white !important; }
                .bottom { background: black; height: 1px; }
                a { color: black; }
                input { width: 500px }
            """)
            self._parsed_css = True # lazy

        tabs = []
        for i in range(state.get_tab_count()):
            str = state.get_title_by_index(i)
            if len(str) > 20:
                str = str[:20] + "..."
            # TODO escape html
            if i == active_tab_index:
                tabs.append("<b>")
            tabs.append(f"<a href=showtab/{i}>{str}</a>")
            if i == active_tab_index:
                tabs.append(f"</b><a href=close/{i}>x</a>")

        match self.browser.state.get_secure():
            case "yes":
                padlock = "<span style=color:green>\N{lock}</span>"
            case "no":
                padlock = "<span style=color:red>\N{SKULL AND CROSSBONES}</span>"
            case _:
                padlock = ""

        self._view.set_innerHTML(f"""
            <body>
                <div>
                    <a href=bookmarks>☰</a>
                    <a href=newtab>+</a>
                    {"".join(tabs)}
                </div>
                <div>
                    <a href=back>&lt;</a>
                    <a href=forward>&gt;</a>
                    <a href=reload>\u21ba</a>
                    <a href=bookmark>{bookmark_icon}</a>
                    {padlock}
                    <input name=url value="{url}" />
                </div>
                <div class="bottom"></div>
            </body>
        """)
        self._view.layout()
        self._view.paint()
        self.bottom = self._view.scroll_bottom
        self.rect = Rect(0, 0, self.rect.right, self.bottom)


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
        self.focus = None
        self.loaded = ""
        self.loadedpayload = ""
        self.toload = ""
        self.topayload = ""
        self.display_list = []
        self.scroll_bottom = 0
        self.rules = []
        self.modal = None
        self.js = None
        self.url = None

    def browse(self, url):
        self.state.browse(url)
        self.start(self.state)

    def restorestate(self, isreload=False):
        self.scroll = self.state.get_scroll() or 0
        url = self.state.get_url()
        payload = self.state.get_payload()
        if not isreload and url == self.loaded and payload == self.loadedpayload:
            # already loaded
            return
        if payload:
            # with POST request we must get user confirmation
            self.toload = url
            self.topayload = payload
            rect = Rect(0, 0, self.width, self.height)
            dialog = rect.create_dialog(500, 200)
            self.modal = HTMLView(
                dialog,
                """
                <form style=\"background:white;border:2px solid black;padding:16px\">
                    <p>To display this page, the browser must send information that will repeat any action (such as a search or order confirmation) that was performed earlier.</p>
                    <button formaction=submitpayload>Yes</button>
                    <button formaction=closedialog>No</button>
                </form>
            """,
            )
            self.render()
            return
    
        # proceed with loading GET requests only
        self.load(self.state.get_url(), readcache=not isreload)

    def load(self, urlstr, readcache, payload=None, referrer=None, method=None):
        self.loaded = ""
        self.loadedpayload = ""
        if urlstr == "" or urlstr.isspace():
            urlstr = "about:blank"
        self.modal = None
        self.set_title(urlstr)
        try:
            url = URL(urlstr)
        except Exception as err:
            import traceback

            print("Error: failed to parse URL", err)
            print(traceback.format_exc())
            url = URL("about:blank")
        finally:
            self.url = url

        headers = {}
        if url.scheme == "about":  # handle meta pages
            if url.path == "blank":
                result = ""
            elif url.path == "bookmarks":
                result = generate_bookmarks_page(self.browser.bookmarks)
            else:
                raise Exception("about page not found!")
        else:  # external data source
            try:
                headers, result, url = url.request(max_redirect=5, readcache=readcache, payload=payload, cookies=self.browser.cookies, referrer=referrer, method=method)
                if self.url is not url:
                    self.url = url # url may change due to request handling redirect
                self.state.set_secure("yes" if self.url.scheme == "https" else "")
            except Exception as err:
                import ssl
                if isinstance(err, ssl.SSLCertVerificationError):
                    # TODO separate tab state from browser state
                    self.state.set_secure("no")
                print("exception during top level navigation", type(err).__name__, err)
                result = generate_error_page(err, url)
                raise err

        self.allowed_origins = None
        if "content-security-policy" in headers:
            csp = headers["content-security-policy"].split()
            if len(csp) > 0 and csp[0] == "default-src":
                self.allowed_origins = []
                for origin in csp[1:]:
                    self.allowed_origins.append(URL(origin).origin())

        parser_class = HTMLParser if not url.viewsource else HTMLSourceParser

        self.nodes = parser_class(result).parse()

        rules = get_initial_styling_rules()
        self.rules = rules

        nodelist = tree_to_list(self.nodes, [])
        visited_urls = self.browser.history.get_visited_set()
        for node in nodelist:
            if isinstance(node, Element):
                eval_visited(node, url, visited_urls)
                id = node.attributes.get("id")
                if id and self.js:
                    self.js.add_global_name(id, node)
                self.load_node(node)
                # node may have triggered navigation, abort further action on this page
                if url is not self.url:
                    return
        

        # style(self.nodes, sorted(rules, key=cascade_priority))
        # print_tree(self.nodes)

        self.render()
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

        self.loaded = url.get_str()
        self.loadedpayload = payload
        if self.js:
            self.dispatch_js_event("load", self.get_body())

    def load_node(self, node):
        if node.tag == "link":
            self.load_link(node)
        elif node.tag == "style":
            self.rules.extend(CSSParser(node.get_text()).parse())
        elif node.tag == "title":
            self.set_title(node.get_text())
        elif node.tag == "script" and self.is_js_enabled():
            self.load_script(node)

    def load_link(self, node):
        if (
            node.attributes.get("rel") == "stylesheet"
            and "href" in node.attributes
        ):
            link = node.attributes["href"]
            style_url = URL(link, parent=self.url)
            try:
                _, body, url = style_url.request(referrer=self.url)
                self.rules.extend(CSSParser(body).parse())
            except Exception as e:
                print("failed to load stylesheet", style_url, e)

    def load_script(self, node):
        src = node.attributes.get("src")
        script_url = src
        try:
            if src:
                script_url = URL(src, parent=self.url)
                if not self.allowed_request(script_url):
                    print("Blocked script", script_url, "due to CSP")
                    return
                _, code, url = script_url.request(referrer=self.url)
            else:
                script_url = f'{self.url}'
                code = node.get_text()
            self.evaljs(script_url, code)
        except Exception as e:
            print("failed to load script", self.url, script_url, e)

    def unload_node(self, node):
        if node.tag == "link":
            self.unload_link(node)

    def unload_link(self, node):
        if (
            node.attributes.get("rel") == "stylesheet"
            and "href" in node.attributes
        ):
            # inefficient implementation, rebuild rules by reloading all stylesheets
            self.rules = get_initial_styling_rules()
            nodelist = tree_to_list(self.nodes, [])
            for node in nodelist:
                if isinstance(node, Element) and node.tag == "link":
                    self.load_link(node)
        
    def allowed_request(self, url):
        return self.allowed_origins is None or url.origin() in self.allowed_origins

    def render(self):
        self.display_list = []
        if self.nodes:
            style(self.nodes, sorted(self.rules, key=cascade_priority))
            self.document = DocumentLayout(self.nodes)
            self.document.set_size(self.width, self.height)
            self.document.set_step(self.hstep, self.vstep)
            self.document.layout()
            self.scroll_bottom = self.document.height
            paint_tree(self.document, self.display_list)
        if self.modal:
            rect = Rect(0, 0, self.width, self.height)
            self.display_list.append(DrawRect(rect, "black", None, opacity=0.2))

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

        if self.modal:
            for cmd in self.modal.display_list:
                cmd.execute(-self.modal.rect.top-self.top, canvas, hscroll=-self.modal.rect.left)

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

    def do_default(self, node, event_type):
        if event_type == "click":
            button = 1 # TODO grab from event
            self.handle_default_click(node, button)

    def click(self, x, y, button):

        if self.modal:
            node = self.modal.click(x,y,button)
            if isinstance(node, Element):
                action = node.attributes.get("formaction")
                if action == "submitpayload":
                    self.load(self.toload, readcache=False, payload=self.topayload)
                if action == "closedialog":
                    self.modal = None
                self.render()
            return

        if self.focus:
            self.focus.is_focused = False
            self.focus = None
        node = None

        y += self.scroll

        for item in reversed(self.display_list):
            if not item.rect.contains_point(x, y):
                continue
            if not hasattr(item, "node"):
                continue
            node = item.node
            break
        
        self.click_node(node, button)

    def click_node(self, node, button):
        if self.dispatch_js_event('click', node): 
            return
        self.handle_default_click(node, button)
    
    def handle_default_click(self, node, button):
        need_render = False
        form_submit = False
        form = None
        travelurl = ""
        while node:
            if isinstance(node, Element):
                if node.tag == "a" and "href" in node.attributes:
                    travelurl = self.resolve_url(node.attributes["href"])
                    self.focus = node
                elif node.tag == "input":
                    if self.dispatch_js_event('click', node):
                        return
                    input_element_handle_click(node)
                    need_render = True
                    self.focus = node
                elif node.tag == "button":
                    if self.dispatch_js_event('click', node):
                        return
                    form_submit = True
                    self.focus = node
                elif node.tag == "form" and "action" in node.attributes:
                    form = node
            node = node.parent

        if self.focus:
            self.focus.is_focused = True

        if need_render:
            self.render()

        if form_submit and form:
            self.submit_form(form)

        if travelurl:
            if button == 1:
                # TODO add referrer to pushlocation to validate samesite
                self.state.pushlocation(travelurl)
                self.restorestate()
            elif button == 2:
                # TODO add referrer to validate samesite
                self.state.newtab(travelurl)
                self.restorestate()
            else:
                pass

    def blur(self):
        if self.focus:
            self.focus.is_focused = False
            self.focus = None
            self.render()

    def input(self, txt):
        if self.focus:
            if self.dispatch_js_event("keydown", self.focus):
                return True
            if input_element_handle_input(self.focus, txt):
                self.render()
                return True
        return False

    def pressarrowright(self):
        if not self.focus:
            return False
        if self.dispatch_js_event("keydown", self.focus):
            return True
        if input_element_move_cursor(self.focus, +1):
            self.render()
            return True
        return False

    def pressarrowleft(self):
        if not self.focus:
            return False
        if self.dispatch_js_event("keydown", self.focus):
            return True
        if input_element_move_cursor(self.focus, -1):
            self.render()
            return True
        return False

    def pressbackspace(self):
        if self.focus:
            if self.dispatch_js_event("keydown", self.focus):
                pass
            elif input_element_handle_backspace(self.focus):
                self.render()
            return True
        return False

    def pressenter(self):
        if self.focus:
            if self.dispatch_js_event("keydown", self.focus):
                return
            self.submit_form(self.focus)

    def resize(self, width, height):
        if self.width == width and self.height == height:
            return
        self.width = width
        self.height = height
        if self.nodes:
            self.render()
            self.limitscrollinbounds()

    def set_title(self, titlestr):
        self.state.set_title(titlestr)
        self.browser.title(titlestr)

    def get_title(self):
        return self.state.get_title()

    def get_body(self):
        return self.nodes.body

    def submit_form(self, form):
        while form and form.tag != "form":
            form = form.parent

        if not form:
            return
        
        if self.dispatch_js_event("submit", form):
            return

        inputs = [
            node
            for node in tree_to_list(form, [])
            if isinstance(node, Element)
            and node.tag == "input"
            and "name" in node.attributes
        ]
        method = form.attributes.get("method", "post").strip().casefold()
        body = ""
        for input in inputs:
            import urllib.parse

            type = input.attributes.get("type")
            name = input.attributes["name"]
            value = input.attributes.get("value", "")
            name = urllib.parse.quote(name)
            value = urllib.parse.quote(value)
            if type == "checkbox":
                if not hasattr(input, "ischecked") or not input.ischecked:
                    continue
            # TODO this is not secure, need to escape values
            body += "&" + name + "=" + value
        body = body[1:]
        href = form.attributes.get("action", "")
        if method == "get":
            href += "?" + body
            body = None

        method=method.upper()
        url = self.resolve_url(href)
        # TODO security reasons we should add referrer to state location history as well
        # so the brower restore cannot be attacked by CSRF
        self.state.pushlocation(url, payload=body, method=method)
        # load should be last instruction as it can do a lot
        self.load(url, readcache=False, payload=body, referrer=self.url, method=method)


    def is_js_enabled(self):
        if self.js:
            return True
        if self.js is False:
            return False
        if self.browser.is_js_enabled():
            if JSContext.is_feature_avaiable():
                return True
        self.js = False
        return False

    def evaljs(self, url, code):
        if not self.js and self.is_js_enabled():
            self.js = JSContext(self)
        self.js.run(url, code)

    def dispatch_js_event(self, type, node):
        return self.js and self.js.dispatch_event(type, node)

    def resolve_url(self, urlstr):
        parent = URL(self.state.get_url())
        return URL(urlstr, parent=parent).get_str()


class HTMLView:
    def __init__(self, rect, html=""):
        self.set_rect(rect)
        self.set_CSS("")
        self.set_innerHTML(html)
        self.focus = None

    def set_rect(self, rect):
        self.rect = rect
        self.width = rect.right - rect.left
        self.height = rect.bottom - rect.top

    def set_CSS(self, csstext):
        self.rules = get_initial_styling_rules()
        self.rules.extend(CSSParser(csstext).parse())

    def set_innerHTML(self, html):
        self.nodes = HTMLParser(html).parse()
        self.render()

    def render(self):
        self.layout()
        self.paint()

    def layout(self):
        style(self.nodes, sorted(self.rules, key=cascade_priority))
        self.document = DocumentLayout(self.nodes)
        self.document.set_size(self.width, self.height)
        self.document.set_step(0, 0)
        self.document.layout()
        self.scroll_bottom = self.document.height
    
    def paint(self):
        self.display_list = []
        paint_tree(self.document, self.display_list)

    def focus_on_node(self, node):
        self.blur()
        # assmes node is from this view
        self.focus = node
        if node:
            self.focus.is_focused = True
        
    def input(self, input_txt):
        if self.focus and self.focus.tag == "input":
            if input_element_handle_input(self.focus, input_txt):
                self.paint()
                return True
        return False

    def pressbackspace(self):
        if self.focus and self.focus.tag == "input":
            if input_element_handle_backspace(self.focus):
                self.paint()
                self.address_bar = self.focus.attributes.get("value", "")
            return True
        return False

    def pressarrowleft(self):
        return self._movecursor(-1)

    def pressarrowright(self):
        return self._movecursor(+1)

    def _movecursor(self, amount):
        if self.focus and self.focus.tag == "input":
            if input_element_move_cursor(self.focus, amount):
                self.paint()
                return True
        return False
        
    def enter(self):
        return False

    def click(self, x, y, button):
        x -= self.rect.left
        y -= self.rect.top
        if self.focus:
            self.focus.is_focused = False
            self.focus = None
        for item in reversed(self.display_list):
            if not item.rect.contains_point(x, y):
                continue
            if not hasattr(item, "node"):
                continue
            node = item.node
            break
        need_render = False
        while node:
            # logic is somewhat duplicated from browser tab
            if isinstance(node, Element):
                if node.tag == "a" and "href" in node.attributes or node.tag == "button":
                    self.focus = node
                if node.tag == "input":
                    input_element_handle_click(node)
                    need_render = True
                    self.focus = node
            node = node.parent

        if self.focus:
            self.focus.is_focused = True

        if need_render:
            self.render()

        return self.focus

    def blur(self):
        if self.focus:
            self.focus.is_focused = False
            self.focus = None
            self.render()


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

    def should_paint(self):
        return True

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

    def should_paint(self):
        return (
            isinstance(self.node, list)
            or isinstance(self.node, Text)
            or (self.node.tag != "input" and self.node.tag != "button")
        )

    def paint(self):
        cmds = []

        if isinstance(self.node, Element):
            bgcolor = self.node.style.get("background-color", "transparent")

            if bgcolor != "transparent":
                rect = DrawRect(self.self_rect(), bgcolor, self.node)
                cmds.append(rect)

            if self.node.tag == "li":
                x = self.x - 8
                y = self.y + 14
                rect = Rect(x - 2, y - 2, x + 2, y + 2)
                cmd = DrawRect(rect, "#000", self.node)
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

    def recurse(self, node):
        if isinstance(node, Text):
            self.word(node)
        else:
            self.open_tag(node.tag)
            if node.tag == "input" or node.tag == "button":
                self.input(node)
            else:
                for child in node.children:
                    self.recurse(child)
            self.close_tag(node.tag)

    def input(self, node):
        w = InputLayout.determine_width(node)
        if self.cursor_x + w > self.width:
            self.newline()
        line = self.children[-1]
        previous_word = line.children[-1] if line.children else None
        input = InputLayout(node, line, previous_word)
        line.children.append(input)

        weight = node.style["font-weight"]
        style = node.style["font-style"]
        if style == "normal":
            style = "roman"
        size = int(parse_size(node.style["font-size"]) * 0.75)
        font = get_font("", size, weight, style)

        self.cursor_x += w + font.measure(" ")

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
                size = int(parse_size(size_str) * 0.75)
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
    def __init__(self, node, parent, previous, textalign="left"):
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
            max_ascent = max([word.get_ascent() for word in self.children])
            baseline = self.y + 1.25 * max_ascent
            for word in self.children:
                word.y = baseline - word.get_ascent()
            max_descent = max([word.get_descent() for word in self.children])

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

    def should_paint(self):
        return True

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
                size = int(parse_size(size_str) * 0.75)
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

    def get_ascent(self):
        return self.font.metrics("ascent")

    def get_descent(self):
        return self.font.metrics("descent")

    def should_paint(self):
        return True

    def paint(self):
        rect = Rect(self.x, self.y, self.x + self.width, self.y + self.height)
        return [DrawText(rect, self.word, self.font, self.color, self.node)]

    def __repr__(self):
        return f"Text {repr(self.word)} {self.x},{self.y} {self.width},{self.height}"


class InputLayout:
    CHECKBOX_SIZE = 16

    def determine_width(node):
        nodetype = node.attributes.get("type")
        if nodetype == "hidden":
            return 0
        if nodetype == "checkbox":
            return InputLayout.CHECKBOX_SIZE
        stylewidth = node.style.get("width")
        if stylewidth:
            return parse_size(stylewidth)
        return 200

    def __init__(self, node, parent, previous):
        self.node = node
        self.children = []
        self.parent = parent
        self.previous = previous
        self.ptop = 0
        self.pbottom = 0

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
                size = int(parse_size(size_str) * 0.75)
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

        self.color = node.style.get("color", "black")
        self.font = get_font(font_family, size, weight, style)

        self.width = InputLayout.determine_width(self.node)

        thickness = 0
        border = self.node.style.get("border-style")
        if border and border != "none" and border != "hidden":
            border_width = self.node.style.get("border-width")
            thickness = parse_size(border_width)

        ptop = pbottom = thickness
        ptop += parse_size(self.node.style.get("padding-top"))
        pbottom += parse_size(self.node.style.get("padding-bottom"))
        self.ptop = ptop
        self.pbottom = pbottom

        if self.previous:
            space = self.previous.font.measure(" ")
            self.x = self.previous.x + space + self.previous.width
        else:
            self.x = self.parent.x

        if node.attributes.get("type") == "checkbox":
            self.width = InputLayout.CHECKBOX_SIZE
            self.height = InputLayout.CHECKBOX_SIZE
            return

        self.height = self.font.metrics("linespace") + ptop + pbottom
        self.y = self.parent.y

        if node.tag == "button" and not (len(self.node.children) == 1 and isinstance(self.node.children[0], Text)):
            list = []
            previous = None
            for item in node.children:
                if item.style.get("display", "inline") == "inline":
                    list.append(item)
                else:
                    if list:
                        child = BlockLayout(list, self, previous)
                        self.children.append(child)
                        previous = child
                        list = []
                    
                    child = BlockLayout(item, self, previous)
                    self.children.append(child)
                    previous = child
            if list:
                child = BlockLayout(list, self, previous)
                self.children.append(child)
                previous = child

            for child in self.children:
                child.set_size(self.width, self.height)
                child.set_step(0, 0)
                child.x = self.x
                child.y = self.y
                child.layout()

    def should_paint(self):
        if self.node.attributes.get("type") == "hidden":
            return False
        return True

    def paint(self):
        cmds = []
        bgcolor = self.node.style.get("background-color", "transparent")
        drawtext = True
        drawcheck = False
        type = self.node.attributes.get("type")

        if type == "checkbox":
            drawtext = False
            drawcheck = True

        if self.children:
            drawtext = False

        if bgcolor != "transparent":
            rect = DrawRect(self.self_rect(), bgcolor, self.node)
            cmds.append(rect)

        thickness = 0
        border = self.node.style.get("border-style")
        if border and border != "none" and border != "hidden":
            border_color = self.node.style.get("border-color")
            border_width = self.node.style.get("border-width")
            thickness = parse_size(border_width)
            cmds.append(
                DrawOutline(self.self_rect(), border_color, thickness, self.node)
            )

        ptop = pright = pbottom = pleft = thickness
        ptop += parse_size(self.node.style.get("padding-top"))
        pright += parse_size(self.node.style.get("padding-right"))
        pbottom += parse_size(self.node.style.get("padding-bottom"))
        pleft += parse_size(self.node.style.get("padding-left"))

        text = self.get_text()
        if type == "password":
            text = "*" * len(text)
        textwidth = self.font.measure(text)
        align = self.node.style.get("text-align")
        if align == "center":
            rect = Rect(
                self.x + (self.width - textwidth) // 2,
                self.y + ptop,
                self.x + self.width - pright,
                self.y + self.height - pbottom,
            )
        else:
            rect = Rect(
                self.x + pleft,
                self.y + ptop,
                self.x + self.width - pright,
                self.y + self.height - pbottom,
            )

        if drawtext:
            cmds.append(DrawText(rect, text, self.font, self.color, self.node))

            if self.node.is_focused:
                pos = self.node.cursor
                text_to_measure = text[0:pos]
                textwidth = self.x + self.font.measure(text_to_measure)
                cmds.append(
                    DrawLine(
                        textwidth + pleft,
                        self.y + ptop,
                        textwidth + pleft,
                        self.y + self.height - pbottom,
                        "black",
                        1,
                    )
                )
        if drawcheck:
            if hasattr(self.node, "ischecked") and self.node.ischecked:
                cmds.append(DrawRect(self.self_rect(3), "black", self.node))


        return cmds

    def get_text(self):
        if self.node.tag == "input":
            text = self.node.attributes.get("value", "")
        elif self.node.tag == "button":
            if len(self.node.children) == 1 and isinstance(self.node.children[0], Text):
                text = self.node.children[0].text
            else:
                text = ""
        return text

    def get_ascent(self):
        return self.font.metrics("ascent") + self.ptop

    def get_descent(self):
        return self.font.metrics("descent") + self.pbottom

    def self_rect(self, pad=0):
        return Rect(
            self.x + pad,
            self.y + pad,
            self.x + self.width - pad,
            self.y + self.height - pad,
        )

    def __repr__(self):
        return f"Input {self.x},{self.y} {self.width},{self.height}"


def paint_tree(layout_object, display_list):
    if layout_object.should_paint():
        display_list.extend(layout_object.paint())

    for child in layout_object.children:
        paint_tree(child, display_list)


def query_selector(selector, node):
    css = CSSParser(selector + "{ color: red }").parse()
    # baseurl = ""
    for node in tree_to_list(node, []):
        # eval_visited(node, baseurl, visited)
        for rule in css:
            if rule[0].matches(node):
                return node
    return None


def query_selector_all(selector, node):
    css = CSSParser(selector + "{ color: red }").parse()
    result = []
    # baseurl = ""
    for node in tree_to_list(node, []):
        # eval_visited(node, baseurl, visited)
        for rule in css:
            if rule[0].matches(node):
                result.append(node)
    return result


def get_font(family, size, weight, style):
    FONTS = font_cache
    key = (family, size, weight, style)
    if key not in FONTS:
        import tkinter.font

        font = tkinter.font.Font(family=family, size=size, weight=weight, slant=style)
        label = tkinter.Label(font=font)
        FONTS[key] = (font, label)
    return FONTS[key][0]


def get_initial_styling_rules():
    global default_style_sheet

    if default_style_sheet is None:
        with open("browser.css") as f:
            text = f.read()
            default_style_sheet = CSSParser(text).parse()

    return default_style_sheet.copy()


class DrawText:
    def __init__(self, rect, text, font, color, node):
        self.rect = rect
        self.text = text
        self.font = font
        self.color = color
        self.node = node

    def execute(self, scroll, canvas, hscroll=0):
        canvas.create_text(
            self.rect.left - hscroll,
            self.rect.top - scroll,
            text=self.text,
            font=self.font,
            anchor="nw",
            fill=self.color,
        )


class DrawRect:
    def __init__(self, rect, color, node, opacity=1.0):
        self.rect = rect
        self.color = color
        self.node = node
        self.fill = color
        if opacity > 0.9:
            self.stipple = None
        elif opacity > 0.6:
            self.stipple = "gray75"
        elif opacity > 0.3:
            self.stipple = "gray50"
        elif opacity > 0.1:
            self.stipple = "gray25"
        else:
            self.stipple = None
            self.fill = None

    def execute(self, scroll, canvas, hscroll=0):
        canvas.create_rectangle(
            self.rect.left - hscroll,
            self.rect.top - scroll,
            self.rect.right - hscroll,
            self.rect.bottom - scroll,
            width=0,
            fill=self.fill,
            stipple=self.stipple,
        )


class DrawOutline:
    def __init__(self, rect, color, thickness, node):
        self.rect = rect
        self.color = color
        self.thickness = thickness
        self.node = node

    def execute(self, scroll, canvas, hscroll=0):
        canvas.create_rectangle(
            self.rect.left - hscroll,
            self.rect.top - scroll,
            self.rect.right - hscroll,
            self.rect.bottom - scroll,
            width=self.thickness,
            outline=self.color,
        )


class DrawLine:
    def __init__(self, x1, y1, x2, y2, color, thickness):
        self.rect = Rect(x1, y1, x2, y2)
        self.color = color
        self.thickness = thickness

    def execute(self, scroll, canvas, hscroll=0):
        canvas.create_line(
            self.rect.left - hscroll,
            self.rect.top - scroll,
            self.rect.right - hscroll,
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

    def create_dialog(self, width, height):
        left = (self.left + self.right - width) // 2
        top = (self.top + self.bottom - height) // 2
        right = left + width
        bottom = top + height
        return Rect(
            max(self.left, left),
            max(self.top, top),
            min(self.right, right),
            min(self.bottom, bottom),
        )

    def pad(self, amount):
        return Rect(
            self.left + amount,
            self.top + amount,
            self.right - amount,
            self.bottom - amount,
        )


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
        "&rsquo;":"’",
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
            elif open_tags and open_tags[-1] == tag and tag in ["p", "li", "button"]:
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
        elif prop == "border":
            width = "1px"
            style = "solid"
            color = "black"
            parsed_size = False
            parsed_color = False
            for item in expression:
                if item in [
                    "solid",
                    "dotted",
                    "dashed",
                    "inset",
                    "outset",
                    "ridge",
                    "groove",
                    "double",
                    "none",
                    "hidden",
                ]:
                    style = item
                elif not parsed_size:
                    width = item
                    parsed_size = True
                elif not parsed_color:
                    color = item
                    parsed_color = True
            pairs["border-width"] = width
            pairs["border-style"] = style
            pairs["border-color"] = color
        elif prop == "padding":
            top = right = bottom = left = "0px"
            if len(expression) >= 4:
                top = expression[0]
                right = expression[1]
                bottom = expression[2]
                left = expression[3]
            elif len(expression) == 3:
                top = expression[0]
                right = left = expression[1]
                bottom = expression[2]
            elif len(expression) == 2:
                top = bottom = expression[0]
                right = left = expression[1]
            elif len(expression) == 1:
                top = right = bottom = left = expression[0]
            pairs["padding-top"] = top
            pairs["padding-right"] = right
            pairs["padding-bottom"] = bottom
            pairs["padding-left"] = left

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
    "text-align": "left",
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
        parent_px = parse_size(parent_font_size[:-2])
        node.style["font-size"] = str(node_pct * parent_px) + "px"

    for child in node.children:
        style(child, rules, depth=depth + 1)


def cascade_priority(rule):
    selector, body = rule
    return selector.priority


def parse_size(str):
    if not str:
        return 0.0
    if str == "0":
        return 0.0
    if str.endswith("px"):
        return float(str[:-2])
    if str.endswith("%"):
        return float(str[:-1]) / 100.0 * 16.0  # incorrect
    if str.endswith("rem"):
        return float(str[:-3]) * 16.0  # incorrect
    if str.endswith("em"):
        return float(str[:-2]) * 16.0  # incorrect
    else:
        return 16.0  # unhandle dformat


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
    test_CookieJar()
    test_parse_http_date()


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

    # TODO
    # results = parse("div { color: #000!important; }")
    # assert results[0][1]["color"] == "#000"

    results = parse("h1 { border: 1px solid black; }")
    assert results[0][1]["border-width"] == "1px"
    assert results[0][1]["border-style"] == "solid"
    assert results[0][1]["border-color"] == "black"


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
    assert url.get_str() == "https://example.org:8080/"

    url = URL("file:///path/to/file/index.html")
    assert url.scheme == "file"
    assert url.path == "/path/to/file/index.html"

    url = URL("data:text/html,Hello world!")
    assert url.scheme == "data"
    assert url.mimetype == "text/html"
    assert url.content == "Hello world!"
    _, content, url = url.request()
    assert content == "Hello world!"
    assert url.scheme == "data"

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
    assert url.host == ""
    assert url.path == "C:/Users/someone/index.html"

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

    url = URL("about:blank")
    assert url.scheme == "about"
    assert url.path == "blank"
    assert url.get_str() == "about:blank"

    url = URL("file://C:\\www\\page.html")
    url = URL("main.js", parent=url)
    assert url.scheme == "file"
    assert url.path == "C:/www/main.js"

    url = URL("localhost:8000")
    assert url.scheme == "http"
    assert url.port == 8000
    assert url.path == "/"
    assert url.origin() == "http://localhost:8000"


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

    # with payload
    state.pushlocation("https://example.com", payload="&subscribe=on")
    assert state.get_payload() == "&subscribe=on"
    state.pushlocation("https://another.com")
    assert state.get_payload() is None
    state.back()
    assert state.get_payload() == "&subscribe=on"

    # with method
    state.pushlocation("https://example.com", method="POST")
    assert state.get_method() == "POST"

    # get/set secure
    state.pushlocation("https://something.com")
    assert state.get_secure() == ""
    state.set_secure("yes")
    assert state.get_secure() == "yes"


def test_BrowserBookmarks():
    bm = BrowserBookmarks(None)
    assert bm.get_count() == 0
    bm.toggle("https://example.com", "Example")
    assert bm.get_count() == 1
    assert bm.contains("https://example.com")
    assert bm.get_urls() == ["https://example.com"]
    assert bm.get_title("https://example.com") == "Example"
    bm.toggle("https://example.com", "Example")
    assert bm.get_count() == 0


def test_CookieJar():
    cj = CookieJar(None)
    
    # basic get/set
    cj.set_cookie_by_host("a", "test=4")
    assert cj.get_cookie_value_by_host("a") == "test=4"

    # set multiple cookies
    cj.set_cookie_by_host("b", "test=4")
    cj.set_cookie_by_host("b", "other=9")
    assert cj.get_cookie_value_by_host("b") == "test=4; other=9"

    # http only
    cj.set_cookie_by_host("c", "session=1; HttpOnly")
    assert cj.get_cookie_value_by_host("c", is_script=True) == ""
    cj.set_cookie_by_host("c", "session=2", is_script=True)
    assert cj.get_cookie_value_by_host("c", is_script=True) == ""
    assert cj.get_cookie_value_by_host("c") == "session=1"

    # expires
    cj.set_cookie_by_host("d", "value=4")


def test_parse_http_date():
    parse = parse_http_date
    fmt = format_http_date
    assert fmt(0) == "Thu, 01 Jan 1970 00:00:00 GMT"
    assert parse("Thu, 01 Jan 1970 00:00:00 GMT") == 0
    assert parse("Tue, 29 Oct 2024 16:56:32 GMT") == 1730220992
    assert fmt(1730220992) == "Tue, 29 Oct 2024 16:56:32 GMT"


def integration_test(browser, testsuite):
    import os
    import time

    bail = True
    totalstart = time.time()
    wdata = BrowserData()
    wdata.makeprivate()
    wdata.restore()
    browser.setup(wdata)
    wtestdir = URL(testsuite, parent=URL(__file__)).path
    browser.state.newtab("about:blank")
    failed = []
    raised = []
    items = os.listdir(wtestdir)
    reset = "\x1b[30m"
    procenv = None
    portstr = None
    for item in items:
        try:
            proc = None
            start = time.time()
            itempath = wtestdir + "/" + item
            browsepath = itempath

            if item.endswith(".py"):
                global http_cache
                import subprocess
                import sys

                http_cache = {}  # wipe http cache

                if not portstr:
                    portstr = "9099"

                if not procenv:
                    procenv = os.environ.copy()
                    procenv["DEFAULT_HTTP_PORT"] = portstr
                    procenv["PYTHONPATH"] = os.path.dirname(__file__)
                proc = subprocess.Popen([sys.executable, itempath], env=procenv)
                browsepath = "http://localhost:" + portstr
                time.sleep(0.1) # wait for process to open port

            browser.state.replacelocation(browsepath, None)
            browser.restorestate()
            end = time.time()
            itempassed = browser.state.get_title() == "passed"
            if not itempassed:
                failed.append(item)
            ms = int((end-start)*1000)
            print(item, itempassed, ms, "ms")
        except Exception as err:
            import traceback
            print("Error: exception during wtest", item, err)
            print(traceback.format_exc())
            raised.append(err)
        finally:
            if proc:
                proc.kill()
        if bail and (failed or raised):
            raise Exception("pass condition not met", failed)

    browser.state.closetab()
    totalend = time.time()
    totalms = int((totalend - totalstart)*1000)
    if len(failed) != 0:
        print("\x1b[31mwtest failed", failed, "test(s)", totalms, "ms", reset, "\x1b[0m")
        raise raised[0] if len(raised) > 0 else Exception("wtest condition not met")
    else:
        print("\x1b[32m{} all tests passed!".format(testsuite), totalms, "ms", reset, "\x1b[0m")


def test_all():
    import sys
    import subprocess


    # TODO currently there is a bug when the browser initializes multiple times
    # we currently use subprocesses to stabilize the runs
    for item in [
        [sys.executable, sys.argv[0], "--test", "--wtest", "--exit"],
        [sys.executable, sys.argv[0], "--wstest", "--exit"],
    ]:
        p = subprocess.Popen(item)
        p.wait()
        if p.returncode != 0:
            sys.exit(p.returncode)


if __name__ == "__main__":
    import sys

    ui = GUIBrowser()
    data = BrowserData()
    parsearg = None
    for arg in sys.argv[1:]:
        if parsearg:
            if parsearg == "--profile-dir":
                data.usedir(arg)
            parsearg = None
        elif arg.startswith("-"):
            flag = arg
            if "--private" == flag:
                data.makeprivate()
            elif "--disable-javascript" == flag or "--nojs" == flag:
                data.disablejs()
            elif "--gui" == flag:
                ui = GUIBrowser()
            elif "--cli" == flag:
                ui = CLI()
            elif "--test" == flag:
                test()
            elif "--wtest" == flag:
                integration_test(ui, "wtest")
            elif "--wstest" == flag:
                integration_test(ui, "wstest")
            elif "--version" == flag:
                print("1.0.0")
            elif "--help" == flag:
                print("gal web browser")
            elif "--exit" == flag:
                sys.exit(0)
            elif "--testall" == flag or "--test-all" == flag:
                test_all()
            elif flag == "--rtl":
                default_rtl = True
            elif flag in ["--cache-dir", "--profile-dir", "--profile"]:
                parsearg = "--profile-dir"
            else:
                raise Exception(f"unknown flag '{flag}'")
        else:
            url = arg
            data.state.newtab(url)

    try:
        data.restore()
        ui.setup(data)
    except Exception as err:
        import traceback

        print("Error: failed to restore browser state", err)
        print(traceback.format_exc())

    ui.mainloop()
