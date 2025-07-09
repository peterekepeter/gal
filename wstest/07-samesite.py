from test.lib import HttpServer, Html, Text, Header


def reroute(type, url):
    if type == "toplevel_get":
        return (
            200,
            Html(f"""
            <body><a id=lnk1 href={url}>click me</a>
            <script>lnk1.click()</script>
        """),
        )
    elif type == "toplevel_post":
        return (
            200,
            Html(f"""
            <body>
            <form method=post action={url}>
            <button type=submit id=btn1 /orders>Click!</button>
            </form>
            <script>btn1.click()</script>
        """),
        )
    else:
        raise Exception("not defined")


server_2 = HttpServer(
    lambda x: reroute("toplevel_get", server_1.get_address() + "/verify_0")
    if x.path == "/test_0"
    else reroute("toplevel_post", server_1.get_address() + "/verify_1")
    if x.path == "/test_1"
    else (404),
    port=0,
    address="127.0.0.1", # must be differet than server_1 for samesite
)
server_2.listen_on_thread()

server_1 = HttpServer(
    lambda x: (
        301,
        Text("starting test_0"),
        Header("Set-Cookie", "test=test_0; SameSite=Lax"),
        Header("Location", server_2.get_address() + "/test_0"),
    )
    if x.method == "GET" and x.path == "/"
    else (
        301,
        Text("test_0 ok, starting test_1"),
        Header("Set-Cookie", "test=test_1; SameSite=Lax"),
        Header("Location", server_2.get_address() + "/test_1"),
    )
    if x.method == "GET"
    and x.path == "/verify_0"
    and "test=test_0" in x.get_header("Cookie")
    else (
        200,
        Html("<title>passed</title><body>test_1 ok</body>"),
    )
    if x.method == "POST"
    and x.path == "/verify_1"
    and "test=test_1" not in x.get_header("Cookie")
    else (
        500,
        Html(
            f"""
            <p>something went terribly wrong <a href={server_1.get_address()}>click here to retry</a></p>
            <pre>
                method: {x.method}
                path: {x.path}
                cookie: {x.get_header("Cookie")}
            </pre>
            """
        ),
    ),
    address="localhost" # must be different than server_2 for samesite
)
server_1.listen()
