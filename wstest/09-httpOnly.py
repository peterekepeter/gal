# # web service test 01 - basic sanity check
from test.lib import HttpServer, Html, Header, ExitProcess

HttpServer(
    lambda x: (
        301,
        Header("Set-Cookie", "session=secret09; HttpOnly"),
        Html("""<script>
            var initialValue = document.cookie;
            if (document.cookie.includes("session=secret09"))
                throw new Error("should not read")
            document.cookie = "session=custom"
            if (document.cookie != initialValue)
                throw new Error("should not write")
            window.location = "/login"
        </script>""")
    )
    if x.path == "/"
    else (
        200,
        Html("<title>passed</title>ok"),
        ExitProcess(), # TODO maybe we can replace exit process with tet failed/success
    )
    if x.path == "/login" and "session=secret09" in x.get_header("Cookie") 
    else (
        print("Cookie was", x.get_header("Cookie")),
        404,
        Html("<title>failed</title>failed, <a href=/>retry?</a>"),
        ExitProcess(1),
    )
).listen()
