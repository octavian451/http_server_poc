"""Main module."""

import socket
from collections.abc import Callable

HOST: str = "127.0.0.1"
PORT: int = 8080
MAX_HEADER_SIZE: int = 8 * 1024
MAX_BODY_SIZE: int = 1024 * 1024
HEADER_SEPARATOR: bytes = b"\r\n\r\n"
REQUEST_LINE_PARTS: int = 3


def hello() -> tuple[str, str]:
    """Handle /hello endpoint."""
    return "200 OK", "Hello!"


def health() -> tuple[str, str]:
    """Handle /health endpoint."""
    return "200 OK", "OK"


def root() -> tuple[str, str]:
    """Handle / endpoint."""
    return "200 OK", "Hello world!"


ROUTES: dict[str, dict[str, Callable]] = {
    "/": {
        "GET": root,
    },
    "/health": {
        "GET": health,
    },
    "/hello": {
        "GET": hello,
    },
}


def start_server() -> socket.socket:
    """Configure and start the server."""
    server: socket.socket = socket.socket(
        family=socket.AF_INET,
        type=socket.SOCK_STREAM,
    )
    server.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1,
    )
    server.bind((HOST, PORT))
    server.listen()

    return server


def receive_headers(
    client: socket.socket,
    buffer: bytes,
) -> bytes | None:
    """Receive data until header separator is met."""
    data: bytes = buffer
    while HEADER_SEPARATOR not in data:
        chunk: bytes = client.recv(1024)

        if not chunk:
            if not data:
                return None
            raise ValueError("Connection closed before headers were completely read.")

        data += chunk
        if len(data) > MAX_HEADER_SIZE + len(HEADER_SEPARATOR):
            raise ValueError("Request headers too large")

    return data


def receive_body(
    client: socket.socket,
    body: bytes,
    content_length: int,
) -> bytes:
    """Receive until the complete body arrives."""
    while len(body) < content_length:
        chunk = client.recv(1024)

        if not chunk:
            raise ValueError("Connection closed before body was completely read.")

        body += chunk

    return body


def read_request(
    client: socket.socket,
    buffer: bytes,
) -> tuple[tuple[str, str, str, dict[str, str], bytes] | None, bytes]:
    """Receive one HTTP request from the client."""
    data: bytes | None = receive_headers(client, buffer)

    if data is None:
        return None, b""

    header_section, body = data.split(HEADER_SEPARATOR, maxsplit=1)

    if len(header_section) > MAX_HEADER_SIZE:
        raise ValueError("Request headers too large")

    # Determine the expected body length.
    method, path, version, headers = parse_header_section(header_section)

    try:
        content_length: int = int(headers.get("content-length", "0"))
    except ValueError:
        raise ValueError("Invalid Content-Length value") from None

    if content_length > MAX_BODY_SIZE:
        raise ValueError("Request body too large")

    if content_length < 0:
        raise ValueError("Invalid Content-Length value")

    body = receive_body(client, body, content_length)

    request_body: bytes = body[:content_length]
    remaining_data: bytes = body[content_length:]

    request = (
        method,
        path,
        version,
        headers,
        request_body,
    )

    return request, remaining_data


def parse_request_line(
    line: str,
) -> tuple[str, str, str]:
    """Parse the HTTP request line."""
    parts: list[str] = line.split(" ", maxsplit=2)

    if len(parts) != REQUEST_LINE_PARTS:
        raise ValueError("Invalid request line")

    method, path, version = parts

    if version != "HTTP/1.1":
        raise ValueError("Unsupported HTTP version")

    return method, path, version


def parse_headers(
    lines: list[str],
) -> dict[str, str]:
    """Parse HTTP header lines."""
    headers: dict[str, str] = {}

    for line in lines:
        # a header key-value pair needs the : separator
        if ":" not in line:
            raise ValueError("Invalid header")

        key, value = line.split(":", maxsplit=1)
        key = key.lower().strip()

        # don't allow whitespace inside the header key
        if not key or any(char.isspace() for char in key):
            raise ValueError("Invalid header name")

        # don't allow header overwriting
        if key in headers:
            raise ValueError("Duplicate header")

        headers[key] = value.strip()

    return headers


def parse_header_section(
    request_headers: bytes,
) -> tuple[str, str, str, dict[str, str]]:
    """Parse HTTP request headers."""
    if not request_headers.strip():
        raise ValueError("Empty request")

    lines: list[str] = request_headers.decode("utf-8").split("\r\n")
    request_line, *header_lines = lines

    method, path, version = parse_request_line(request_line)
    headers: dict[str, str] = parse_headers(header_lines)

    if "host" not in headers:
        raise ValueError("Missing host header")

    return method, path, version, headers


def build_response(
    status: str,
    body: str,
    content_type: str = "text/plain",
) -> bytes:
    """Build an HTTP response."""
    body_bytes: bytes = body.encode("utf-8")

    response_headers: bytes = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        "\r\n"
    ).encode()

    return response_headers + body_bytes


def route_request(
    method: str,
    path: str,
) -> bytes:
    """Route request."""
    methods: dict[str, Callable] | None = ROUTES.get(path)
    if methods is None:
        return build_response(
            status="404 Not Found",
            body="Not Found",
        )

    handler: Callable | None = methods.get(method)
    if handler is None:
        return build_response(
            status="405 Method Not Allowed",
            body="Method Not Allowed",
        )

    status, response_body = handler()
    return build_response(
        status=status,
        body=response_body,
    )


def send_response(
    client: socket.socket,
    response: bytes,
) -> None:
    """Send HTTP response."""
    client.sendall(response)


def handle_request(
    client: socket.socket,
    request: tuple[str, str, str, dict[str, str], bytes],
) -> bool:
    """Handle one HTTP request."""
    method, path, _version, _headers, _body = request

    response: bytes = route_request(method, path)

    send_response(client, response)

    return True


def serve_client(
    client: socket.socket,
) -> None:
    """Serve HTTP requests to clients."""
    buffer: bytes = b""

    while True:
        try:
            request, buffer = read_request(client, buffer)
        except ValueError, TimeoutError:
            return

        if request is None:
            return

        if not handle_request(client, request):
            return


def main_loop(
    server: socket.socket,
) -> None:
    """Execute main processing loop."""
    try:
        while True:
            client, _address = server.accept()

            with client:
                client.settimeout(10)
                serve_client(client)

    except KeyboardInterrupt:
        pass

    finally:
        server.close()


if __name__ == "__main__":
    server: socket.socket = start_server()
    main_loop(server)
