from test.lib import HttpServer, Html, JavaScript, Header, Text

server_2 = HttpServer(
    lambda x: (
        200,
        Header("Access-Control-Allow-Origin", "*"),
        Text("allowed"),
    ),
    port=0, # allocate random
)
server_2.listen_on_thread()

server_3 = HttpServer(
    lambda x: (
        200,
        Text("not allowed"),
    ),
    port=0, # allocate random
)
server_3.listen_on_thread()

server_1 = HttpServer(
    lambda x: (
        200,
        Html(f"""<body><script>
            xhr = new XMLHttpRequest();
            xhr.open("GET", "{server_2.get_address()}", false)
            xhr.send()
            if (xhr.responseText !== "allowed")
                throw new Error("simple CORS failed allow!")
            xhr = new XMLHttpRequest();
            xhr.open("GET", "{server_3.get_address()}", false);
            try
            {{
                xhr.send();
                console.error("simple CORS failed reject!");
            }}
            catch (err)
            {{
                document.title="passed";
            }}
        </script></body>"""),
    )
)
server_1.listen()
