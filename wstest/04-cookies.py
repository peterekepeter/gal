# # web service test 01 - basic sanity check
from test.lib import HttpServer, Html, Header, ExitProcess

HttpServer(
    lambda x: (
        301,
        Header("Set-Cookie", "session=1234"),
        Header("Location", "/login"),
    )
    if x.path == "/"
    else (
        200,
        Html("<title>passed</title>"),
        ExitProcess(),
    )
    if x.path == "/login" and x.get_header("Cookie") == "session=1234"
    else (
        404,
        ExitProcess(1),
    )
).listen()
