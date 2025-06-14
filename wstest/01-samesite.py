# web service test 01 - samesite cookies
# tests if a web browser handles samesite lax, strict or none properly
#
# 1. test will print URL that browser needs to access
# 2. process exits with code 0 on success
# 3. process exits with code 1 on failure

import socket

class HttpRequest:
    def __init__(self, conx, addr):
        self.conx = conx
        self.addr = addr
        self.body = None
        self.status = 200
        self.explanation = "OK"
        self.is_closed = False
        self.response_headers = {}
        self.body = ""
        req = conx.makefile("b")
        reqline = req.readline().decode("utf8")
        method, path, version = reqline.split(" ", 2)
        headers = {}
        self.method = method
        self.path = path
        self.version = version

        # IMPORTANT: assumes request is well form
        while True:
            line = req.readline().decode("utf8")
            if line == "\r\n":
                break
            header, value = line.split(":", 1)
            headers[header.casefold()] = value.strip()

            if "content-length" in headers:
                length = int(headers["content-length"])
                self.body = req.read(length).decode("utf8")

    def set_status(self, status, explanation=""):
        self.status = status
        self.explanation = explanation

    def set_header(self, key, value):
        self.response_headers[key] = value

    def set_body(self, body):
        self.body = body

    def send_response(self, body=None):
        if self.is_closed:
            return
        response = "HTTP/1.0 {} {}\r\n".format(self.status, self.explanation)
        for key, value in enumerate(self.response_headers):
            response += "{}: {}\r\n".format(key, value)
        response += "Content-Length: {}\r\n".format(len(self.body.encode("utf8")))
        response += "\r\n" + self.body
        self.conx.send(response.encode("utf8"))
        self.conx.close()
        self.is_closed = True

# TODO: might need to extract this
class HttpServer:
    def __init__(self, request_handler):
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        self.s.bind(("", 0))
        self.print_requests = True
        self.request_handler = request_handler

    def get_address(self) -> str:
        addr = self.s.getsockname()
        return "http://{}:{}".format(addr[0], addr[1])

    # NOTE: never returns
    def listen(self):
        self.s.listen()
        while True:
            conx, addr = self.s.accept()
            res = HttpRequest(conx, addr)
            try: 
                result = self.request_handler(res)
                if result:
                    if isinstance(result, str):
                        res.set_body(result)
                    elif isinstance(result, int):
                        res.set_status(result)
            except Exception as e:
                res.set_status(500, "Internal Server Error")
                res.set_body(str(e))
            if self.print_requests:
                print("{} {} {}".format(res.method, res.path, res.status))
            res.send_response()

server = HttpServer(lambda x: 404)
print(server.get_address())
server.listen()