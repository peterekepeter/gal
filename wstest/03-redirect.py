# # web service test 01 - basic sanity check
from test.lib import HttpServer, Html, Header, ExitProcess

HttpServer(
    lambda x: (
        301,
        Header("Location", "/redir1"),
    ) if x.path == "/" else (
        301,
        Header("Location", "/redir2"),
    ) if x.path == "/redir1" else (
        301,
        Header("Location", "/redir3"),
    ) if x.path == "/redir2" else (
        200,
        Html("<title>passed</title>"),
        ExitProcess(),
    ) if x.path == "/redir3" else (
        404,
        ExitProcess(1),
    )
).listen()
