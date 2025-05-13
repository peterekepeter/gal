import socket

data_dir = "./data"
PORT = 8000


def main():
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

    try:
        status, body = do_request(method, url, headers, body)
    except Exception as e:
        import traceback

        print(traceback.format_exc())
        print(e)
        status = "500 Internal Server Error"
        body = status

    print(status, method, url)

    response = "HTTP/1.0 {}\r\n".format(status)
    response += "Content-Length: {}\r\n".format(len(body.encode("utf8")))
    response += "\r\n" + body
    conx.send(response.encode("utf8"))
    conx.close()


def do_request(method, url, headers, body):
    import urllib.parse

    parsed_url = urllib.parse.urlparse(url)
    path = parsed_url.path
    query = urllib.parse.parse_qs(parsed_url.query)

    if method == "GET" and path == "/":
        flt = get_query_single_value(query, "q", "")
        return "200 OK", show_comments(flt=flt)
    elif method == "POST" and path == "/addpost":
        params = form_decode(body)
        topic = params["topic"].strip()
        username = params["username"].strip()
        if "/" in topic or " " in topic or "." in topic or len(topic) > 24:
            return "400 Invalid", "Topic name not allowed!"
        if "/" in username or " " in username or "." in username or len(username) > 24:
            return "400 Invalid", "Invalid username!"
        message = params["message"].strip()
        data_add_topic_message(topic, username, message)
        return "200 OK", show_topic_created(topic)
    elif method == "GET" and path.startswith("/topics/"):
        topic = path[len("/topics/") :]
        if not data_topic_exists(topic):
            return "404 Not Found", not_found(url, method)
        return "200 OK", show_topic(topic)
    else:
        return "404 Not Found", not_found(url, method)


def get_query_single_value(query, key, default):
    if key not in query:
        return default
    print(query)
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


def data_get_topics_dirpath():
    return data_dir + "/topics"


def data_get_topics():
    import os

    topicsdir = data_get_topics_dirpath()
    if not os.path.isdir(topicsdir):
        return []
    return [x.rstrip(".txt") for x in os.listdir(topicsdir)]


def data_add_topic_message(topic, username, message):
    import os
    import time

    topicsdir = data_get_topics_dirpath()
    os.makedirs(topicsdir, exist_ok=True)
    topicfile = data_get_topic_filepath(topic)
    with open(topicfile, "a") as f:
        f.write(str(time.time()))
        f.write(" ")
        f.write(username)
        f.write(" ")
        f.write(message.replace("\n", "\\n"))
        f.write("\n")


def data_get_topic_filepath(topic):
    return data_get_topics_dirpath() + "/" + topic + ".txt"


def data_get_topic_messages(topic):
    import os

    path = data_get_topic_filepath(topic)
    if not os.path.isfile(path):
        return []

    with open(path) as f:
        content = f.read()

    result = []
    messages = content.split("\n")
    for msg in messages:
        if not msg.strip():
            continue
        timestamp, user, msgbody = msg.split(" ", 2)
        result.append(
            {
                "time": timestamp,
                "user": user,
                "message": msgbody.replace("\\n", "\n"),
            }
        )
    return result


def data_topic_exists(topic):
    import os

    path = data_get_topic_filepath(topic)
    if not os.path.isfile(path):
        return False
    return True


def not_found(url, method):
    out = "<!doctype html>"
    out += "<h1>{} {} not found!</h1>".format(method, url)
    return out


def show_topic_created(topic):
    import html

    out = "<!doctype html>\n"
    out += "<title>messageboard</title>\n"
    out += "<h2>Topic created successfullyt!</h2>"
    out += f"<a href=topics/{html.escape(topic)}>Click here to view!</a>"
    out += "<a href=/>Click here to view all topics!</a>"
    return out


def show_comments(flt=""):
    import html

    all_topics = data_get_topics()
    topics = [x for x in all_topics if flt in x]

    out = "<!doctype html>\n"
    out += "<title>messageboard</title>\n"
    out += "<h2>messageboard</h2>"
    out += f'<form action=/ method=get><input name=q value="{html.escape(flt)}"><button>Search!</button></form>\n'
    out += f"<p>{len(topics)} of {len(all_topics)} topic(s)</p>"
    for topic in topics:
        if flt in topic:
            out += (
                f"<p><a href=topics/{html.escape(topic)}>{html.escape(topic)}</a></p>"
            )
    out = render_post_form(out)
    return out


def show_topic(topic):
    import html

    title = html.escape(topic) + " - messageboard"
    out = "<!doctype html>\n"
    out += f"<title>{title}</title>\n"
    out += f"<h2>{title}</h2>"
    for item in data_get_topic_messages(topic):
        out += f"<p>{html.escape(item['user'])} posted on {item['time']}:</p>"
        out += f"<p>{html.escape(item['message'])}</p>"
    out += "<h3>Add comment?</h3>"
    out = render_post_form(out, topic)
    out += "<a href=/>Return to topics!</a>"
    return out


def render_post_form(out, topic=None):
    import html

    out += "<form action=/addpost method=post>\n"
    if not topic:
        out += "<p>New Topic</p>"
        out += "<p><input name=topic></p>\n"
    else:
        out += f"<p><input name=topic type=hidden value={html.escape(topic)}></p>\n"

    out += "<p>Username</p>"
    out += "<p><input name=username></p>\n"
    out += "<p>Message</p>"
    out += "<p><input name=message></p>\n"
    out += "<p><button>Post!</button></p>\n"
    out += "</form>\n"
    return out


if __name__ == "__main__":
    main()
