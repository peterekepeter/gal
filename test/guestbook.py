# This is a server meant for TESTING there are no security guarantees

import socket
import random

data_dir = "./data"
PORT = 8000
SESSIONS = {}
LOGINS = {
    "crashoverride": "0cool",
    "cerealkiller": "emmanuel",
}


def main():
    data_restore_sesssions()
    s = socket.socket(
        family=socket.AF_INET, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
    )
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", PORT))
    s.listen()
    print(f"listening on http://localhost:{PORT}")

    while True:
        conx, addr = s.accept()
        handle_connection(conx)


def handle_connection(conx):
    req = conx.makefile("b")
    reqline = req.readline().decode("utf8")
    method, url, version = reqline.split(" ", 2)
    assert method in ["GET", "POST"]
    headers = {}
    while True:
        line = req.readline().decode("utf8")
        if line == "\r\n":
            break
        header, value = line.split(":", 1)
        headers[header.casefold()] = value.strip()
    if "content-length" in headers:
        length = int(headers["content-length"])
        body = req.read(length).decode("utf8")
    else:
        body = None

    if "cookie" in headers:
        token = headers["cookie"][len("token=") :]
    else:
        token = str(random.random())[2:]  # not secure

    session = SESSIONS.setdefault(token, {})

    try:
        status, body = do_request(session, method, url, headers, body)
    except Exception as e:
        import traceback

        print(traceback.format_exc())
        print(e)
        status = "500 Internal Server Error"
        body = status

    print(status, method, url)

    response = "HTTP/1.0 {}\r\n".format(status)
    if "cookie" not in headers:
        template = "Set-Cookie: token={}\r\n"
        response += template.format(token)
    response += "Content-Length: {}\r\n".format(len(body.encode("utf8")))
    response += "\r\n" + body
    conx.send(response.encode("utf8"))
    conx.close()


def do_request(session, method, url, headers, body):
    import urllib.parse

    parsed_url = urllib.parse.urlparse(url)
    path = parsed_url.path
    query = urllib.parse.parse_qs(parsed_url.query)

    if method == "GET" and path == "/":
        flt = get_query_single_value(query, "q", "")
        return "200 OK", show_comments(session, flt=flt)
    elif method == "POST" and url == "/":
        params = form_decode(body)
        return do_login(session, params)
    elif method == "GET" and url == "/login":
        return "200 OK", login_form(session)
    elif method == "POST" and path == "/add":
        params = form_decode(body)
        return "200 OK", add_entry(session, params)
    else:
        return "404 Not Found", not_found(url, method)


def get_query_single_value(query, key, default):
    if key not in query:
        return default
    list = query.get(key)
    if len(list) == 0:
        return default
    return list[0]


def form_decode(body):
    import urllib.parse

    params = {}
    for field in body.split("&"):
        name, value = field.split("=", 1)
        name = urllib.parse.unquote_plus(name)
        value = urllib.parse.unquote_plus(value)
        params[name] = value
    return params


def add_entry(session, params):
    if "user" not in session:
        return
    if "guest" in params:
        message = params["guest"]
        data_append(session["user"], message)

    return show_comments(session)


def data_get_path():
    return data_dir + "/guestbook.txt"


def data_append(username, message):
    import os

    message = message.replace("\n", " ").strip()
    os.makedirs(data_dir, exist_ok=True)
    with open(data_get_path(), "a") as f:
        # not safe encoding
        f.write(username + ":" + message + "\n")


def data_get_all():
    import os

    fname = data_get_path()
    if os.path.isfile(fname):
        with open(fname) as f:
            return f.read().split("\n")
    return []


def data_get_sessions_path():
    return data_dir + "/sessions.txt"


def data_save_sessions():
    import json

    with open(data_get_sessions_path(), "w") as f:
        json.dump(SESSIONS, f, indent=1)


def data_restore_sesssions():
    import json

    global SESSIONS

    with open(data_get_sessions_path()) as f:
        SESSIONS = json.load(f)


def not_found(url, method):
    out = "<!doctype html>"
    out += "<h1>{} {} not found!</h1>".format(method, url)
    return out


def show_comments(session, flt=""):
    import html

    print(repr(flt))
    out = "<!doctype html>\n"
    out += "<title>Guestbook</title>\n"

    if "user" in session:
        out += "<h1>Hello, " + session["user"] + "</h1>"
        out += "<form action=add method=post>"
        out += "<p><input name=guest></p>"
        out += "<p><button>Sign the book!</button></p>"
        out += "</form>"
    else:
        out += "<a href=/login>Sign in to write in the guest book</a>"

    # unsafe
    out += f'<form action=/ method=get><input name=q value="{html.escape(flt)}"><button>Search!</button></form>\n'
    out += "<h2>Guestbook</h2>"
    entries = data_get_all()
    out += f"<p>{len(entries)} post(s)</p>"
    for entry in entries:
        if flt in entry:
            parts = entry.split(":", 1)
            if len(parts) == 2:
                who = parts[0]
                entry = parts[1]
            else:
                who = "unknown"
            out += "<p>" + html.escape(entry)
            out += "<i> by " + html.escape(who) + "</i></p>"
    out += "<form action=add method=post>\n"
    out += "<p><input name=guest></p>\n"
    out += "<p><button>Sign the book!</button></p>\n"
    out += "</form>\n"
    return out


def login_form(session):
    body = "<!doctype html>"
    body += "<form action=/ method=post>"
    body += "<p>Username: <input name=username></p>"
    body += "<p>Password: <input name=password type=password></p>"
    body += "<p><button>Log in</button></p>"
    body += "</form>"
    return body


def do_login(session, params):
    username = params.get("username")
    password = params.get("password")
    if username in LOGINS and LOGINS[username] == password:
        session["user"] = username
        data_save_sessions()
        return "200 OK", show_comments(session)
    else:
        out = "<!doctype html>"
        out += "<h1>Invalid password for {}</h1>".format(username)
        return "401 Unauthorized", out


if __name__ == "__main__":
    main()
