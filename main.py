

class URL:
    def __init__(self, url):
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
    
    def request(self):
        if self.scheme == "file":
            return self.requestFile()
        else:
            return self.requestSocket()

    def requestFile(self):
        with open(self.path) as f:
            return f.read()

    def requestSocket(self):
        import socket

        reqlines = [
            f'GET {self.path} HTTP/1.1\r\n',
            f'Host: {self.host}\r\n',
            f'Connection: close\r\n'
            '\r\n',
        ]
        request = "".join(reqlines)

        s = socket.socket(
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
        s.connect((self.host, self.port))
        if self.scheme == "https":
            import ssl
            ctx = ssl.create_default_context()
            s = ctx.wrap_socket(s, server_hostname=self.host)
        
        bytessent = s.send(request.encode('utf8'))
        response = s.makefile("r", encoding="utf8", newline="\r\n")

        statusline = response.readline()
        version, status, explanation = statusline.split(" ",2)
        print(status, explanation.strip(), "GET", self.host, self.path)
        response_headers = {}
        while True:
            line = response.readline()
            if line == "\r\n": break
            header, value = line.split(":", 1)
            response_headers[header.casefold()] = value.strip()
        
        # content encoding not supported
        assert "transfer-encoding" not in response_headers
        assert "content-encoding" not in response_headers
        
        content = response.read()
        
        s.close()
        return content


def show(body):
    in_tag = False
    for c in body:
        if c == "<":
            in_tag = True
        elif c == ">":
            in_tag = False
        elif not in_tag:
            print(c, end="")


def browse(urlstr):
    print("navigating to", urlstr)
    url = URL(urlstr)
    result = url.request()
    show(result)
    

def test():
    print("running tests")

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

if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        test()
    elif "--version" in sys.argv:
        print("1.0.0")
    elif "--help" in sys.argv:
        print("gal web browser")
    elif len(sys.argv) == 2:
        browse(sys.argv[1])
    else:
        print("unknowns args")
        sys.exit(1)