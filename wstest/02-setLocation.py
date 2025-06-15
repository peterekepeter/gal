# # web service test 01 - basic sanity check
from test.lib import HttpServer, Html, ExitProcess

HttpServer(
    lambda x: (
        200,
        Html("<script>window.location='/other'</script>"),
    ) if x.path == "/" else (
        200,
        Html("<title>passed</title>"),
        ExitProcess(),
    ) if x.path == "/other" else (
        404,
        ExitProcess(1),
    )
).listen()
