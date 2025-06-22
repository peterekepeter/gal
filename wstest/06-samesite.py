# # web service test 01 - basic sanity check
from test.lib import HttpServer, Html, Text, Header, ExitProcess

server_2 = HttpServer(
    lambda x: (
        200,
        # TODO test if request to main server works properly
        Html(f"""<script>
            var api = "{server_1.get_address()}";
            var xhr = new XMLHttpRequest();
            xhr.open("GET", api + "/orders", false);
            xhr.send();
            if (xhr.responseText != "ok") throw new Error("expected authorized");
            var xhr2 = new XMLHttpRequest();
            xhr2.open("POST", api + "/orders", false);
            xhr2.send();
            if (xhr.responseText != "denied") throw new Error("expected unauthorized");
            document.title = "passed";
        </script>"""),
    ),
    port=0,
)
server_2.listen_on_thread()

server_1 = HttpServer(
    lambda x: (
        301,
        Header("Set-Cookie", "foo=bar; SameSite=Lax"),
        Header("Location", server_2.get_address()),
    )
    if x.path == "/" else (
        Text("ok"),
        200,
    ) 
    if x.path == "/orders" and x.get_header("Cookie") == "foo=bar" else (
        print("cookies was", x.get_header("Cookie")),
        Text("denied"),
        401,
        ExitProcess(1),
    )
    if x.path == "/orders" else (
        500,
        ExitProcess(1)
    )
)
server_1.listen()
