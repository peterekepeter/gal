import socket
import os
import threading


class Request:
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
        self.headers = {}
        self.method = method
        self.path = path
        self.version = version

        # IMPORTANT: assumes request is well form
        while True:
            line = req.readline().decode("utf8")
            if line == "\r\n":
                break
            header, value = line.split(":", 1)
            self.headers[header.casefold()] = value.strip()

            if "content-length" in self.headers:
                length = int(self.headers["content-length"])
                self.body = req.read(length).decode("utf8")

    def set_status(self, status, explanation=""):
        self.status = status
        self.explanation = explanation

    def set_status_text(self, status_text):
        self.explanation = status_text

    def set_header(self, key, value):
        self.response_headers[key] = value

    def get_header(self, key):
        return self.headers.get(key.casefold(), "")

    def set_body(self, body):
        self.body = body

    def send_response(self, body=None):
        if self.is_closed:
            return
        response = "HTTP/1.0 {} {}\r\n".format(self.status, self.explanation)
        for key in self.response_headers:
            response += "{}: {}\r\n".format(key, self.response_headers[key])
        response += "Content-Length: {}\r\n".format(len(self.body.encode("utf8")))
        response += "\r\n" + self.body
        self.conx.send(response.encode("utf8"))
        self.conx.close()
        self.is_closed = True


class Html:
    def __init__(self, content):
        self.content = content


class Text:
    def __init__(self, content):
        self.content = content


class JavaScript:
    def __init__(self, content):
        self.content = content


class Header:
    def __init__(self, key, value):
        self.key = key
        self.value = value


class ExitServer:
    pass


class ExitProcess:
    def __init__(self, code=0):
        self.code = code


# TODO: might need to extract this
class HttpServer:
    def __init__(
        self,
        handler,
        address="localhost",
        port=None,
        print_address=True,
        print_requests=True,
    ):
        if port is None:
            port = int(os.environ.get("DEFAULT_HTTP_PORT", "8000"))
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._address = address
        self._bind_address = address if address != "localhost" else "127.0.0.1"
        self._bind_port = port
        self.s.bind((self._bind_address, self._bind_port))
        self.print_requests = print_requests
        self.handler = handler
        self.is_exit = False
        self.is_exit_process = False
        self.exit_process_code = 0
        if print_address:
            print("listening on", self.get_address())

    def get_address(self, localhost=True) -> str:
        host = self._address
        port = self._bind_port
        if not port:
            addr = self.s.getsockname()
            port = addr[1]
        if host == "0.0.0.0":
            host = "127.0.0.1"  # make it a valid address
        return "http://{}:{}".format(host, port)

    def get_address_ip(self) -> str:
        return self.get_address(localhost=False)

    def get_address_localhost(self) -> str:
        return self.get_address(localhost=True)

    # NOTE: never returns
    def listen(self):
        self.s.listen()
        while not self.is_exit:
            conx, addr = self.s.accept()
            res = Request(conx, addr)
            try:
                x = self.handler(res)
                if isinstance(x, list) or isinstance(x, tuple):
                    self._exec_cmd_list(res, x)
                else:
                    self._exec_cmd(res, x)
            except Exception as e:
                import traceback

                res.set_status(500, "Internal Server Error")
                res.set_body(f"{str(e)}\n{traceback.format_exc()}")
            if self.print_requests:
                print("{} {} {}".format(res.method, res.path, res.status))
            res.send_response()
        if self.is_exit_process:
            exit(self.exit_process_code)

    def listen_on_thread(self):
        self.thread = threading.Thread(target=self.listen)
        self.thread.start()

    def _exec_cmd_list(self, res, x):
        for item in x:
            self._exec_cmd(res, item)

    def _exec_cmd(self, res, x):
        if isinstance(x, int):
            res.set_status(x)
        elif isinstance(x, str):
            res.set_status_text(x)
        elif isinstance(x, Html):
            res.set_body(x.content)
            res.set_header("Content-Type", "text/html")
        elif isinstance(x, Text):
            res.set_body(x.content)
            res.set_header("Content-Type", "text/plain")
        elif isinstance(x, JavaScript):
            res.set_body(x.content)
            res.set_header("Content-Type", "text/javascript")
        elif isinstance(x, Header):
            res.set_header(x.key, x.value)
        elif isinstance(x, ExitServer):
            self.is_exit = True
        elif isinstance(x, ExitProcess):
            self.is_exit = True
            self.is_exit_process = True
            self.exit_process_code = x.code
